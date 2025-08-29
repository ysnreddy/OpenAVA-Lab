import argparse
import logging
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
import time
import io
import zipfile

import psycopg2
import psycopg2.extras

# Assume cvat_integration.py is in the services directory
from cvat_integration import CVATClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class PostAnnotationService:
    def __init__(self, db_params: Dict[str, str], cvat_client: CVATClient):
        self.db_params = db_params
        self.cvat_client = cvat_client
        self.conn: Optional[psycopg2.extensions.connection] = None

    def connect_db(self) -> bool:
        try:
            self.conn = psycopg2.connect(**self.db_params)
            logger.info("✓ Successfully connected to PostgreSQL.")
            return True
        except psycopg2.OperationalError as e:
            logger.error(f"✗ Could not connect to the database: {e}")
            self.conn = None
            return False

    def close_db(self) -> None:
        if self.conn:
            self.conn.close()
            logger.info("Database connection closed.")
            self.conn = None

    def get_completed_jobs_from_cvat(self, project_id: int) -> List[Dict]:
        try:
            url = f"{self.cvat_client.host}/api/jobs?project_id={project_id}"
            resp = self.cvat_client._make_authenticated_request("GET", url)
            resp.raise_for_status()
            jobs = resp.json().get("results", [])
            completed_jobs = [job for job in jobs if job.get("state") == "completed"]
            logger.info(f"Found {len(completed_jobs)} completed jobs in CVAT project {project_id}")
            return completed_jobs
        except Exception as e:
            logger.error(f"Error fetching jobs from CVAT: {e}")
            return []

    def export_annotations_from_job(self, job_id: int) -> Optional[Dict]:
        try:
            url = f"{self.cvat_client.host}/api/jobs/{job_id}/dataset/export"
            params = {"format": "CVAT for video 1.1", "save_images": False}
            resp = self.cvat_client._make_authenticated_request("POST", url, params=params)

            if resp.status_code != 202:
                logger.error(f"Failed to start export for job {job_id}: {resp.status_code} - {resp.text}")
                return None

            rq_id = resp.json().get("rq_id")
            if not rq_id: return None

            logger.info(f"Started annotation export job {rq_id} for job {job_id}")
            while True:
                status_resp = self.cvat_client._make_authenticated_request("GET",
                                                                           f"{self.cvat_client.host}/api/requests/{rq_id}")
                if status_resp.status_code != 200: return None

                status_data = status_resp.json()
                status = status_data.get("status")

                if status == "finished":
                    result_url = status_data.get("result_url")
                    if not result_url: return None

                    download_resp = self.cvat_client._make_authenticated_request("GET", result_url)
                    download_resp.raise_for_status()

                    with zipfile.ZipFile(io.BytesIO(download_resp.content)) as z:
                        for filename in z.namelist():
                            if filename.lower().endswith('annotations.xml'):
                                xml_data = z.read(filename).decode('utf-8')
                                logger.info(f"✓ Successfully extracted '{filename}' for job {job_id}.")
                                return {"type": "xml", "data": xml_data}
                    return None
                elif status == "failed":
                    logger.error(f"✗ Annotation export failed for job {job_id}: {status_data}")
                    return None
                else:
                    time.sleep(3)
        except Exception as e:
            logger.error(f"Failed to export annotations for job {job_id}: {e}")
            return None

    @staticmethod
    def _parse_cvat_xml(xml_text: str) -> List[tuple]:
        root = ET.fromstring(xml_text)
        annotations = []
        for track in root.findall("track"):
            track_id = int(track.get("id"))
            for box in track.findall("box"):
                annotations.append((
                    track_id, int(box.get("frame")), float(box.get("xtl")), float(box.get("ytl")),
                    float(box.get("xbr")), float(box.get("ybr")), box.get("outside") == "1",
                    json.dumps({attr.get("name"): (attr.text or "") for attr in box.findall("attribute")}),
                ))
        return annotations

    def process_and_store_job(self, project_id: int, job: Dict) -> None:
        if not self.conn: raise ConnectionError("Database not connected.")
        job_id, task_id = job["id"], job["task_id"]
        assignee = (job.get("assignee") or {}).get("username", "N/A")

        logger.info(f"Processing completed job {job_id} for task {task_id} by {assignee}...")
        annotations_data = self.export_annotations_from_job(job_id)
        if not annotations_data or annotations_data.get("type") != "xml":
            logger.warning(f"No valid XML annotations for job {job_id}. Skipping.")
            return

        annotations = self._parse_cvat_xml(annotations_data["data"])
        if not annotations:
            logger.warning(f"No annotations could be parsed for job {job_id}. Skipping.")
            return

        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO tasks (task_id, project_id, name, status, assignee, retrieved_at) VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP) ON CONFLICT (task_id) DO UPDATE SET status = EXCLUDED.status, assignee = EXCLUDED.assignee, retrieved_at = EXCLUDED.retrieved_at;",
                    (task_id, project_id, f"Task {task_id}", 'completed', assignee)
                )
                cur.execute("DELETE FROM annotations WHERE task_id = %s;", (task_id,))
                insert_query = "INSERT INTO annotations (task_id, track_id, frame, xtl, ytl, xbr, ybr, outside, attributes) VALUES %s;"
                data_to_insert = [(task_id,) + ann for ann in annotations]
                psycopg2.extras.execute_values(cur, insert_query, data_to_insert,
                                               template="(%s, %s, %s, %s, %s, %s, %s, %s, %s)")
                logger.info(f"✓ Stored {cur.rowcount} annotations for task {task_id}.")
            self.conn.commit()
        except Exception as e:
            logger.error(f"Database transaction failed for task {task_id}: {e}")
            self.conn.rollback()

    def run_sync(self, project_id: int) -> None:
        if not self.connect_db(): return
        try:
            # ✨ FIX: Get project details from CVAT to ensure it exists in our DB
            project_details = self.cvat_client.get_project_details(project_id)
            if not project_details:
                logger.error(f"Could not find project with ID {project_id} in CVAT.")
                return

            with self.conn.cursor() as cur:
                # ✨ FIX: Insert the project into our DB before processing tasks
                cur.execute(
                    "INSERT INTO projects (project_id, name) VALUES (%s, %s) ON CONFLICT (project_id) DO NOTHING;",
                    (project_id, project_details['name'])
                )
                self.conn.commit()

                completed_jobs = self.get_completed_jobs_from_cvat(project_id)
                cur.execute("SELECT task_id FROM tasks WHERE qc_status != 'pending'")
                processed_task_ids = {row[0] for row in cur.fetchall()}

            jobs_to_process = [j for j in completed_jobs if j['task_id'] not in processed_task_ids]
            logger.info(f"Found {len(jobs_to_process)} new completed jobs to process.")

            for job in jobs_to_process:
                self.process_and_store_job(project_id, job)
        finally:
            self.close_db()


