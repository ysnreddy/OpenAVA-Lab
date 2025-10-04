import psycopg2
import pandas as pd
import logging
from typing import Dict, Any
import json
import os
import cv2
from tqdm import tqdm
from pathlib import Path  

# 🔹 Import shared config with alias
from services.shared_config import ATTRIBUTE_DEFINITIONS as aname  

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def calculate_action_mapping():
    """Assigns cumulative base ID for each attribute group."""
    attribute_nums = {}
    cumulative_count = 0
    for attr_name in sorted(aname.keys()):
        attr_info = aname[attr_name]
        attribute_nums[attr_name] = cumulative_count
        cumulative_count += len(attr_info["options"])
    return attribute_nums


class DatasetGenerator:
    def __init__(self, db_params: Dict[str, Any], frame_dir: str):
        self.db_params = db_params
        self.frame_dir = frame_dir
        self.conn = None
        self.action_id_map = calculate_action_mapping()
        self.image_dims_cache = {}

    def _ensure_connection(self):
        """Ensure there is an active DB connection."""
        if self.conn is None or self.conn.closed:
            try:
                self.conn = psycopg2.connect(**self.db_params)
                logger.info("✅ Database connection established")
            except psycopg2.OperationalError as e:
                logger.error(f"❌ Could not connect to database: {e}")
                raise

    def close_db(self):
        if self.conn:
            self.conn.close()
            self.conn = None
            logger.info("🔒 Database connection closed")

    def _get_image_dimensions(self, task_name):
        if task_name in self.image_dims_cache:
            return self.image_dims_cache[task_name]

        actual_clip_name = "_".join(task_name.split("_")[1:])
        clip_path = os.path.join(self.frame_dir, actual_clip_name)

        if not os.path.isdir(clip_path):
            logger.warning(f"⚠️ Frame directory not found for {task_name}, using default (1280x720)")
            self.image_dims_cache[task_name] = (1280, 720)
            return 1280, 720

        try:
            first_frame = sorted([f for f in os.listdir(clip_path) if f.endswith('.jpg')])[0]
            img = cv2.imread(os.path.join(clip_path, first_frame))
            height, width, _ = img.shape
            self.image_dims_cache[task_name] = (width, height)
            return width, height
        except Exception as e:
            logger.warning(f"⚠️ Could not read frame for {task_name}: {e}, defaulting to 1280x720")
            self.image_dims_cache[task_name] = (1280, 720)
            return 1280, 720

    def fetch_approved_annotations(self, project_id: int = -1) -> pd.DataFrame:
        """Fetch only approved annotations, optionally filtering by project_id."""
        self._ensure_connection()

        query = """
            SELECT t.project_id, t.name as task_name, a.track_id, a.frame,
                   a.xtl, a.ytl, a.xbr, a.ybr, a.attributes
            FROM annotations a
            JOIN tasks t ON a.task_id = t.task_id
            WHERE t.qc_status = 'approved'
        """
        params = ()
        if project_id != -1:
            query += " AND t.project_id = %s"
            params = (project_id,)

        df = pd.read_sql(query, self.conn, params=params)
        logger.info(f"📥 Retrieved {len(df)} approved annotations from DB for project {project_id}")
        return df

    def _parse_attributes(self, raw_attrs):
        if isinstance(raw_attrs, dict):
            return raw_attrs
        if isinstance(raw_attrs, str):
            try:
                return json.loads(raw_attrs)
            except Exception:
                try:
                    return json.loads(raw_attrs.replace("'", '"'))
                except Exception:
                    logger.warning(f"⚠️ Could not parse attributes string: {raw_attrs}")
                    return {}
        return {}

    def generate_ava_csv(self, output_csv_path: str, project_id: int):
        """Generate AVA-style CSV file from approved annotations."""
        df = self.fetch_approved_annotations(project_id=project_id)
        if df.empty:
            logger.warning(f"No approved annotations found for project {project_id}")
            return

        rows = []
        for _, row in df.iterrows():
            video_id = Path(row["task_name"]).stem
            timestamp = row["frame"]

            img_w, img_h = self._get_image_dimensions(row["task_name"])

            x1 = row["xtl"] / img_w
            y1 = row["ytl"] / img_h
            x2 = row["xbr"] / img_w
            y2 = row["ybr"] / img_h

            parsed_attrs = self._parse_attributes(row["attributes"])
            actions = []
            for attr_name, value in parsed_attrs.items():
                base_id = self.action_id_map.get(attr_name, 0)
                try:
                    idx = aname[attr_name]["options"].index(value)
                    actions.append(base_id + idx)
                except ValueError:
                    pass

            if actions:
                for action_id in actions:
                    rows.append([video_id, timestamp, x1, y1, x2, y2, action_id, row["track_id"]])
            else:
                rows.append([video_id, timestamp, x1, y1, x2, y2, -1, row["track_id"]])

        columns = ["video_id", "frame_timestamp", "x1", "y1", "x2", "y2", "action_id", "person_id"]
        pd.DataFrame(rows, columns=columns).to_csv(output_csv_path, index=False)
        logger.info(f"✅ AVA CSV saved for project {project_id} → {output_csv_path}")
