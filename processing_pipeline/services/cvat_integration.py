import requests
import json
import os
import zipfile
import logging
from typing import List, Dict, Any
from pathlib import Path
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class CVATClient:
    def __init__(self, host, username, password):
        self.host = host.rstrip('/')
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.csrf_token = None
        self.authenticated = False
        self.login()

    def get_csrf_token(self):
        try:
            response = self.session.get(f"{self.host}/auth/login", timeout=30)
            response.raise_for_status()

            if 'csrftoken' in response.cookies:
                self.csrf_token = response.cookies['csrftoken']
                self.session.headers.update({'X-CSRFToken': self.csrf_token})
                logger.debug(f"CSRF token updated: {self.csrf_token[:10]}...")
                return True
        except Exception as e:
            logger.error(f"Failed to get CSRF token: {e}")
            return False
        return False

    def login(self):
        try:
            if not self.get_csrf_token():
                logger.error("Failed to get CSRF token for login")
                return False

            url = f"{self.host}/api/auth/login"
            headers = {'Content-Type': 'application/json'}
            data = {'username': self.username, 'password': self.password}

            response = self.session.post(url, headers=headers, json=data, timeout=30)

            if response.status_code == 200:
                self.authenticated = True
                logger.info(f"✓ Login successful for user: {self.username}")

                if 'csrftoken' in response.cookies:
                    self.csrf_token = response.cookies['csrftoken']
                    self.session.headers.update({'X-CSRFToken': self.csrf_token})

                return True
            else:
                logger.error(f"Login failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Login exception: {e}")
            return False

    def _make_authenticated_request(self, method, url, **kwargs):
        if not self.authenticated:
            logger.error("Client is not authenticated")
            raise Exception("Client is not authenticated.")

        if 'timeout' not in kwargs:
            kwargs['timeout'] = 60

        if method.upper() not in ['GET', 'HEAD', 'OPTIONS']:
            if not self.get_csrf_token():
                logger.warning("Failed to refresh CSRF token")

        try:
            response = self.session.request(method, url, **kwargs)

            if response.status_code == 403 and "CSRF" in response.text:
                logger.warning("CSRF token expired, refreshing and retrying...")
                if self.get_csrf_token():
                    response = self.session.request(method, url, **kwargs)
                else:
                    logger.error("Failed to refresh CSRF token on 403 error")

            return response

        except Exception as e:
            logger.error(f"Request failed: {method} {url} - {e}")
            raise

    def create_project(self, name, labels):
        try:
            project_data = {'name': name, 'labels': labels}
            response = self._make_authenticated_request('POST', f"{self.host}/api/projects", json=project_data)

            if response.status_code == 201:
                project_id = response.json()['id']
                logger.info(f"✓ Project '{name}' created with ID: {project_id}")
                return project_id
            else:
                logger.error(f"Failed to create project: {response.status_code} - {response.text}")
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
            labels: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        created_tasks = []

        for annotator, clips in assignments.items():
            logger.info(f"Processing {len(clips)} clips for annotator: {annotator}")

            for i, clip_name in enumerate(clips):
                logger.info(f"Processing clip {i + 1}/{len(clips)}: {clip_name}")

                task_name = f"{annotator}_{clip_name.replace('.zip', '')}"
                zip_file_path = zip_dir / clip_name
                xml_file_path = xml_dir / f"{clip_name.replace('.zip', '')}_annotations.xml"

                if not zip_file_path.exists():
                    logger.error(f"✗ ZIP file not found: {zip_file_path}")
                    continue

                if not xml_file_path.exists():
                    logger.error(f"✗ XML file not found: {xml_file_path}")
                    continue

                task_id = self.create_task(task_name, project_id)
                if not task_id:
                    logger.error(f"✗ Failed to create task '{task_name}'")
                    continue

                logger.info(f"✓ Task '{task_name}' (ID: {task_id}) created")

                if not self.upload_data_to_task(task_id, str(zip_file_path)):
                    logger.error(f"✗ Failed to upload data for task {task_id}")
                    continue

                time.sleep(2)

                if not self.import_annotations(task_id, str(xml_file_path)):
                    logger.error(f"✗ Failed to import annotations for task {task_id}")
                    continue

                if self.assign_user_to_task(task_id, annotator):
                    logger.info(f"✓ Task {task_id} assigned to {annotator}")
                    created_tasks.append({
                        'task_id': task_id,
                        'annotator': annotator,
                        'clip': clip_name
                    })
                else:
                    logger.error(f"✗ Failed to assign task {task_id} to {annotator}")

        return created_tasks

    def create_task(self, name, project_id, labels=None):
        try:
            logger.info(f"Creating task '{name}' in project {project_id}...")

            task_data = {"name": name, "project_id": project_id}

            response = self._make_authenticated_request('POST', f"{self.host}/api/tasks", json=task_data)

            if response.status_code == 201:
                task_id = response.json()['id']
                logger.info(f"✓ Task '{name}' created with ID: {task_id}")
                return task_id
            else:
                logger.error(f"Failed to create task: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Exception creating task: {e}")
            return None

    def upload_data_to_task(self, task_id, zip_file_path):
        try:
            logger.info(f"Uploading '{os.path.basename(zip_file_path)}' to task {task_id}...")

            with open(zip_file_path, 'rb') as file_handle:
                files = {
                    'client_files[0]': (
                        os.path.basename(zip_file_path),
                        file_handle,
                        'application/zip'
                    )
                }
                data = {
                    'image_quality': '95',
                    'use_zip_chunks': 'true',
                    'use_cache': 'true'
                }

                response = self._make_authenticated_request(
                    'POST',
                    f"{self.host}/api/tasks/{task_id}/data",
                    files=files,
                    data=data,
                    timeout=300
                )

            if response.status_code == 202:
                logger.info("✓ Data upload initiated. Waiting for processing...")
                return self.wait_for_data_upload_completion(task_id)
            else:
                logger.error(f"Data upload failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Exception uploading data: {e}")
            return False

    def import_annotations(self, task_id, xml_file_path):
        try:
            if not os.path.exists(xml_file_path):
                logger.error(f"Annotation XML file not found: {xml_file_path}")
                return False

            logger.info(f"Importing annotations from '{os.path.basename(xml_file_path)}' to task {task_id}...")

            with open(xml_file_path, 'rb') as file_handle:
                files = {
                    'annotation_file': (
                        os.path.basename(xml_file_path),
                        file_handle,
                        'application/xml'
                    )
                }
                data = {
                    'format': 'CVAT for images 1.1',
                    'use_default_location': 'true'
                }

                response = self._make_authenticated_request(
                    'PUT',
                    f"{self.host}/api/tasks/{task_id}/annotations",
                    files=files,
                    data=data,
                    timeout=120
                )

            if response.status_code in [200, 202]:
                logger.info("✓ Annotation import initiated. Waiting for completion...")
                return self.wait_for_annotation_import_completion(task_id)
            else:
                logger.error(f"Annotation import failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Exception importing annotations: {e}")
            return False

    def assign_user_to_task(self, task_id, username):
        try:
            logger.info(f"Assigning user '{username}' to task {task_id}...")

            response = self._make_authenticated_request('GET', f"{self.host}/api/users?search={username}")

            if response.status_code != 200:
                logger.error(f"Failed to search for user: {response.status_code}")
                return False

            users = response.json().get('results', [])
            if not users:
                logger.error(f"User '{username}' not found")
                return False

            user_id = users[0]['id']

            response = self._make_authenticated_request('GET', f"{self.host}/api/jobs?task_id={task_id}")

            if response.status_code != 200:
                logger.error(f"Failed to get jobs for task: {response.status_code}")
                return False

            jobs = response.json().get('results', [])
            if not jobs:
                logger.error(f"No jobs found for task {task_id}")
                return False

            success = True
            for job in jobs:
                job_response = self._make_authenticated_request(
                    'PATCH',
                    f"{self.host}/api/jobs/{job['id']}",
                    json={'assignee': user_id}
                )

                if job_response.status_code == 200:
                    logger.info(f"✓ Assigned '{username}' to job {job['id']}")
                else:
                    logger.error(f"Failed to assign job {job['id']}: {job_response.status_code}")
                    success = False

            return success

        except Exception as e:
            logger.error(f"Exception assigning user: {e}")
            return False

    def wait_for_data_upload_completion(self, task_id, max_wait=600):
        try:
            start_time = time.time()
            logger.info(f"Waiting for data upload completion for task {task_id}...")

            while time.time() - start_time < max_wait:
                response = self._make_authenticated_request('GET', f"{self.host}/api/tasks/{task_id}/status")

                if response.status_code == 200:
                    status_data = response.json()
                    state = status_data.get('state', 'unknown')

                    logger.debug(f"Task {task_id} status: {state}")

                    if state in ['finished', 'completed']:
                        logger.info(f"✓ Data upload completed for task {task_id}")
                        return True
                    elif state == 'failed':
                        logger.error(f"✗ Data upload failed for task {task_id}")
                        return False
                    elif state in ['queued', 'started']:
                        time.sleep(5)
                        continue
                    else:
                        logger.warning(f"Unknown status for task {task_id}: {state}")
                        time.sleep(5)
                        continue
                else:
                    logger.error(f"Failed to get task status: {response.status_code}")
                    time.sleep(5)
                    continue

            logger.error(f"Timeout waiting for data upload completion for task {task_id}")
            return False

        except Exception as e:
            logger.error(f"Exception waiting for data upload: {e}")
            return False

    def wait_for_annotation_import_completion(self, task_id, max_wait=300):
        try:
            start_time = time.time()
            logger.info(f"Waiting for annotation import completion for task {task_id}...")

            initial_count = self.get_annotation_count(task_id)

            while time.time() - start_time < max_wait:
                current_count = self.get_annotation_count(task_id)

                if current_count > initial_count:
                    logger.info(f"✓ Annotations imported successfully for task {task_id} (count: {current_count})")
                    return True

                time.sleep(3)

            logger.error(f"Timeout waiting for annotation import for task {task_id}")
            return False

        except Exception as e:
            logger.error(f"Exception waiting for annotation import: {e}")
            return False

    def get_annotation_count(self, task_id):
        try:
            response = self._make_authenticated_request('GET', f"{self.host}/api/tasks/{task_id}/annotations")

            if response.status_code == 200:
                annotations = response.json()
                track_count = len(annotations.get('tracks', []))
                shape_count = len(annotations.get('shapes', []))
                return track_count + shape_count
            else:
                return 0

        except Exception as e:
            logger.error(f"Exception getting annotation count: {e}")
            return 0


