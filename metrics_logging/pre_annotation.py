# /ava_unified_platform/routers/pre_annotation.py

import os
import pickle
import zipfile
import tempfile
import shutil
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from processing_pipeline.services.proposals_to_cvat import process_clip

router = APIRouter(
    prefix="/pre-annotation",
    tags=["1. Pre-Annotation Tool"]
)

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
    """Function to remove the temporary directory in the background."""
    shutil.rmtree(path)

@router.post("/process-clips", summary="Generate CVAT packages from proposals")
async def process_clips_endpoint(
    background_tasks: BackgroundTasks,
    pickle_file: UploadFile = File(..., description="The dense_proposals.pkl file."),
    frames_zip: UploadFile = File(..., description="A ZIP file containing all frame images.")
):
    """
    Upload a `dense_proposals.pkl` and a `frames.zip` folder to generate CVAT-ready packages.
    This endpoint processes the files and returns a single downloadable ZIP file containing all generated XMLs and clip ZIPs.
    """
    work_dir = tempfile.mkdtemp()
    pickle_path = os.path.join(work_dir, "dense_proposals.pkl")
    frame_dir = os.path.join(work_dir, "frames")
    output_zip_dir = os.path.join(work_dir, "output_zips")
    output_xml_dir = os.path.join(work_dir, "output_xmls")
    
    os.makedirs(frame_dir, exist_ok=True)
    os.makedirs(output_zip_dir, exist_ok=True)
    os.makedirs(output_xml_dir, exist_ok=True)

    # Save uploaded files
    with open(pickle_path, "wb") as f:
        shutil.copyfileobj(pickle_file.file, f)

    frames_zip_path = os.path.join(work_dir, "frames.zip")
    with open(frames_zip_path, "wb") as f:
        shutil.copyfileobj(frames_zip.file, f)
    with zipfile.ZipFile(frames_zip_path, "r") as zip_ref:
        zip_ref.extractall(frame_dir)

    try:
        with open(pickle_path, 'rb') as f:
            proposals_data = pickle.load(f)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read pickle file: {e}")


    for video_id, frames_data in proposals_data.items():
        process_clip(video_id, frames_data, frame_dir, output_zip_dir, output_xml_dir, attributes_dict)

    final_zip_path = os.path.join(work_dir, "cvat_packages.zip")
    with zipfile.ZipFile(final_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in Path(output_zip_dir).rglob("*.zip"):
            zf.write(file, arcname=f"clips/{file.name}")
        for file in Path(output_xml_dir).rglob("*.xml"):
            zf.write(file, arcname=f"xmls/{file.name}")

    background_tasks.add_task(cleanup_temp_dir, work_dir)
    
    return FileResponse(
        final_zip_path,
        media_type="application/zip",
        filename="cvat_packages.zip"
    )