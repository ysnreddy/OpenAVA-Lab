# tools/extract_frames.py

import os
import cv2
import argparse
from pathlib import Path

def extract_frames(input_dir, output_dir, fps=1):
    os.makedirs(output_dir, exist_ok=True)
    video_files = sorted([f for f in os.listdir(input_dir) if f.endswith(('.mp4', '.avi'))])

    for video_file in video_files:
        video_path = os.path.join(input_dir, video_file)
        basename = Path(video_file).stem  # e.g., clip_000
        video_output_dir = os.path.join(output_dir, basename)
        os.makedirs(video_output_dir, exist_ok=True)

        cap = cv2.VideoCapture(video_path)
        video_fps = cap.get(cv2.CAP_PROP_FPS)
        frame_interval = int(video_fps // fps)

        frame_count = 0
        saved_frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_count % frame_interval == 0:
                frame_filename = f"{basename}_frame_{saved_frame_idx:04d}.jpg"
                frame_path = os.path.join(video_output_dir, frame_filename)
                cv2.imwrite(frame_path, frame)
                saved_frame_idx += 1
            frame_count += 1

        cap.release()

    print(" Frame extraction completed.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract frames at 1 FPS from video clips.")
    parser.add_argument("--input_dir", required=True, help="Path to folder with clipped videos.")
    parser.add_argument("--output_dir", required=True, help="Path to save extracted frames.")
    args = parser.parse_args()

    extract_frames(args.input_dir, args.output_dir)