def get_default_labels():
    return [
        {
            "name": "person",
            "color": "#ff0000",
            "tools": [{"name": "box", "type": "box"}],
            "attributes": [
                {"name": "walking_behavior", "mutable": True, "input_type": "select", "default_value": "normal_walk",
                 "values": ["normal_walk", "fast_walk", "slow_walk", "standing_still", "jogging", "window_shopping"]},
                {"name": "phone_usage", "mutable": True, "input_type": "select", "default_value": "no_phone",
                 "values": ["no_phone", "talking_phone", "texting", "taking_photo", "listening_music"]},
                {"name": "social_interaction", "mutable": True, "input_type": "select", "default_value": "alone",
                 "values": ["alone", "talking_companion", "group_walking", "greeting_someone", "asking_directions",
                            "avoiding_crowd"]},
                {"name": "carrying_items", "mutable": True, "input_type": "select", "default_value": "empty_hands",
                 "values": ["empty_hands", "shopping_bags", "backpack", "briefcase_bag", "umbrella", "food_drink",
                            "multiple_items"]},
                {"name": "street_behavior", "mutable": True, "input_type": "select",
                 "default_value": "sidewalk_walking",
                 "values": ["sidewalk_walking", "crossing_street", "waiting_signal", "looking_around", "checking_map",
                            "entering_building", "exiting_building"]},
                {"name": "posture_gesture", "mutable": True, "input_type": "select", "default_value": "upright_normal",
                 "values": ["upright_normal", "looking_down", "looking_up", "hands_in_pockets", "arms_crossed",
                            "pointing_gesture", "bowing_gesture"]},
                {"name": "clothing_style", "mutable": True, "input_type": "select", "default_value": "business_attire",
                 "values": ["business_attire", "casual_wear", "tourist_style", "school_uniform", "sports_wear",
                            "traditional_wear"]},
                {"name": "time_context", "mutable": True, "input_type": "select", "default_value": "rush_hour",
                 "values": ["rush_hour", "leisure_time", "shopping_time", "tourist_hours", "lunch_break",
                            "evening_stroll"]}
            ]
        }
    ]