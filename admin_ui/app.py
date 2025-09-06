# # app.py (fixed)
# import os
# import shutil
# import zipfile
# import json
# import glob
# from pathlib import Path
# from fastapi import FastAPI, UploadFile, File, HTTPException
# from fastapi.responses import FileResponse
# from fastapi.middleware.cors import CORSMiddleware
# from tools import clip_video, extract_frames, person_tracker, dense_proposals_train

# # ------------------- Directory Configuration -------------------
# BASE_DIR = Path(__file__).resolve().parent
# UPLOAD_DIR = BASE_DIR / "uploads"
# CLIP_DIR = BASE_DIR / "tracking_video_clip"
# FRAME_DIR = BASE_DIR / "tracking_frames"
# JSON_DIR = BASE_DIR / "tracking_json"
# DENSE_DIR = BASE_DIR / "dense_proposals"
# ZIP_DIR = BASE_DIR / "temp_zips"

# # Creating all necessary directories
# for d in [UPLOAD_DIR, CLIP_DIR, FRAME_DIR, JSON_DIR, DENSE_DIR, ZIP_DIR]:
#     d.mkdir(parents=True, exist_ok=True)

# app = FastAPI(title="Video Processing API")
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"]
# )
# MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB


# # ---------------- Upload Video ----------------
# @app.post("/upload_video/")
# async def upload_video(file: UploadFile = File(...)):
#     """Upload a video file to the server."""
#     file_path = UPLOAD_DIR / file.filename
#     with open(file_path, "wb") as f:
#         shutil.copyfileobj(file.file, f)
#     return {"filename": file.filename, "path": str(file_path)}


# # ---------------- Helper: safe find json ----------------
# def find_json_for_clip(json_dir: Path, clip_stem: str):
#     """
#     Attempt to locate a json file for a clip (if tracker returned None).
#     Returns Path or None.
#     """
#     if not json_dir.exists():
#         return None
#     # look for exact match first
#     candidate = json_dir / f"{clip_stem}.json"
#     if candidate.exists():
#         return candidate
#     # fallback: search any json that starts with clip_stem
#     pattern = str(json_dir / f"{clip_stem}*.json")
#     matches = glob.glob(pattern)
#     if matches:
#         return Path(matches[0])
#     return None


# # ---------------- Process Video ----------------
# @app.post("/process_video/")
# def process_video(file_name: str):
#     """
#     Process an uploaded video:
#       - clip into 15s chunks (saved under tracking_video_clip/<video_id>/)
#       - extract frames (tracking_frames/<video_id>/<clip_stem>/...)
#       - run person tracking on each clip (tracking_json/<video_id>/<clip_stem>.json)
#       - generate dense_proposals.pkl from the jsons
#       - create separate zip files: <clip>_video.zip, <clip>_json.zip, <clip>_frames.zip and dense_proposals.zip
#     Returns JSON with created zip file names and paths.
#     """
#     input_path = UPLOAD_DIR / file_name
#     if not input_path.exists():
#         raise HTTPException(status_code=404, detail="Uploaded file not found.")

#     print(f"Starting processing for file: {file_name}")

#     video_id = Path(file_name).stem
#     clip_output_dir = CLIP_DIR / video_id
#     frame_output_dir = FRAME_DIR / video_id
#     json_output_dir = JSON_DIR / video_id

#     clip_output_dir.mkdir(exist_ok=True, parents=True)
#     frame_output_dir.mkdir(exist_ok=True, parents=True)
#     json_output_dir.mkdir(exist_ok=True, parents=True)

#     # Step 1: Clip the video
#     print("Step 1: Clipping video...")
#     clipped_file_paths = clip_video.clip_single_video(str(input_path), str(clip_output_dir), clip_duration=15)
#     # clip_single_video should return a list of paths (or [] on failure)
#     if not clipped_file_paths:
#         raise HTTPException(status_code=500, detail="Video clipping failed. No clips were generated.")

