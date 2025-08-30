# services/dataset_generator.py
import psycopg2
import pandas as pd
import logging
from typing import Dict, Any, List
from collections import defaultdict
import json
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Assume quality_service is in the same services directory for the IoU function
from services.quality_service import QualityService


class DatasetGenerator:
    def __init__(self, db_params: Dict[str, Any]):
        self.db_params = db_params
        self.conn = None
        self.qc_service = QualityService(db_params)  # For reusing IoU calculation

    def connect_db(self):
        try:
            self.conn = psycopg2.connect(**self.db_params)
            logger.info("✓ DatasetGenerator connected to PostgreSQL.")
        except psycopg2.OperationalError as e:
            logger.error(f"✗ DatasetGenerator could not connect to database: {e}")
            self.conn = None

    def close_db(self):
        if self.conn:
            self.conn.close()

    def fetch_approved_annotations(self) -> pd.DataFrame:
        """Fetches all annotations from tasks marked as 'approved'."""
        if not self.conn:
            raise ConnectionError("Database is not connected.")

        query = """
                SELECT t.name as clip_name, \
                       t.assignee, \
                       a.track_id, \
                       a.frame, \
                       a.xtl, \
                       a.ytl, \
                       a.xbr, \
                       a.ybr, \
                       a.attributes
                FROM annotations a
                         JOIN tasks t ON a.task_id = t.task_id
                WHERE t.qc_status = 'approved'; \
                """
        df = pd.read_sql(query, self.conn)
        logger.info(f"Fetched {len(df)} approved annotations from the database.")
        return df

    def _apply_consensus(self, group: pd.DataFrame) -> pd.DataFrame:
        """
        Applies consensus logic to a group of annotations for a single clip.
        """
        annotators = group['assignee'].unique()
        if len(annotators) <= 1:
            # No overlap, return the data as is
            return group

        # This is an overlap clip, apply consensus
        # For this prototype, we'll use a simple "Annotator 1 wins" tie-breaker
        # A more advanced system might average boxes or use a third adjudicator.

        # Group by track and frame to find matching annotations
        final_annotations = []
        ann1_df = group[group['assignee'] == annotators[0]]
        ann2_df = group[group['assignee'] == annotators[1]]

        # Use the first annotator's data as the base
        base_annotations = ann1_df.set_index(['track_id', 'frame'])
        other_annotations = ann2_df.set_index(['track_id', 'frame'])

        for idx, row in base_annotations.iterrows():
            # Check if the other annotator also labeled this instance
            if idx in other_annotations.index:
                # Simple consensus: Average the bounding boxes
                other_row = other_annotations.loc[idx]
                avg_xtl = (row['xtl'] + other_row['xtl']) / 2
                avg_ytl = (row['ytl'] + other_row['ytl']) / 2
                avg_xbr = (row['xbr'] + other_row['xbr']) / 2
                avg_ybr = (row['ybr'] + other_row['ybr']) / 2

                # Simple consensus: Prefer the first annotator's attributes
                final_attributes = row['attributes']

                final_row = row.copy()
                final_row['xtl'], final_row['ytl'], final_row['xbr'], final_row[
                    'ybr'] = avg_xtl, avg_ytl, avg_xbr, avg_ybr
                final_row['attributes'] = final_attributes
                final_annotations.append(final_row.to_dict())
            else:
                # Only annotator 1 labeled this, so we keep it
                final_annotations.append(row.to_dict())

        return pd.DataFrame(final_annotations).reset_index()

    def generate_ava_csv(self, output_path: str):
        """
        Main method to generate the final AVA-style CSV file.
        """
        self.connect_db()
        if not self.conn:
            return

        try:
            df = self.fetch_approved_annotations()
            if df.empty:
                logger.warning("No approved annotations found. No CSV will be generated.")
                return

            # Apply consensus logic to each clip
            # We assume clip_name is derived from the task name, e.g., "annotator1_1_clip_005" -> "1_clip_005"
            df['original_clip_name'] = df['clip_name'].apply(lambda x: '_'.join(x.split('_')[1:]))

            final_df = df.groupby('original_clip_name').apply(self._apply_consensus).reset_index(drop=True)

            # Format the final DataFrame into AVA CSV format
            # This requires mapping your action attributes to a single action_id
            # For this prototype, we'll create a placeholder action_id
            final_df['action_id'] = 1  # Placeholder

            ava_df = final_df.rename(columns={
                'original_clip_name': 'video_id',
                'frame': 'frame_timestamp',  # Assuming frame number is the timestamp for now
                'track_id': 'person_id'
            })

            # Select and order columns for the final CSV
            ava_df = ava_df[['video_id', 'frame_timestamp', 'xtl', 'ytl', 'xbr', 'ybr', 'action_id', 'person_id']]

            ava_df.to_csv(output_path, index=False)
            logger.info(f"✓ Successfully generated AVA dataset at: {output_path}")

        finally:
            self.close_db()