# main.py
from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import boto3
import logging
import os

from config import settings  # or environment variables
from routers import  task_creator, quality_control, metrics
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("ava_unified_platform")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Limits request body size to prevent memory overload."""
    def __init__(self, app, max_size: int):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            raise HTTPException(
                status_code=413,
                detail=f"Request too large. Max allowed: {self.max_size / (1024**3):.2f} GB"
            )
        response = await call_next(request)
        return response


app = FastAPI(
    title=settings.APP_NAME,
    description="AVA Unified Platform API - Pre-Annotation, Task Creation, QC & Metrics",
    version="1.0.0"
)


app.add_middleware(MaxBodySizeMiddleware, max_size=5 * 1024**3)


@app.on_event("startup")
async def startup_event():
    """Initialize S3 client via IAM Role (preferred for EC2)."""
    try:
        app.state.s3_client = boto3.client(
            "s3",
            region_name=settings.AWS_DEFAULT_REGION
        )
        app.state.s3_bucket = settings.S3_BUCKET
        logger.info(f"✅ S3 client initialized. Bucket: {settings.S3_BUCKET}")
    except Exception as e:
        logger.error(f"❌ S3 initialization failed: {e}")



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(task_creator.router)
app.include_router(quality_control.router)
app.include_router(metrics.router)


@app.get("/", tags=["Root"])
def read_root():
    return {
        "message": f"Welcome to {settings.APP_NAME} (EC2 Ready)",
        "documentation_url": "/docs"
    }

# -------------------------
# Notes for Large File Handling
# -------------------------
"""
1️⃣ Do NOT send large files directly via FastAPI. Use pre-signed S3 URLs from backend.
2️⃣ Streamlit frontend should:
   - Request pre-signed URL from backend
   - Upload directly to S3 (multipart if >5GB)
   - Trigger backend processing via API after upload
3️⃣ IAM Role attached to EC2 instance avoids hardcoding AWS credentials.
4️⃣ Ensure EC2 security group allows ports 8000 (FastAPI) and 8501 (Streamlit).
5️⃣ Consider asynchronous processing (Celery/RQ) for heavy pre-annotation tasks.
"""