#     created_zips = []

#     # Step 2: Extract frames for all clips (extract_frames will create subfolders based on clip name)
#     print("Step 2: Extracting frames for clips...")
#     extract_frames.extract_frames(str(clip_output_dir), str(frame_output_dir), fps=1)

#     # Step 3: Run person tracking for each clip and create per-clip zips
#     print("Step 3: Running person tracking for each clip...")
#     for clip_path in clipped_file_paths:
#         clip_path = Path(clip_path)
#         clip_name = clip_path.name                      # e.g. "1_clip_000_0.mp4"
#         clip_stem = clip_path.stem                      # e.g. "1_clip_000_0"
#         print(f"Processing clip: {clip_name}")

#         # Run tracker - expect this function to return json path (string). But be defensive.
#         tracker = person_tracker.PersonTracker(video_id=clip_stem, conf=0.5)
#         try:
#             json_result = tracker.process_video(str(clip_path), output_json_dir=str(json_output_dir), fps=1)
#         except Exception as e:
#             print(f"Tracker raised exception for {clip_name}: {e}")
#             json_result = None

#         # If tracker returned nothing (None), try to find created json
#         if not json_result:
#             located = find_json_for_clip(json_output_dir, clip_stem)
#             if located:
#                 json_path = located
#                 print(f"Tracker did not return path — found JSON at: {json_path}")
#             else:
#                 json_path = None
#                 print(f"Warning: JSON for clip {clip_stem} not found.")
#         else:
#             json_path = Path(json_result)

#         # Make clip zip (video only)
#         video_zip = ZIP_DIR / f"{clip_stem}_video.zip"
#         if video_zip.exists():
#             video_zip.unlink()
#         try:
#             with zipfile.ZipFile(video_zip, "w", zipfile.ZIP_DEFLATED) as zf:
#                 zf.write(clip_path, arcname=clip_path.name)
#             created_zips.append(str(video_zip))
#         except Exception as e:
#             print(f"Failed to create video zip for {clip_name}: {e}")

#         # Make json zip (if exists)
#         if json_path and json_path.exists():
#             json_zip = ZIP_DIR / f"{clip_stem}_json.zip"
#             if json_zip.exists():
#                 json_zip.unlink()
#             try:
#                 with zipfile.ZipFile(json_zip, "w", zipfile.ZIP_DEFLATED) as zf:
#                     zf.write(json_path, arcname=json_path.name)
#                 created_zips.append(str(json_zip))
#             except Exception as e:
#                 print(f"Failed to create json zip for {clip_name}: {e}")

#         # Make frames zip for this clip (frames are in FRAME_DIR / video_id / clip_stem)
#         frames_root = FRAME_DIR / video_id / clip_stem
#         if frames_root.exists() and frames_root.is_dir():
#             frames_zip = ZIP_DIR / f"{clip_stem}_frames.zip"
#             if frames_zip.exists():
#                 frames_zip.unlink()
#             try:
#                 with zipfile.ZipFile(frames_zip, "w", zipfile.ZIP_DEFLATED) as zf:
#                     # add all jpg/png files inside frames_root
#                     for root, _, files in os.walk(frames_root):
#                         for fname in files:
#                             file_path = Path(root) / fname
#                             arcname = file_path.relative_to(frames_root)
#                             zf.write(file_path, arcname=str(arcname))
#                 created_zips.append(str(frames_zip))
#             except Exception as e:
#                 print(f"Failed to create frames zip for {clip_name}: {e}")
#         else:
#             print(f"No frames folder found at {frames_root} for clip {clip_stem}")

