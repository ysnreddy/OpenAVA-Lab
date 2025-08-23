import os
import pickle
import argparse
import zipfile
import cv2  # Make sure to have opencv-python installed: pip install opencv-python
from tqdm import tqdm
from collections import defaultdict
import xml.etree.ElementTree as ET
from xml.dom import minidom
import re


def get_image_dimensions(frame_path):
    """Reads an image file and returns its width and height."""
    try:
        img = cv2.imread(frame_path)
        if img is not None:
            height, width, _ = img.shape
            return width, height
    except Exception as e:
        print(f"⚠️ Warning: Could not read image {frame_path}. Error: {e}")
    return None, None


def prettify_xml(elem):
    """Return a pretty-printed XML string for the Element."""
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def generate_cvat_xml(frames_data, image_width, image_height, attributes_dict, clip_id):
    """
    Generates the content for a CVAT XML 1.1 format file with tracks.
    """
    # Root element
    annotations = ET.Element('annotations')
    ET.SubElement(annotations, 'version').text = '1.1'

    # Meta information
    meta = ET.SubElement(annotations, 'meta')
    task = ET.SubElement(meta, 'task')
    ET.SubElement(task, 'id').text = '0'  # Placeholder
    ET.SubElement(task, 'name').text = clip_id
    ET.SubElement(task, 'size').text = str(len(frames_data))
    ET.SubElement(task, 'mode').text = 'interpolation'
    ET.SubElement(task, 'overlap').text = '0'
    ET.SubElement(task, 'bugtracker')
    ET.SubElement(task, 'created').text = '2025-08-23 13:30:35.000000+05:30'  # Placeholder
    ET.SubElement(task, 'updated').text = '2025-08-23 13:30:35.000000+05:30'  # Placeholder
    subset = ET.SubElement(task, 'subset')
    subset.text = 'default'

    # Add image information to meta
    # Sort frames to ensure consistent ordering
    sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d+)\.jpg$', f).group(1)))
    for i, frame_name in enumerate(sorted_frame_names):
        frame_meta = ET.SubElement(task, 'frame')
        ET.SubElement(frame_meta, 'id').text = str(i)
        ET.SubElement(frame_meta, 'name').text = frame_name
        ET.SubElement(frame_meta, 'width').text = str(image_width)
        ET.SubElement(frame_meta, 'height').text = str(image_height)

    source = ET.SubElement(meta, 'source')
    source.text = 'frames'

    # Labels and Attributes
    labels = ET.SubElement(task, 'labels')
    person_label = ET.SubElement(labels, 'label')
    ET.SubElement(person_label, 'name').text = 'person'
    ET.SubElement(person_label, 'color').text = '#ff0000'

    attributes_xml = ET.SubElement(person_label, 'attributes')
    for attr in attributes_dict.values():
        attribute = ET.SubElement(attributes_xml, 'attribute')
        ET.SubElement(attribute, 'name').text = attr['aname']
        ET.SubElement(attribute, 'mutable').text = 'true'
        ET.SubElement(attribute, 'input_type').text = 'select'
        ET.SubElement(attribute, 'default_value').text = list(attr['options'].values())[
            0]  # Use first option as default
        ET.SubElement(attribute, 'values').text = '\n'.join(attr['options'].values())

    # Group detections by track_id
    tracks = defaultdict(list)
    for frame_name, detections in frames_data.items():
        try:
            # Extract frame number from filename like '..._0001.jpg'
            frame_num_match = re.search(r'_(\d+)\.jpg$', frame_name)
            if not frame_num_match:
                print(f"⚠️ Warning: Could not parse frame number from '{frame_name}', skipping.")
                continue
            frame_num = int(frame_num_match.group(1))

            for det in detections:
                track_id = det[5]
                bbox = det[0:4]  # Bbox: [x1, y1, x2, y2]
                tracks[track_id].append({'frame': frame_num, 'bbox': bbox})
        except (AttributeError, IndexError, TypeError):
            print(f"⚠️ Warning: Could not parse detection for {frame_name}")
            continue

    # Create <track> elements
    for track_id, detections in tracks.items():
        track_xml = ET.SubElement(annotations, 'track', {
            'id': str(track_id),
            'label': 'person',
        })

        # Sort detections by frame number to ensure correct order
        sorted_detections = sorted(detections, key=lambda d: d['frame'])

        for det in sorted_detections:
            x1, y1, x2, y2 = det['bbox']
            box_attributes = {
                'frame': str(det['frame']),
                'xtl': str(float(x1)),
                'ytl': str(float(y1)),
                'xbr': str(float(x2)),
                'ybr': str(float(y2)),
                'outside': '0',
                'occluded': '0',
                'keyframe': '1',  # Every detected frame is a keyframe
            }
            ET.SubElement(track_xml, 'box', box_attributes)

    return prettify_xml(annotations)


