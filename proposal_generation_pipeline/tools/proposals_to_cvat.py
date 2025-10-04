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
    try:
        img = cv2.imread(frame_path)
        if img is not None:
            height, width, _ = img.shape
            return width, height
    except Exception as e:
        logger.warning(f"Could not read image {frame_path}: {e}")
    return None, None


def prettify_xml(elem):
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def generate_cvat_xml(frames_data, image_width, image_height, attributes_dict, clip_id):
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

    sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d+)\.jpg$', f).group(1)))
    frame_map = {name: i for i, name in enumerate(sorted_frame_names)}
    tracks_data = defaultdict(dict)
    for frame_name, detections in frames_data.items():
        if frame_name not in frame_map:
            continue
        frame_idx = frame_map[frame_name]
        for det in detections:
            # Assuming track_id is at index 5
            track_id, bbox = det[5], det[0:4]
            tracks_data[track_id][frame_idx] = bbox

    for track_id, detections_by_frame in tracks_data.items():
        track_xml = ET.SubElement(annotations, 'track', {'id': str(track_id), 'label': 'person'})
        if not detections_by_frame:
            continue
        min_frame, max_frame = min(detections_by_frame.keys()), max(detections_by_frame.keys())
        last_known_bbox = None
        for frame_num in range(min_frame, max_frame + 1):
            bbox = detections_by_frame.get(frame_num)
            is_outside = "1" if bbox is None else "0"
            is_keyframe = "1" if bbox is not None else "0"
            if bbox is None:
                bbox = last_known_bbox if last_known_bbox is not None else [0, 0, 0, 0]
            else:
                last_known_bbox = bbox
            x1, y1, x2, y2 = bbox
            box_attributes = {'frame': str(frame_num), 'xtl': str(x1), 'ytl': str(y1), 'xbr': str(x2), 'ybr': str(y2),
                              'outside': is_outside, 'occluded': '0', 'keyframe': is_keyframe}
            box_xml = ET.SubElement(track_xml, 'box', box_attributes)
            for attr_data in attributes_dict.values():
                default_value = list(attr_data['options'].values())[0]
                ET.SubElement(box_xml, 'attribute', {'name': attr_data['aname']}).text = default_value
    return prettify_xml(annotations)


def generate_all_xmls(pickle_path: str, frame_dir: str, output_xml_dir: str):
    """
    NEW: Core logic refactored into this function for importability.
    Generates XML files from a dense proposal pickle file.
    """
    os.makedirs(output_xml_dir, exist_ok=True)
    try:
        with open(pickle_path, 'rb') as f:
            proposals_data = pickle.load(f)
    except FileNotFoundError:
        logger.error(f"Pickle file not found at {pickle_path}")
        return

    # This can be moved to a separate config file later if needed
    attributes_dict = {
        '1': dict(aname='walking_behavior', options={'unknown': 'unknown', 'normal_walk': 'normal_walk'}),
        '2': dict(aname='phone_usage', options={'unknown': 'unknown', 'no_phone': 'no_phone'}),
    }

    success_count = 0
    for video_id, frames_data in tqdm(proposals_data.items(), desc="  -> Generating XML for clips"):
        clip_frame_path = os.path.join(frame_dir, video_id)
        if not os.path.isdir(clip_frame_path):
            logger.warning(f"Frame directory not found for clip '{video_id}', skipping XML generation.")
            continue

        try:
            sorted_frame_names = sorted(frames_data.keys(), key=lambda f: int(re.search(r'_(\d+)\.jpg$', f).group(1)))
        except (AttributeError, ValueError):
            logger.warning(f"Could not sort frames for clip '{video_id}', skipping XML generation.")
            continue

        if not sorted_frame_names:
            logger.warning(f"No frames found in data for clip '{video_id}', skipping XML generation.")
            continue

        first_frame_path = os.path.join(clip_frame_path, sorted_frame_names[0])
        width, height = get_image_dimensions(first_frame_path)
        if not width or not height:
            logger.error(f"Could not get image dimensions for clip '{video_id}', skipping XML generation.")
            continue

        xml_content = generate_cvat_xml(frames_data, width, height, attributes_dict, video_id)
        xml_path = os.path.join(output_xml_dir, f"{video_id}_annotations.xml")
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write(xml_content)
        success_count += 1

    logger.info(f"✅ Successfully created {success_count} XML annotation files.")


# The main block now just calls the refactored function
def main():
    parser = argparse.ArgumentParser(description="Create CVAT XML files from a dense proposal file.")
    parser.add_argument('--pickle_path', type=str, required=True, help="Path to the dense_proposals.pkl file.")
    parser.add_argument('--frame_dir', type=str, required=True, help="Root directory containing frame subdirectories.")
    parser.add_argument('--output_xml_dir', type=str, required=True, help="Directory to save the final XML files.")
    args = parser.parse_args()

    generate_all_xmls(args.pickle_path, args.frame_dir, args.output_xml_dir)


if __name__ == "__main__":
    main()