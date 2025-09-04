# # # /ava_unified_platform/routers/task_creator.py

# # import os
# # from typing import List
# # from fastapi import APIRouter, UploadFile, File, HTTPException, Body
# # from pydantic import BaseModel, Field
# # import os
# # import sys
# # sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# # from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
# # from processing_pipeline.services.assignment_generator import AssignmentGenerator
# # from config import settings, DATA_PATH, XML_PATH

# # router = APIRouter(
# #     prefix="/task-creator",
# #     tags=["2. CVAT Task Creator"]
# # )

# # class ProjectCreationRequest(BaseModel):
# #     project_name: str = Field(..., example=f"AVA_Project_{os.urandom(4).hex()}", description="Name for the new CVAT project.")
# #     annotators: List[str] = Field(..., example=["annotator1", "annotator2"], description="List of CVAT usernames for assignment.")
# #     overlap_percentage: int = Field(20, ge=0, le=100, description="Percentage of tasks to be assigned to multiple annotators for QC.")
# #     org_slug: str = Field(None, example="my-org", description="Optional CVAT organization slug.")


# # @router.post("/upload-assets", summary="Upload clip ZIPs and XMLs for task creation")
# # async def upload_assets(
# #     zip_files: List[UploadFile] = File(..., description="Clip ZIP files containing frames."),
# #     xml_files: List[UploadFile] = File(..., description="Corresponding CVAT XML annotation files.")
# # ):
# #     """
# #     Upload all required ZIP and XML files. These files will be stored on the server
# #     and used by the 'create-project' endpoint.
# #     """
# #     for uploaded_file in zip_files:
# #         with open(os.path.join(DATA_PATH, uploaded_file.filename), "wb") as f:
# #             f.write(uploaded_file.file.read())
            
# #     for uploaded_xml in xml_files:
# #         with open(os.path.join(XML_PATH, uploaded_xml.filename), "wb") as f:
# #             f.write(uploaded_xml.file.read())
            
# #     return {"message": "Files uploaded successfully.", "zip_files": [f.filename for f in zip_files], "xml_files": [f.filename for f in xml_files]}


# # @router.post("/create-project", summary="Create CVAT project and tasks")
# # async def create_project_and_tasks(request: ProjectCreationRequest):
# #     """
# #     This endpoint orchestrates the creation of a CVAT project, generates assignments,
# #     and creates all the tasks based on previously uploaded assets.
# #     """
# #     client = CVATClient(host=settings.CVAT_HOST, username=settings.CVAT_USERNAME, password=settings.CVAT_PASSWORD)
# #     if not client.authenticated:
# #         raise HTTPException(status_code=401, detail="Failed to authenticate with CVAT. Check credentials in .env file.")

# #     try:
# #         all_zip_files = [f for f in os.listdir(DATA_PATH) if f.endswith('.zip')]
# #         if not all_zip_files:
# #             raise HTTPException(status_code=404, detail=f"No ZIP files found in the upload directory ({DATA_PATH}). Please upload assets first.")

# #         if not request.annotators:
# #             raise HTTPException(status_code=400, detail="Annotator list cannot be empty.")

# #         # 1. Generate assignments
# #         assignment_generator = AssignmentGenerator()
# #         assignments = assignment_generator.generate_random_assignments(
# #             clips=all_zip_files,
# #             annotators=request.annotators,
# #             overlap_percentage=request.overlap_percentage
# #         )

# #         # 2. Create Project in CVAT
# #         labels = get_default_labels()
# #         project_id = client.create_project(request.project_name, labels, org_slug=request.org_slug)
# #         if not project_id:
# #             raise HTTPException(status_code=500, detail="Failed to create CVAT project.")

# #         # 3. Create Tasks from Assignments
# #         results = client.create_tasks_from_assignments(
# #             project_id=project_id,
# #             assignments=assignments,
# #             zip_dir=DATA_PATH,
# #             xml_dir=XML_PATH
# #         )

# #         if not results:
# #              raise HTTPException(status_code=500, detail="Project was created, but task creation failed.")

# #         return {
# #             "message": f"Successfully created project and {len(results)} tasks.",
# #             "project_id": project_id,
# #             "project_name": request.project_name,
# #             "task_creation_details": results
# #         }
# #     except Exception as e:
# #         # Catch any other exceptions and return a generic server error
# #         raise HTTPException(status_code=500, detail=str(e))














# import os
# import logging
# from typing import List, Optional

# from fastapi import APIRouter, UploadFile, File, HTTPException
# from pydantic import BaseModel, Field

# import sys
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
# from processing_pipeline.services.assignment_generator import AssignmentGenerator
# from config import settings, DATA_PATH, XML_PATH

# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# router = APIRouter(
#     prefix="/task-creator",
#     tags=["2. CVAT Task Creator"]
# )


# class ProjectCreationRequest(BaseModel):
#     project_name: str = Field(..., example=f"AVA_Project_{os.urandom(4).hex()}", description="Name for the new CVAT project.")
#     annotators: List[str] = Field(..., example=["annotator1", "annotator2"], description="List of CVAT usernames for assignment.")
#     overlap_percentage: int = Field(20, ge=0, le=100, description="Percentage of tasks to be assigned to multiple annotators for QC.")
#     # make org_slug optional
#     org_slug: Optional[str] = Field(None, example="my-org", description="Optional CVAT organization slug.")


