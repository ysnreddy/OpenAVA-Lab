# services/dataset_generator.py
import psycopg2
import pandas as pd
import logging
from typing import Dict, Any, List
import json
import os
import cv2  # Requires opencv-python
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# This dictionary is the single source of truth for all actions.
ATTRIBUTE_DEFINITIONS = {
    'walking_behavior': {'options': ['unknown', 'normal_walk', 'fast_walk', 'slow_walk', 'standing_still', 'jogging',
                                     'window_shopping']},
    'phone_usage': {'options': ['unknown', 'no_phone', 'talking_phone', 'texting', 'taking_photo', 'listening_music']},
    'social_interaction': {
        'options': ['unknown', 'alone', 'talking_companion', 'group_walking', 'greeting_someone', 'asking_directions',
                    'avoiding_crowd']},
    'carrying_items': {
        'options': ['unknown', 'empty_hands', 'shopping_bags', 'backpack', 'briefcase_bag', 'umbrella', 'food_drink',
                    'multiple_items']},
    'street_behavior': {
        'options': ['unknown', 'sidewalk_walking', 'crossing_street', 'waiting_signal', 'looking_around',
                    'checking_map', 'entering_building', 'exiting_building']},
    'posture_gesture': {
        'options': ['unknown', 'upright_normal', 'looking_down', 'looking_up', 'hands_in_pockets', 'arms_crossed',
                    'pointing_gesture', 'bowing_gesture']},
    'clothing_style': {
        'options': ['unknown', 'business_attire', 'casual_wear', 'tourist_style', 'school_uniform', 'sports_wear',
                    'traditional_wear']},
    'time_context': {
        'options': ['unknown', 'rush_hour', 'leisure_time', 'shopping_time', 'tourist_hours', 'lunch_break',
                    'evening_stroll']}
}


def calculate_action_mapping():
    """Calculates the cumulative base value for each action category (AVA standard)."""
    attribute_nums = {}
    cumulative_count = 0
    for attr_name in sorted(ATTRIBUTE_DEFINITIONS.keys()):
        attr_info = ATTRIBUTE_DEFINITIONS[attr_name]
        attribute_nums[attr_name] = cumulative_count
        cumulative_count += len(attr_info['options'])
    return attribute_nums


class DatasetGenerator:
    def __init__(self, db_params: Dict[str, Any], frame_dir: str):
        self.db_params = db_params
        self.frame_dir = frame_dir
        self.conn = None
        self.action_id_map = calculate_action_mapping()
        self.image_dims_cache = {}

    def connect_db(self):
        try:
            self.conn = psycopg2.connect(**self.db_params)
        except psycopg2.OperationalError as e:
            logger.error(f"Could not connect to database: {e}")
            self.conn = None

    def close_db(self):
        if self.conn: self.conn.close()

    def _get_image_dimensions(self, task_name):
        if task_name in self.image_dims_cache:
            return self.image_dims_cache[task_name]

        actual_clip_name = '_'.join(task_name.split('_')[1:])
        clip_path = os.path.join(self.frame_dir, actual_clip_name)

        if not os.path.isdir(clip_path):
            self.image_dims_cache[task_name] = (1280, 720)
            return 1280, 720

        try:
            first_frame = sorted([f for f in os.listdir(clip_path) if f.endswith('.jpg')])[0]
            img = cv2.imread(os.path.join(clip_path, first_frame))
            height, width, _ = img.shape
            self.image_dims_cache[task_name] = (width, height)
            return width, height
        except Exception:
            self.image_dims_cache[task_name] = (1280, 720)
            return 1280, 720

    def fetch_approved_annotations(self) -> pd.DataFrame:
        if not self.conn: raise ConnectionError("Database not connected.")
        query = "SELECT t.name as task_name, a.track_id, a.frame, a.xtl, a.ytl, a.xbr, a.ybr, a.attributes FROM annotations a JOIN tasks t ON a.task_id = t.task_id WHERE t.qc_status = 'approved';"
        return pd.read_sql(query, self.conn)

    def _apply_consensus(self, group: pd.DataFrame) -> pd.DataFrame:
        return group.drop_duplicates(subset=['track_id', 'frame'], keep='first')

    def generate_ava_csv(self, output_path: str):
        self.connect_db()
        if not self.conn: return

        try:
            df = self.fetch_approved_annotations()
            if df.empty:
                logger.warning("No approved annotations found. No CSV will be generated.")
                return

            df['clip_id'] = df['task_name'].apply(lambda x: '_'.join(x.split('_')[1:]))
            final_df = df.groupby('clip_id').apply(self._apply_consensus).reset_index(drop=True)

            ava_rows = []
            for _, row in tqdm(final_df.iterrows(), total=final_df.shape[0], desc="Formatting AVA CSV"):
                img_W, img_H = self._get_image_dimensions(row['task_name'])

                x1_norm, y1_norm = row['xtl'] / img_W, row['ytl'] / img_H
                x2_norm, y2_norm = row['xbr'] / img_W, row['ybr'] / img_H

                attributes = row['attributes']

                # ✨ FIX: Only create rows for actions that have been explicitly annotated
                # and are not "negative" or "unknown" defaults.
                negative_defaults = ["unknown", "no_phone", "alone", "empty_hands"]

                for attr_name, attr_value in attributes.items():
                    if not attr_value or attr_value in negative_defaults:
                        continue

                    base_id = self.action_id_map.get(attr_name)
                    if base_id is None: continue

                    options_list = ATTRIBUTE_DEFINITIONS[attr_name]['options']
                    try:
                        option_index = options_list.index(attr_value)
                        final_action_id = base_id + option_index + 1

                        ava_rows.append([
                            row['clip_id'], row['frame'], f"{x1_norm:.6f}", f"{y1_norm:.6f}",
                            f"{x2_norm:.6f}", f"{y2_norm:.6f}", final_action_id, row['track_id']
                        ])
                    except ValueError:
                        logger.warning(f"Value '{attr_value}' for '{attr_name}' not in definitions. Skipping.")

            header = ['video_id', 'frame_timestamp', 'x1', 'y1', 'x2', 'y2', 'action_id', 'person_id']
            ava_df = pd.DataFrame(ava_rows, columns=header)
            ava_df = ava_df.sort_values(by=['video_id', 'frame_timestamp', 'person_id'])
            ava_df.to_csv(output_path, index=False)

            logger.info(f"✓ Successfully generated AVA dataset with {len(ava_df)} rows at: {output_path}")

        finally:
            self.close_db()