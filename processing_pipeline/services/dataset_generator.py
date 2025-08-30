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

# --- This section is adapted directly from your via_to_ava_csv.py script ---
ATTRIBUTE_DEFINITIONS = {
    '1': {'aname': 'walking_behavior',
          'options': {'0': 'normal_walk', '1': 'fast_walk', '2': 'slow_walk', '3': 'standing_still', '4': 'jogging',
                      '5': 'window_shopping'}},
    '2': {'aname': 'phone_usage',
          'options': {'0': 'no_phone', '1': 'talking_phone', '2': 'texting', '3': 'taking_photo',
                      '4': 'listening_music'}},
    '3': {'aname': 'social_interaction',
          'options': {'0': 'alone', '1': 'talking_companion', '2': 'group_walking', '3': 'greeting_someone',
                      '4': 'asking_directions', '5': 'avoiding_crowd'}},
    '4': {'aname': 'carrying_items',
          'options': {'0': 'empty_hands', '1': 'shopping_bags', '2': 'backpack', '3': 'briefcase_bag', '4': 'umbrella',
                      '5': 'food_drink', '6': 'multiple_items'}},
    '5': {'aname': 'street_behavior',
          'options': {'0': 'sidewalk_walking', '1': 'crossing_street', '2': 'waiting_signal', '3': 'looking_around',
                      '4': 'checking_map', '5': 'entering_building', '6': 'exiting_building'}},
    '6': {'aname': 'posture_gesture',
          'options': {'0': 'upright_normal', '1': 'looking_down', '2': 'looking_up', '3': 'hands_in_pockets',
                      '4': 'arms_crossed', '5': 'pointing_gesture', '6': 'bowing_gesture'}},
    '7': {'aname': 'clothing_style',
          'options': {'0': 'business_attire', '1': 'casual_wear', '2': 'tourist_style', '3': 'school_uniform',
                      '4': 'sports_wear', '5': 'traditional_wear'}},
    '8': {'aname': 'time_context',
          'options': {'0': 'rush_hour', '1': 'leisure_time', '2': 'shopping_time', '3': 'tourist_hours',
                      '4': 'lunch_break', '5': 'evening_stroll'}}
}


def calculate_action_mapping():
    """Calculates the cumulative base value for each action category."""
    attribute_nums = {}
    cumulative_count = 0
    # Sort by the dictionary key (1 through 8)
    for attr_id in sorted(ATTRIBUTE_DEFINITIONS.keys(), key=int):
        attr_info = ATTRIBUTE_DEFINITIONS[attr_id]
        attribute_nums[attr_info['aname']] = cumulative_count
        cumulative_count += len(attr_info['options'])
    logger.info(f"Action ID mapping calculated. Total unique actions: {cumulative_count}")
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
        except psycopg2.OperationalError:
            self.conn = None

    def close_db(self):
        if self.conn:
            self.conn.close()

    def _get_image_dimensions(self, clip_name):
        """Gets and caches image dimensions for a clip."""
        if clip_name in self.image_dims_cache:
            return self.image_dims_cache[clip_name]

        clip_path = os.path.join(self.frame_dir, clip_name)
        if not os.path.isdir(clip_path):
            logger.warning(f"Frame directory not found for {clip_name}. Using default 1280x720.")
            return 1280, 720

        try:
            first_frame = sorted(os.listdir(clip_path))[0]
            img = cv2.imread(os.path.join(clip_path, first_frame))
            height, width, _ = img.shape
            self.image_dims_cache[clip_name] = (width, height)
            return width, height
        except Exception:
            logger.warning(f"Could not read frames for {clip_name}. Using default 1280x720.")
            return 1280, 720

    def fetch_approved_annotations(self) -> pd.DataFrame:
        if not self.conn: raise ConnectionError("Database not connected.")
        query = """
                SELECT t.name as task_name, \
                       a.track_id, \
                       a.frame, \
                       a.xtl, \
                       a.ytl, \
                       a.xbr, \
                       a.ybr, \
                       a.attributes
                FROM annotations a \
                         JOIN tasks t ON a.task_id = t.task_id
                WHERE t.qc_status = 'approved'; \
                """
        return pd.read_sql(query, self.conn)

    def _apply_consensus(self, group: pd.DataFrame) -> pd.DataFrame:
        # For simplicity, we assume the first annotator's work is the ground truth in overlaps.
        # A more complex system could average boxes or use a third adjudicator.
        return group.drop_duplicates(subset=['track_id', 'frame'], keep='first')

    def generate_ava_csv(self, output_path: str):
        self.connect_db()
        if not self.conn:
            logger.error("Could not connect to database for dataset generation.")
            return

        try:
            df = self.fetch_approved_annotations()
            if df.empty:
                logger.warning("No approved annotations found. No CSV generated.")
                return

            df['clip_id'] = df['task_name'].apply(lambda x: '_'.join(x.split('_')[1:]))

            # Apply consensus logic to each clip group
            final_df = df.groupby('clip_id').apply(self._apply_consensus).reset_index(drop=True)

            ava_rows = []
            for _, row in tqdm(final_df.iterrows(), total=final_df.shape[0], desc="Formatting AVA CSV"):
                img_W, img_H = self._get_image_dimensions(row['clip_id'])

                # Normalize coordinates
                x1_norm = row['xtl'] / img_W
                y1_norm = row['ytl'] / img_H
                x2_norm = row['xbr'] / img_W
                y2_norm = row['ybr'] / img_H

                # ✨ FIX: Calculate the final cumulative action_id
                attributes = row['attributes']
                for attr_name, attr_value in attributes.items():
                    base_id = self.action_id_map.get(attr_name, 0)

                    # Find the index of the option to get the offset
                    attr_key = next((k for k, v in ATTRIBUTE_DEFINITIONS.items() if v['aname'] == attr_name), None)
                    if attr_key:
                        option_id = next(
                            (k for k, v in ATTRIBUTE_DEFINITIONS[attr_key]['options'].items() if v == attr_value), None)
                        if option_id:
                            final_action_id = base_id + int(option_id) + 1
                            ava_rows.append([
                                row['clip_id'], row['frame'], f"{x1_norm:.6f}", f"{y1_norm:.6f}",
                                f"{x2_norm:.6f}", f"{y2_norm:.6f}", final_action_id, row['track_id']
                            ])

            # Create the final DataFrame and save
            header = ['video_id', 'frame_timestamp', 'x1', 'y1', 'x2', 'y2', 'action_id', 'person_id']
            ava_df = pd.DataFrame(ava_rows, columns=header)
            ava_df = ava_df.sort_values(by=['video_id', 'frame_timestamp', 'person_id'])
            ava_df.to_csv(output_path, index=False)

            logger.info(f"✓ Successfully generated AVA dataset with {len(ava_df)} rows at: {output_path}")

        finally:
            self.close_db()