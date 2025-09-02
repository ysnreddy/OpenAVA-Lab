import requests
import json
import os
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CVATClient:
    def __init__(self, host: str, username: str, password: str):
        self.host = host.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.token = None
        self.authenticated = self.login()

    def login(self) -> bool:
        """Log in to CVAT and store API token."""
        try:
            url = f"{self.host}/api/auth/login"
            resp = self.session.post(url, json={"username": self.username, "password": self.password}, timeout=30)
            resp.raise_for_status()
            key = resp.json().get("key")
            if not key:
                logger.error(f"Login response did not contain token: {resp.json()}")
                return False

            self.token = key
            self.session.headers.update({"Authorization": f"Token {self.token}"})
            logger.info(f"✓ Login successful for user: {self.username}")
            return True

        except Exception as e:
            logger.error(f"Login exception: {e}")
            return False

    def _make_authenticated_request(self, method: str, url: str, **kwargs) -> requests.Response:
        if not self.authenticated:
            raise RuntimeError("Client is not authenticated.")
        kwargs.setdefault("timeout", 60)
        try:
            return self.session.request(method.upper(), url, **kwargs)
        except Exception as e:
            logger.error(f"Request failed: {method} {url} - {e}")
            raise

    def get_project_details(self, project_id: int) -> Optional[Dict]:
        """ ✨ NEW: Fetches details for a specific project. """
        try:
            url = f"{self.host}/api/projects/{project_id}"
            resp = self._make_authenticated_request("GET", url)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get project details for ID {project_id}: {e}")
            return None

    def create_project(self, name: str, labels: List[Dict[str, Any]], org_slug: str = None) -> int | None:
        """Creates a new project, optionally within an organization."""
        try:
            payload = {"name": name, "labels": labels}
            if org_slug:
                payload['org'] = org_slug
                logger.info(f"Creating project in organization: {org_slug}")
            else:
                logger.info("Creating project in personal workspace.")

            resp = self._make_authenticated_request('POST', f"{self.host}/api/projects", json=payload)

            if resp.status_code == 201:
                project_id = resp.json().get("id")
                logger.info(f"✓ Project '{name}' created with ID: {project_id}")
                return project_id
            else:
                logger.error(f"Failed to create project: {resp.status_code} - {resp.text}")
                return None
        except Exception as e:
            logger.error(f"Exception creating project: {e}")
            return None

    def create_tasks_from_assignments(
            self,
            project_id: int,
            assignments: Dict[str, List[str]],
            zip_dir: Path,
            xml_dir: Path,
    ) -> List[Dict[str, Any]]:
        created_tasks: List[Dict[str, Any]] = []
        for annotator, clips in assignments.items():
            logger.info(f"Processing {len(clips)} clips for annotator: {annotator}")
            for i, clip_name in enumerate(clips):
                logger.info(f"Processing clip {i + 1}/{len(clips)}: {clip_name}")
                task_name = f"{annotator}_{clip_name.replace('.zip', '')}"
                zip_file_path = zip_dir / clip_name
                xml_file_path = xml_dir / f"{clip_name.replace('.zip', '')}_annotations.xml"

                if not zip_file_path.exists() or not xml_file_path.exists():
                    logger.error(f"✗ ZIP or XML file not found for {clip_name}. Skipping.")
                    continue

                task_id = self.create_task(task_name, project_id)
                if not task_id:
                    logger.error(f"✗ Failed to create task '{task_name}'")
                    continue

                if not self.upload_data_to_task(task_id, str(zip_file_path)):
                    logger.error(f"✗ Failed to upload data for task {task_id}")
                    continue

                time.sleep(2)

                if not self.import_annotations(task_id, str(xml_file_path)):
                    logger.error(f"✗ Failed to import annotations for task {task_id}")
                    continue

                if self.assign_user_to_task(task_id, annotator):
                    created_tasks.append({"task_id": task_id, "annotator": annotator, "clip": clip_name})
                else:
                    logger.error(f"✗ Failed to assign task {task_id} to {annotator}")
        return created_tasks

    def create_task(self, name: str, project_id: int) -> int | None:
        try:
            logger.info(f"Creating task '{name}' in project {project_id}...")
            payload = {"name": name, "project_id": project_id}
            resp = self._make_authenticated_request('POST', f"{self.host}/api/tasks", json=payload)
            if resp.status_code == 201:
                task_id = resp.json().get("id")
                logger.info(f"✓ Task '{name}' created with ID: {task_id}")
                return task_id
            logger.error(f"Failed to create task: {resp.status_code} - {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Exception creating task: {e}")
            return None

    def upload_data_to_task(self, task_id: int, zip_file_path: str) -> bool:
        try:
            logger.info(f"Uploading '{os.path.basename(zip_file_path)}' to task {task_id}...")
            with open(zip_file_path, 'rb') as fh:
                files = {'client_files[0]': (os.path.basename(zip_file_path), fh, 'application/zip')}
                data = {'image_quality': '95', 'use_zip_chunks': 'true', 'use_cache': 'true'}
                resp = self._make_authenticated_request(
                    'POST', f"{self.host}/api/tasks/{task_id}/data", files=files, data=data, timeout=300
                )
            if resp.status_code == 202:
                logger.info("✓ Data upload accepted. Waiting for processing...")
                return self.wait_for_data_upload_completion(task_id)
            logger.error(f"Data upload failed: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Exception uploading data: {e}")
            return False
        
    def get_project_details(self, project_id: int) -> Optional[Dict]:
        """ Fetches details for a specific project from the CVAT API. """
        try:
            url = f"{self.host}/api/projects/{project_id}"
            resp = self._make_authenticated_request("GET", url)
            resp.raise_for_status()
            logger.info(f"✓ Successfully fetched details for project {project_id}")
            return resp.json()
        except Exception as e:
            logger.error(f"Failed to get project details for ID {project_id}: {e}")
        return None  
    
    
    def get_all_tasks_for_project(self, project_id: int) -> List[Dict]:
        """ ✨ NEW: Fetches the full details of all tasks within a project. """
        try:
            url = f"{self.host}/api/tasks?project_id={project_id}"
            resp = self._make_authenticated_request("GET", url)
            resp.raise_for_status()
            logger.info(f"✓ Successfully fetched all tasks for project {project_id}")
            return resp.json().get("results", [])
        except Exception as e:
            logger.error(f"Failed to get tasks for project ID {project_id}: {e}")
            return []  

    def import_annotations(self, task_id: int, xml_file: str) -> bool:
        try:
            url = f"{self.host}/api/tasks/{task_id}/annotations?action=upload&format=CVAT%201.1"
            with open(xml_file, "rb") as fh:
                files = {"annotation_file": (os.path.basename(xml_file), fh, "application/xml")}
                resp = self._make_authenticated_request("POST", url, files=files)

            if resp.status_code not in (201, 202):
                logger.error(f"Annotation import failed to start: {resp.status_code} - {resp.text}")
                return False

            rq_id = resp.json().get("rq_id")
            if not rq_id: return True

            logger.info(f"Started annotation import job {rq_id} for task {task_id}")
            while True:
                status_resp = self._make_authenticated_request("GET", f"{self.host}/api/requests/{rq_id}")
                if status_resp.status_code != 200: return False
                status = status_resp.json().get("status")
                if status == "finished": return True
                if status == "failed":
                    logger.error(f"✗ Annotation import failed: {status_resp.json()}")
                    return False
                time.sleep(2)
        except Exception as e:
            logger.error(f"Exception importing annotations: {e}")
            return False

    def assign_user_to_task(self, task_id: int, username: str) -> bool:
        try:
            logger.info(f"Assigning user '{username}' to task {task_id}...")
            resp = self._make_authenticated_request('GET', f"{self.host}/api/users", params={"search": username})
            if resp.status_code != 200 or not resp.json().get('results'): return False
            user_id = resp.json()['results'][0]['id']

            resp = self._make_authenticated_request('GET', f"{self.host}/api/jobs", params={"task_id": task_id})
            if resp.status_code != 200: return False
            jobs = resp.json().get('results', [])
            if not jobs: return False

            ok = True
            for job in jobs:
                j_resp = self._make_authenticated_request('PATCH', f"{self.host}/api/jobs/{job['id']}",
                                                            json={'assignee': user_id})
                if j_resp.status_code == 200:
                    logger.info(f"✓ Assigned '{username}' to job {job['id']}")
                else:
                    ok = False
            return ok
        except Exception as e:
            logger.error(f"Exception assigning user: {e}")
            return False

    def wait_for_data_upload_completion(self, task_id: int, max_wait: int = 600) -> bool:
        start = time.time()
        while time.time() - start < max_wait:
            resp = self._make_authenticated_request('GET', f"{self.host}/api/tasks/{task_id}/status")
            if resp.status_code == 200:
                state = (resp.json().get('state') or '').lower()
                if state in ('finished', 'completed'): return True
                if state in ('failed',): return False
                time.sleep(3)
            else:
                time.sleep(3)
        return False


