# /ava_unified_platform/routers/quality_control.py

import os
import pandas as pd
from typing import List
from fastapi import APIRouter, HTTPException, Body, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import sys
import uuid
import tempfile
import shutil
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from database import get_db_connection, get_db_params
from processing_pipeline.services.quality_service import QualityService
from processing_pipeline.services.dataset_generator import DatasetGenerator

router = APIRouter(
    prefix="/quality-control",
    tags=["3. Quality Control & Dataset Generation"]
)

FRAME_DIR_PATH = "/path/to/frames"  # fallback default, can be overridden in requests

class QCStatusUpdateRequest(BaseModel):
    task_ids: List[int] = Field(..., example=[101, 102], description="List of task IDs to update.")
    new_status: str = Field(..., example="approved", description="The new status, either 'approved' or 'rejected'.")

class DatasetRequest(BaseModel):
    output_filename: str = Field("final_ava_dataset.csv", description="The name of the output CSV file.")
    frames_root_directory: str = Field(FRAME_DIR_PATH, description="Absolute path to the root directory containing frame images.")
    s3_upload: bool = Field(True, description="Whether to upload the final dataset to S3.")

def cleanup_temp_dir(path: str):
    """Background cleanup."""
    shutil.rmtree(path, ignore_errors=True)

# ----------------- S3 Presigned URL endpoint -----------------

@router.post("/get-upload-url", summary="Generate presigned URL for uploading dataset")
async def get_upload_url(request: Request, filename: str = "upload.csv"):
    """
    Returns a presigned URL for direct S3 upload.
    """
    s3_client = request.app.state.s3_client
    bucket = request.app.state.s3_bucket
    key = f"uploads/{uuid.uuid4().hex}_{filename}"
    presigned_url = s3_client.generate_presigned_url(
        ClientMethod='put_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=3600,  # 1 hour
        HttpMethod='PUT'
    )
    return {"url": presigned_url, "key": key}

# ----------------- Standard endpoints -----------------

@router.get("/projects", summary="List all projects from the database")
def list_projects():
    with get_db_connection() as conn:
        df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
    if df.empty:
        return {"message": "No projects found."}
    return {"projects": df['project_id'].tolist()}

@router.get("/projects/{project_id}/tasks", summary="Get all tasks for a specific project")
def get_project_tasks(project_id: int):
    with get_db_connection() as conn:
        query = "SELECT task_id, name, assignee, status, qc_status FROM tasks WHERE project_id = %s ORDER BY task_id"
        df = pd.read_sql(query, conn, params=(project_id,))
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No tasks found for project ID {project_id}.")
    return df.to_dict(orient='records')

@router.post("/run-iaa-check", summary="Run Inter-Annotator Agreement check")
def run_iaa_check(task_pair: List[int] = Body(..., example=[101, 102])):
    if len(task_pair) != 2:
        raise HTTPException(status_code=400, detail="Please provide exactly two task IDs for comparison.")
        
    qc_service = QualityService(get_db_params())
    results = qc_service.run_quality_check(task_pair[0], task_pair[1])
    
    if "error" in results:
        raise HTTPException(status_code=404, detail=results["error"])
        
    return results

@router.post("/update-task-status", summary="Approve or reject tasks")
def update_task_qc_status(request: QCStatusUpdateRequest):
    if request.new_status not in ["approved", "rejected"]:
        raise HTTPException(status_code=400, detail="Status must be 'approved' or 'rejected'.")
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tasks SET qc_status = %s WHERE task_id = ANY(%s)", (request.new_status, request.task_ids))
        conn.commit()
        
    return {"message": f"Successfully updated {len(request.task_ids)} tasks to '{request.new_status}'."}

# ----------------- S3-based dataset generation -----------------

@router.post("/generate-dataset-s3", summary="Generate final AVA dataset CSV and upload to S3")
def generate_final_dataset_s3(request: Request, background_tasks: BackgroundTasks, payload: DatasetRequest):
    """
    Generates final CSV from approved annotations, uploads to S3, and returns download URL.
    """
    s3_client = request.app.state.s3_client
    bucket = request.app.state.s3_bucket

    # Temporary local path
    work_dir = tempfile.mkdtemp()
    background_tasks.add_task(cleanup_temp_dir, work_dir)
    output_path = os.path.join(work_dir, payload.output_filename)

    try:
        generator = DatasetGenerator(get_db_params(), payload.frames_root_directory)
        generator.generate_ava_csv(output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dataset generation failed: {e}")

    if not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Output file was not generated.")

    if payload.s3_upload:
        s3_key = f"results/{uuid.uuid4().hex}_{payload.output_filename}"
        try:
            s3_client.upload_file(output_path, bucket, s3_key)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to upload CSV to S3: {e}")

        download_url = s3_client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': bucket, 'Key': s3_key},
            ExpiresIn=3600
        )
        return {"download_url": download_url, "s3_key": s3_key}
    else:
        # Direct download from FastAPI (only for small datasets)
        return FileResponse(output_path, media_type='text/csv', filename=payload.output_filename)
