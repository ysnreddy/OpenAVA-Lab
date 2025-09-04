import os
import json
import pickle
import argparse
from collections import defaultdict
from tqdm import tqdm


def generate_proposals_from_tracks(tracking_dir, output_path):
    """
    Converts tracking JSON files to a frame-based dense proposals PKL file,
    storing raw, absolute pixel coordinates.
    """
    if not os.path.isdir(tracking_dir):
        print(f"❌ Error: Tracking directory not found at '{tracking_dir}'")
        return

    json_files = [f for f in os.listdir(tracking_dir) if f.endswith('.json')]
    if not json_files:
        print(f"❌ Error: No tracking .json files found in '{tracking_dir}'")
        return

    print(f"🔍 Found {len(json_files)} tracking JSON files to process.")
    results_dict = defaultdict(lambda: defaultdict(list))

    for json_file in tqdm(json_files, desc="Processing tracked clips"):
        file_path = os.path.join(tracking_dir, json_file)

        try:
            with open(file_path, 'r') as f:
                tracked_detections = json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            print(f"\n⚠️ Warning: Skipping corrupted or empty JSON file: {json_file}")
            continue

        for det in tracked_detections:
            video_id = det.get('video_id')
            frame_name = det.get('frame')
            bbox = det.get('bbox')
            track_id = det.get('track_id')

            if not all([video_id, frame_name, bbox, track_id is not None]):
                continue
            score = 1.0
            proposal_entry = [bbox[0], bbox[1], bbox[2], bbox[3], score, track_id]
            results_dict[video_id][frame_name].append(proposal_entry)

    if not results_dict:
        print("❌ Error: No detections were processed. Check your JSON files.")
        return

    print(f"\n✅ Processing complete. Found proposals for {len(results_dict)} unique video clips.")
    final_dict = {vid: dict(frames) for vid, frames in results_dict.items()}

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    try:
        with open(output_path, "wb") as pkl_file:
            pickle.dump(final_dict, pkl_file)
        print(f"💾 Successfully saved frame-based dense proposals to: {output_path}")
    except Exception as e:
        print(f"❌ Error saving pickle file: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert tracking JSON to a frame-based dense proposals PKL file with absolute coordinates.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('--tracking_dir', type=str, required=True,
                        help="Directory containing the tracking JSON files from DeepSORT/ByteSORT.")
    parser.add_argument('--output_path', type=str, required=True,
                        help="Path to save the final dense_proposals.pkl file.")

    args = parser.parse_args()

    generate_proposals_from_tracks(args.tracking_dir, args.output_path)


if __name__ == "__main__":
    main()
