import json
import os
import psycopg2
import logging
import time
import xml.etree.ElementTree as ET
from typing import List, Dict, Any
from pathlib import Path

# Assuming cvat_integration is in the same services directory
from cvat_integration import CVATClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- PostgreSQL Database Schema ---
# You need to run this SQL code in your PostgreSQL database once to create the necessary tables.
# You can use a tool like DBeaver, pgAdmin, or the `psql` command-line tool.
"""
CREATE TABLE IF NOT EXISTS projects (
    project_id INTEGER PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES projects(project_id),
    name VARCHAR(255) NOT NULL,
    status VARCHAR(50),
    assignee VARCHAR(255),
    retrieved_at TIMESTAMP WITH TIME ZONE,
    qc_status VARCHAR(50) DEFAULT 'pending' -- e.g., pending, approved, rejected
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id SERIAL PRIMARY KEY,
    task_id INTEGER REFERENCES tasks(task_id),
    track_id INTEGER NOT NULL,
    frame INTEGER NOT NULL,
    xtl REAL,
    ytl REAL,
    xbr REAL,
    ybr REAL,
    outside BOOLEAN,
    attributes JSONB -- Store all action attributes as a JSON object
);
"""


class PostAnnotationService:
    def __init__(self, db_params: Dict[str, Any], cvat_client: CVATClient):
        """
        Initializes the service with database connection parameters and a CVAT client.

        Args:
            db_params (Dict): Dictionary with keys like 'dbname', 'user', 'password', 'host', 'port'.
            cvat_client (CVATClient): An authenticated CVATClient instance.
        """
        self.db_params = db_params
        self.cvat_client = cvat_client
        self.conn = None

    def connect_db(self):
        """Establishes a connection to the PostgreSQL database."""
        try:
            self.conn = psycopg2.connect(**self.db_params)
            logger.info("✓ Successfully connected to PostgreSQL database.")
        except psycopg2.OperationalError as e:
            logger.error(f"✗ Could not connect to the database: {e}")
            self.conn = None

    def close_db(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")

    def get_completed_tasks_from_cvat(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Fetches all tasks from a CVAT project and filters for those marked 'completed'.
        """
        try:
            url = f"{self.cvat_client.host}/api/tasks?project_id={project_id}"
            response = self.cvat_client._make_authenticated_request('GET', url)
            response.raise_for_status()

            tasks = response.json().get('results', [])
            completed_tasks = [t for t in tasks if t.get('status') == 'completed']
            logger.info(f"Found {len(completed_tasks)} completed tasks in project {project_id}.")
            return completed_tasks
        except Exception as e:
            logger.error(f"Failed to fetch tasks from CVAT: {e}")
            return []

    def export_annotations_from_cvat(self, task_id: int) -> str | None:
        """
        Exports annotations for a given task from CVAT in XML format.
        """
        try:
            # Note: The format name might need adjustment based on your CVAT version.
            url = f"{self.cvat_client.host}/api/tasks/{task_id}/annotations?format=CVAT%201.1"
            response = self.cvat_client._make_authenticated_request('GET', url)
            response.raise_for_status()
            return response.text  # Returns the XML content as a string
        except Exception as e:
            logger.error(f"Failed to export annotations for task {task_id}: {e}")
            return None

    def parse_and_store_annotations(self, task_id: int, project_id: int, assignee: str, xml_data: str):
        """
        Parses the CVAT XML data and stores it in the PostgreSQL database.
        """
        if not self.conn:
            logger.error("No database connection.")
            return

        try:
            root = ET.fromstring(xml_data)
            annotations_to_insert = []

            for track in root.findall('track'):
                track_id = int(track.get('id'))
                for box in track.findall('box'):
                    frame = int(box.get('frame'))
                    attributes = {attr.get('name'): attr.text for attr in box.findall('attribute')}

                    annotation = {
                        "task_id": task_id,
                        "track_id": track_id,
                        "frame": frame,
                        "xtl": float(box.get('xtl')),
                        "ytl": float(box.get('ytl')),
                        "xbr": float(box.get('xbr')),
                        "ybr": float(box.get('ybr')),
                        "outside": box.get('outside') == '1',
                        "attributes": json.dumps(attributes)
                    }
                    annotations_to_insert.append(annotation)

            with self.conn.cursor() as cur:
                # First, update the task's status in our database
                cur.execute(
                    """
                    UPDATE tasks
                    SET status       = %s,
                        retrieved_at = CURRENT_TIMESTAMP,
                        assignee     = %s
                    WHERE task_id = %s;
                    INSERT INTO tasks (task_id, project_id, status, retrieved_at, assignee)
                    SELECT %s,
                           %s,
                           %s,
                           CURRENT_TIMESTAMP,
                           %s WHERE NOT EXISTS (SELECT 1 FROM tasks WHERE task_id = %s);
                    """,
                    ('completed', assignee, task_id, task_id, project_id, 'completed', assignee, task_id)
                )

                # Then, insert all the annotations
                for ann in annotations_to_insert:
                    cur.execute(
                        """
                        INSERT INTO annotations (task_id, track_id, frame, xtl, ytl, xbr, ybr, outside, attributes)
                        VALUES (%(task_id)s, %(track_id)s, %(frame)s, %(xtl)s, %(ytl)s, %(xbr)s, %(ybr)s, %(outside)s,
                                %(attributes)s);
                        """,
                        ann
                    )

            self.conn.commit()
            logger.info(f"✓ Stored {len(annotations_to_insert)} annotations for task {task_id}.")

        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to parse or store annotations for task {task_id}: {e}")

    def run_sync(self, project_id: int):
        """
        Runs the full synchronization process: fetches completed tasks, exports their
        annotations, and stores them in the database.
        """
        self.connect_db()
        if not self.conn:
            return

        logger.info(f"Starting sync for project ID: {project_id}...")

        # 1. Get completed tasks from CVAT
        completed_cvat_tasks = self.get_completed_tasks_from_cvat(project_id)

        # 2. Get tasks already processed from our DB to avoid re-processing
        with self.conn.cursor() as cur:
            cur.execute("SELECT task_id FROM tasks WHERE status = 'completed'")
            processed_task_ids = {row[0] for row in cur.fetchall()}

        # 3. Determine which new tasks to process
        tasks_to_process = [
            task for task in completed_cvat_tasks
            if task['id'] not in processed_task_ids
        ]

        logger.info(f"Found {len(tasks_to_process)} new completed tasks to process.")

        # 4. Process each new task
        for task in tasks_to_process:
            task_id = task['id']
            assignee = task.get('assignee', {}).get('username', 'N/A') if task.get('assignee') else 'N/A'

            logger.info(f"Processing task {task_id} assigned to {assignee}...")

            xml_data = self.export_annotations_from_cvat(task_id)
            if xml_data:
                self.parse_and_store_annotations(task_id, project_id, assignee, xml_data)
            else:
                logger.warning(f"Could not retrieve XML for task {task_id}. Skipping.")

        self.close_db()
        logger.info("Sync process finished.")


if __name__ == '__main__':
    # --- Example Usage ---
    # 1. Fill in your CVAT and Database credentials
    CVAT_HOST = "http://localhost:8080"
    CVAT_USERNAME = "mv350"
    CVAT_PASSWORD = "Amazon123"

    DB_PARAMS = {
        "dbname": "cvat_annotations",
        "user": "postgres",
        "password": "Amazon123",
        "host": "localhost",
        "port": "5433"
    }

    # The ID of the project in CVAT you want to monitor
    PROJECT_ID_TO_SYNC = 1

    # 2. Initialize the clients
    cvat_client = CVATClient(host=CVAT_HOST, username=CVAT_USERNAME, password=CVAT_PASSWORD)

    if cvat_client.authenticated:
        # 3. Run the service
        service = PostAnnotationService(db_params=DB_PARAMS, cvat_client=cvat_client)
        service.run_sync(project_id=PROJECT_ID_TO_SYNC)
    else:
        logger.error("Could not authenticate with CVAT. Exiting.")
