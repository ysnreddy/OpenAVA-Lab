# tools/rename_resize.py

import os
import cv2
import argparse
from pathlib import Path

def resize_with_padding(frame, target_size=(1280, 720)):
    h, w = frame.shape[:2]
    scale = min(target_size[0] / w, target_size[1] / h)
    new_w, new_h = int(w * scale), int(h * scale)

    resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
    padded = cv2.copyMakeBorder(
        resized,
        top=(target_size[1] - new_h) // 2,
        bottom=(target_size[1] - new_h + 1) // 2,
        left=(target_size[0] - new_w) // 2,
        right=(target_size[0] - new_w + 1) // 2,
        borderType=cv2.BORDER_CONSTANT,
        value=(0, 0, 0)
    )
    return padded

def process_videos(input_dir, output_dir, target_size=(1280, 720)):
    os.makedirs(output_dir, exist_ok=True)
    # Added '.mkv' to the list of recognized video formats
    video_files = sorted([f for f in os.listdir(input_dir) if f.lower().endswith(('.mp4', '.avi', '.mov', '.mkv'))])

    for idx, video_file in enumerate(video_files, 1):
        input_path = os.path.join(input_dir, video_file)
        # The output file will have a simple numbered name with the .mp4 extension
        output_path = os.path.join(output_dir, f"{idx}.mp4")

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            print(f" Failed to open {video_file}")
            continue

        fps = cap.get(cv2.CAP_PROP_FPS)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, fps, target_size)

        print(f" Processing: {video_file} -> {idx}.mp4")

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            resized_frame = resize_with_padding(frame, target_size)
            out.write(resized_frame)

        cap.release()
        out.release()

    print(f" Completed processing {len(video_files)} videos. Output saved to: {output_dir}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Rename and resize raw CCTV clips.")
    parser.add_argument("--input_dir", required=True, help="Folder with raw videos")
    parser.add_argument("--output_dir", default="raw_videos", help="Destination for renamed and resized videos")
    args = parser.parse_args()

    process_videos(args.input_dir, args.output_dir)