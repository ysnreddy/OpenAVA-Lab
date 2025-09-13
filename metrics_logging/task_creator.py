# metrics_logging/task_creator.py
import os
import logging
import time
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
from processing_pipeline.services.assignment_generator import AssignmentGenerator
from .metrics_logger import log_metric

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv

# Load .env from project root
import sys
import os 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
load_dotenv()

router = APIRouter(
    prefix="/task-creator",
    tags=["2. Task Creator"]
)

# Data directories
DATA_PATH = Path("data/uploads")
XML_PATH = Path("data/cvat_xmls")
os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(XML_PATH, exist_ok=True)


class ProjectRequest(BaseModel):
    project_name: str
    annotators: List[str]
    overlap_percentage: int
    org_slug: Optional[str] = ""


@router.post("/upload-assets")
async def upload_assets(
    zip_files: List[UploadFile] = File(..., description="Clip ZIPs"),
    xml_files: List[UploadFile] = File(..., description="Annotation XMLs"),
    project_id: Optional[int] = None
):
    """
    Save uploaded assets into server directories and log ingest_time.
    Optional: pass project_id if known.
    """
    try:
        saved_files = {"zips": [], "xmls": []}

        for f in zip_files:
            dest = DATA_PATH / f.filename
            with open(dest, "wb") as buffer:
                buffer.write(await f.read())
            saved_files["zips"].append(str(dest))

        for f in xml_files:
            dest = XML_PATH / f.filename
            with open(dest, "wb") as buffer:
                buffer.write(await f.read())
            saved_files["xmls"].append(str(dest))

        # log ingest_time metric (include filenames so makespan can be matched)
        log_metric("ingest_time", project_id=project_id or -1, extra={"files": saved_files})

        return {"message": "Files uploaded successfully", "files": saved_files}

    except Exception as e:
        logger.exception("Failed to save uploaded files.")
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")


@router.post("/create-project")
async def create_project(request: ProjectRequest):
    """Create CVAT project and tasks based on uploaded assets + assignment plan."""
    try:
        # Collect uploaded ZIPs
        all_zip_files = [f for f in os.listdir(DATA_PATH) if f.endswith(".zip")]
        if not all_zip_files:
            raise HTTPException(status_code=400, detail="No ZIP files uploaded. Please upload first.")

        if not request.annotators:
            raise HTTPException(status_code=400, detail="Annotators list is empty.")

        # CVAT credentials should come from ENV (secure) or config
        cvat_host = os.getenv("CVAT_HOST", "http://localhost:8080")
        cvat_user = os.getenv("CVAT_USERNAME","Strawhat03")
        cvat_pass = os.getenv("CVAT_PASSWORD","Test@123")
        if not all([cvat_host, cvat_user, cvat_pass]):
            raise HTTPException(status_code=400, detail="CVAT credentials are not set in environment variables.")

        # Connect to CVAT
        client = CVATClient(host=cvat_host, username=cvat_user, password=cvat_pass)
        if not client.authenticated:
            raise HTTPException(status_code=401, detail="Failed to authenticate with CVAT.")

        # Generate random assignments
        assignment_generator = AssignmentGenerator()
        assignments = assignment_generator.generate_random_assignments(
            clips=all_zip_files,
            annotators=request.annotators,
            overlap_percentage=request.overlap_percentage,
        )

        # Create CVAT Project
        labels = get_default_labels()

        start_time = time.time()
        project_id = client.create_project(request.project_name, labels, org_slug=request.org_slug or None)
        if not project_id:
            raise HTTPException(status_code=500, detail="Failed to create project in CVAT.")

        results = client.create_tasks_from_assignments(
            project_id=project_id,
            assignments=assignments,
            zip_dir=DATA_PATH,
            xml_dir=XML_PATH,
        )
        duration = time.time() - start_time

        # log task_ready + time_on_task_creation
        log_metric("task_ready", project_id=project_id, extra={
            "num_tasks": len(results),
            "time_on_task_creation": duration
        })

        return {
            "message": f"Project '{request.project_name}' created successfully",
            "project_id": project_id,
            "tasks_created": len(results),
            "results": results,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed during project/task creation.")
        raise HTTPException(status_code=500, detail=f"Task creation failed: {e}")