#     # Step 4: Generate dense proposals from all jsons (if any)
#     print("Step 4: Generating dense_proposals.pkl...")
#     dense_output = DENSE_DIR / "dense_proposals.pkl"
#     try:
#         dense_proposals_train.generate_dense_proposals(str(json_output_dir), str(dense_output), img_width=1280, img_height=720, fps=15)
#         # zip proposals
#         proposals_zip = ZIP_DIR / "dense_proposals.zip"
#         if proposals_zip.exists():
#             proposals_zip.unlink()
#         with zipfile.ZipFile(proposals_zip, "w", zipfile.ZIP_DEFLATED) as zf:
#             zf.write(dense_output, arcname=dense_output.name)
#         created_zips.append(str(proposals_zip))
#     except Exception as e:
#         print(f"Failed to generate or zip dense proposals: {e}")

#     print("Processing complete 🎉")
#     return {
#         "status": "success",
#         "video_id": video_id,
#         "created_zips": created_zips
#     }


# # ---------------- Download Endpoints (unchanged) ----------------
# @app.get("/download_clip/{video_id}/{clip_name}")
# def download_clip(video_id: str, clip_name: str):
#     """Download a video clip inside a zip."""
#     clip_path = CLIP_DIR / video_id / clip_name
#     if not clip_path.exists():
#         raise HTTPException(status_code=404, detail="Clip not found.")
#     zip_path = ZIP_DIR / f"{Path(clip_name).stem}_video.zip"
#     if zip_path.exists():
#         os.remove(zip_path)
#     with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
#         zf.write(clip_path, clip_path.name)
#     return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)


# @app.get("/download_json/{video_id}/{json_name}")
# def download_json(video_id: str, json_name: str):
#     """Download JSON results inside a zip."""
#     json_path = JSON_DIR / video_id / json_name
#     if not json_path.exists():
#         raise HTTPException(status_code=404, detail="JSON not found.")
#     zip_path = ZIP_DIR / f"{Path(json_name).stem}_json.zip"
#     if zip_path.exists():
#         os.remove(zip_path)
#     with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
#         zf.write(json_path, json_path.name)
#     return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)


# @app.get("/download_dense_proposals/")
# def download_dense_proposals():
#     """Download dense proposals inside a zip."""
#     pkl_path = DENSE_DIR / "dense_proposals.pkl"
#     if not pkl_path.exists():
#         raise HTTPException(status_code=404, detail="dense_proposals.pkl not found.")
#     zip_path = ZIP_DIR / "dense_proposals.zip"
#     if zip_path.exists():
#         os.remove(zip_path)
#     with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
#         zf.write(pkl_path, pkl_path.name)
#     return FileResponse(zip_path, media_type="application/octet-stream", filename=zip_path.name)


# @app.get("/download_frames/{video_id}")
# def download_frames(video_id: str):
#     """Download all extracted frames inside a zip."""
#     frames_path = FRAME_DIR / video_id
#     if not frames_path.is_dir():
#         raise HTTPException(status_code=404, detail="Frames not found.")
#     zip_path = ZIP_DIR / f"{video_id}_frames.zip"
#     if zip_path.exists():
#         os.remove(zip_path)
#     with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
#         for root, _, files in os.walk(frames_path):
#             for file in files:
#                 file_path = Path(root) / file
#                 arcname = file_path.relative_to(frames_path)
#                 zf.write(file_path, arcname=arcname)
#     return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)




























import os
import shutil
import zipfile
import glob
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from tools import clip_video, extract_frames, person_tracker, dense_proposals_train

# ------------------- Directory Configuration -------------------
BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
CLIP_DIR = BASE_DIR / "tracking_video_clip"
FRAME_DIR = BASE_DIR / "tracking_frames"
JSON_DIR = BASE_DIR / "tracking_json"
DENSE_DIR = BASE_DIR / "dense_proposals"
ZIP_DIR = BASE_DIR / "temp_zips"

# Create directories
for d in [UPLOAD_DIR, CLIP_DIR, FRAME_DIR, JSON_DIR, DENSE_DIR, ZIP_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Processing API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# Mount temp_zips as /static so Streamlit can download
app.mount("/static", StaticFiles(directory=ZIP_DIR), name="static")

MAX_FILE_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB

# ---------------- Upload Video ----------------
@app.post("/upload_video/")
async def upload_video(file: UploadFile = File(...)):
    file_path = UPLOAD_DIR / file.filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"filename": file.filename, "path": str(file_path)}

