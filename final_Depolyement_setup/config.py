# config.py

import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    """
    Loads and validates application settings from the .env file.
    Uses pydantic-settings to load configuration from environment variables,
    falling back to defaults if provided.
    """

    APP_NAME: str = "AVA Unified Platform"
    ENV: str = "dev"

    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    CVAT_HOST: str
    CVAT_USERNAME: str
    CVAT_PASSWORD: str

    S3_BUCKET: str = Field(..., description="The S3 bucket for uploads and results.")
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_DEFAULT_REGION: Optional[str] = None


    FASTAPI_URL: Optional[str] = None

    FRAME_DIR_PATH: Optional[str] = None
    TEMP_DIR_PATH: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding='utf-8',
        extra="ignore"  
    )


settings = Settings()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_DATA_PATH = os.path.join(BASE_DIR, "data", "uploads")
DEFAULT_XML_PATH = os.path.join(BASE_DIR, "data", "cvat_xmls")
DEFAULT_FRAME_PATH = os.path.join(BASE_DIR, "data", "frames")
DEFAULT_LOG_PATH = os.path.join(BASE_DIR, "data", "logs")

DATA_PATH = getattr(settings, "DATA_PATH", DEFAULT_DATA_PATH)
XML_PATH = getattr(settings, "XML_PATH", DEFAULT_XML_PATH)
FRAME_DIR_PATH = settings.FRAME_DIR_PATH or DEFAULT_FRAME_PATH
TEMP_DIR_PATH = settings.TEMP_DIR_PATH or os.path.join(BASE_DIR, "data", "temp")
LOG_DIR = os.path.join(BASE_DIR, "data", "logs")  

os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(XML_PATH, exist_ok=True)
os.makedirs(FRAME_DIR_PATH, exist_ok=True)
os.makedirs(TEMP_DIR_PATH, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