def process_clip(video_id, frames_data, frame_dir, output_dir, attributes_dict):
    """
    Generates XML and creates a ZIP file for a single video clip.
    """
    clip_frame_path = os.path.join(frame_dir, video_id)
    if not os.path.isdir(clip_frame_path):
        print(f"⚠️ Warning: Frame directory not found for clip '{video_id}', skipping.")
        return

    sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d+)\.jpg$', f).group(1)))
    if not sorted_frame_names:
        print(f"⚠️ Warning: No frames found for clip '{video_id}', skipping.")
        return

    width, height = get_image_dimensions(os.path.join(clip_frame_path, sorted_frame_names[0]))
    if not width or not height:
        print(f"❌ Error: Could not determine image dimensions for clip '{video_id}', skipping.")
        return

    # 1. Generate XML content
    xml_content = generate_cvat_xml(frames_data, width, height, attributes_dict, video_id)

    # 2. Create the ZIP file
    zip_path = os.path.join(output_dir, f"{video_id}.zip")
    try:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('annotations.xml', xml_content)

            for frame_name in sorted_frame_names:
                frame_file_path = os.path.join(clip_frame_path, frame_name)
                if os.path.exists(frame_file_path):
                    zf.write(frame_file_path, arcname=frame_name)
        return True
    except Exception as e:
        print(f"❌ Error creating ZIP file for clip '{video_id}': {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Create CVAT-compatible ZIP files with pre-annotations from a dense proposal file."
    )
    parser.add_argument('--pickle_path', type=str, required=True,
                        help="Path to the frame-based dense_proposals.pkl file.")
    parser.add_argument('--frame_dir', type=str, required=True,
                        help="Root directory containing frame subdirectories for each clip.")
    parser.add_argument('--output_dir', type=str, required=True,
                        help="Directory to save the final ZIP files.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    try:
        with open(args.pickle_path, 'rb') as f:
            proposals_data = pickle.load(f)
    except FileNotFoundError:
        print(f"❌ Error: Pickle file not found at {args.pickle_path}")
        return

    # ✨ COMPLETE action attributes from your VIA script
    attributes_dict = {
        '1': dict(aname='walking_behavior', type=2,
                  options={'0': 'normal_walk', '1': 'fast_walk', '2': 'slow_walk', '3': 'standing_still',
                           '4': 'jogging', '5': 'window_shopping'}),
        '2': dict(aname='phone_usage', type=2,
                  options={'0': 'no_phone', '1': 'talking_phone', '2': 'texting', '3': 'taking_photo',
                           '4': 'listening_music'}),
        '3': dict(aname='social_interaction', type=2,
                  options={'0': 'alone', '1': 'talking_companion', '2': 'group_walking', '3': 'greeting_someone',
                           '4': 'asking_directions', '5': 'avoiding_crowd'}),
        '4': dict(aname='carrying_items', type=2,
                  options={'0': 'empty_hands', '1': 'shopping_bags', '2': 'backpack', '3': 'briefcase_bag',
                           '4': 'umbrella', '5': 'food_drink', '6': 'multiple_items'}),
        '5': dict(aname='street_behavior', type=2,
                  options={'0': 'sidewalk_walking', '1': 'crossing_street', '2': 'waiting_signal',
                           '3': 'looking_around', '4': 'checking_map', '5': 'entering_building',
                           '6': 'exiting_building'}),
        '6': dict(aname='posture_gesture', type=2,
                  options={'0': 'upright_normal', '1': 'looking_down', '2': 'looking_up', '3': 'hands_in_pockets',
                           '4': 'arms_crossed', '5': 'pointing_gesture', '6': 'bowing_gesture'}),
        '7': dict(aname='clothing_style', type=2,
                  options={'0': 'business_attire', '1': 'casual_wear', '2': 'tourist_style', '3': 'school_uniform',
                           '4': 'sports_wear', '5': 'traditional_wear'}),
        '8': dict(aname='time_context', type=2,
                  options={'0': 'rush_hour', '1': 'leisure_time', '2': 'shopping_time', '3': 'tourist_hours',
                           '4': 'lunch_break', '5': 'evening_stroll'})
    }

    print(f"Found proposals for {len(proposals_data)} unique video clips.")
    success_count = 0
    for video_id, frames_data in tqdm(proposals_data.items(), desc="Processing clips"):
        if process_clip(video_id, frames_data, args.frame_dir, args.output_dir, attributes_dict):
            success_count += 1

    print(f"\n🎉 Processing complete. Successfully created {success_count} ZIP files in '{args.output_dir}'.")


if __name__ == "__main__":
    main()