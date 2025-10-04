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

    # Create attributes without any "unknown" values in the header
    for attr_key, attr_data in attributes_dict.items():
        attribute = ET.SubElement(attributes_xml, 'attribute')
        ET.SubElement(attribute, 'name').text = attr_data['aname']
        ET.SubElement(attribute, 'mutable').text = 'true'
        ET.SubElement(attribute, 'input_type').text = 'select'
        
        all_options = list(attr_data['options'].values())
        valid_options = []
        for opt in all_options:
            if opt and opt.strip() and opt.lower() != 'unknown':
                valid_options.append(opt.strip())
        
        if not valid_options:
            valid_options = ['not_specified']  # Fallback
            
        default_value = valid_options[0]
        ET.SubElement(attribute, 'default_value').text = default_value
        ET.SubElement(attribute, 'values').text = '\n'.join(valid_options)
        
        logger.info(f"Created attribute {attr_data['aname']}: default='{default_value}', options={valid_options}")

    # Create a mapping from filename to a zero-based index
    sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d+)\.jpg$', f).group(1)))
    frame_map = {name: i for i, name in enumerate(sorted_frame_names)}

    tracks_data = defaultdict(dict)
    # Correctly parse and store the bounding box and attribute data from the detections
    # Assuming detection format: [x1, y1, x2, y2, score, track_id, attr1, attr2, ...]
    for frame_name, detections in frames_data.items():
        if frame_name not in frame_map:
            continue
        frame_idx = frame_map[frame_name]
        for det in detections:
            track_id, bbox = det[5], det[0:4]
            # Capture all attribute values that follow the bounding box and track ID
            attrs = det[6:]  
            tracks_data[track_id][frame_idx] = (bbox, attrs)

    for track_id, detections_by_frame in tracks_data.items():
        track_xml = ET.SubElement(annotations, 'track', {'id': str(track_id), 'label': 'person'})

        if not detections_by_frame:
            continue

        min_frame = min(detections_by_frame.keys())
        max_frame = max(detections_by_frame.keys())
        last_known_data = None

        for frame_num in range(min_frame, max_frame + 1):
            data_tuple = detections_by_frame.get(frame_num)
            is_outside = "1" if data_tuple is None else "0"
            is_keyframe = "1" if data_tuple is not None else "0"

            if data_tuple is None:
                # If a frame has no detection, use the last known data
                data_tuple = last_known_data if last_known_data is not None else ([0, 0, 0, 0], ['not_specified'] * len(attributes_dict))
            else:
                last_known_data = data_tuple

            bbox, attrs = data_tuple
            x1, y1, x2, y2 = bbox

            box_attributes = {
                'frame': str(frame_num), 'xtl': str(x1), 'ytl': str(y1),
                'xbr': str(x2), 'ybr': str(y2),
                'outside': is_outside, 'occluded': '0', 'keyframe': is_keyframe
            }
            box_xml = ET.SubElement(track_xml, 'box', box_attributes)

            # **CRITICAL FIX**: Validate and assign the correct attribute value for the box
            for idx, (attr_key, attr_data) in enumerate(attributes_dict.items()):
                # Get valid options and a default value for the current attribute
                all_options = list(attr_data['options'].values())
                valid_options = [opt.strip() for opt in all_options if opt and opt.strip() and opt.lower() != 'unknown']
                default_value = valid_options[0] if valid_options else 'not_specified'
                
                # Get the value from the source data for this specific box
                try:
                    source_value = attrs[idx]
                except IndexError:
                    source_value = None # No value found
                
                # Assign a valid value. If the source value is not in the valid options, use the default.
                final_value = source_value if source_value in valid_options else default_value
                
                attr_element = ET.SubElement(box_xml, 'attribute', {'name': attr_data['aname']})
                attr_element.text = final_value

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

    # COMPLETELY CLEAN ATTRIBUTES - NO "unknown" ANYWHERE
    attributes_dict = {
        '1': dict(aname='walking_behavior',
                  options={
                      '1': 'normal_walk', 
                      '2': 'fast_walk',
                      '3': 'slow_walk', 
                      '4': 'standing_still', 
                      '5': 'jogging',
                      '6': 'window_shopping'
                  }),
        '2': dict(aname='phone_usage',
                  options={
                      '1': 'no_phone', 
                      '2': 'talking_phone',
                      '3': 'texting', 
                      '4': 'taking_photo', 
                      '5': 'listening_music'
                  }),
        '3': dict(aname='social_interaction',
                  options={
                      '1': 'alone', 
                      '2': 'talking_companion',
                      '3': 'group_walking', 
                      '4': 'greeting_someone',
                      '5': 'asking_directions', 
                      '6': 'avoiding_crowd'
                  }),
        '4': dict(aname='carrying_items',
                  options={
                      '1': 'empty_hands', 
                      '2': 'shopping_bags',
                      '3': 'backpack', 
                      '4': 'briefcase_bag', 
                      '5': 'umbrella',
                      '6': 'food_drink', 
                      '7': 'multiple_items'
                  }),
        '5': dict(aname='street_behavior', 
                  options={
                      '1': 'sidewalk_walking',
                      '2': 'crossing_street',
                      '3': 'waiting_signal',
                      '4': 'looking_around', 
                      '5': 'checking_map',
                      '6': 'entering_building',
                      '7': 'exiting_building'
                  }),
        '6': dict(aname='posture_gesture',
                  options={
                      '1': 'upright_normal', 
                      '2': 'looking_down',
                      '3': 'looking_up', 
                      '4': 'hands_in_pockets',
                      '5': 'arms_crossed', 
                      '6': 'pointing_gesture',
                      '7': 'bowing_gesture'
                  }),
        '7': dict(aname='clothing_style',
                  options={
                      '1': 'business_attire', 
                      '2': 'casual_wear',
                      '3': 'tourist_style', 
                      '4': 'school_uniform',
                      '5': 'sports_wear', 
                      '6': 'traditional_wear'
                  }),
        '8': dict(aname='time_context',
                  options={
                      '1': 'rush_hour', 
                      '2': 'leisure_time',
                      '3': 'shopping_time', 
                      '4': 'tourist_hours',
                      '5': 'lunch_break', 
                      '6': 'evening_stroll'
                  })
    }

    # Log what we're using for attributes
    logger.info("=== ATTRIBUTE VALIDATION ===")
    for attr_key, attr_data in attributes_dict.items():
        options = list(attr_data['options'].values())
        has_unknown = any(opt.lower() == 'unknown' for opt in options)
        logger.info(f"{attr_data['aname']}: {options} | Has 'unknown': {has_unknown}")
    
    success_count = 0
    for video_id, frames_data in tqdm(proposals_data.items(), desc="Processing clips"):
        if process_clip(video_id, frames_data, args.frame_dir, args.output_zip_dir, args.output_xml_dir,
                         attributes_dict):
            success_count += 1

    print(f"\n🎉 Processing complete. Successfully created {success_count} ZIP and XML files.")


if __name__ == "__main__":
    main()