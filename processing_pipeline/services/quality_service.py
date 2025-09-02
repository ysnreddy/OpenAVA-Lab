import json
import psycopg2
import logging
from typing import List, Dict, Any, Tuple
from collections import defaultdict
import numpy as np

# ✨ FIX: Import the shared attribute definitions
from services.shared_config import ATTRIBUTE_DEFINITIONS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class QualityService:
    def __init__(self, db_params: Dict[str, Any]):
        self.db_params = db_params
        self.conn = None

    def connect_db(self):
        try:
            self.conn = psycopg2.connect(**self.db_params)
            logger.info("✓ QualityService connected to PostgreSQL.")
        except psycopg2.OperationalError as e:
            logger.error(f"✗ QualityService could not connect to database: {e}")
            self.conn = None

    def close_db(self):
        if self.conn:
            self.conn.close()

    def _fetch_annotations_for_tasks(self, task_ids: List[int]) -> Dict[int, Dict[Tuple[int, int], Dict]]:
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
        xA = max(boxA[0], boxB[0])
        yA = max(boxA[1], boxB[1])
        xB = min(boxA[2], boxB[2])
        yB = min(boxA[3], boxB[3])
        interArea = max(0, xB - xA) * max(0, yB - yA)
        boxAArea = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        boxBArea = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        iou = interArea / float(boxAArea + boxBArea - interArea) if (boxAArea + boxBArea - interArea) > 0 else 0.0
        return iou

    def _calculate_cohens_kappa(self, annotations1: Dict, annotations2: Dict, attribute_name: str,
                                categories: List[str]):
        num_categories = len(categories)
        cat_map = {cat: i for i, cat in enumerate(categories)}
        confusion_matrix = np.zeros((num_categories, num_categories))
        common_keys = set(annotations1.keys()) & set(annotations2.keys())
        if not common_keys: return 0.0

        for key in common_keys:
            val1 = annotations1[key]['attributes'].get(attribute_name)
            val2 = annotations2[key]['attributes'].get(attribute_name)
            if val1 in cat_map and val2 in cat_map:
                idx1 = cat_map[val1]
                idx2 = cat_map[val2]
                confusion_matrix[idx1, idx2] += 1

        total_observations = np.sum(confusion_matrix)
        if total_observations == 0: return 1.0

        p_observed = np.trace(confusion_matrix) / total_observations
        row_totals = np.sum(confusion_matrix, axis=1)
        col_totals = np.sum(confusion_matrix, axis=0)
        p_expected = np.sum((row_totals * col_totals)) / (total_observations ** 2)
        if p_expected == 1: return 1.0
        kappa = (p_observed - p_expected) / (1 - p_expected)
        return kappa

    def run_quality_check(self, task_id1: int, task_id2: int) -> Dict[str, Any]:
        self.connect_db()
        if not self.conn:
            return {"error": "Could not connect to the database."}

        try:
            annotations = self._fetch_annotations_for_tasks([task_id1, task_id2])
            annotations1 = annotations.get(task_id1, {})
            annotations2 = annotations.get(task_id2, {})

            if not annotations1 or not annotations2:
                return {"error": "One or both tasks have no annotations in the database."}

            iou_scores = []
            common_keys = set(annotations1.keys()) & set(annotations2.keys())
            for key in common_keys:
                iou = self._calculate_iou(annotations1[key]['box'], annotations2[key]['box'])
                iou_scores.append(iou)

            avg_iou = np.mean(iou_scores) if iou_scores else 0.0

            # ✨ FIX: Dynamically build the categories from the shared config file
            kappa_scores = {}
            for attr_name, attr_info in ATTRIBUTE_DEFINITIONS.items():
                categories = attr_info['options']
                kappa = self._calculate_cohens_kappa(annotations1, annotations2, attr_name, categories)
                kappa_scores[attr_name] = kappa

            return {
                "average_iou": avg_iou,
                "kappa_scores": kappa_scores,
                "compared_annotations": len(common_keys)
            }
        finally:
            self.close_db()