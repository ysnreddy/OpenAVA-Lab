# # metrics_logging/post_annotation_service.py
# import argparse
# import logging
# import json
# import xml.etree.ElementTree as ET
# from typing import Dict, List, Optional
# import time
# import io
# import zipfile
# from dateutil import parser  # timestamp parsing
# import os
# import psycopg2
# import psycopg2.extras
# from pathlib import Path
# import sys

# # Ensure parent directory is in path
# sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# from metrics_logging.metrics_logger import log_metric  # metrics
# from cvat_integration import CVATClient

# # ---------------- Logging ----------------
# logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
# logger = logging.getLogger(__name__)

# # ---------------- PostAnnotation Service ----------------
# class PostAnnotationService:
#     def __init__(self, db_params: Dict[str, str], cvat_client: CVATClient, normalized_clips: List[str]):
#         self.db_params = db_params
#         self.cvat_client = cvat_client
#         self.normalized_clips = normalized_clips
#         self.conn: Optional[psycopg2.extensions.connection] = None

#     # ---------------- DB Connection ----------------
#     def connect_db(self) -> bool:
#         try:
#             self.conn = psycopg2.connect(**self.db_params)
#             logger.info("✓ Successfully connected to PostgreSQL.")
#             return True
#         except psycopg2.OperationalError as e:
#             logger.error(f"✗ Could not connect to the database: {e}")
#             self.conn = None
#             return False

#     def close_db(self) -> None:
#         if self.conn:
#             self.conn.close()
#             logger.info("Database connection closed.")
#             self.conn = None

#     # ---------------- CVAT Jobs ----------------
#     def get_completed_jobs_from_cvat(self, project_id: int) -> List[Dict]:
#         try:
#             all_jobs = []
#             url = f"{self.cvat_client.host}/api/jobs?project_id={project_id}"
            
#             while url:
#                 resp = self.cvat_client._make_authenticated_request("GET", url)
#                 resp.raise_for_status()
#                 data = resp.json()
#                 jobs = data.get("results", [])
#                 all_jobs.extend(jobs)
#                 url = data.get("next")
#                 logger.info(f"Fetched {len(jobs)} jobs, total so far: {len(all_jobs)}")
            
#             completed_jobs = [job for job in all_jobs if job.get("state") == "completed"]
#             logger.info(f"Found {len(completed_jobs)} completed jobs out of {len(all_jobs)} total jobs.")

#             # Log annotator counts
#             annotator_counts = {}
#             for job in completed_jobs:
#                 assignee = (job.get("assignee") or {}).get("username", "unassigned")
#                 annotator_counts[assignee] = annotator_counts.get(assignee, 0) + 1
#             for annotator, count in annotator_counts.items():
#                 logger.info(f"  {annotator}: {count} completed jobs")
            
#             return completed_jobs
#         except Exception as e:
#             logger.error(f"Error fetching jobs from CVAT: {e}")
#             return []

#     # ---------------- Export Annotations ----------------
#     def export_annotations_from_job(self, job_id: int, project_id: int, task_id: int, assignee: str) -> Optional[Dict]:
#         try:
#             log_metric("export_start", project_id=project_id, task_id=task_id, annotator=assignee, extra={"job_id": job_id})

#             url = f"{self.cvat_client.host}/api/jobs/{job_id}/dataset/export"
#             params = {"format": "CVAT for video 1.1", "save_images": False}
#             resp = self.cvat_client._make_authenticated_request("POST", url, params=params)

#             if resp.status_code != 202:
#                 logger.error(f"Failed to start export for job {job_id}: {resp.status_code} - {resp.text}")
#                 log_metric("job_failed", project_id=project_id, task_id=task_id, annotator=assignee,
#                            extra={"job_id": job_id, "reason": resp.text})
#                 return None

#             rq_id = resp.json().get("rq_id")
#             if not rq_id:
#                 return None

#             logger.info(f"Started annotation export job {rq_id} for job {job_id}")

