# /ava_unified_platform/routers/pre_annotation.py

import os
import pickle
import zipfile
import tempfile
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks, Request
from fastapi.responses import JSONResponse
import boto3
from datetime import datetime, timedelta
import uuid
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from processing_pipeline.services.proposals_to_cvat import process_clip

router = APIRouter(
    prefix="/pre-annotation",
    tags=["1. Pre-Annotation Tool"]
)

# Attributes dict
attributes_dict = {
    '1': dict(aname='walking_behavior', options={'unknown': 'unknown', 'normal_walk': 'normal_walk', 'fast_walk': 'fast_walk', 'slow_walk': 'slow_walk', 'standing_still': 'standing_still', 'jogging': 'jogging', 'window_shopping': 'window_shopping'}),
    '2': dict(aname='phone_usage', options={'unknown': 'unknown', 'no_phone': 'no_phone', 'talking_phone': 'talking_phone', 'texting': 'texting', 'taking_photo': 'taking_photo', 'listening_music': 'listening_music'}),
    '3': dict(aname='social_interaction', options={'unknown': 'unknown', 'alone': 'alone', 'talking_companion': 'talking_companion', 'group_walking': 'group_walking', 'greeting_someone': 'greeting_someone', 'asking_directions': 'asking_directions', 'avoiding_crowd': 'avoiding_crowd'}),
    '4': dict(aname='carrying_items', options={'unknown': 'unknown', 'empty_hands': 'empty_hands', 'shopping_bags': 'shopping_bags', 'backpack': 'backpack', 'briefcase_bag': 'briefcase_bag', 'umbrella': 'umbrella', 'food_drink': 'food_drink', 'multiple_items': 'multiple_items'}),
    '5': dict(aname='street_behavior', options={'unknown': 'unknown', 'sidewalk_walking': 'sidewalk_walking', 'crossing_street': 'crossing_street', 'waiting_signal': 'waiting_signal', 'looking_around': 'looking_around', 'checking_map': 'checking_map', 'entering_building': 'entering_building', 'exiting_building': 'exiting_building'}),
    '6': dict(aname='posture_gesture', options={'unknown': 'unknown', 'upright_normal': 'upright_normal', 'looking_down': 'looking_down', 'looking_up': 'looking_up', 'hands_in_pockets': 'hands_in_pockets', 'arms_crossed': 'arms_crossed', 'pointing_gesture': 'pointing_gesture', 'bowing_gesture': 'bowing_gesture'}),
    '7': dict(aname='clothing_style', options={'unknown': 'unknown', 'business_attire': 'business_attire', 'casual_wear': 'casual_wear', 'tourist_style': 'tourist_style', 'school_uniform': 'school_uniform', 'sports_wear': 'sports_wear', 'traditional_wear': 'traditional_wear'}),
    '8': dict(aname='time_context', options={'unknown': 'unknown', 'rush_hour': 'rush_hour', 'leisure_time': 'leisure_time', 'shopping_time': 'shopping_time', 'tourist_hours': 'tourist_hours', 'lunch_break': 'lunch_break', 'evening_stroll': 'evening_stroll'})
}

def cleanup_temp_dir(path: str):
    """Background cleanup."""
    shutil.rmtree(path, ignore_errors=True)


@router.post("/get-upload-urls", summary="Generate presigned S3 URLs for uploading files")
async def get_upload_urls(request: Request, files: dict):
    """
    Returns presigned URLs for direct S3 upload of large files.
    Frontend can upload files directly to S3 without hitting FastAPI.
    """
    s3_client = request.app.state.s3_client
    bucket = request.app.state.s3_bucket
    urls = {}
    for filename in files.get("files", []):
        key = f"uploads/{uuid.uuid4().hex}_{filename}"
        presigned_url = s3_client.generate_presigned_url(
            ClientMethod='put_object',
            Params={'Bucket': bucket, 'Key': key},
            ExpiresIn=3600,  # 1 hour
            HttpMethod='PUT'
        )
        urls[filename] = {"url": presigned_url, "key": key}
    return JSONResponse(content=urls)


@router.post("/process-clips-s3", summary="Process uploaded files from S3")
async def process_clips_s3(request: Request, background_tasks: BackgroundTasks, payload: dict):
    """
    Expects payload like:
    {
        "pickle_key": "uploads/abcd_dense_proposals.pkl",
        "frames_key": "uploads/abcd_frames.zip"
    }
    Downloads from S3, processes locally, uploads result back to S3, returns download URL.
    """
    s3_client = request.app.state.s3_client
    bucket = request.app.state.s3_bucket

    work_dir = tempfile.mkdtemp()
    background_tasks.add_task(cleanup_temp_dir, work_dir)

    pickle_path = os.path.join(work_dir, "dense_proposals.pkl")
    frames_zip_path = os.path.join(work_dir, "frames.zip")
    frame_dir = os.path.join(work_dir, "frames")
    output_zip_dir = os.path.join(work_dir, "output_zips")
    output_xml_dir = os.path.join(work_dir, "output_xmls")

    os.makedirs(frame_dir, exist_ok=True)
    os.makedirs(output_zip_dir, exist_ok=True)
    os.makedirs(output_xml_dir, exist_ok=True)

    # Download from S3
    try:
        s3_client.download_file(bucket, payload["pickle_key"], pickle_path)
        s3_client.download_file(bucket, payload["frames_key"], frames_zip_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to download from S3: {e}")

    # Extract frames zip
    with zipfile.ZipFile(frames_zip_path, 'r') as zip_ref:
        zip_ref.extractall(frame_dir)

    # Load proposals pickle
    try:
        with open(pickle_path, 'rb') as f:
            proposals_data = pickle.load(f)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read pickle file: {e}")

    # Process clips
    for video_id, frames_data in proposals_data.items():
        process_clip(video_id, frames_data, frame_dir, output_zip_dir, output_xml_dir, attributes_dict)

    # Create final zip
    final_zip_path = os.path.join(work_dir, "cvat_packages.zip")
    with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in Path(output_zip_dir).rglob("*.zip"):
            zf.write(file, arcname=f"clips/{file.name}")
        for file in Path(output_xml_dir).rglob("*.xml"):
            zf.write(file, arcname=f"xmls/{file.name}")

    # Upload final zip back to S3
    s3_key = f"results/cvat_packages_{uuid.uuid4().hex}.zip"
    try:
        s3_client.upload_file(final_zip_path, bucket, s3_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload result to S3: {e}")

    download_url = s3_client.generate_presigned_url(
        ClientMethod='get_object',
        Params={'Bucket': bucket, 'Key': s3_key},
        ExpiresIn=3600
    )

    return {"download_url": download_url, "s3_key": s3_key}
