import os
import cv2
import argparse
from pathlib import Path

def clip_single_video(video_path, output_path, clip_duration=15):
    """Clips a single video file into fixed chunks and returns the clip file paths."""
    os.makedirs(output_path, exist_ok=True)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Failed to open: {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps
    basename = Path(video_path).stem

    num_clips = int(duration // clip_duration) or 1
    print(f"Clipping {basename} into {num_clips} clips...")

    clip_paths = []

    for i in range(num_clips):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i * clip_duration * fps))
        out_filename = f"{basename}_{i}.mp4"   # ✅ nice numbering
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
        clip_paths.append(out_path)

    cap.release()
    print(f"✅ All clips from {basename} saved successfully.")
    return clip_paths


def clip_video(input_path, output_path, clip_duration=15):
    """
    Clips all videos in a directory and returns a dict:
    { "video_name": [list_of_generated_clips] }
    """
    os.makedirs(output_path, exist_ok=True)
    video_files = [f for f in os.listdir(input_path) if f.endswith(('.mp4', '.avi', '.mov'))]

    all_clips = {}
    for video_file in video_files:
        video_path = os.path.join(input_path, video_file)
        video_basename = Path(video_file).stem
        clips = clip_single_video(video_path, os.path.join(output_path, video_basename), clip_duration)
        all_clips[video_basename] = clips
    
    print("✅ All videos clipped successfully.")
    return all_clips


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clip videos into chunks.")
    parser.add_argument("--input_path", required=True, help="Path to folder with input videos.")
    parser.add_argument("--output_path", required=True, help="Path to save clipped videos.")
    parser.add_argument("--clip_duration", type=int, default=15, help="Clip duration in seconds.")
    args = parser.parse_args()
    
    clip_video(args.input_path, args.output_path, args.clip_duration)