#             while True:
#                 status_resp = self.cvat_client._make_authenticated_request("GET", f"{self.cvat_client.host}/api/requests/{rq_id}")
#                 if status_resp.status_code != 200:
#                     logger.error(f"Failed to check export status for job {job_id}")
#                     return None

#                 status_data = status_resp.json()
#                 status = status_data.get("status")

#                 if status == "finished":
#                     result_url = status_data.get("result_url")
#                     if not result_url:
#                         logger.error(f"No result URL for finished export {rq_id}")
#                         return None

#                     download_resp = self.cvat_client._make_authenticated_request("GET", result_url)
#                     download_resp.raise_for_status()

#                     with zipfile.ZipFile(io.BytesIO(download_resp.content)) as z:
#                         for filename in z.namelist():
#                             if filename.lower().endswith('annotations.xml'):
#                                 xml_data = z.read(filename).decode('utf-8')
#                                 logger.info(f"✓ Extracted '{filename}' for job {job_id}.")
#                                 log_metric("export_end", project_id=project_id, task_id=task_id, annotator=assignee, extra={"job_id": job_id})
#                                 return {"type": "xml", "data": xml_data}

#                     logger.error(f"No XML found in downloaded archive for job {job_id}.")
#                     log_metric("job_failed", project_id=project_id, task_id=task_id, annotator=assignee,
#                                extra={"job_id": job_id, "reason": "no_xml"})
#                     return None

#                 elif status == "failed":
#                     logger.error(f"✗ Annotation export failed for job {job_id}: {status_data}")
#                     log_metric("job_failed", project_id=project_id, task_id=task_id, annotator=assignee,
#                                extra={"job_id": job_id, "reason": "export_failed"})
#                     return None
#                 else:
#                     logger.info(f"Export for job {job_id} is '{status}', waiting...")
#                     time.sleep(3)

#         except Exception as e:
#             logger.error(f"Failed to export annotations for job {job_id}: {e}")
#             log_metric("job_failed", project_id=project_id, task_id=task_id, annotator=assignee,
#                        extra={"job_id": job_id, "reason": str(e)})
#             return None

#     # ---------------- Parse CVAT XML ----------------
#     @staticmethod
#     def _parse_cvat_xml(xml_text: str) -> List[tuple]:
#         root = ET.fromstring(xml_text)
#         annotations = []
#         for track in root.findall("track"):
#             track_id = int(track.get("id"))
#             for box in track.findall("box"):
#                 annotations.append((
#                     track_id,
#                     int(box.get("frame")),
#                     float(box.get("xtl")),
#                     float(box.get("ytl")),
#                     float(box.get("xbr")),
#                     float(box.get("ybr")),
#                     box.get("outside") == "1",
#                     json.dumps({attr.get("name"): (attr.text or "") for attr in box.findall("attribute")})
#                 ))
#         return annotations

#     # ---------------- Process & Store ----------------
#     def process_and_store_job(self, project_id: int, job: Dict) -> None:
#         if not self.conn:
#             raise ConnectionError("Database not connected.")

#         job_id, task_id = job["id"], job["task_id"]
#         assignee = (job.get("assignee") or {}).get("username", "N/A")

#         # ✅ Use the actual task name from CVAT (no normalize fallback!)
#         # ✅ Always fetch the true task name from CVAT if missing
#         task_name = job.get("task", {}).get("name")
#         if not task_name:
#             try:
#                 task_resp = self.cvat_client._make_authenticated_request(
#                     "GET", f"{self.cvat_client.host}/api/tasks/{task_id}"
#                 )
#                 if task_resp.status_code == 200:
#                     task_name = task_resp.json().get("name", f"{assignee}_task{task_id}")
#                 else:
#                     task_name = f"{assignee}_task{task_id}"  # last fallback
#             except Exception as e:
#                 logger.warning(f"Could not fetch task {task_id} name from CVAT: {e}")
#                 task_name = f"{assignee}_task{task_id}"

#                 logger.info(f"Processing job {job_id} for task '{task_name}' by {assignee}...")

#         annotations_data = self.export_annotations_from_job(job_id, project_id, task_id, assignee)
#         if not annotations_data or annotations_data.get("type") != "xml":
#             logger.warning(f"No valid XML for job {job_id}. Skipping.")
#             return