# @router.post("/upload-assets", summary="Upload clip ZIPs and XMLs for task creation")
# async def upload_assets(
#     zip_files: List[UploadFile] = File(..., description="Clip ZIP files containing frames."),
#     xml_files: List[UploadFile] = File(..., description="Corresponding CVAT XML annotation files.")
# ):
#     """
#     Upload all required ZIP and XML files. These files will be stored on the server
#     and used by the 'create-project' endpoint.
#     """
#     os.makedirs(DATA_PATH, exist_ok=True)
#     os.makedirs(XML_PATH, exist_ok=True)

#     try:
#         for uploaded_file in zip_files:
#             target = os.path.join(DATA_PATH, uploaded_file.filename)
#             with open(target, "wb") as f:
#                 f.write(uploaded_file.file.read())

#         for uploaded_xml in xml_files:
#             target = os.path.join(XML_PATH, uploaded_xml.filename)
#             with open(target, "wb") as f:
#                 f.write(uploaded_xml.file.read())

#     except Exception as e:
#         logger.exception("Failed to save uploaded files.")
#         raise HTTPException(status_code=500, detail=f"Failed to save uploaded files: {e}")

#     return {"message": "Files uploaded successfully.", "zip_files": [f.filename for f in zip_files], "xml_files": [f.filename for f in xml_files]}


# @router.post("/create-project", summary="Create CVAT project and tasks")
# async def create_project_and_tasks(request: ProjectCreationRequest):
#     """
#     This endpoint orchestrates the creation of a CVAT project, generates assignments,
#     and creates all the tasks based on previously uploaded assets.
#     """
#     # Create CVAT client
#     client = CVATClient(host=settings.CVAT_HOST, username=settings.CVAT_USERNAME, password=settings.CVAT_PASSWORD)
#     if not client.authenticated:
#         logger.error("Failed to authenticate with CVAT using provided credentials.")
#         raise HTTPException(status_code=401, detail="Failed to authenticate with CVAT. Check credentials in .env file.")

#     try:
#         all_zip_files = [f for f in os.listdir(DATA_PATH) if f.endswith('.zip')]
#         if not all_zip_files:
#             raise HTTPException(status_code=404, detail=f"No ZIP files found in the upload directory ({DATA_PATH}). Please upload assets first.")

#         if not request.annotators:
#             raise HTTPException(status_code=400, detail="Annotator list cannot be empty.")

#         # 1. Generate assignments
#         assignment_generator = AssignmentGenerator()
#         assignments = assignment_generator.generate_random_assignments(
#             clips=all_zip_files,
#             annotators=request.annotators,
#             overlap_percentage=request.overlap_percentage
#         )

#         # 2. Create Project in CVAT
#         labels = get_default_labels()
#         # normalize org_slug: treat empty-string like None
#         org_slug_to_send = request.org_slug.strip() if (request.org_slug and request.org_slug.strip()) else None

#         logger.info(f"Creating project '{request.project_name}' (org: {org_slug_to_send}) with {len(all_zip_files)} clip(s).")
#         project_id = client.create_project(request.project_name, labels, org_slug=org_slug_to_send)

#         if not project_id:
#             logger.error("CVAT project creation returned falsy response.")
#             raise HTTPException(status_code=500, detail="Failed to create CVAT project.")

#         # 3. Create Tasks from Assignments
#         results = client.create_tasks_from_assignments(
#             project_id=project_id,
#             assignments=assignments,
#             zip_dir=DATA_PATH,
#             xml_dir=XML_PATH
#         )

#         if not results:
#             logger.error("Task creation from assignments failed after project creation.")
#             raise HTTPException(status_code=500, detail="Project was created, but task creation failed.")

#         return {
#             "message": f"Successfully created project and {len(results)} tasks.",
#             "project_id": project_id,
#             "project_name": request.project_name,
#             "task_creation_details": results
#         }

#     except HTTPException:
#         # pass through HTTPExceptions
#         raise
#     except Exception as e:
#         logger.exception("Unexpected error during create-project flow.")
#         raise HTTPException(status_code=500, detail=str(e))




import os
import logging
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
from processing_pipeline.services.assignment_generator import AssignmentGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
from dotenv import load_dotenv
import os

# Load .env from project root
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "Deployment_setup"))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))



router = APIRouter(
    prefix="/task-creator",
    tags=["2. Task Creator"]
)

# Data directories (same as your Streamlit script)
DATA_PATH = Path("data/uploads")
XML_PATH = Path("data/cvat_xmls")
os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(XML_PATH, exist_ok=True)


# -----------------------------
# 1. Upload Assets (ZIP + XML)
# -----------------------------
@router.post("/upload-assets")
async def upload_assets(
    zip_files: List[UploadFile] = File(..., description="Clip ZIPs"),
    xml_files: List[UploadFile] = File(..., description="Annotation XMLs"),
):
    """Save uploaded assets into server directories."""
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

        return {"message": "Files uploaded successfully", "files": saved_files}

    except Exception as e:
        logger.exception("Failed to save uploaded files.")
        raise HTTPException(status_code=500, detail=f"File upload failed: {e}")


# -----------------------------
# 2. Create Project & Tasks
# -----------------------------
class ProjectRequest(BaseModel):
    project_name: str
    annotators: List[str]
    overlap_percentage: int
    org_slug: Optional[str] = ""


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
        cvat_user = os.getenv("CVAT_USERNAME")
        cvat_pass = os.getenv("CVAT_PASSWORD")
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
        project_id = client.create_project(request.project_name, labels, org_slug=request.org_slug or None)
        if not project_id:
            raise HTTPException(status_code=500, detail="Failed to create project in CVAT.")

        # Create tasks inside project
        results = client.create_tasks_from_assignments(
            project_id=project_id,
            assignments=assignments,
            zip_dir=DATA_PATH,
            xml_dir=XML_PATH,
        )

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
