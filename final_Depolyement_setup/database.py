# /ava_unified_platform/database.py

import psycopg2
import psycopg2.pool
from contextlib import contextmanager
from fastapi import HTTPException
from .config import settings 
db_pool = None
try:
    db_pool = psycopg2.pool.SimpleConnectionPool(
        minconn=1,
        maxconn=20, # Set a reasonable maximum for the pool size
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        dbname=settings.DB_NAME
    )
    print("INFO: PostgreSQL connection pool successfully initialized.")

except psycopg2.OperationalError as e:
    print(f"FATAL: Could not connect to the database. Error: {e}")
    db_pool = None
except Exception as e:
    print(f"FATAL: Unexpected error during database pool initialization: {e}")
    db_pool = None

@contextmanager
def get_db_connection():
    """
    Context manager to get a connection from the pool.
    
    Ensures the connection is returned to the pool, even if errors occur.
    Yields the connection object.
    """
    if db_pool is None:

        raise HTTPException(status_code=503, detail="Database service is unavailable. Check server logs for connection errors.")
    
    conn = None
    try:
        conn = db_pool.getconn()
        yield conn
    finally:
        if conn:
            db_pool.putconn(conn)

def get_db_params() -> dict:
    """
    Returns a dictionary of database parameters.
    
    This is useful for external libraries or services (like DataFrame readers)
    that need parameters but should not handle connection pool management.
    """
    return {
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "host": settings.DB_HOST,
        "port": settings.DB_PORT,
        "dbname": settings.DB_NAME
    }

def close_db_pool():
    """Closes all database connections in the pool."""
    global db_pool
    if db_pool:
        db_pool.closeall()
        print("INFO: PostgreSQL connection pool closed.")
        db_pool = None