import os
import json
import csv
import argparse
from tqdm import tqdm
import re


def calculate_action_mapping(attributes):
    """
    Calculates the base value for each action category for cumulative action IDs.
    This is the standard AVA methodology.
    """
    attribute_nums = {}
    cumulative_count = 0
    sorted_attrs = sorted(attributes.items(), key=lambda x: int(x[0]))

    for attr_id, attr_info in sorted_attrs:
        if attr_id.isdigit() and int(attr_id) <= 8:
            attribute_nums[attr_id] = cumulative_count
            if 'options' in attr_info:
                cumulative_count += len(attr_info['options'])

    print(f"✅ Action ID mapping calculated. Total unique actions: {cumulative_count}")
    return attribute_nums


def process_via_file(json_path, frame_dir, action_id_map, fps):
    """
    Processes a single finished VIA JSON file and returns a list of CSV rows.
    """
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            via_json = json.load(f)
    except (json.JSONDecodeError, FileNotFoundError) as e:
        print(f"⚠️ Warning: Skipping corrupted or empty file: {json_path} ({e})")
        return []
    files = {f_data['fid']: f_data['fname'] for f_key, f_data in via_json.get('file', {}).items()}
    try:
        first_fname = next(iter(files.values()))
        video_id = '_'.join(first_fname.split('_')[:-2])
        img_path = os.path.join(frame_dir, video_id, first_fname)
        import cv2
        img = cv2.imread(img_path)
        img_H, img_W = img.shape[:2]
    except (StopIteration, AttributeError, FileNotFoundError):
        print(f"⚠️ Warning: Could not read frames for {video_id} to get dimensions. Using 1280x720 as default.")
        img_H, img_W = 720, 1280

    csv_rows = []
    for metadata in via_json.get('metadata', {}).values():
        fname = files.get(metadata['vid'])
        if not fname:
            continue
        video_id = '_'.join(fname.split('_')[:-2])
        frame_num_match = re.search(r'_(\d{4,})\.jpg$', fname)
        if not frame_num_match:
            continue
        frame_timestamp = int(frame_num_match.group(1)) // fps
        xy = metadata.get('xy', [])
        if len(xy) < 5: continue

        abs_x1, abs_y1, width, height = xy[1], xy[2], xy[3], xy[4]
        abs_x2 = abs_x1 + width
        abs_y2 = abs_y1 + height
        x1_norm = abs_x1 / img_W
        y1_norm = abs_y1 / img_H
        x2_norm = abs_x2 / img_W
        y2_norm = abs_y2 / img_H

        attributes = metadata.get('av', {})
        person_id = attributes.get('9', '-1')
        has_action = False
        for attr_id, option_id in attributes.items():
            if attr_id.isdigit() and int(attr_id) <= 8 and option_id != '':
                has_action = True
                base_action_id = action_id_map.get(attr_id, 0)
                final_action_id = base_action_id + int(option_id) + 1
                csv_rows.append([
                    video_id,
                    frame_timestamp,
                    f"{x1_norm:.6f}",
                    f"{y1_norm:.6f}",
                    f"{x2_norm:.6f}",
                    f"{y2_norm:.6f}",
                    final_action_id,
                    person_id
                ])

    return csv_rows


def main():
    parser = argparse.ArgumentParser(
        description="Convert annotated VIA JSON files directly to the final AVA-format train.csv.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--frame_dir', type=str, required=True,
                        help="Root directory containing the frame subdirectories, used for finding annotated files.")
    parser.add_argument('--output_csv', type=str, default='./train.csv', help="Path to save the final train.csv file.")
    parser.add_argument('--fps', type=int, default=25,
                        help="The frames-per-second of the source videos, for calculating the timestamp.")
    args = parser.parse_args()
    action_id_map = {}
    try:
        first_json_path = ""
        for root, _, files in os.walk(args.frame_dir):
            for file in files:
                if file.endswith("_finish.json"):
                    first_json_path = os.path.join(root, file)
                    break
            if first_json_path:
                break

        with open(first_json_path, 'r', encoding='utf-8') as f:
            sample_json = json.load(f)
        action_id_map = calculate_action_mapping(sample_json.get('attribute', {}))
    except (FileNotFoundError, IndexError):
        print(
            "❌ Error: Could not find a sample '_finish.json' file to build action map. Please ensure at least one annotated file exists.")
        return
    all_csv_rows = []
    json_files_to_process = []
    for root, _, files in os.walk(args.frame_dir):
        for file in files:
            if file.endswith("_finish.json"):
                json_files_to_process.append(os.path.join(root, file))

    if not json_files_to_process:
        print(
            "❌ Error: No '_finish.json' files found. Rename your annotated files (e.g., '4_clip_001_via.json' -> '4_clip_001_finish.json').")
        return

    print(f"Found {len(json_files_to_process)} annotated files to process.")
    for json_path in tqdm(json_files_to_process, desc="Processing annotations"):
        rows = process_via_file(json_path, args.frame_dir, action_id_map, args.fps)
        all_csv_rows.extend(rows)
    header = ['video_id', 'frame_timestamp', 'x1', 'y1', 'x2', 'y2', 'action_id', 'person_id']
    all_csv_rows.sort(key=lambda x: (x[0], int(x[1])))

    try:
        with open(args.output_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(all_csv_rows)
        print(f"\n🎉 Success! Generated {len(all_csv_rows)} rows. Final dataset saved to: {args.output_csv}")
    except IOError as e:
        print(f"\n❌ Error writing to CSV file: {e}")


if __name__ == "__main__":
    main()
