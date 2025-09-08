# /ava_unified_platform/main.py

from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from .config import settings
from .routers import pre_annotation, task_creator, quality_control
from mangum import Mangum
import boto3

# -----------------------------
# Middleware: Max Request Body Size
# -----------------------------
class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_size: int):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Request body is too large. "
                    f"Maximum allowed size is {self.max_size / (1024**3)} GB."
                ),
            )
        response = await call_next(request)
        return response

# -----------------------------
# FastAPI App
# -----------------------------
app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "A unified API for the AVA annotation pipeline, combining pre-annotation, "
        "task creation, and quality control into a single platform."
    ),
    version="1.0.0",
)

# Limit request size to 5GB (only applies if uploading directly, but S3 handles large files)
app.add_middleware(MaxBodySizeMiddleware, max_size=5 * 1024**3)

# -----------------------------
# S3 Initialization
# -----------------------------
@app.on_event("startup")
async def startup_event():
    """
    Initialize S3 client and attach to app.state so all routers can use it.
    """
    app.state.s3_client = boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )
    app.state.s3_bucket = settings.S3_BUCKET
    print(f"✅ Connected to S3 bucket: {settings.S3_BUCKET}")

# -----------------------------
# Routers
# -----------------------------
app.include_router(pre_annotation.router)
app.include_router(task_creator.router)
app.include_router(quality_control.router)

# -----------------------------
# Root Endpoint
# -----------------------------
@app.get("/", tags=["Root"])
def read_root():
    """A welcome message to confirm the API is running."""
    return {
        "message": f"Welcome to the {settings.APP_NAME}",
        "documentation_url": "/docs",
    }

# -----------------------------
# AWS Lambda Handler
# -----------------------------
handler = Mangum(app)
