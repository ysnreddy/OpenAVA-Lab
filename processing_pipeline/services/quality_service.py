import json
import psycopg2
import logging
from typing import List, Dict, Any, Tuple
from collections import defaultdict
import numpy as np
import os
import sys

# Ensure the parent directory is in the path to find the shared_config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from processing_pipeline.services.shared_config import ATTRIBUTE_DEFINITIONS

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
            self.conn = None

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
                # ✅ Parse JSON attributes
                try:
                    attr_dict = json.loads(attributes) if attributes else {}
                except Exception:
                    attr_dict = {}
                annotations_by_task[task_id][key] = {
                    "box": [xtl, ytl, xbr, ybr],
                    "attributes": attr_dict
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
        return interArea / float(boxAArea + boxBArea - interArea) if (boxAArea + boxBArea - interArea) > 0 else 0.0

    def _calculate_cohens_kappa(self, annotations1: Dict, annotations2: Dict, attr_name: str, categories: List[str]):
        num_categories = len(categories)
        cat_map = {cat: i for i, cat in enumerate(categories)}
        matrix = np.zeros((num_categories, num_categories))
        common_keys = set(annotations1.keys()) & set(annotations2.keys())
        if not common_keys: return 0.0

        for key in common_keys:
            val1 = annotations1[key]['attributes'].get(attr_name)
            val2 = annotations2[key]['attributes'].get(attr_name)
            if val1 in cat_map and val2 in cat_map:
                matrix[cat_map[val1], cat_map[val2]] += 1

        total = np.sum(matrix)
        if total == 0: return 1.0
        p_observed = np.trace(matrix) / total
        p_expected = np.sum(np.sum(matrix, axis=1) * np.sum(matrix, axis=0)) / (total ** 2)
        if p_expected == 1: return 1.0
        return (p_observed - p_expected) / (1 - p_expected)

    def _calculate_flip_rate(self, annotations: Dict) -> Dict[str, float]:
        tracks = defaultdict(list)
        for (track_id, frame), data in annotations.items():
            tracks[track_id].append({'frame': frame, 'attributes': data['attributes']})

        avg_flip_rates = {}
        for attr_name in ATTRIBUTE_DEFINITIONS.keys():
            total_flips = 0
            total_opportunities = 0
            for track_id, frames in tracks.items():
                if len(frames) < 2:
                    continue
                sorted_frames = sorted(frames, key=lambda x: x['frame'])
                num_flips = 0
                for i in range(1, len(sorted_frames)):
                    prev_val = sorted_frames[i - 1]['attributes'].get(attr_name)
                    curr_val = sorted_frames[i]['attributes'].get(attr_name)
                    if prev_val != curr_val:
                        num_flips += 1
                total_flips += num_flips
                total_opportunities += len(sorted_frames) - 1
            avg_flip_rates[attr_name] = total_flips / total_opportunities if total_opportunities > 0 else 0.0
        return avg_flip_rates

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

            # --- IoU Calculation ---
            iou_scores = []
            common_keys = set(annotations1.keys()) & set(annotations2.keys())
            for key in common_keys:
                iou_scores.append(self._calculate_iou(annotations1[key]['box'], annotations2[key]['box']))

            avg_iou = np.mean(iou_scores) if iou_scores else 0.0
            percent_iou_gte_05 = np.mean([1 if s >= 0.5 else 0 for s in iou_scores]) if iou_scores else 0.0

            # --- Kappa Calculation ---
            kappa_scores = {}
            for attr_name, attr_info in ATTRIBUTE_DEFINITIONS.items():
                kappa_scores[attr_name] = self._calculate_cohens_kappa(annotations1, annotations2, attr_name, attr_info['options'])
            macro_avg_kappa = np.mean(list(kappa_scores.values())) if kappa_scores else 0.0

            # --- Flip Rate Calculation ---
            flip_rate1 = self._calculate_flip_rate(annotations1)
            flip_rate2 = self._calculate_flip_rate(annotations2)

            return {
                "average_iou": avg_iou,
                "percent_iou_gte_05": percent_iou_gte_05,
                "kappa_scores": kappa_scores,
                "macro_avg_kappa": macro_avg_kappa,
                "flip_rates": {"annotator_1": flip_rate1, "annotator_2": flip_rate2},
                "compared_annotations": len(common_keys)
            }
        finally:
            self.close_db()