#         annotations = self._parse_cvat_xml(annotations_data["data"])
#         if not annotations:
#             logger.warning(f"No annotations parsed for job {job_id}. Skipping.")
#             return

#         start_ts = parser.parse(job["created_date"]).timestamp()
#         end_ts = parser.parse(job["updated_date"]).timestamp()
#         duration_seconds = end_ts - start_ts

#         try:
#             with self.conn.cursor() as cur:
#                 # ---------------- Ensure Project Exists ----------------
#                 cur.execute(
#                     """
#                     INSERT INTO projects (project_id, name)
#                     VALUES (%s, %s)
#                     ON CONFLICT (project_id) DO NOTHING;
#                     """,
#                     (project_id, f"CVAT Project {project_id}")
#                 )

#                 # ---------------- Insert/Update Task ----------------
#                 cur.execute(
#                     """
#                     INSERT INTO tasks (task_id, project_id, name, status, assignee, retrieved_at)
#                     VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
#                     ON CONFLICT (task_id) DO UPDATE 
#                     SET name = EXCLUDED.name,
#                         assignee = EXCLUDED.assignee,
#                         retrieved_at = EXCLUDED.retrieved_at;
#                     """,
#                     (task_id, project_id, task_name, 'in_progress', assignee)
#                 )

#                 # ---------------- Insert Annotations ----------------
#                 cur.execute("DELETE FROM annotations WHERE job_id = %s;", (job_id,))
#                 insert_query = """
#                     INSERT INTO annotations (
#                         task_id, job_id, track_id, frame, xtl, ytl, xbr, ybr, outside, attributes
#                     ) VALUES %s;
#                 """
#                 data_to_insert = [(task_id, job_id) + ann for ann in annotations]
#                 psycopg2.extras.execute_values(cur, insert_query, data_to_insert,
#                                                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")

#                 logger.info(f"✓ Stored {len(annotations)} annotations for job {job_id}.")
#             self.conn.commit()

#             log_metric("job_completed", project_id=project_id, task_id=task_id, annotator=assignee,
#                        extra={"job_id": job_id, "annotation_count": len(annotations),
#                               "duration_seconds": duration_seconds})

#         except Exception as e:
#             logger.error(f"DB transaction failed for job {job_id}: {e}")
#             self.conn.rollback()
#             log_metric("job_failed", project_id=project_id, task_id=task_id, annotator=assignee,
#                        extra={"job_id": job_id, "reason": str(e)})

#     # ---------------- Main Sync ----------------
#     def run_sync(self, project_id: int) -> None:
#         if not self.connect_db():
#             return
#         try:
#             completed_jobs = self.get_completed_jobs_from_cvat(project_id)

#             with self.conn.cursor() as cur:
#                 cur.execute("SELECT DISTINCT job_id FROM annotations")
#                 processed_job_ids = {row[0] for row in cur.fetchall()}

#             jobs_to_process = [j for j in completed_jobs if j['id'] not in processed_job_ids]
#             logger.info(f"{len(jobs_to_process)} new completed jobs to process.")

#             for job in jobs_to_process:
#                 self.process_and_store_job(project_id, job)
#         finally:
#             self.close_db()

# # ---------------- CLI ----------------
# def parse_args():
#     parser = argparse.ArgumentParser(description="Sync completed CVAT jobs to a PostgreSQL DB.")
#     parser.add_argument("--project-id", required=True, type=int, help="CVAT project ID to sync.")
#     return parser.parse_args()


# if __name__ == "__main__":
#     DB_PARAMS = {
#         "dbname": "cvat_annotations_db",
#         "user": "admin",
#         "password": "admin",
#         "host": "localhost",
#         "port": "55432",
#     }
#     CVAT_HOST = "http://localhost:8080"
#     CVAT_USERNAME = "strawhat03"
#     CVAT_PASSWORD = "Test@123"

#     args = parse_args()
#     cvat_client = CVATClient(host=CVAT_HOST, username=CVAT_USERNAME, password=CVAT_PASSWORD)

