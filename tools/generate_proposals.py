# tools/generate_proposals.py

import os
import json
import argparse
from tqdm import tqdm

def normalize_bbox(bbox, img_w, img_h):
    x1, y1, x2, y2 = bbox
    return [x1 / img_w, y1 / img_h, x2 / img_w, y2 / img_h]

def main():
    parser = argparse.ArgumentParser(description="Generate AVA-style proposals from tracking outputs.")
    parser.add_argument('--tracking_dir', type=str, required=True, help="Path to tracking JSONs.")
    parser.add_argument('--output_file', type=str, required=True, help="Output JSON file path.")
    parser.add_argument('--fps', type=int, default=30, help="Frame rate for timestamp conversion.")
    parser.add_argument('--img_width', type=int, default=1920, help="Width of original frames.")
    parser.add_argument('--img_height', type=int, default=1080, help="Height of original frames.")
    args = parser.parse_args()

    all_proposals = []

    video_files = [f for f in os.listdir(args.tracking_dir) if f.endswith('.json')]
    print(f" Found {len(video_files)} tracking files to process...")

    for file_name in tqdm(video_files, desc="Generating proposals"):
        file_path = os.path.join(args.tracking_dir, file_name)

        with open(file_path, 'r') as f:
            tracks = json.load(f)

        for entry in tracks:
            video_id = entry['video_id']
            frame_name = os.path.splitext(entry['frame'])[0]
            frame_number = int(''.join(filter(str.isdigit, os.path.splitext(frame_name)[0][-4:])))
            timestamp = frame_number // args.fps
            person_id = entry['track_id']
            bbox = normalize_bbox(entry['bbox'], args.img_width, args.img_height)

            all_proposals.append({
                'video_id': video_id,
                'timestamp': timestamp,
                'person_id': person_id,
                'bbox': bbox
            })

    with open(args.output_file, 'w') as f:
        json.dump(all_proposals, f, indent=2)

    print(f" Proposals written to {args.output_file}")

if __name__ == "__main__":
    main()
