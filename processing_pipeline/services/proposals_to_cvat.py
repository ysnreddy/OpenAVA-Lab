import os
import pickle
import argparse
import zipfile
import cv2
from tqdm import tqdm
from collections import defaultdict
import xml.etree.ElementTree as ET
from xml.dom import minidom
import re
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_image_dimensions(frame_path):
    """Reads an image file and returns its width and height."""
    try:
        img = cv2.imread(frame_path)
        if img is not None:
            height, width, _ = img.shape
            return width, height
    except Exception as e:
        logger.warning(f"Could not read image {frame_path}: {e}")
    return None, None


def prettify_xml(elem):
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def generate_cvat_xml(frames_data, image_width, image_height, attributes_dict, clip_id):
    """
    Generates a robust CVAT XML 1.1 file, using correct frame indexing and filling track gaps.
    """
    annotations = ET.Element('annotations')
    ET.SubElement(annotations, 'version').text = '1.1'

    meta = ET.SubElement(annotations, 'meta')
    task = ET.SubElement(meta, 'task')
    ET.SubElement(task, 'id').text = '0'
    ET.SubElement(task, 'name').text = clip_id
    ET.SubElement(task, 'size').text = str(len(frames_data))
    ET.SubElement(task, 'mode').text = 'interpolation'
    ET.SubElement(task, 'overlap').text = '0'

    original_size = ET.SubElement(task, 'original_size')
    ET.SubElement(original_size, 'width').text = str(image_width)
    ET.SubElement(original_size, 'height').text = str(image_height)

    labels = ET.SubElement(task, 'labels')
    person_label = ET.SubElement(labels, 'label')
    ET.SubElement(person_label, 'name').text = 'person'
    ET.SubElement(person_label, 'color').text = '#ff0000'
    attributes_xml = ET.SubElement(person_label, 'attributes')

    for attr_data in attributes_dict.values():
        attribute = ET.SubElement(attributes_xml, 'attribute')
        ET.SubElement(attribute, 'name').text = attr_data['aname']
        ET.SubElement(attribute, 'mutable').text = 'true'
        ET.SubElement(attribute, 'input_type').text = 'select'
        default_value = list(attr_data['options'].values())[0]
        ET.SubElement(attribute, 'default_value').text = default_value
        ET.SubElement(attribute, 'values').text = '\n'.join(attr_data['options'].values())

    # ✨ FIX: Create a mapping from filename to a zero-based index
    sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d+)\.jpg$', f).group(1)))
    frame_map = {name: i for i, name in enumerate(sorted_frame_names)}

    tracks_data = defaultdict(dict)
    for frame_name, detections in frames_data.items():
        if frame_name not in frame_map:
            continue
        frame_idx = frame_map[frame_name]
        for det in detections:
            track_id, bbox = det[5], det[0:4]
            tracks_data[track_id][frame_idx] = bbox

    for track_id, detections_by_frame in tracks_data.items():
        track_xml = ET.SubElement(annotations, 'track', {'id': str(track_id), 'label': 'person'})

        if not detections_by_frame:
            continue

        min_frame = min(detections_by_frame.keys())
        max_frame = max(detections_by_frame.keys())
        last_known_bbox = None

        # ✨ This is the definitive ghosting fix
        for frame_num in range(min_frame, max_frame + 1):
            bbox = detections_by_frame.get(frame_num)
            is_outside = "1" if bbox is None else "0"
            is_keyframe = "1" if bbox is not None else "0"

            if bbox is None:
                bbox = last_known_bbox if last_known_bbox is not None else [0, 0, 0, 0]
            else:
                last_known_bbox = bbox

            x1, y1, x2, y2 = bbox
            box_attributes = {
                'frame': str(frame_num), 'xtl': str(x1), 'ytl': str(y1),
                'xbr': str(x2), 'ybr': str(y2),
                'outside': is_outside, 'occluded': '0', 'keyframe': is_keyframe
            }
            box_xml = ET.SubElement(track_xml, 'box', box_attributes)

            for attr_data in attributes_dict.values():
                default_value = list(attr_data['options'].values())[0]
                ET.SubElement(box_xml, 'attribute', {'name': attr_data['aname']}).text = default_value

    return prettify_xml(annotations)


