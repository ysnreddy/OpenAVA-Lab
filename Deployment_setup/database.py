# /ava_unified_platform/database.py

import psycopg2
import psycopg2.pool
from contextlib import contextmanager
from fastapi import HTTPException
from config import settings

# Create a connection pool
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        minconn=1,
        maxconn=20,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        dbname=settings.DB_NAME
    )
except psycopg2.OperationalError as e:
    print(f"FATAL: Could not connect to the database. Error: {e}")
    db_pool = None

@contextmanager
def get_db_connection():
    """Context manager to get a connection from the pool."""
    if db_pool is None:
        raise HTTPException(status_code=503, detail="Database service is unavailable.")
    
    conn = None
    try:
        conn = db_pool.getconn()
        yield conn
    finally:
        if conn:
            db_pool.putconn(conn)

def get_db_params() -> dict:
    """Returns a dictionary of database parameters for services that need it."""
    return {
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "host": settings.DB_HOST,
        "port": settings.DB_PORT,
        "dbname": settings.DB_NAME
    }