# # routers/pre_annotation.py
# import os
# import pickle
# import zipfile
# import tempfile
# import shutil
# from pathlib import Path
# from fastapi import APIRouter, HTTPException, BackgroundTasks, Request,Body
# from fastapi.responses import JSONResponse
# import boto3 
# import uuid
# import sys
# from typing import List

# import json
# from pydantic import BaseModel
# import logging

# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO)
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# try:
#     from processing_pipeline.services.shared_config import ATTRIBUTE_DEFINITIONS
# except ImportError:
#     sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config')))
#     from processing_pipeline.services.shared_config import ATTRIBUTE_DEFINITIONS

# from processing_pipeline.services.proposals_to_cvat import process_clip
# def cleanup_temp_dir(path: str):
#     """Background cleanup."""
#     logger.info(f"🗑️ Cleaning up temporary directory: {path}")
#     shutil.rmtree(path, ignore_errors=True)

# router = APIRouter(
#     prefix="/pre-annotation",
#     tags=["1. Pre-Annotation Tool"]
# )

# class ProcessClipPayload(BaseModel):
#     pickle_key: str  # S3 key for dense_proposals.pkl
#     frames_key: str  # S3 key for frames.zip

# @router.post("/get-upload-urls", summary="Generate presigned S3 URLs for uploading files")
# async def get_upload_urls(request: Request, files: List[str] = Body(..., example=["dense_proposals.pkl", "frames.zip"], description="List of filenames to upload.")):
#     """
#     Returns presigned URLs for direct S3 upload of large files.
#     The frontend uploads files directly to S3.
#     """
#     try:
#         s3_client = request.app.state.s3_client
#         bucket = request.app.state.s3_bucket
#     except AttributeError:
#         raise HTTPException(status_code=500, detail="S3 client not configured on the application state.")

#     urls = {}
#     for filename in files:
#         key = f"uploads/{uuid.uuid4().hex}_{filename}"
#         presigned_url = s3_client.generate_presigned_url(
#             ClientMethod='put_object',
#             Params={'Bucket': bucket, 'Key': key},
#             ExpiresIn=3600,  # 1 hour
#             HttpMethod='PUT'
#         )
#         urls[filename] = {"url": presigned_url, "key": key}
    
#     return JSONResponse(content=urls)


# @router.post("/process-clips-s3", summary="Process uploaded files from S3")
# async def process_clips_s3(request: Request, background_tasks: BackgroundTasks, payload: ProcessClipPayload):
#     """
#     Downloads the dense_proposals.pkl and frames.zip from S3 keys provided in the payload.
#     Processes them locally to generate CVAT XMLs and clip ZIPs.
#     Uploads the resulting package ZIP back to S3 and returns a download URL.
#     """
#     try:
#         s3_client = request.app.state.s3_client
#         bucket = request.app.state.s3_bucket
#     except AttributeError:
#         raise HTTPException(status_code=500, detail="S3 client not configured on the application state.")

#     work_dir = tempfile.mkdtemp()
#     background_tasks.add_task(cleanup_temp_dir, work_dir)

#     pickle_path = os.path.join(work_dir, "dense_proposals.pkl")
#     frames_zip_path = os.path.join(work_dir, "frames.zip")
#     frame_dir = os.path.join(work_dir, "frames")
#     output_zip_dir = os.path.join(work_dir, "output_zips")
#     output_xml_dir = os.path.join(work_dir, "output_xmls")

#     os.makedirs(frame_dir, exist_ok=True)
#     os.makedirs(output_zip_dir, exist_ok=True)
#     os.makedirs(output_xml_dir, exist_ok=True)
    
#     logger.info(f"Processing S3 keys: {payload.pickle_key}, {payload.frames_key}")

#     try:
#         s3_client.download_file(bucket, payload.pickle_key, pickle_path)
#         s3_client.download_file(bucket, payload.frames_key, frames_zip_path)
#     except Exception as e:
#         logger.error(f"S3 download failed: {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to download files from S3: {e}")

#     try:

#         with zipfile.ZipFile(frames_zip_path, 'r') as zip_ref:
#             zip_ref.extractall(frame_dir)
#             logger.info(f"Extracted frames to {frame_dir}")

#         with open(pickle_path, 'rb') as f:
#             proposals_data = pickle.load(f)
#             logger.info(f"Loaded proposals data for {len(proposals_data)} clips.")
#     except Exception as e:
#         logger.error(f"File extraction/loading failed: {e}")
#         raise HTTPException(status_code=400, detail=f"Failed to extract or read local files: {e}")


#     try:
#         for video_id, frames_data in proposals_data.items():
#             process_clip(video_id, frames_data, frame_dir, output_zip_dir, output_xml_dir, ATTRIBUTE_DEFINITIONS)
#         logger.info("Clip processing completed.")
#     except Exception as e:
#         logger.error(f"Clip processing failed: {e}")
#         raise HTTPException(status_code=500, detail=f"Clip processing failed: {e}")

#     final_zip_path = os.path.join(work_dir, "cvat_packages.zip")
#     try:
#         with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
#             for file in Path(output_zip_dir).rglob("*.zip"):
#                 zf.write(file, arcname=f"clips/{file.name}")
#             for file in Path(output_xml_dir).rglob("*.xml"):
#                 zf.write(file, arcname=f"xmls/{file.name}")
#         logger.info(f"Final package zip created at {final_zip_path}")
#     except Exception as e:
#         logger.error(f"Final zip creation failed: {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to create final ZIP package: {e}")

#     s3_key = f"results/cvat_packages_{uuid.uuid4().hex}.zip"
#     try:
#         s3_client.upload_file(final_zip_path, bucket, s3_key)
#         logger.info(f"Result uploaded to S3 at: {s3_key}")
#     except Exception as e:
#         logger.error(f"S3 upload failed: {e}")
#         raise HTTPException(status_code=500, detail=f"Failed to upload result to S3: {e}")

#     download_url = s3_client.generate_presigned_url(
#         ClientMethod='get_object',
#         Params={'Bucket': bucket, 'Key': s3_key},
#         ExpiresIn=3600 # 1 hour
#     )

#     return {"download_url": download_url, "s3_key": s3_key, "message": "Pre-annotation package generated and uploaded to S3."}