# ---------------- Helper: safe find json ----------------
def find_json_for_clip(json_dir: Path, clip_stem: str):
    if not json_dir.exists():
        return None
    candidate = json_dir / f"{clip_stem}.json"
    if candidate.exists():
        return candidate
    matches = glob.glob(str(json_dir / f"{clip_stem}*.json"))
    if matches:
        return Path(matches[0])
    return None

# ---------------- Process Video ----------------
@app.post("/process_video/")
def process_video(file_name: str):
    input_path = UPLOAD_DIR / file_name
    if not input_path.exists():
        raise HTTPException(status_code=404, detail="Uploaded file not found.")

    video_id = Path(file_name).stem
    clip_output_dir = CLIP_DIR / video_id
    frame_output_dir = FRAME_DIR / video_id
    json_output_dir = JSON_DIR / video_id

    clip_output_dir.mkdir(exist_ok=True, parents=True)
    frame_output_dir.mkdir(exist_ok=True, parents=True)
    json_output_dir.mkdir(exist_ok=True, parents=True)

    # Step 1: Clip video
    clipped_file_paths = clip_video.clip_single_video(str(input_path), str(clip_output_dir), clip_duration=15)
    if not clipped_file_paths:
        raise HTTPException(status_code=500, detail="Video clipping failed.")

    created_zips = []

    # Step 2: Extract frames
    extract_frames.extract_frames(str(clip_output_dir), str(frame_output_dir), fps=1)

    # Step 3: Person tracking per clip
    for clip_path in clipped_file_paths:
        clip_path = Path(clip_path)
        clip_stem = clip_path.stem

        tracker = person_tracker.PersonTracker(video_id=clip_stem, conf=0.5)
        try:
            json_result = tracker.process_video(str(clip_path), output_json_dir=str(json_output_dir), fps=1)
        except Exception:
            json_result = None

        json_path = Path(json_result) if json_result else find_json_for_clip(json_output_dir, clip_stem)

        # Create video zip
        video_zip = ZIP_DIR / f"{clip_stem}_video.zip"
        if video_zip.exists(): video_zip.unlink()
        with zipfile.ZipFile(video_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(clip_path, arcname=clip_path.name)
        created_zips.append(str(video_zip))

        # Create json zip
        if json_path and json_path.exists():
            json_zip = ZIP_DIR / f"{clip_stem}_json.zip"
            if json_zip.exists(): json_zip.unlink()
            with zipfile.ZipFile(json_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(json_path, arcname=json_path.name)
            created_zips.append(str(json_zip))

        # Create frames zip
        frames_root = FRAME_DIR / video_id / clip_stem
        if frames_root.exists():
            frames_zip = ZIP_DIR / f"{clip_stem}_frames.zip"
            if frames_zip.exists(): frames_zip.unlink()
            with zipfile.ZipFile(frames_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(frames_root):
                    for fname in files:
                        file_path = Path(root) / fname
                        arcname = file_path.relative_to(frames_root)
                        zf.write(file_path, arcname=str(arcname))
            created_zips.append(str(frames_zip))

    # Step 4: Dense proposals
    dense_output = DENSE_DIR / "dense_proposals.pkl"
    dense_proposals_train.generate_dense_proposals(str(json_output_dir), str(dense_output), img_width=1280, img_height=720, fps=15)
    proposals_zip = ZIP_DIR / "dense_proposals.zip"
    if proposals_zip.exists(): proposals_zip.unlink()
    with zipfile.ZipFile(proposals_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(dense_output, arcname=dense_output.name)
    created_zips.append(str(proposals_zip))

    return {"status": "success", "video_id": video_id, "created_zips": [Path(p).name for p in created_zips]}
