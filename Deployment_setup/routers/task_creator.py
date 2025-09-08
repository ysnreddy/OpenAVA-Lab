# /ava_unified_platform/routers/task_creator.py

import os
import logging
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
import uuid
import tempfile
import shutil
import boto3
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
from processing_pipeline.services.assignment_generator import AssignmentGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ----------------------------- Helper -----------------------------
def cleanup_temp_dir(path: str):
    """Remove temporary directories in background."""
    shutil.rmtree(path, ignore_errors=True)

# ----------------------------- Router -----------------------------
router = APIRouter(
    prefix="/task-creator",
    tags=["2. Task Creator"]
)

# ----------------- S3 Presigned URL endpoint -----------------
@router.post("/get-upload-url", summary="Generate presigned URL for uploading ZIP/XML")
async def get_upload_url(request: Request, filename: str):
    """
    Returns a presigned URL for direct S3 upload of ZIP/XML files.
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

# ----------------- Create Project & Tasks -----------------
class ProjectRequest(BaseModel):
    project_name: str
    annotators: List[str]
    overlap_percentage: int
    s3_keys: List[str]  # S3 keys for uploaded assets
    org_slug: Optional[str] = ""

@router.post("/create-project-s3", summary="Create CVAT project using assets from S3")
def create_project_s3(request: Request, payload: ProjectRequest, background_tasks: BackgroundTasks):
    """
    Creates a CVAT project and tasks by pulling uploaded assets from S3.
    Handles large files via temporary directories.
    """
    if not payload.annotators:
        raise HTTPException(status_code=400, detail="Annotators list is empty.")
    if not payload.s3_keys:
        raise HTTPException(status_code=400, detail="No S3 keys provided for uploaded assets.")

    s3_client = request.app.state.s3_client
    bucket = request.app.state.s3_bucket

    # Temporary local directories
    work_dir = tempfile.mkdtemp()
    zip_dir = os.path.join(work_dir, "zips")
    xml_dir = os.path.join(work_dir, "xmls")
    os.makedirs(zip_dir, exist_ok=True)
    os.makedirs(xml_dir, exist_ok=True)
    background_tasks.add_task(cleanup_temp_dir, work_dir)

    # Download files from S3
    for key in payload.s3_keys:
        local_path = os.path.join(zip_dir if key.endswith(".zip") else xml_dir, os.path.basename(key))
        try:
            s3_client.download_file(bucket, key, local_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to download {key} from S3: {e}")

    # CVAT credentials from environment
    cvat_host = os.getenv("CVAT_HOST", "http://localhost:8080")
    cvat_user = os.getenv("CVAT_USERNAME")
    cvat_pass = os.getenv("CVAT_PASSWORD")
    if not all([cvat_host, cvat_user, cvat_pass]):
        raise HTTPException(status_code=400, detail="CVAT credentials are not set in environment variables.")

    # Connect to CVAT
    client = CVATClient(host=cvat_host, username=cvat_user, password=cvat_pass)
    if not client.authenticated:
        raise HTTPException(status_code=401, detail="Failed to authenticate with CVAT.")

    # Generate assignments
    all_zip_files = [f for f in os.listdir(zip_dir) if f.endswith(".zip")]
    assignment_generator = AssignmentGenerator()
    assignments = assignment_generator.generate_random_assignments(
        clips=all_zip_files,
        annotators=payload.annotators,
        overlap_percentage=payload.overlap_percentage,
    )

    # Create CVAT project
    labels = get_default_labels()
    project_id = client.create_project(payload.project_name, labels, org_slug=payload.org_slug or None)
    if not project_id:
        raise HTTPException(status_code=500, detail="Failed to create project in CVAT.")

    # Create tasks
    results = client.create_tasks_from_assignments(
        project_id=project_id,
        assignments=assignments,
        zip_dir=zip_dir,
        xml_dir=xml_dir,
    )

    return {
        "message": f"Project '{payload.project_name}' created successfully",
        "project_id": project_id,
        "tasks_created": len(results),
        "results": results,
    }
