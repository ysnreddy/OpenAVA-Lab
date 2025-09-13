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

@router.get("/projects", summary="List all projects from the database")
def list_projects():
    """Fetches a list of all unique project IDs that have tasks in the database."""
    with get_db_connection() as conn:
        df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
    if df.empty:
        return {"message": "No projects found."}
    return {"projects": df['project_id'].tolist()}

@router.get("/projects/{project_id}/tasks", summary="Get all tasks for a specific project")
def get_project_tasks(project_id: int):
    """Retrieves a detailed list of all tasks associated with a given project ID."""
    with get_db_connection() as conn:
        query = "SELECT task_id, name, assignee, status, qc_status FROM tasks WHERE project_id = %s ORDER BY task_id"
        df = pd.read_sql(query, conn, params=(project_id,))
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No tasks found for project ID {project_id}.")
    return df.to_dict(orient='records')

@router.post("/run-iaa-check", summary="Run Inter-Annotator Agreement check")
def run_iaa_check(task_pair: List[int] = Body(..., example=[101, 102], description="A list containing exactly two task IDs to compare.")):
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

@router.post("/generate-dataset", summary="Generate the final AVA dataset CSV")
def generate_final_dataset(request: DatasetRequest):
    """
    Generates the final `train.csv` file from all 'approved' annotations.
    This process applies consensus logic to overlapping tasks.
    The generated file is returned for download.
    """
    # Save in current working directory (Windows-friendly)
    output_path = os.path.join(os.getcwd(), request.output_filename)
    start_time = time.time()
    
    try:
        generator = DatasetGenerator(get_db_params(), request.frames_root_directory)
        generator.generate_ava_csv(output_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Dataset generation failed: {e}")

    duration = time.time() - start_time

    if not os.path.exists(output_path):
        raise HTTPException(status_code=404, detail="Output file was not generated.")

    # log export_time + time_on_export (attach project_id if provided)
    log_metric("export_time", project_id=request.project_id or -1, extra={
        "output_file": request.output_filename,
        "time_on_export": duration
    })

    return FileResponse(
        path=output_path,
        media_type='text/csv',
        filename=request.output_filename
    )
