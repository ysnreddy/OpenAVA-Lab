# tools/clip_video.py

#This script clips video files into 15-second chunks and saves them to a specified output directory

import os
import cv2
import argparse
from pathlib import Path

def clip_video(input_path, output_path, clip_duration=15):
    os.makedirs(output_path, exist_ok=True)
    video_files = [f for f in os.listdir(input_path) if f.endswith(('.mp4', '.avi', '.mov'))]

    for video_file in video_files:
        video_path = os.path.join(input_path, video_file)
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            print(f"Failed to open: {video_path}")
            continue

        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        basename = Path(video_file).stem

        num_clips = int(duration // clip_duration)
        print(f"Clipping {video_file} into {num_clips} clips...")

        for i in range(num_clips):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i * clip_duration * fps))
            out_filename = f"{basename}_clip_{i:03d}.mp4"
            out_path = os.path.join(output_path, out_filename)

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            out = cv2.VideoWriter(out_path, fourcc, fps, (width, height))

            for _ in range(int(clip_duration * fps)):
                ret, frame = cap.read()
                if not ret:
                    break
                out.write(frame)
            out.release()
        cap.release()

    print(" All videos clipped successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clip videos into 15-second chunks.")
    parser.add_argument("--input_path", required=True, help="Path to folder with input videos.")
    parser.add_argument("--output_path", required=True, help="Path to save clipped videos.")
    parser.add_argument("--clip_duration", type=int, default=15, help="Clip duration in seconds.")
    args = parser.parse_args()

    clip_video(args.input_path, args.output_path, args.clip_duration)
