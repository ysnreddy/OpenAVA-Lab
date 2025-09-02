# /ava_unified_platform/config.py

import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """
    Loads and validates application settings from the .env file.
    """
    # Application settings
    APP_NAME: str = "AVA Unified Platform"
    ENV: str = "dev"
    
    # Database connection
    DB_HOST: str
    DB_PORT: int
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str

    # CVAT credentials
    CVAT_HOST: str
    CVAT_USERNAME: str
    CVAT_PASSWORD: str

    class Config:
        env_file = ".env"
        env_file_encoding = 'utf-8'

# Instantiate the settings object to be used across the application
settings = Settings()

# Define project-level paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(BASE_DIR, "data", "uploads")
XML_PATH = os.path.join(BASE_DIR, "data", "cvat_xmls")
FRAME_DIR_PATH = os.path.join(BASE_DIR, "data", "frames")

# Create directories if they don't exist
os.makedirs(DATA_PATH, exist_ok=True)
os.makedirs(XML_PATH, exist_ok=True)
os.makedirs(FRAME_DIR_PATH, exist_ok=True)