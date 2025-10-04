# metrics_logging/quality_control.py
import os
import time
import pandas as pd
from typing import List
from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from Deployment_setup.database import get_db_connection, get_db_params
from processing_pipeline.services.quality_service import QualityService
from processing_pipeline.services.dataset_generator import DatasetGenerator
from .metrics_logger import log_metric
from Deployment_setup.config import FRAME_DIR_PATH
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/quality-control",
    tags=["3. Quality Control & Dataset Generation"]
)

class QCStatusUpdateRequest(BaseModel):
    task_ids: List[int] = Field(..., example=[101, 102], description="List of task IDs to update.")
    new_status: str = Field(..., example="approved", description="The new status, either 'approved' or 'rejected'.")

class DatasetRequest(BaseModel):
    output_filename: str = Field("final_ava_dataset.csv", description="The name of the output CSV file.")
    frames_root_directory: str = Field(FRAME_DIR_PATH, description="Absolute path to the root directory containing frame images.")
    project_id: int = Field(-1, description="Optional project id to attach to export log.")

# ----------------- Project & Task Endpoints -----------------
@router.get("/projects", summary="List all projects from the database")
def list_projects():
    """Fetches a list of all unique project IDs that have tasks in the database."""
    try:
        with get_db_connection() as conn:
            df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
        
        logger.info(f"DEBUG: Found {len(df)} projects in database")
        
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
        
        logger.info(f"DEBUG: Found {len(df)} tasks for project {project_id}")
        
        if not df.empty:
            for _, row in df.iterrows():
                logger.info(f"DEBUG: Task {row['task_id']}: '{row['name']}' (assignee: {row['assignee']}, status: {row['status']})")
        
        if df.empty:
            raise HTTPException(status_code=404, detail=f"No tasks found for project ID {project_id}.")
        
        return df.to_dict(orient='records')
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching tasks for project {project_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

# ----------------- Inter-Annotator Agreement Endpoint -----------------
@router.post("/run-iaa-check", summary="Run Inter-Annotator Agreement check")
def run_iaa_check(data: dict = Body(..., example={"task_ids": [101, 102]})):
    """
    Run IAA check for exactly two tasks.
    Accepts POST body: {"task_ids": [task_id1, task_id2]}
    """
    task_pair = data.get("task_ids", [])
    logger.info(f"Received task_pair: {task_pair}")

    if len(task_pair) != 2:
        raise HTTPException(status_code=400, detail="Please provide exactly two task IDs for comparison.")

    logger.info(f"DEBUG: Running IAA check for tasks {task_pair[0]} and {task_pair[1]}")
    
    try:
        qc_service = QualityService(get_db_params())
        results = qc_service.run_quality_check(task_pair[0], task_pair[1])
        
        if "error" in results:
            logger.error(f"IAA check failed: {results['error']}")
            raise HTTPException(status_code=404, detail=results["error"])
        
        logger.info(f"DEBUG: IAA check completed successfully")
        return results
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error during IAA check: {e}")
        raise HTTPException(status_code=500, detail=f"IAA check failed: {e}")

# ----------------- Update Task Status Endpoint -----------------
@router.post("/update-task-status", summary="Approve, reject, or mark as pending tasks")
def update_task_qc_status(request: QCStatusUpdateRequest):
    """Updates the 'qc_status' field for one or more tasks."""
    if request.new_status not in ["approved", "rejected", "pending"]:  # <-- added pending
        raise HTTPException(status_code=400, detail="Status must be 'approved', 'rejected', or 'pending'.")
    
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tasks SET qc_status = %s WHERE task_id = ANY(%s)",
                (request.new_status, request.task_ids)
            )
        conn.commit()
        
    return {"message": f"Successfully updated {len(request.task_ids)} tasks to '{request.new_status}'."}

# ----------------- Dataset Generation Endpoint -----------------
@router.post("/generate-dataset", summary="Generate the final AVA dataset CSV")
def generate_final_dataset(request: DatasetRequest):
    """
    Generates the final AVA dataset CSV from all 'approved' annotations for the selected project.
    Normalizes bounding boxes to [0,1]. Returns the CSV file for download.
    """
    output_path = os.path.join(os.getcwd(), request.output_filename)
    start_time = time.time()
    
    logger.info(f"DEBUG: Starting dataset generation")
    logger.info(f"DEBUG: Output path: {output_path}")
    logger.info(f"DEBUG: Frames directory: {request.frames_root_directory}")
    logger.info(f"DEBUG: Project ID: {request.project_id}")

    try:
        generator = DatasetGenerator(get_db_params(), request.frames_root_directory)
        # ✅ Pass the selected project_id
        generator.generate_ava_csv(output_path, project_id=request.project_id)
    except Exception as e:
        logger.error(f"Dataset generation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Dataset generation failed: {e}")

    duration = time.time() - start_time
    
    logger.info(f"DEBUG: Dataset generation completed in {duration:.2f} seconds")

    if not os.path.exists(output_path):
        logger.error(f"Output file was not created: {output_path}")
        raise HTTPException(status_code=404, detail="Output file was not generated.")

    file_size = os.path.getsize(output_path)
    logger.info(f"DEBUG: Generated file size: {file_size} bytes")

    log_metric("export_time", project_id=request.project_id or -1, extra={
        "output_file": request.output_filename,
        "time_on_export": duration,
        "file_size_bytes": file_size
    })

    return FileResponse(
        path=output_path,
        media_type='text/csv',
        filename=request.output_filename
    )
