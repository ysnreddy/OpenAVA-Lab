# routers/s3_quality_control.py (Updated for S3 and Metrics)

import os
import time
import pandas as pd
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Body, Request, BackgroundTasks
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from .metrics_logger import log_metric
import sys
import uuid
import tempfile
import shutil
import logging

logger = logging.getLogger(__name__)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


try:
    from database import get_db_connection, get_db_params
    from processing_pipeline.services.quality_service import QualityService
    from processing_pipeline.services.dataset_generator import DatasetGenerator
    from .metrics_logger import log_metric
    from config import FRAME_DIR_PATH
except ImportError as e:

    logger.error(f"Failed to import from internal modules: {e}")
    # Using a fallback for FRAME_DIR_PATH if config import fails
    FRAME_DIR_PATH = "data/frames" 

# ----------------------------- Helper -----------------------------
def cleanup_temp_dir(path: str):
    """Background cleanup."""
    logger.info(f"🗑️ Cleaning up temporary directory: {path}")
    shutil.rmtree(path, ignore_errors=True)

# ----------------------------- Router -----------------------------
router = APIRouter(
    prefix="/quality-control",
    tags=["3. Quality Control & Dataset Generation"]
)

# ----------------- Request Models -----------------

class QCStatusUpdateRequest(BaseModel):
    task_ids: List[int] = Field(..., example=[101, 102], description="List of task IDs to update.")
    new_status: str = Field(..., example="approved", description="The new status, either 'approved', 'rejected', or 'pending'.")

class DatasetRequest(BaseModel):
    output_filename: str = Field("final_ava_dataset.csv", description="The name of the output CSV file.")
    frames_root_directory: str = Field(FRAME_DIR_PATH, description="Absolute path to the root directory containing frame images.")
    project_id: Optional[int] = Field(None, description="Optional project id to filter the data and attach to the export log.")
    s3_upload: bool = Field(True, description="Whether to upload the final dataset to S3. If False, returns the file directly.")


# ----------------- S3 Presigned URL endpoint -----------------

@router.post("/get-upload-url", summary="Generate presigned URL for uploading dataset")
async def get_upload_url(request: Request, filename: str = "upload.csv"):
    """
    Returns a presigned URL for direct S3 upload.
    """
    try:
        s3_client = request.app.state.s3_client
        bucket = request.app.state.s3_bucket
    except AttributeError:
        raise HTTPException(status_code=500, detail="S3 client not configured on the application state.")
        
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
    """Fetches a list of all unique project IDs that have tasks in the database."""
    try:
        with get_db_connection() as conn:
            df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
        
        if df.empty:
            return {"message": "No projects found."}
        return {"projects": df['project_id'].tolist()}
    except Exception as e:
        logger.error(f"Error fetching projects: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@router.get("/projects/{project_id}/tasks", summary="Get all tasks for a specific project")
def get_project_tasks(project_id: int):
    """Retrieves a detailed list of all tasks associated with a given project ID."""
    try:
        with get_db_connection() as conn:
            query = "SELECT task_id, name, assignee, status, qc_status FROM tasks WHERE project_id = %s ORDER BY task_id"
            df = pd.read_sql(query, conn, params=(project_id,))
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No tasks found for project ID {project_id}.")
        
        return df.to_dict(orient='records')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tasks for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

@router.post("/run-iaa-check", summary="Run Inter-Annotator Agreement check")
def run_iaa_check(data: dict = Body(..., example={"task_ids": [101, 102]})):
    """Run IAA check for exactly two tasks."""
    task_pair = data.get("task_ids", [])
    if len(task_pair) != 2:
        raise HTTPException(status_code=400, detail="Please provide exactly two task IDs for comparison.")
        
    try:
        qc_service = QualityService(get_db_params())
        results = qc_service.run_quality_check(task_pair[0], task_pair[1])
        
        if "error" in results:
            logger.error(f"IAA check failed: {results['error']}")
            raise HTTPException(status_code=404, detail=results["error"])
        
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during IAA check: {e}")
        raise HTTPException(status_code=500, detail=f"IAA check failed: {e}")

@router.post("/update-task-status", summary="Approve, reject, or mark as pending tasks")
def update_task_qc_status(request: QCStatusUpdateRequest):
    """Updates the 'qc_status' field for one or more tasks."""
    if request.new_status not in ["approved", "rejected", "pending"]:
        raise HTTPException(status_code=400, detail="Status must be 'approved', 'rejected', or 'pending'.")
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET qc_status = %s WHERE task_id = ANY(%s)",
                (request.new_status, request.task_ids)
            )
        conn.commit()
        
    return {"message": f"Successfully updated {len(request.task_ids)} tasks to '{request.new_status}'."}


@router.post("/generate-dataset-s3", summary="Generate final AVA dataset CSV and upload to S3")
def generate_final_dataset_s3(request: Request, background_tasks: BackgroundTasks, payload: DatasetRequest):
    """
    Generates final CSV from approved annotations, uploads to S3, and returns download URL.
    Logs 'export_time' metric.
    """
    try:
        s3_client = request.app.state.s3_client
        bucket = request.app.state.s3_bucket
    except AttributeError:

        if payload.s3_upload:
            raise HTTPException(status_code=500, detail="S3 client is required but not configured on the application state.")

    work_dir = tempfile.mkdtemp()
    background_tasks.add_task(cleanup_temp_dir, work_dir)
    output_path = os.path.join(work_dir, payload.output_filename)
    
    start_time = time.time()
    logger.info(f"Starting dataset generation. Project ID: {payload.project_id}")

    try:
        generator = DatasetGenerator(get_db_params(), payload.frames_root_directory)
        generator.generate_ava_csv(output_path, project_id=payload.project_id) # Pass project_id for filtering
    except Exception as e:
        logger.error(f"Dataset generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Dataset generation failed: {e}")

    if not os.path.exists(output_path):
        logger.error(f"Output file was not generated: {output_path}")
        raise HTTPException(status_code=404, detail="Output file was not generated.")

    duration = time.time() - start_time
    file_size = os.path.getsize(output_path)
    
    log_metric("export_time", project_id=payload.project_id or -1, extra={
        "output_file": payload.output_filename,
        "time_on_export": duration,
        "file_size_bytes": file_size,
        "s3_upload_requested": payload.s3_upload
    })
    logger.info(f"Dataset generation completed in {duration:.2f} seconds. Size: {file_size} bytes.")

    if payload.s3_upload:
        s3_key = f"results/{uuid.uuid4().hex}_{payload.output_filename}"
        try:
            s3_client.upload_file(output_path, bucket, s3_key)
            logger.info(f"Successfully uploaded to S3: {s3_key}")
        except Exception as e:
            logger.error(f"Failed to upload CSV to S3: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to upload CSV to S3: {e}")


        download_url = s3_client.generate_presigned_url(
            ClientMethod='get_object',
            Params={'Bucket': bucket, 'Key': s3_key},
            ExpiresIn=3600 # 1 hour
        )
        return {"download_url": download_url, "s3_key": s3_key, "message": "Dataset generated and uploaded to S3."}
    else:
        return FileResponse(
            path=output_path,
            media_type='text/csv',
            filename=payload.output_filename
        )