def parse_args():
    parser = argparse.ArgumentParser(description="Sync completed CVAT jobs to a PostgreSQL database.")
    parser.add_argument("--project-id", required=True, type=int, help="CVAT project ID to sync.")
    return parser.parse_args()


if __name__ == "__main__":
    DB_PARAMS = {
        "dbname": "cvat_annotations_db",
        "user": "admin",
        "password": "admin",
        "host": "localhost",
        "port": "55432",
    }
    CVAT_HOST = "http://localhost:8080"
    CVAT_USERNAME = "strawhat03"
    CVAT_PASSWORD = "Test@123"

    # You will need to add a 'get_project_details' method to your CVATClient
    # Here's how to add it to your services/cvat_integration.py file:
    """
    # In services/cvat_integration.py, inside the CVATClient class:

    def get_project_details(self, project_id: int) -> Optional[Dict]:
        try:
            url = f"{self.host}/api/projects/{project_id}"
            resp = self._make_authenticated_request("GET", url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get project details for ID {project_id}: {e}")
            return None
    """

    args = parse_args()
    # Make sure your CVATClient class has the get_project_details method
    cvat_client = CVATClient(host=CVAT_HOST, username=CVAT_USERNAME, password=CVAT_PASSWORD)

    if cvat_client.authenticated:
        service = PostAnnotationService(db_params=DB_PARAMS, cvat_client=cvat_client)
        service.run_sync(project_id=args.project_id)
    else:
        logger.error("CVAT client authentication failed. Exiting.")