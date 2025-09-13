import os
import json
import pickle
import argparse
import re
from collections import defaultdict
from tqdm import tqdm


def generate_dense_proposals(input_dir, output_path, img_width, img_height, fps):
    """
    Converts YOLOvX JSON detection files to a dense proposals PKL file.

    Args:
        input_dir (str): Directory containing the JSON detection files.
        output_path (str): Path to save the output .pkl file.
        img_width (int): The width of the video frames for normalization.
        img_height (int): The height of the video frames for normalization.
        fps (int): The frames per second of the source video to calculate timestamps.
    """
    if not os.path.isdir(input_dir):
        print(f"❌ Error: Input directory not found at '{input_dir}'")
        return

    json_files = [f for f in os.listdir(input_dir) if f.endswith('.json')]
    if not json_files:
        print(f"❌ Error: No .json files found in '{input_dir}'")
        return

    print(f"🔍 Found {len(json_files)} JSON files to process.")
    results_dict = defaultdict(list)
    score_warning_issued = False

    for json_file in tqdm(json_files, desc="Processing video clips"):
        file_path = os.path.join(input_dir, json_file)

        try:
            with open(file_path, 'r') as f:
                detections = json.load(f)
        except json.JSONDecodeError:
            print(f"\n⚠️ Warning: Skipping corrupted or empty JSON file: {json_file}")
            continue

        for det in detections:
            video_id = det['video_id']
            frame_name = det['frame']
            bbox = det['bbox']
            if 'score' in det:
                score = det['score']
            else:
                if not score_warning_issued:
                    print(
                        "\n⚠️ Warning: 'score' key not found in JSON. Defaulting to 1.0. This is not recommended for tracking.")
                    score_warning_issued = True
                score = 1.0
            match = re.search(r'(\d+)\.jpg$', frame_name)
            if not match:
                print(f"\n⚠️ Warning: Could not parse frame number from '{frame_name}'. Skipping.")
                continue

            frame_num = int(match.group(1))
            second = frame_num // fps
            key = f"{video_id},{str(second).zfill(4)}"
            x1_norm = bbox[0] / img_width
            y1_norm = bbox[1] / img_height
            x2_norm = bbox[2] / img_width
            y2_norm = bbox[3] / img_height
            detection_entry = [x1_norm, y1_norm, x2_norm, y2_norm, score]
            results_dict[key].append(detection_entry)

    if not results_dict:
        print("❌ Error: No detections were processed. Check your JSON files and input parameters.")
        return
    print(f"\n✅ Processing complete. Found detections for {len(results_dict)} unique timestamps.")
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    try:
        with open(output_path, "wb") as pkl_file:
            pickle.dump(dict(results_dict), pkl_file)
        print(f"💾 Successfully saved dense proposals to: {output_path}")
    except Exception as e:
        print(f"❌ Error saving pickle file: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert YOLOvX JSON detections to an AVA-style dense proposals PKL file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--input_dir', type=str, required=True,
                        help="Path to the directory containing YOLOvX JSON detection files.")
    parser.add_argument('--output_path', type=str, required=True,
                        help="Path to save the final dense_proposals.pkl file.")
    parser.add_argument('--width', type=int, default=1280,
                        help="Width of the source video frames for normalization.")
    parser.add_argument('--height', type=int, default=720,
                        help="Height of the source video frames for normalization.")
    parser.add_argument('--fps', type=int, default=30,
                        help="Frame rate of the source videos used for timestamp calculation.")

    args = parser.parse_args()

    generate_dense_proposals(args.input_dir, args.output_path, args.width, args.height, args.fps)


if __name__ == "__main__":
    main()