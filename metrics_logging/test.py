# metrics_logging/test.py
from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from Deployment_setup.config import settings
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from . import task_creator, quality_control, metrics , pre_annotation

class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_size: int):
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_size:
            raise HTTPException(
                status_code=413,
                detail=f"Request body is too large. Maximum allowed size is {self.max_size / (1024**3)} GB."
            )
        return await call_next(request)


app = FastAPI(
    title=settings.APP_NAME,
    description="A unified API for the AVA annotation pipeline, combining pre-annotation, "
                "task creation, and quality control into a single platform.",
    version="1.0.0"
)


app.add_middleware(MaxBodySizeMiddleware, max_size=5 * 1024**3)

# app.include_router(pre_annotation.router)

app.include_router(task_creator.router)
app.include_router(quality_control.router)
app.include_router(metrics.router)

@app.get("/", tags=["Root"])
def read_root():
    return {
        "message": f"Welcome to the {settings.APP_NAME}",
        "documentation_url": "/docs"
    }