def get_default_labels() -> List[Dict[str, Any]]:
    return [
        {
            "name": "person",
            "color": "#ff0000",
            "tools": [{"name": "box", "type": "box"}],
            "attributes": [
                {"name": "walking_behavior", "mutable": True, "input_type": "select", "default_value": "normal_walk", "values": ["normal_walk", "fast_walk", "slow_walk", "standing_still", "jogging", "window_shopping"]},
                {"name": "phone_usage", "mutable": True, "input_type": "select", "default_value": "no_phone", "values": ["no_phone", "talking_phone", "texting", "taking_photo", "listening_music"]},
                {"name": "social_interaction", "mutable": True, "input_type": "select", "default_value": "alone", "values": ["alone", "talking_companion", "group_walking", "greeting_someone", "asking_directions", "avoiding_crowd"]},
                {"name": "carrying_items", "mutable": True, "input_type": "select", "default_value": "empty_hands", "values": ["empty_hands", "shopping_bags", "backpack", "briefcase_bag", "umbrella", "food_drink", "multiple_items"]},
                {"name": "street_behavior", "mutable": True, "input_type": "select", "default_value": "sidewalk_walking", "values": ["sidewalk_walking", "crossing_street", "waiting_signal", "looking_around", "checking_map", "entering_building", "exiting_building"]},
                {"name": "posture_gesture", "mutable": True, "input_type": "select", "default_value": "upright_normal", "values": ["upright_normal", "looking_down", "looking_up", "hands_in_pockets", "arms_crossed", "pointing_gesture", "bowing_gesture"]},
                {"name": "clothing_style", "mutable": True, "input_type": "select", "default_value": "business_attire", "values": ["business_attire", "casual_wear", "tourist_style", "school_uniform", "sports_wear", "traditional_wear"]},
                {"name": "time_context", "mutable": True, "input_type": "select", "default_value": "rush_hour", "values": ["rush_hour", "leisure_time", "shopping_time", "tourist_hours", "lunch_break", "evening_stroll"]},
            ]
        }
    ]