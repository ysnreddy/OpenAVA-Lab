import os
import shutil
import zipfile
import uuid
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
# ✨ FIX: Import BackgroundTask from starlette
from starlette.background import BackgroundTask

# Import all your tool scripts
from tools.rename_resize import process_videos as rename_resize_videos
from tools.clip_video import clip_video
from tools.extract_frames import extract_frames
from tools.person_tracker import PersonTracker
from tools.create_proposals_from_tracks import generate_proposals_from_tracks

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- App and Directory Configuration ---
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
TEMP_DIR = BASE_DIR / "temp_processing"
FINAL_OUTPUT_DIR = BASE_DIR / "final_outputs"

for d in [UPLOAD_DIR, TEMP_DIR, FINAL_OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Processing and Annotation Pipeline")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

job_status_db = {}


class ProcessRequest(BaseModel):
    filename: str


def cleanup_temp_dir(path: str):
    if os.path.isdir(path):
        shutil.rmtree(path)
        logger.info(f"Cleaned up temporary directory: {path}")


def process_in_background(job_id: str, master_zip_path: str):
    """The main background process that runs the entire pipeline."""
    work_dir = TEMP_DIR / job_id
    try:
        job_status_db[job_id]['status'] = 'unzipping'
        raw_video_dir = work_dir / "0_raw"
        raw_video_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(master_zip_path, 'r') as zf:
            zf.extractall(raw_video_dir)

        job_status_db[job_id]['status'] = 'resizing'
        resized_video_dir = work_dir / "1_resized"
        rename_resize_videos(str(raw_video_dir), str(resized_video_dir))

        job_status_db[job_id]['status'] = 'clipping'
        clipped_dir = work_dir / "2_clipped"
        all_clipped_paths_map = clip_video(str(resized_video_dir), str(clipped_dir))
        all_clips = [path for paths in all_clipped_paths_map.values() for path in paths]

        job_status_db[job_id]['status'] = 'extracting_frames'
        frames_dir = work_dir / "3_frames"
        extract_frames(str(clipped_dir), str(frames_dir))

        job_status_db[job_id]['status'] = 'tracking'
        tracking_json_dir = work_dir / "4_tracking_json"
        tracking_json_dir.mkdir()

        for clip_path_str in all_clips:
            clip_path = Path(clip_path_str)
            clip_stem = clip_path.stem
            logger.info(f"[{job_id}] Tracking clip: {clip_stem}")

            tracker = PersonTracker(video_id=clip_stem, conf=0.45)
            tracker.process_video(str(clip_path), str(tracking_json_dir))

        job_status_db[job_id]['status'] = 'generating_proposals'
        proposals_dir = work_dir / "5_proposals"
        proposals_dir.mkdir()
        proposals_pkl_path = proposals_dir / "dense_proposals.pkl"
        generate_proposals_from_tracks(str(tracking_json_dir), str(proposals_pkl_path))

        job_status_db[job_id]['status'] = 'packaging'
        final_proposals_path = FINAL_OUTPUT_DIR / f"{job_id}_dense_proposals.pkl"
        final_frames_zip_path = FINAL_OUTPUT_DIR / f"{job_id}_frames.zip"
        shutil.move(proposals_pkl_path, final_proposals_path)

        with zipfile.ZipFile(final_frames_zip_path, 'w', zipfile.ZIP_DEFLATED) as master_zip:
            master_zip.writestr("frames/", "")
            for clip_folder in Path(frames_dir).iterdir():
                if clip_folder.is_dir():
                    clip_frames_zip_path = work_dir / f"{clip_folder.name}.zip"
                    with zipfile.ZipFile(clip_frames_zip_path, 'w', zipfile.ZIP_DEFLATED) as clip_zip:
                        for frame_file in clip_folder.glob("*.jpg"):
                            clip_zip.write(frame_file, arcname=frame_file.name)
                    master_zip.write(clip_frames_zip_path, arcname=f"frames/{clip_frames_zip_path.name}")

        job_status_db[job_id]['status'] = 'completed'
        job_status_db[job_id]['result_paths'] = {
            "proposals_pkl": str(final_proposals_path),
            "frames_zip": str(final_frames_zip_path)
        }
    except Exception as e:
        logger.error(f"[{job_id}] Processing failed: {e}", exc_info=True)
        job_status_db[job_id]['status'] = 'failed'
        job_status_db[job_id]['error'] = str(e)
    finally:
        cleanup_temp_dir(str(work_dir))


@app.get("/list_videos/")
async def list_available_videos():
    """Lists the ZIP files available in the upload directory."""
    try:
        files = [f for f in os.listdir(UPLOAD_DIR) if f.lower().endswith('.zip')]
        return {"files": files}
    except FileNotFoundError:
        return {"files": []}


@app.post("/start_processing/")
async def create_processing_job(request: ProcessRequest, background_tasks: BackgroundTasks):
    """Starts the pipeline in the background using a file already on the server."""
    job_id = str(uuid.uuid4())

    master_zip_path = UPLOAD_DIR / request.filename
    if not master_zip_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found in upload directory: {request.filename}")

    job_status_db[job_id] = {"status": "pending", "filename": request.filename}
    background_tasks.add_task(process_in_background, job_id, str(master_zip_path))

    return {"message": "Processing started.", "job_id": job_id}


@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    job = job_status_db.get(job_id)
    if not job: raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.get("/download/{job_id}/{file_type}", response_class=FileResponse)
async def download_package(job_id: str, file_type: str):
    """Download one of the final output files."""
    job = job_status_db.get(job_id)
    if not job or job['status'] != 'completed':
        raise HTTPException(status_code=404, detail="Package not ready or job not found.")
    file_path_str = job.get('result_paths', {}).get(file_type)
    if not file_path_str or not os.path.exists(file_path_str):
        raise HTTPException(status_code=404, detail="Result file not found.")

    # ✨ FIX: Removed the background task to prevent deleting the file on download.
    return FileResponse(
        file_path_str,
        media_type="application/octet-stream",
        filename=os.path.basename(file_path_str)
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

