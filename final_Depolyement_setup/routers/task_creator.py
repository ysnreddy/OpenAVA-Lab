# metrics_logging/task_creator.py

import os
import logging
import time
import shutil
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
import uuid
import tempfile
import sys
# Import boto3 for S3 if it's not already available via app state, but we'll
# rely on request.app.state for consistency with the reference file.
# import boto3 
from pathlib import Path
from dotenv import load_dotenv
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
from processing_pipeline.services.assignment_generator import AssignmentGenerator
from .metrics_logger import log_metric
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
load_dotenv()

def cleanup_temp_dir(path: str):
    """Remove temporary directories in background."""
    logger.info(f"🗑️ Cleaning up temporary directory: {path}")
    shutil.rmtree(path, ignore_errors=True)

router = APIRouter(
    prefix="/task-creator",
    tags=["2. Task Creator"]
)

@router.post("/get-upload-url", summary="Generate presigned URL for uploading ZIP/XML")
async def get_upload_url(request: Request, filename: str):
    """
    Returns a presigned URL for direct S3 upload of ZIP/XML files.
    Assets are uploaded to a 'uploads/' prefix with a unique identifier.
    """
    try:
        s3_client = request.app.state.s3_client
        bucket = request.app.state.s3_bucket
    except AttributeError as e:
        logger.error(f"S3 client or bucket not in app state: {e}")
        raise HTTPException(status_code=500, detail="S3 client is not configured on the server.")

    key = f"uploads/{uuid.uuid4().hex}_{filename}"
    presigned_url = s3_client.generate_presigned_url(
        ClientMethod='put_object',
        Params={'Bucket': bucket, 'Key': key},
        ExpiresIn=3600,  # 1 hour
        HttpMethod='PUT'
    )
    return {"url": presigned_url, "key": key}

class ProjectRequest(BaseModel):
    project_name: str
    annotators: List[str]
    overlap_percentage: int
    s3_keys: List[str]  
    org_slug: Optional[str] = ""

@router.post("/create-project-s3", summary="Create CVAT project using assets from S3")
def create_project_s3(request: Request, payload: ProjectRequest, background_tasks: BackgroundTasks):
    """
    Creates a CVAT project and tasks by pulling uploaded assets from S3.
    It uses temporary local storage for CVAT file imports and cleans up afterward.
    Logs task creation metrics.
    """
    start_total_time = time.time() 

    if not payload.annotators:
        raise HTTPException(status_code=400, detail="Annotators list is empty.")
    if not payload.s3_keys:
        raise HTTPException(status_code=400, detail="No S3 keys provided for uploaded assets.")


    try:
        s3_client = request.app.state.s3_client
        bucket = request.app.state.s3_bucket
    except AttributeError:
        raise HTTPException(status_code=500, detail="S3 client not configured on the application.")

    work_dir = tempfile.mkdtemp()
    zip_dir = os.path.join(work_dir, "zips")
    xml_dir = os.path.join(work_dir, "xmls")
    os.makedirs(zip_dir, exist_ok=True)
    os.makedirs(xml_dir, exist_ok=True)
    background_tasks.add_task(cleanup_temp_dir, work_dir)


    zip_file_names = []
    for key in payload.s3_keys:
        filename = os.path.basename(key)
        

        if filename.lower().endswith(".zip"):
            local_path = os.path.join(zip_dir, filename)
            zip_file_names.append(filename)
        elif filename.lower().endswith((".xml", ".annotations")): 
            local_path = os.path.join(xml_dir, filename)
        else:
            logger.warning(f"Skipping unsupported file type for S3 key: {key}")
            continue

        try:
            download_start_time = time.time()
            s3_client.download_file(bucket, key, local_path)
            download_duration = time.time() - download_start_time
            logger.info(f"⬇️ Downloaded {filename} in {download_duration:.2f}s")

            if filename.lower().endswith(".zip"):
                log_metric(
                    "ingest_time", 
                    project_id=payload.project_name, 
                    extra={
                        "files": {"zips": [filename]}, 
                        "download_duration": download_duration,
                        "s3_key": key
                    }
                )

        except Exception as e:
            logger.exception(f"Failed to download {key} from S3.")
            raise HTTPException(status_code=500, detail=f"Failed to download {key} from S3: {e}")

    if not zip_file_names:
        raise HTTPException(status_code=400, detail="No ZIP files found in the provided S3 keys to create tasks.")

    cvat_host = os.getenv("CVAT_HOST", "http://localhost:8080")
    cvat_user = os.getenv("CVAT_USERNAME")
    cvat_pass = os.getenv("CVAT_PASSWORD")
    if not all([cvat_host, cvat_user, cvat_pass]):
        raise HTTPException(status_code=400, detail="CVAT credentials are not set in environment variables.")

    client = CVATClient(host=cvat_host, username=cvat_user, password=cvat_pass)
    if not client.authenticated:
        raise HTTPException(status_code=401, detail="Failed to authenticate with CVAT. Check credentials.")

    assignment_generator = AssignmentGenerator()
    assignments = assignment_generator.generate_random_assignments(
        clips=zip_file_names, 
        annotators=payload.annotators,
        overlap_percentage=payload.overlap_percentage,
    )
    logger.info(f"📊 Generated {len(assignments)} assignments for {len(zip_file_names)} clips.")

    labels = get_default_labels()
    project_create_start_time = time.time()
    project_id = client.create_project(payload.project_name, labels, org_slug=payload.org_slug or None)
    if not project_id:
        raise HTTPException(status_code=500, detail="Failed to create project in CVAT.")
    logger.info(f"✅ CVAT Project ID: {project_id}")

    # --- Create Tasks ---
    results = client.create_tasks_from_assignments(
        project_id=project_id,
        assignments=assignments,
        zip_dir=Path(zip_dir), 
        xml_dir=Path(xml_dir),
    )
    total_creation_duration = time.time() - project_create_start_time
    total_process_duration = time.time() - start_total_time

    per_task_duration = total_creation_duration / len(results) if results else 0

    for task in results:
        task_id = task.get("task_id") or task.get("id")
        clip_name = task.get("clip")
        annotator = task.get("annotator")
        

        if not annotator:
            for assignment in assignments:
                if assignment["clip"] == clip_name:
                    annotator = assignment["annotator"]
                    break

        log_metric(
            "task_ready",
            project_id=project_id,
            task_id=task_id,
            annotator=annotator,
            extra={
                "time_on_task_creation": per_task_duration,
                "clip": clip_name,
                "total_tasks": len(results),
                "total_project_creation_duration": total_creation_duration,
            }
        )

    logger.info(f"🎯 Created {len(results)} tasks in {total_creation_duration:.2f} seconds (Total process: {total_process_duration:.2f}s)")


    return {
        "message": f"Project '{payload.project_name}' created successfully from S3 assets.",
        "project_id": project_id,
        "tasks_created": len(results),
        "results": results,
    }