def process_clip(video_id, frames_data, frame_dir, output_zip_dir, output_xml_dir, attributes_dict):
    """
    Generates a ZIP file with only frames and a separate XML file.
    """
    clip_frame_path = os.path.join(frame_dir, video_id)
    if not os.path.isdir(clip_frame_path):
        logger.warning(f"Frame directory not found for clip '{video_id}', skipping.")
        return False

    try:
        sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d+)\.jpg$', f).group(1)))
    except (AttributeError, ValueError):
        logger.warning(f"Could not sort frames for clip '{video_id}', skipping.")
        return False

    if not sorted_frame_names:
        logger.warning(f"No frames found in data for clip '{video_id}', skipping.")
        return False

    width, height = get_image_dimensions(os.path.join(clip_frame_path, sorted_frame_names[0]))
    if not width or not height:
        logger.error(f"Could not determine image dimensions for clip '{video_id}', skipping.")
        return False

    xml_content = generate_cvat_xml(frames_data, width, height, attributes_dict, video_id)

    # Save XML to its dedicated directory
    xml_path = os.path.join(output_xml_dir, f"{video_id}_annotations.xml")
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(xml_content)

    # Create the ZIP file with only frames
    zip_path = os.path.join(output_zip_dir, f"{video_id}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for frame_name in sorted_frame_names:
            frame_file_path = os.path.join(clip_frame_path, frame_name)
            if os.path.exists(frame_file_path):
                zf.write(frame_file_path, arcname=frame_name)
    return True


def main():
    parser = argparse.ArgumentParser(description="Create separate ZIP and XML files from a dense proposal file.")
    parser.add_argument('--pickle_path', type=str, required=True, help="Path to the dense_proposals.pkl file.")
    parser.add_argument('--frame_dir', type=str, required=True, help="Root directory containing frame subdirectories.")
    parser.add_argument('--output_zip_dir', type=str, required=True, help="Directory to save the final ZIP files.")
    parser.add_argument('--output_xml_dir', type=str, required=True, help="Directory to save the final XML files.")
    args = parser.parse_args()

    os.makedirs(args.output_zip_dir, exist_ok=True)
    os.makedirs(args.output_xml_dir, exist_ok=True)

    try:
        with open(args.pickle_path, 'rb') as f:
            proposals_data = pickle.load(f)
    except FileNotFoundError:
        logger.error(f"Pickle file not found at {args.pickle_path}")
        return

    attributes_dict = {
        '1': dict(aname='walking_behavior',
                  options={'unknown': 'unknown', 'normal_walk': 'normal_walk', 'fast_walk': 'fast_walk',
                           'slow_walk': 'slow_walk', 'standing_still': 'standing_still', 'jogging': 'jogging',
                           'window_shopping': 'window_shopping'}),
        '2': dict(aname='phone_usage',
                  options={'unknown': 'unknown', 'no_phone': 'no_phone', 'talking_phone': 'talking_phone',
                           'texting': 'texting', 'taking_photo': 'taking_photo', 'listening_music': 'listening_music'}),
        '3': dict(aname='social_interaction',
                  options={'unknown': 'unknown', 'alone': 'alone', 'talking_companion': 'talking_companion',
                           'group_walking': 'group_walking', 'greeting_someone': 'greeting_someone',
                           'asking_directions': 'asking_directions', 'avoiding_crowd': 'avoiding_crowd'}),
        '4': dict(aname='carrying_items',
                  options={'unknown': 'unknown', 'empty_hands': 'empty_hands', 'shopping_bags': 'shopping_bags',
                           'backpack': 'backpack', 'briefcase_bag': 'briefcase_bag', 'umbrella': 'umbrella',
                           'food_drink': 'food_drink', 'multiple_items': 'multiple_items'}),
        '5': dict(aname='street_behavior', options={'unknown': 'unknown', 'sidewalk_walking': 'sidewalk_walking',
                                                    'crossing_street': 'crossing_street',
                                                    'waiting_signal': 'waiting_signal',
                                                    'looking_around': 'looking_around', 'checking_map': 'checking_map',
                                                    'entering_building': 'entering_building',
                                                    'exiting_building': 'exiting_building'}),
        '6': dict(aname='posture_gesture',
                  options={'unknown': 'unknown', 'upright_normal': 'upright_normal', 'looking_down': 'looking_down',
                           'looking_up': 'looking_up', 'hands_in_pockets': 'hands_in_pockets',
                           'arms_crossed': 'arms_crossed', 'pointing_gesture': 'pointing_gesture',
                           'bowing_gesture': 'bowing_gesture'}),
        '7': dict(aname='clothing_style',
                  options={'unknown': 'unknown', 'business_attire': 'business_attire', 'casual_wear': 'casual_wear',
                           'tourist_style': 'tourist_style', 'school_uniform': 'school_uniform',
                           'sports_wear': 'sports_wear', 'traditional_wear': 'traditional_wear'}),
        '8': dict(aname='time_context',
                  options={'unknown': 'unknown', 'rush_hour': 'rush_hour', 'leisure_time': 'leisure_time',
                           'shopping_time': 'shopping_time', 'tourist_hours': 'tourist_hours',
                           'lunch_break': 'lunch_break', 'evening_stroll': 'evening_stroll'})
    }

    success_count = 0
    for video_id, frames_data in tqdm(proposals_data.items(), desc="Processing clips"):
        if process_clip(video_id, frames_data, args.frame_dir, args.output_zip_dir, args.output_xml_dir,
                        attributes_dict):
            success_count += 1

    print(f"\n🎉 Processing complete. Successfully created {success_count} ZIP and XML files.")


if __name__ == "__main__":
    main()
 