#     if cvat_client.authenticated:
#         DATA_PATH = Path("data/uploads")
#         normalized_clips = [f for f in os.listdir(DATA_PATH) if f.endswith(".zip")]
#         service = PostAnnotationService(db_params=DB_PARAMS, cvat_client=cvat_client, normalized_clips=normalized_clips)
#         service.run_sync(project_id=args.project_id)
#     else:
#         logger.error("CVAT client authentication failed. Exiting.")


















# metrics_logging/post_annotation_service.py
# metrics_logging/post_annotation_service.py
import argparse
import logging
import json
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
import time
import io
import zipfile
from dateutil import parser  # timestamp parsing
import os
import psycopg2
import psycopg2.extras
from pathlib import Path
import sys

# Ensure parent directory is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from metrics_logging.metrics_logger import log_metric  # metrics logging
from cvat_integration import CVATClient

# ---------------- Logging ----------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ---------------- PostAnnotation Service ----------------
class PostAnnotationService:
    def __init__(self, db_params: Dict[str, str], cvat_client: CVATClient, normalized_clips: List[str]):
        self.db_params = db_params
        self.cvat_client = cvat_client
        self.normalized_clips = normalized_clips
        self.conn: Optional[psycopg2.extensions.connection] = None

    # ---------------- DB Connection ----------------
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

    # ---------------- CVAT Jobs ----------------
    def get_completed_jobs_from_cvat(self, project_id: int) -> List[Dict]:
        try:
            all_jobs = []
            url = f"{self.cvat_client.host}/api/jobs?project_id={project_id}"
            
            while url:
                resp = self.cvat_client._make_authenticated_request("GET", url)
                resp.raise_for_status()
                data = resp.json()
                jobs = data.get("results", [])
                all_jobs.extend(jobs)
                url = data.get("next")
                logger.info(f"Fetched {len(jobs)} jobs, total so far: {len(all_jobs)}")
            
            completed_jobs = [job for job in all_jobs if job.get("state") == "completed"]
            logger.info(f"Found {len(completed_jobs)} completed jobs out of {len(all_jobs)} total jobs.")

            # Log annotator counts
            annotator_counts = {}
            for job in completed_jobs:
                assignee = (job.get("assignee") or {}).get("username", "unassigned")
                annotator_counts[assignee] = annotator_counts.get(assignee, 0) + 1
            for annotator, count in annotator_counts.items():
                logger.info(f"  {annotator}: {count} completed jobs")
            
            return completed_jobs
        except Exception as e:
            logger.error(f"Error fetching jobs from CVAT: {e}")
            return []

    # ---------------- Export Annotations from Job ----------------
    def export_annotations_from_job(self, job_id: int, project_id: int, task_id: int, assignee: str) -> Optional[Dict]:
        """Export annotations for a specific job and return the XML data."""
        export_start_time = time.time()
        
        try:
            # Log export start
            log_metric("export_start", project_id=project_id, task_id=task_id, annotator=assignee, 
                      extra={"job_id": job_id})

            url = f"{self.cvat_client.host}/api/jobs/{job_id}/dataset/export"
            params = {"format": "CVAT for video 1.1", "save_images": False}
            resp = self.cvat_client._make_authenticated_request("POST", url, params=params)

            if resp.status_code != 202:
                logger.error(f"Failed to start export for job {job_id}: {resp.status_code} - {resp.text}")
                log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                          extra={"job_id": job_id, "time_on_export": time.time() - export_start_time, 
                                "export_status": "failed", "reason": resp.text})
                return None

            rq_id = resp.json().get("rq_id")
            if not rq_id:
                log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                          extra={"job_id": job_id, "time_on_export": time.time() - export_start_time,
                                "export_status": "failed", "reason": "no_rq_id"})
                return None

            logger.info(f"Started annotation export job {rq_id} for job {job_id}")

            # Poll for completion
            while True:
                status_resp = self.cvat_client._make_authenticated_request("GET", f"{self.cvat_client.host}/api/requests/{rq_id}")
                if status_resp.status_code != 200:
                    logger.error(f"Failed to check export status for job {job_id}")
                    log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                              extra={"job_id": job_id, "time_on_export": time.time() - export_start_time,
                                    "export_status": "failed", "reason": "status_check_failed"})
                    return None

                status_data = status_resp.json()
                status = status_data.get("status")

                if status == "finished":
                    result_url = status_data.get("result_url")
                    if not result_url:
                        logger.error(f"No result URL for finished export {rq_id}")
                        log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                                  extra={"job_id": job_id, "time_on_export": time.time() - export_start_time,
                                        "export_status": "failed", "reason": "no_result_url"})
                        return None

                    download_resp = self.cvat_client._make_authenticated_request("GET", result_url)
                    download_resp.raise_for_status()

                    with zipfile.ZipFile(io.BytesIO(download_resp.content)) as z:
                        for filename in z.namelist():
                            if filename.lower().endswith('annotations.xml'):
                                xml_data = z.read(filename).decode('utf-8')
                                export_duration = time.time() - export_start_time
                                
                                # Log successful export
                                log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                                          extra={"job_id": job_id, "time_on_export": export_duration,
                                                "export_status": "success", "output_file": filename})
                                
                                logger.info(f"✓ Extracted '{filename}' for job {job_id} in {export_duration:.2f}s")
                                return {"type": "xml", "data": xml_data}

                    logger.error(f"No XML found in downloaded archive for job {job_id}.")
                    log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                              extra={"job_id": job_id, "time_on_export": time.time() - export_start_time,
                                    "export_status": "failed", "reason": "no_xml_in_archive"})
                    return None

                elif status == "failed":
                    logger.error(f"✗ Annotation export failed for job {job_id}: {status_data}")
                    log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                              extra={"job_id": job_id, "time_on_export": time.time() - export_start_time,
                                    "export_status": "failed", "reason": "cvat_export_failed"})
                    return None
                else:
                    logger.info(f"Export for job {job_id} is '{status}', waiting...")
                    time.sleep(3)

        except Exception as e:
            export_duration = time.time() - export_start_time
            logger.error(f"Failed to export annotations for job {job_id}: {e}")
            log_metric("export_time", project_id=project_id, task_id=task_id, annotator=assignee,
                      extra={"job_id": job_id, "time_on_export": export_duration,
                            "export_status": "error", "error": str(e)})
            return None

    # ---------------- Parse CVAT XML ----------------
    @staticmethod
    def _parse_cvat_xml(xml_text: str) -> List[tuple]:
        root = ET.fromstring(xml_text)
        annotations = []
        for track in root.findall("track"):
            track_id = int(track.get("id"))
            for box in track.findall("box"):
                annotations.append((
                    track_id,
                    int(box.get("frame")),
                    float(box.get("xtl")),
                    float(box.get("ytl")),
                    float(box.get("xbr")),
                    float(box.get("ybr")),
                    box.get("outside") == "1",
                    json.dumps({attr.get("name"): (attr.text or "") for attr in box.findall("attribute")})
                ))
        return annotations

    # ---------------- Process & Store ----------------
    def process_and_store_job(self, project_id: int, job: Dict) -> None:
        if not self.conn:
            raise ConnectionError("Database not connected.")

        job_id, task_id = job["id"], job["task_id"]
        assignee = (job.get("assignee") or {}).get("username", "N/A")

        # Get task name
        task_name = job.get("task", {}).get("name")
        if not task_name:
            try:
                task_resp = self.cvat_client._make_authenticated_request(
                    "GET", f"{self.cvat_client.host}/api/tasks/{task_id}"
                )
                if task_resp.status_code == 200:
                    task_name = task_resp.json().get("name", f"{assignee}_task{task_id}")
                else:
                    task_name = f"{assignee}_task{task_id}"
            except Exception as e:
                logger.warning(f"Could not fetch task {task_id} name from CVAT: {e}")
                task_name = f"{assignee}_task{task_id}"

        logger.info(f"Processing job {job_id} for task '{task_name}' by {assignee}...")

        # Log task_ready event (task is ready to be processed)
        log_metric("task_ready", project_id=project_id, task_id=task_id, annotator=assignee,
                  extra={"time_on_task_creation": 0})  # Zero since task was already created

        # Export annotations (this will log export_start and export_time)
        annotations_data = self.export_annotations_from_job(job_id, project_id, task_id, assignee)
        if not annotations_data or annotations_data.get("type") != "xml":
            logger.warning(f"No valid XML for job {job_id}. Skipping.")
            return

        annotations = self._parse_cvat_xml(annotations_data["data"])
        if not annotations:
            logger.warning(f"No annotations parsed for job {job_id}. Skipping.")
            return

        start_ts = parser.parse(job["created_date"]).timestamp()
        end_ts = parser.parse(job["updated_date"]).timestamp()
        duration_seconds = end_ts - start_ts

        try:
            with self.conn.cursor() as cur:
                # Ensure project exists
                cur.execute(
                    """
                    INSERT INTO projects (project_id, name)
                    VALUES (%s, %s)
                    ON CONFLICT (project_id) DO NOTHING;
                    """,
                    (project_id, f"CVAT Project {project_id}")
                )

                # Insert/Update Task
                cur.execute(
                    """
                    INSERT INTO tasks (task_id, project_id, name, status, assignee, retrieved_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (task_id) DO UPDATE 
                    SET name = EXCLUDED.name,
                        assignee = EXCLUDED.assignee,
                        retrieved_at = EXCLUDED.retrieved_at;
                    """,
                    (task_id, project_id, task_name, 'in_progress', assignee)
                )

                # Insert Annotations
                cur.execute("DELETE FROM annotations WHERE job_id = %s;", (job_id,))
                insert_query = """
                    INSERT INTO annotations (
                        task_id, job_id, track_id, frame, xtl, ytl, xbr, ybr, outside, attributes
                    ) VALUES %s;
                """
                data_to_insert = [(task_id, job_id) + ann for ann in annotations]
                psycopg2.extras.execute_values(cur, insert_query, data_to_insert,
                                               template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")

                logger.info(f"✓ Stored {len(annotations)} annotations for job {job_id}.")
            self.conn.commit()

            # Log job completion
            log_metric("job_completed", project_id=project_id, task_id=task_id, annotator=assignee,
                       extra={"job_id": job_id, "annotation_count": len(annotations),
                              "duration_seconds": duration_seconds})

        except Exception as e:
            logger.error(f"DB transaction failed for job {job_id}: {e}")
            self.conn.rollback()
            log_metric("job_failed", project_id=project_id, task_id=task_id, annotator=assignee,
                       extra={"job_id": job_id, "reason": str(e)})

    # ---------------- Main Sync ----------------
    def run_sync(self, project_id: int) -> None:
        if not self.connect_db():
            return
        try:
            completed_jobs = self.get_completed_jobs_from_cvat(project_id)

            with self.conn.cursor() as cur:
                cur.execute("SELECT DISTINCT job_id FROM annotations")
                processed_job_ids = {row[0] for row in cur.fetchall()}

            jobs_to_process = [j for j in completed_jobs if j['id'] not in processed_job_ids]
            logger.info(f"{len(jobs_to_process)} new completed jobs to process.")

            for job in jobs_to_process:
                self.process_and_store_job(project_id, job)
                
        finally:
            self.close_db()

# ---------------- CLI ----------------
def parse_args():
    parser = argparse.ArgumentParser(description="Sync completed CVAT jobs to a PostgreSQL DB.")
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

    args = parse_args()
    cvat_client = CVATClient(host=CVAT_HOST, username=CVAT_USERNAME, password=CVAT_PASSWORD)

    if cvat_client.authenticated:
        DATA_PATH = Path("data/uploads")
        normalized_clips = [f for f in os.listdir(DATA_PATH) if f.endswith(".zip")]
        service = PostAnnotationService(db_params=DB_PARAMS, cvat_client=cvat_client, normalized_clips=normalized_clips)
        service.run_sync(project_id=args.project_id)
    else:
        logger.error("CVAT client authentication failed. Exiting.")