import os
import shutil
import zipfile
from pathlib import Path
import argparse
from tqdm import tqdm
import logging

# Import the functions/classes from your tool scripts
from tools.rename_resize import process_videos as rename_resize_videos
from tools.clip_video import clip_video
from tools.person_tracker import PersonTracker
from tools.create_proposals_from_tracks import generate_proposals_from_tracks

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def run_pipeline(zip_file_path: str, output_dir: str):
    """
    Runs the entire pre-processing pipeline from a master ZIP of raw videos
    to final packaged outputs, with stage-wise progress tracking.
    """
    base_output_path = Path(output_dir)
    # Use a temporary directory for all intermediate files
    work_dir = base_output_path / "temp_processing"

    # ✨ CHANGE: Updated to 7 total stages to include JSON packaging
    total_stages = 7
    with tqdm(total=total_stages, desc="Initializing Pipeline", bar_format="{l_bar}{bar:10}{r_bar}") as pbar:
        try:
            # --- 1. Define and Create Directory Structure ---
            raw_video_dir = work_dir / "0_raw_videos"
            resized_dir = work_dir / "1_resized_videos"
            clipped_dir = work_dir / "2_clipped_videos"
            frames_dir = work_dir / "3_tracking_frames"
            json_dir = work_dir / "4_tracking_json"

            for d in [work_dir, raw_video_dir, resized_dir, clipped_dir, frames_dir, json_dir, base_output_path]:
                d.mkdir(parents=True, exist_ok=True)
            logger.info("✅ Directory structure created successfully.")

            # --- Stage 1: Unzip Master Video File ---
            pbar.set_description("[Stage 1/7] Unzipping Master File")
            with zipfile.ZipFile(zip_file_path, 'r') as zf:
                zf.extractall(raw_video_dir)
            pbar.update(1)

            # --- Stage 2: Rename & Resize ---
            pbar.set_description("[Stage 2/7] Renaming & Resizing")
            rename_resize_videos(str(raw_video_dir), str(resized_dir))
            pbar.update(1)

            # --- Stage 3: Clip Videos ---
            pbar.set_description("[Stage 3/7] Clipping Videos")
            clip_video(str(resized_dir), str(clipped_dir))
            pbar.update(1)

            # --- Stage 4: Track & Extract Frames for each clip ---
            pbar.set_description("[Stage 4/7] Tracking & Extracting")
            all_clips_to_process = list(Path(clipped_dir).rglob("*.mp4"))

            for clip_path in tqdm(all_clips_to_process, desc="  -> Tracking individual clips", leave=False):
                clip_stem = clip_path.stem
                clip_frame_output_dir = frames_dir / clip_stem
                clip_frame_output_dir.mkdir(exist_ok=True)

                tracker = PersonTracker(video_id=clip_stem, conf=0.45)
                tracker.process_video(
                    video_path=str(clip_path),
                    output_json_dir=str(json_dir),
                    output_frame_dir=str(clip_frame_output_dir)
                )
            pbar.update(1)

            # --- Stage 5: Generate Dense Proposals ---
            pbar.set_description("[Stage 5/7] Generating Proposals")
            proposals_pkl_path = base_output_path / "dense_proposals.pkl"
            generate_proposals_from_tracks(str(json_dir), str(proposals_pkl_path))
            pbar.update(1)

            # --- Stage 6: Package Final Frames ---
            pbar.set_description("[Stage 6/7] Packaging Frames")
            frames_zip_path = base_output_path / "frames.zip"
            with zipfile.ZipFile(frames_zip_path, 'w', zipfile.ZIP_DEFLATED) as master_zip:
                master_zip.writestr("frames/", "")

                for clip_folder in tqdm(Path(frames_dir).iterdir(), desc="  -> Zipping frame packages", leave=False):
                    if clip_folder.is_dir():
                        temp_clip_zip = work_dir / f"{clip_folder.name}.zip"
                        with zipfile.ZipFile(temp_clip_zip, 'w', zipfile.ZIP_DEFLATED) as clip_zip:
                            for frame_file in clip_folder.glob("*.jpg"):
                                clip_zip.write(frame_file, arcname=frame_file.name)
                        master_zip.write(temp_clip_zip, arcname=f"frames/{temp_clip_zip.name}")
                        os.remove(temp_clip_zip)
            pbar.update(1)

            # --- ✨ NEW: Stage 7: Package Tracking JSONs ---
            pbar.set_description("[Stage 7/7] Packaging JSONs")
            json_zip_path = base_output_path / "tracking_jsons.zip"
            with zipfile.ZipFile(json_zip_path, 'w', zipfile.ZIP_DEFLATED) as json_zip:
                for json_file in Path(json_dir).glob("*.json"):
                    json_zip.write(json_file, arcname=json_file.name)
            pbar.update(1)

            pbar.set_description("✅ Pipeline Complete!")
            logger.info(f"\n🎉🎉🎉 Pipeline complete! Final outputs are in: {base_output_path}")

        finally:
            # --- Cleanup ---
            if work_dir.exists():
                logger.info(f"Cleaning up temporary directory: {work_dir}")
                shutil.rmtree(work_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the full video pre-processing pipeline from a single ZIP file.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    PROJECT_ROOT = Path(__file__).resolve().parent

    parser.add_argument(
        "--zip_file_name",
        required=True,
        help="Name of the master ZIP file located in the 'uploads/' directory."
    )
    args = parser.parse_args()

    input_zip = PROJECT_ROOT / "uploads" / args.zip_file_name
    output_path = PROJECT_ROOT / "outputs"

    if not input_zip.exists():
        logger.error(f"Input file not found: {input_zip}")
    else:
        run_pipeline(str(input_zip), str(output_path))

