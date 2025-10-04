# metrics_logging/task_creator.py
import os
import logging
import time
import json
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
from processing_pipeline.services.assignment_generator import AssignmentGenerator
from .metrics_logger import log_metric

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv
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

# Upload tracker (only last 10 projects kept)
UPLOAD_TRACKER = Path("data/latest_uploads.json")
MAX_TRACKED_PROJECTS = 10


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
    """Save uploaded assets and log ingest_time. Keeps only last 10 projects in tracker."""
    try:
        saved_files = {"zips": [], "xmls": []}
        start_time = time.time()  # Track upload start time

        for f in zip_files:
            dest = DATA_PATH / f.filename
            with open(dest, "wb") as buffer:
                buffer.write(await f.read())
            saved_files["zips"].append(str(dest))
            
            # Log ingest_time for each zip file individually
            log_metric(
                "ingest_time", 
                project_id=project_id or -1, 
                extra={
                    "files": {"zips": [f.filename]},  # Individual file
                    "upload_duration": time.time() - start_time
                }
            )

        for f in xml_files:
            dest = XML_PATH / f.filename
            with open(dest, "wb") as buffer:
                buffer.write(await f.read())
            saved_files["xmls"].append(str(dest))

        total_duration = time.time() - start_time
        logger.info(f"📁 Upload completed in {total_duration:.2f} seconds")

        # 🔑 Save uploaded files info into tracker JSON
        tracker_data = {}
        if UPLOAD_TRACKER.exists():
            tracker_data = json.loads(UPLOAD_TRACKER.read_text())

        key = str(project_id or -1)
        tracker_data[key] = saved_files

        # 🔥 Auto-clear oldest if more than 10 projects
        if len(tracker_data) > MAX_TRACKED_PROJECTS:
            oldest_key = list(tracker_data.keys())[0]
            tracker_data.pop(oldest_key, None)

        UPLOAD_TRACKER.write_text(json.dumps(tracker_data, indent=2))

        return {"message": "Files uploaded successfully", "files": saved_files}

    except Exception as e:
        logger.exception("Failed to save uploaded files.")
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")


@router.post("/create-project")
async def create_project(request: ProjectRequest):
    """Create CVAT project and tasks based on uploaded assets + assignment plan."""
    try:
        # 🔑 Load only the latest uploaded files for this project
        if not UPLOAD_TRACKER.exists():
            raise HTTPException(status_code=400, detail="No uploaded assets found. Please upload first.")

        tracker_data = json.loads(UPLOAD_TRACKER.read_text())
        saved_files = tracker_data.get(request.project_name) or tracker_data.get(str(-1))

        if not saved_files or not saved_files["zips"]:
            raise HTTPException(status_code=400, detail="No ZIP files found for this project. Please upload first.")

        all_zip_files = [Path(f).name for f in saved_files["zips"]]

        if not request.annotators:
            raise HTTPException(status_code=400, detail="Annotators list is empty.")

        cvat_host = os.getenv("CVAT_HOST", "http://localhost:8080")
        cvat_user = os.getenv("CVAT_USERNAME", "Strawhat03")
        cvat_pass = os.getenv("CVAT_PASSWORD", "Test@123")
        if not all([cvat_host, cvat_user, cvat_pass]):
            raise HTTPException(status_code=400, detail="CVAT credentials missing.")

        client = CVATClient(host=cvat_host, username=cvat_user, password=cvat_pass)
        if not client.authenticated:
            raise HTTPException(status_code=401, detail="Failed to authenticate with CVAT.")

        assignment_generator = AssignmentGenerator()
        assignments = assignment_generator.generate_random_assignments(
            clips=all_zip_files,
            annotators=request.annotators,
            overlap_percentage=request.overlap_percentage,
        )

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
        total_creation_duration = time.time() - start_time

        # Calculate per-task duration (approximate)
        per_task_duration = total_creation_duration / len(results) if results else 0

        # Log task_ready + time_on_task_creation per task
        for task in results:
            task_id = task.get("task_id") or task.get("id")
            clip_name = task.get("clip")
            annotator = task.get("annotator")

            # Fallback to assignments if annotator is missing
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
                    "total_tasks": len(results)
                }
            )

        logger.info(f"🎯 Created {len(results)} tasks in {total_creation_duration:.2f} seconds")

        # 🔥 After using, clear this project’s entry from tracker
        tracker_data.pop(request.project_name, None)
        tracker_data.pop(str(-1), None)  # also clean fallback key
        UPLOAD_TRACKER.write_text(json.dumps(tracker_data, indent=2))

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







