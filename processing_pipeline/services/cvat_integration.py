import requests
import json
import os
import zipfile
import re
import logging
from typing import List, Dict, Any, Optional
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
        self.authenticated = False
        self.login()

    def login(self):
        try:
            url = f"{self.host}/api/auth/login"
            headers = {'Content-Type': 'application/json'}
            data = {'username': self.username, 'password': self.password}

            response = self.session.post(url, headers=headers, json=data)

            if response.status_code == 200:
                self.authenticated = True
                logger.info(f"✓ Login successful for user: {self.username}")
                return True
            else:
                logger.error(f"Login failed: {response.status_code} - {response.text}")
                return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def _make_authenticated_request(self, method, url, **kwargs):
        if not self.authenticated:
            raise Exception("Client is not authenticated.")

        response = self.session.request(method, url, **kwargs)
        if response.status_code == 401:
            logger.warning("Session expired, re-authenticating...")
            if self.login():
                response = self.session.request(method, url, **kwargs)
            else:
                raise Exception("Re-authentication failed.")
        return response

    def create_project(self, name, labels):
        try:
            project_data = {'name': name, 'labels': labels}
            response = self._make_authenticated_request('POST', f"{self.host}/api/projects", json=project_data)

            if response.status_code == 201:
                return response.json()['id']
            else:
                logger.error(f"Failed to create project: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Create project error: {e}")
            return None

    def create_tasks_from_assignments(
            self,
            project_id: int,
            assignments: Dict[str, List[str]],
            zip_dir: Path,
            labels: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Creates and uploads a task for each annotator based on an assignment plan.
        """
        created_tasks = []
        for annotator, clips in assignments.items():
            if not clips:
                continue

            task_name = f"{annotator}_task_{project_id}"
            zip_files = [str(zip_dir / clip) for clip in clips]

            task_id = self.create_task_with_data(task_name, project_id, zip_files, labels)

            if task_id:
                logger.info(f"Assigning user '{annotator}' to task '{task_id}'...")
                self.assign_user_to_task(task_id, annotator)
                created_tasks.append({'task_id': task_id, 'annotator': annotator, 'clips': clips})

        return created_tasks

    def create_task_with_data(self, name, project_id, zip_files, labels):
        """
        Creates a task and uploads data in a single request.
        """
        try:
            logger.info(f"Creating task '{name}' and uploading {len(zip_files)} zip file(s)...")

            task_spec = {"name": name, "project_id": project_id, "labels": labels}

            files = {'json_data': (None, json.dumps(task_spec), 'application/json')}
            file_handles = []

            for i, zip_path in enumerate(zip_files):
                file_handle = open(zip_path, 'rb')
                file_handles.append(file_handle)
                files[f'client_files[{i}]'] = (os.path.basename(zip_path), file_handle, 'application/zip')

            response = self._make_authenticated_request('POST', f"{self.host}/api/tasks", files=files)

            for file_handle in file_handles:
                file_handle.close()

            if response.status_code == 201:
                task_id = response.json()['id']
                logger.info(f"✓ Task '{name}' (ID: {task_id}) created. Waiting for data processing...")
                if self.wait_for_task_completion(task_id):
                    return task_id
            else:
                logger.error(f"Failed to create task: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Create task with data error: {e}")
            return None

    def assign_user_to_task(self, task_id, username):
        try:
            # First, get the user's ID
            response = self._make_authenticated_request('GET', f"{self.host}/api/users?search={username}")
            if response.status_code != 200 or not response.json()['results']:
                logger.error(f"User not found: {username}")
                return False
            user_id = response.json()['results'][0]['id']

            # Then, assign the user to all jobs in the task
            response = self._make_authenticated_request('GET', f"{self.host}/api/jobs?task_id={task_id}")
            if response.status_code == 200:
                jobs = response.json().get('results', [])
                for job in jobs:
                    job_id = job['id']
                    job_response = self._make_authenticated_request(
                        'PATCH', f"{self.host}/api/jobs/{job_id}", json={'assignee': user_id}
                    )
                    if job_response.status_code == 200:
                        logger.info(f"✓ Assigned '{username}' to job '{job_id}'")
                    else:
                        logger.warning(f"Failed to assign user to job {job_id}: {job_response.text}")
                return True
            return False
        except Exception as e:
            logger.error(f"Assign user error: {e}")
            return False

    def wait_for_task_completion(self, task_id, max_wait=300):
        try:
            start_time = time.time()
            while time.time() - start_time < max_wait:
                response = self._make_authenticated_request('GET', f"{self.host}/api/tasks/{task_id}/status")
                if response.status_code == 200:
                    status = response.json().get('state', 'unknown')
                    if status in ['finished', 'completed', 'available']:
                        logger.info(f"✓ Task {task_id} data processing completed successfully.")
                        return True
                    elif status == 'failed':
                        logger.error(f"✗ Task {task_id} data processing failed.")
                        return False
                    time.sleep(5)
                else:
                    break
            logger.error(f"Timeout waiting for task {task_id}")
            return False
        except Exception as e:
            logger.error(f"Wait for completion error: {e}")
            return False


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