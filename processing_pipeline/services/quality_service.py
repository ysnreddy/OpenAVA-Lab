import json

import psycopg2
import logging
from typing import List, Dict, Any, Tuple
from collections import defaultdict
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class QualityService:
    def __init__(self, db_params: Dict[str, Any]):
        """
        Initializes the service with database connection parameters.

        Args:
            db_params (Dict): Dictionary with keys like 'dbname', 'user', 'password', 'host', 'port'.
        """
        self.db_params = db_params
        self.conn = None

    def connect_db(self):
        """Establishes a connection to the PostgreSQL database."""
        try:
            self.conn = psycopg2.connect(**self.db_params)
            logger.info("✓ QualityService connected to PostgreSQL.")
        except psycopg2.OperationalError as e:
            logger.error(f"✗ QualityService could not connect to database: {e}")
            self.conn = None

    def close_db(self):
        """Closes the database connection."""
        if self.conn:
            self.conn.close()

    def _fetch_annotations_for_tasks(self, task_ids: List[int]) -> Dict[int, Dict[Tuple[int, int], Dict]]:
        """
        Fetches annotations for a list of tasks and organizes them for comparison.

        Returns:
            A dictionary mapping task_id to its annotations, where each annotation is
            keyed by (track_id, frame).
        """
        if not self.conn:
            raise ConnectionError("Database is not connected.")

        annotations_by_task = defaultdict(dict)
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT task_id, track_id, frame, xtl, ytl, xbr, ybr, attributes FROM annotations WHERE task_id = ANY(%s)",
                (task_ids,)
            )
            for row in cur.fetchall():
                task_id, track_id, frame, xtl, ytl, xbr, ybr, attributes = row
                key = (track_id, frame)
                annotations_by_task[task_id][key] = {
                    "box": [xtl, ytl, xbr, ybr],
                    "attributes": attributes
                }
        return annotations_by_task

    def _calculate_iou(self, boxA: List[float], boxB: List[float]) -> float:
        """Calculate Intersection over Union for two bounding boxes."""
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])

        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])

        iou = interArea / float(boxAArea + boxBArea - interArea)
        return iou

    def _calculate_cohens_kappa(self, annotations1: Dict, annotations2: Dict, attribute_name: str,
                                categories: List[str]):
        """Calculates Cohen's Kappa for a specific attribute."""

        # Create a confusion matrix
        num_categories = len(categories)
        cat_map = {cat: i for i, cat in enumerate(categories)}
        confusion_matrix = np.zeros((num_categories, num_categories))

        common_keys = set(annotations1.keys()) & set(annotations2.keys())
        if not common_keys:
            return 0.0  # No common items to compare

        for key in common_keys:
            val1 = annotations1[key]['attributes'].get(attribute_name)
            val2 = annotations2[key]['attributes'].get(attribute_name)
            if val1 in cat_map and val2 in cat_map:
                idx1 = cat_map[val1]
                idx2 = cat_map[val2]
                confusion_matrix[idx1, idx2] += 1

        total_observations = np.sum(confusion_matrix)
        if total_observations == 0:
            return 1.0  # Perfect agreement if no observations

        p_observed = np.trace(confusion_matrix) / total_observations

        row_totals = np.sum(confusion_matrix, axis=1)
        col_totals = np.sum(confusion_matrix, axis=0)
        p_expected = np.sum((row_totals * col_totals)) / (total_observations ** 2)

        if p_expected == 1:
            return 1.0

        kappa = (p_observed - p_expected) / (1 - p_expected)
        return kappa

    def run_quality_check(self, task_id1: int, task_id2: int) -> Dict[str, Any]:
        """
        Runs the full quality check between two completed tasks.
        """
        self.connect_db()
        if not self.conn:
            return {"error": "Could not connect to the database."}

        try:
            annotations = self._fetch_annotations_for_tasks([task_id1, task_id2])
            annotations1 = annotations.get(task_id1, {})
            annotations2 = annotations.get(task_id2, {})

            if not annotations1 or not annotations2:
                return {"error": "One or both tasks have no annotations in the database."}

            # --- IoU Calculation ---
            iou_scores = []
            common_keys = set(annotations1.keys()) & set(annotations2.keys())
            for key in common_keys:
                iou = self._calculate_iou(annotations1[key]['box'], annotations2[key]['box'])
                iou_scores.append(iou)

            avg_iou = np.mean(iou_scores) if iou_scores else 0.0

            # --- Kappa Calculation for each attribute ---
            # This should be dynamically fetched or configured, but we'll hardcode for this example
            attribute_categories = {
                'walking_behavior': ['unknown', 'normal_walk', 'fast_walk', 'slow_walk', 'standing_still', 'jogging',
                                     'window_shopping'],
                'phone_usage': ['unknown', 'no_phone', 'talking_phone', 'texting', 'taking_photo', 'listening_music'],
                # Add all other attributes and their categories here
            }

            kappa_scores = {}
            for attr, categories in attribute_categories.items():
                kappa = self._calculate_cohens_kappa(annotations1, annotations2, attr, categories)
                kappa_scores[attr] = kappa

            return {
                "average_iou": avg_iou,
                "kappa_scores": kappa_scores,
                "compared_annotations": len(common_keys)
            }

        finally:
            self.close_db()


if __name__ == '__main__':
    # --- Example Usage ---
    DB_PARAMS = {
        "dbname": "cvat_annotations",
        "user": "postgres",
        "password": "your_db_password",
        "host": "localhost",
        "port": "5432"
    }

    # The IDs of two tasks that correspond to the same clip (overlap tasks)
    TASK_ID_1 = 32  # Example task ID from annotator 1
    TASK_ID_2 = 33  # Example task ID from annotator 2 for the same clip

    qc_service = QualityService(db_params=DB_PARAMS)
    results = qc_service.run_quality_check(TASK_ID_1, TASK_ID_2)

    print("--- Quality Check Results ---")
    print(json.dumps(results, indent=2))
