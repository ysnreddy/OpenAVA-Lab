import os
import cv2
import json
import argparse
from tqdm import tqdm

def visualize_tracking(frames_dir, tracking_dir, output_dir, fps=1):
    os.makedirs(output_dir, exist_ok=True)
    video_ids = [f.replace('.json', '') for f in os.listdir(tracking_dir) if f.endswith('.json')]

    for video_id in tqdm(video_ids, desc="Rendering tracking videos"):
        track_path = os.path.join(tracking_dir, f"{video_id}.json")
        frame_folder = os.path.join(frames_dir, video_id)
        output_path = os.path.join(output_dir, f"{video_id}_tracked.mp4")

        with open(track_path, "r") as f:
            track_data = json.load(f)

        frame_files = sorted([f for f in os.listdir(frame_folder) if f.endswith(".jpg")])
        if not frame_files:
            print(f"No frames found for {video_id}")
            continue

        first_frame = cv2.imread(os.path.join(frame_folder, frame_files[0]))
        height, width = first_frame.shape[:2]
        out = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

        frame_dict = {}
        for entry in track_data:
            frame_dict.setdefault(entry['frame'], []).append(entry)

        for frame_file in frame_files:
            frame_path = os.path.join(frame_folder, frame_file)
            frame = cv2.imread(frame_path)
            detections = frame_dict.get(frame_file, [])

            for det in detections:
                bbox = det['bbox']
                track_id = det['track_id']
                x1, y1, x2, y2 = map(int, bbox)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"ID: {track_id}", (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

            out.write(frame)

        out.release()
    print("Tracking visualization completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize tracking output as videos.")
    parser.add_argument('--frames_dir', type=str, required=True, help="Directory with frame images.")
    parser.add_argument('--tracking_dir', type=str, required=True, help="Directory with tracking JSON files.")
    parser.add_argument('--output_dir', type=str, required=True, help="Directory to save output videos.")
    parser.add_argument('--fps', type=int, default=1, help="Frames per second for output video.")
    args = parser.parse_args()

    visualize_tracking(args.frames_dir, args.tracking_dir, args.output_dir, args.fps)
