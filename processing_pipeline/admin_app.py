import streamlit as st
import psycopg2
import psycopg2.pool
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from collections import defaultdict
import time
import os
import numpy as np
import json
from sklearn.metrics import cohen_kappa_score
import logging

# Import all of your backend services
from metrics_logging.quality_service import QualityService
from services.dataset_generator import DatasetGenerator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- App Configuration ---
st.set_page_config(page_title="AVA QC Dashboard", layout="wide")
st.title("Annotation Quality Control Dashboard")


# --- Enhanced Quality Metrics Calculator ---
class EnhancedQualityMetrics:
    """Enhanced quality metrics calculator for E2 Agreement & Quality requirements"""

    def __init__(self, db_params: Dict[str, Any]):
        self.db_params = db_params

    def get_connection(self):
        """Get database connection"""
        return psycopg2.connect(**self.db_params)

    def calculate_frame_level_metrics(self, task1_id: int, task2_id: int) -> Dict[str, Any]:
        """Calculate frame-level box agreement metrics"""
        try:
            with self.get_connection() as conn:
                # Get annotations for both tasks
                query = """
                        SELECT a.frame, \
                               a.track_id, \
                               a.xtl, \
                               a.ytl, \
                               a.xbr, \
                               a.ybr,
                               a.outside, \
                               a.attributes, \
                               t.task_id, \
                               t.assignee
                        FROM annotations a
                                 JOIN tasks t ON a.task_id = t.task_id
                        WHERE a.task_id IN (%s, %s)
                        ORDER BY a.frame, a.track_id \
                        """
                df = pd.read_sql(query, conn, params=(task1_id, task2_id))

            if df.empty:
                return {"error": "No annotations found for the specified tasks"}

            # Group by task
            task1_data = df[df['task_id'] == task1_id]
            task2_data = df[df['task_id'] == task2_id]

            # Calculate IoU for matched frames
            ious = []
            frames_with_iou_gte_05 = 0
            total_matched_frames = 0

            # Get common frames
            common_frames = set(task1_data['frame']) & set(task2_data['frame'])

            for frame in common_frames:
                frame1_boxes = task1_data[task1_data['frame'] == frame]
                frame2_boxes = task2_data[task2_data['frame'] == frame]

                if not frame1_boxes.empty and not frame2_boxes.empty:
                    # Calculate IoU for each pair of boxes in the frame
                    frame_ious = []
                    for _, box1 in frame1_boxes.iterrows():
                        for _, box2 in frame2_boxes.iterrows():
                            iou = self._calculate_iou(box1, box2)
                            frame_ious.append(iou)

                    if frame_ious:
                        max_iou = max(frame_ious)
                        ious.append(max_iou)
                        if max_iou >= 0.5:
                            frames_with_iou_gte_05 += 1
                        total_matched_frames += 1

            mean_iou = np.mean(ious) if ious else 0.0
            percent_iou_gte_05 = (frames_with_iou_gte_05 / total_matched_frames) if total_matched_frames > 0 else 0.0

            return {
                "mean_iou": mean_iou,
                "percent_iou_gte_05": percent_iou_gte_05,
                "total_matched_frames": total_matched_frames,
                "ious": ious
            }

        except Exception as e:
            logger.error(f"Error calculating frame-level metrics: {e}")
            return {"error": str(e)}

    def calculate_tube_level_metrics(self, task1_id: int, task2_id: int) -> Dict[str, Any]:
        """Calculate tube-level action agreement metrics (Cohen's κ and flip-rates)"""
        try:
            with self.get_connection() as conn:
                query = """
                        SELECT a.frame, a.track_id, a.attributes, t.task_id, t.assignee
                        FROM annotations a
                                 JOIN tasks t ON a.task_id = t.task_id
                        WHERE a.task_id IN (%s, %s)
                        ORDER BY a.frame, a.track_id \
                        """
                df = pd.read_sql(query, conn, params=(task1_id, task2_id))

            if df.empty:
                return {"error": "No annotations found for the specified tasks"}

            # Parse attributes and calculate metrics
            task1_data = df[df['task_id'] == task1_id].copy()
            task2_data = df[df['task_id'] == task2_id].copy()

            # Parse JSON attributes
            for data in [task1_data, task2_data]:
                data['parsed_attributes'] = data['attributes'].apply(
                    lambda x: json.loads(x) if isinstance(x, str) else (x if isinstance(x, dict) else {})
                )

            # Get all unique action attributes
            all_actions = set()
            for _, row in pd.concat([task1_data, task2_data]).iterrows():
                attrs = row['parsed_attributes']
                all_actions.update(attrs.keys())

            # Remove non-action attributes (like person_id, etc.)
            action_attributes = [attr for attr in all_actions if not attr.startswith('person')]

            kappa_scores = {}
            flip_rates = {"annotator_1": {}, "annotator_2": {}}

            # Calculate Cohen's κ for each action
            for action in action_attributes:
                task1_labels, task2_labels = self._align_labels_for_action(
                    task1_data, task2_data, action
                )

                if len(task1_labels) > 0 and len(set(task1_labels + task2_labels)) > 1:
                    try:
                        kappa = cohen_kappa_score(task1_labels, task2_labels)
                        kappa_scores[action] = kappa
                    except Exception as e:
                        logger.warning(f"Could not calculate kappa for {action}: {e}")
                        kappa_scores[action] = 0.0
                else:
                    kappa_scores[action] = 0.0

            # Calculate flip-rates for each annotator
            flip_rates["annotator_1"] = self._calculate_flip_rates(task1_data, action_attributes)
            flip_rates["annotator_2"] = self._calculate_flip_rates(task2_data, action_attributes)

            # Calculate macro-average kappa
            macro_avg_kappa = np.mean(list(kappa_scores.values())) if kappa_scores else 0.0

            return {
                "kappa_scores": kappa_scores,
                "macro_avg_kappa": macro_avg_kappa,
                "flip_rates": flip_rates,
                "action_attributes": action_attributes
            }

        except Exception as e:
            logger.error(f"Error calculating tube-level metrics: {e}")
            return {"error": str(e)}

    def run_comprehensive_quality_check(self, task1_id: int, task2_id: int) -> Dict[str, Any]:
        """Run comprehensive quality check combining frame and tube level metrics"""

        # Get task information
        try:
            with self.get_connection() as conn:
                query = "SELECT task_id, name, assignee FROM tasks WHERE task_id IN (%s, %s)"
                task_info = pd.read_sql(query, conn, params=(task1_id, task2_id))
        except Exception as e:
            return {"error": f"Failed to get task information: {e}"}

        if len(task_info) != 2:
            return {"error": "Could not find both tasks in database"}

        # Calculate frame-level metrics
        frame_metrics = self.calculate_frame_level_metrics(task1_id, task2_id)
        if "error" in frame_metrics:
            return frame_metrics

        # Calculate tube-level metrics
        tube_metrics = self.calculate_tube_level_metrics(task1_id, task2_id)
        if "error" in tube_metrics:
            return tube_metrics

        # Combine results
        results = {
            "task_info": {
                "task1": {"id": task1_id, "name": task_info[task_info['task_id'] == task1_id].iloc[0]['name'],
                          "assignee": task_info[task_info['task_id'] == task1_id].iloc[0]['assignee']},
                "task2": {"id": task2_id, "name": task_info[task_info['task_id'] == task2_id].iloc[0]['name'],
                          "assignee": task_info[task_info['task_id'] == task2_id].iloc[0]['assignee']}
            },
            # Frame-level metrics
            "average_iou": frame_metrics["mean_iou"],
            "percent_iou_gte_05": frame_metrics["percent_iou_gte_05"],
            "total_matched_frames": frame_metrics["total_matched_frames"],

            # Tube-level metrics
            "kappa_scores": tube_metrics["kappa_scores"],
            "macro_avg_kappa": tube_metrics["macro_avg_kappa"],
            "flip_rates": tube_metrics["flip_rates"],
            "action_attributes": tube_metrics["action_attributes"]
        }

        return results

    def _calculate_iou(self, box1: pd.Series, box2: pd.Series) -> float:
        """Calculate IoU between two bounding boxes"""
        # Convert to float to avoid issues
        x1_1, y1_1, x2_1, y2_1 = float(box1['xtl']), float(box1['ytl']), float(box1['xbr']), float(box1['ybr'])
        x1_2, y1_2, x2_2, y2_2 = float(box2['xtl']), float(box2['ytl']), float(box2['xbr']), float(box2['ybr'])

        # Calculate intersection
        xi1 = max(x1_1, x1_2)
        yi1 = max(y1_1, y1_2)
        xi2 = min(x2_1, x2_2)
        yi2 = min(y2_1, y2_2)

        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0

        intersection = (xi2 - xi1) * (yi2 - yi1)

        # Calculate union
        area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
        area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0

    def _align_labels_for_action(self, task1_data: pd.DataFrame, task2_data: pd.DataFrame,
                                 action: str) -> Tuple[List[str], List[str]]:
        """Align labels for a specific action across two tasks"""

        # Get common frames and tracks
        task1_frames = set(zip(task1_data['frame'], task1_data['track_id']))
        task2_frames = set(zip(task2_data['frame'], task2_data['track_id']))
        common_frames = task1_frames & task2_frames

        labels1, labels2 = [], []

        for frame, track in common_frames:
            # Get labels for this frame/track combination
            task1_row = task1_data[(task1_data['frame'] == frame) & (task1_data['track_id'] == track)]
            task2_row = task2_data[(task2_data['frame'] == frame) & (task2_data['track_id'] == track)]

            if not task1_row.empty and not task2_row.empty:
                attrs1 = task1_row.iloc[0]['parsed_attributes']
                attrs2 = task2_row.iloc[0]['parsed_attributes']

                label1 = attrs1.get(action, 'unknown')
                label2 = attrs2.get(action, 'unknown')

                labels1.append(str(label1))
                labels2.append(str(label2))

        return labels1, labels2

    def _calculate_flip_rates(self, task_data: pd.DataFrame, action_attributes: List[str]) -> Dict[str, float]:
        """Calculate flip rates for temporal stability"""
        flip_rates = {}

        for action in action_attributes:
            total_flips = 0
            total_transitions = 0

            # Group by track to analyze temporal stability
            for track_id in task_data['track_id'].unique():
                track_data = task_data[task_data['track_id'] == track_id].sort_values('frame')

                if len(track_data) < 2:
                    continue

                prev_label = None
                for _, row in track_data.iterrows():
                    attrs = row['parsed_attributes']
                    current_label = attrs.get(action, 'unknown')

                    if prev_label is not None:
                        total_transitions += 1
                        if current_label != prev_label:
                            total_flips += 1

                    prev_label = current_label

            flip_rates[action] = (total_flips / total_transitions) if total_transitions > 0 else 0.0

        return flip_rates


# --- Database Connection Pool ---
@st.cache_resource
def init_connection_pool(db_params: Dict[str, Any]) -> psycopg2.pool.SimpleConnectionPool:
    """Creates and caches a PostgreSQL connection pool."""
    try:
        return psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=10, **db_params)
    except psycopg2.OperationalError as e:
        st.error(f"Could not connect to database: {e}")
        return None


# --- Data Fetching Functions ---
@st.cache_data
def get_projects(_pool):
    if not _pool: return pd.DataFrame()
    with _pool.getconn() as conn:
        df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
    return df


@st.cache_data
def get_tasks_for_project(_pool, project_id):
    if not _pool: return pd.DataFrame()
    with _pool.getconn() as conn:
        query = "SELECT task_id, name, assignee, status, qc_status FROM tasks WHERE project_id = %s ORDER BY task_id"
        df = pd.read_sql(query, conn, params=(project_id,))
    return df


def update_qc_status(_pool, task_ids: List[int], new_status: str):
    if not _pool: return
    with _pool.getconn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tasks SET qc_status = %s WHERE task_id = ANY(%s)", (new_status, task_ids))
        conn.commit()
    st.cache_data.clear()


# --- Sidebar for DB Connection ---
st.sidebar.header("Database Connection")
db_params = {
    "dbname": st.sidebar.text_input("DB Name", "cvat_annotations_db"),
    "user": st.sidebar.text_input("DB User", "admin"),
    "password": st.sidebar.text_input("DB Password", "admin", type="password"),
    "host": st.sidebar.text_input("DB Host", "127.0.0.1"),
    "port": st.sidebar.text_input("DB Port", "55432")
}
pool = init_connection_pool(db_params)

# --- Main Page Layout ---
if pool:
    st.header("1. Select a Project")
    col1, col2 = st.columns([4, 1])
    projects_df = get_projects(pool)

    if projects_df.empty:
        st.warning("No projects with completed tasks found.")
    else:
        selected_project_id = col1.selectbox("Project ID", projects_df['project_id'])
        if col2.button("🔄 Refresh Task List"):
            st.cache_data.clear()
            st.rerun()

        st.header("2. Project Tasks Overview")
        tasks_df = get_tasks_for_project(pool, selected_project_id)

        if tasks_df.empty:
            st.warning(f"No tasks found for project {selected_project_id}.")
        else:
            st.dataframe(tasks_df, use_container_width=True)

            # --- Enhanced QC Section ---
            st.header("3. Enhanced Quality Control Workflow")
            eligible_tasks = tasks_df[(tasks_df['status'] == 'completed') & (tasks_df['qc_status'] == 'pending')]

            if eligible_tasks.empty:
                st.info("No tasks are currently pending quality control.")
            else:
                clip_to_tasks = defaultdict(list)
                for _, row in eligible_tasks.iterrows():
                    if '_' in row['name']:
                        clip_to_tasks['_'.join(row['name'].split('_')[1:])].append(row['task_id'])

                overlap_clips = {c: t for c, t in clip_to_tasks.items() if len(t) > 1}
                single_tasks = [t[0] for c, t in clip_to_tasks.items() if len(t) == 1]

                st.subheader("A. Inter-Annotator Agreement Check (E2 Metrics)")
                if not overlap_clips:
                    st.warning("No overlap clips found among the pending tasks.")
                else:
                    selected_clip = st.selectbox("Select an Overlap Clip to Compare:", list(overlap_clips.keys()))
                    selected_tasks = overlap_clips[selected_clip]

                    # Display task information
                    st.write(f"**Comparing Tasks:**")
                    for i, task_id in enumerate(selected_tasks, 1):
                        task_row = tasks_df[tasks_df['task_id'] == task_id].iloc[0]
                        st.write(f"  - Task {i}: ID {task_id} by {task_row['assignee']} ('{task_row['name']}')")

                    if st.button("🔍 Run Enhanced Quality Check"):
                        with st.spinner("Running comprehensive quality analysis..."):
                            # Use enhanced quality metrics
                            enhanced_qc = EnhancedQualityMetrics(db_params)
                            results = enhanced_qc.run_comprehensive_quality_check(selected_tasks[0], selected_tasks[1])
                            st.session_state['enhanced_qc_results'] = results
                            st.session_state['tasks_to_update'] = selected_tasks
                            st.rerun()

                st.subheader("B. Approve Single-Annotator Tasks")
                if not single_tasks:
                    st.info("No single-annotator tasks are pending approval.")
                else:
                    tasks_to_approve = st.multiselect("Select single-annotator tasks to approve:", options=single_tasks)
                    if st.button("✅ Approve Selected Single Tasks"):
                        if tasks_to_approve:
                            update_qc_status(pool, tasks_to_approve, "approved")
                            st.toast(f"✅ Tasks {tasks_to_approve} approved!")
                            time.sleep(1)
                            st.rerun()

    # ✨ Enhanced QC Results Display
    if 'enhanced_qc_results' in st.session_state:
        results = st.session_state['enhanced_qc_results']
        tasks_to_update = st.session_state['tasks_to_update']

        st.header("📊 E2 Agreement & Quality Analysis")

        if "error" in results:
            st.error(f"Quality check failed: {results['error']}")
        else:
            # Task Information
            st.subheader("🎯 Task Comparison Summary")
            task_info = results['task_info']
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"**Task 1:** {task_info['task1']['name']}\n\n**Annotator:** {task_info['task1']['assignee']}")
            with col2:
                st.info(f"**Task 2:** {task_info['task2']['name']}\n\n**Annotator:** {task_info['task2']['assignee']}")

            # Frame-Level Metrics
            st.subheader("📐 Frame-Level Box Agreement")
            col1, col2, col3 = st.columns(3)
            col1.metric("Mean IoU", f"{results['average_iou']:.3f}",
                        help="Average Intersection over Union for matched bounding boxes")
            col2.metric("% Frames IoU ≥ 0.5", f"{results['percent_iou_gte_05']:.1%}",
                        help="Percentage of frames with IoU ≥ 0.5")
            col3.metric("Total Matched Frames", results['total_matched_frames'],
                        help="Number of frames compared between annotators")

            # Tube-Level Action Agreement
            st.subheader("🎬 Tube-Level Action Agreement")

            # Summary metrics
            col1, col2 = st.columns(2)
            col1.metric("Macro-Average Cohen's κ", f"{results['macro_avg_kappa']:.3f}",
                        help="Average agreement across all action attributes")

            # Calculate average flip rates
            avg_flip_rate_1 = np.mean(list(results['flip_rates']['annotator_1'].values()))
            avg_flip_rate_2 = np.mean(list(results['flip_rates']['annotator_2'].values()))
            col2.metric("Avg Temporal Stability", f"{1 - max(avg_flip_rate_1, avg_flip_rate_2):.1%}",
                        help="Temporal consistency (1 - flip rate)")

            # Detailed metrics table
            st.subheader("📋 Detailed Action-Level Metrics")
            if results['kappa_scores']:
                kappa_scores = results['kappa_scores']
                flip_rate1 = results['flip_rates']['annotator_1']
                flip_rate2 = results['flip_rates']['annotator_2']

                report_data = {
                    "Action Attribute": list(kappa_scores.keys()),
                    "Cohen's Kappa (κ)": [f"{v:.3f}" for v in kappa_scores.values()],
                    f"{task_info['task1']['assignee']} Flip-Rate": [f"{flip_rate1.get(k, 0):.2%}" for k in
                                                                    kappa_scores.keys()],
                    f"{task_info['task2']['assignee']} Flip-Rate": [f"{flip_rate2.get(k, 0):.2%}" for k in
                                                                    kappa_scores.keys()],
                    "Agreement Level": [
                        "Excellent" if v > 0.8 else
                        "Good" if v > 0.6 else
                        "Moderate" if v > 0.4 else
                        "Fair" if v > 0.2 else "Poor"
                        for v in kappa_scores.values()
                    ]
                }

                report_df = pd.DataFrame(report_data)


                # Color code the dataframe
                def color_kappa(val):
                    if 'Kappa' in val.name:
                        try:
                            num_val = float(val.replace('κ)', '').strip())
                            if num_val > 0.8:
                                return 'background-color: #d4edda'  # Green
                            elif num_val > 0.6:
                                return 'background-color: #fff3cd'  # Yellow
                            elif num_val > 0.4:
                                return 'background-color: #f8d7da'  # Light red
                            else:
                                return 'background-color: #f5c6cb'  # Red
                        except:
                            return ''
                    return ''


                st.dataframe(report_df.style.applymap(color_kappa), use_container_width=True)
            else:
                st.warning("No action attributes found for comparison.")

            # Quality Assessment
            st.subheader("🎯 Quality Assessment")

            # Generate quality report
            quality_issues = []
            if results['average_iou'] < 0.5:
                quality_issues.append(
                    f"⚠️ Low mean IoU ({results['average_iou']:.3f}) indicates poor bounding box agreement")
            if results['percent_iou_gte_05'] < 0.7:
                quality_issues.append(f"⚠️ Only {results['percent_iou_gte_05']:.1%} of frames have IoU ≥ 0.5")
            if results['macro_avg_kappa'] < 0.4:
                quality_issues.append(
                    f"⚠️ Low action agreement (κ = {results['macro_avg_kappa']:.3f}) indicates inconsistent labeling")

            poor_actions = [action for action, kappa in results['kappa_scores'].items() if kappa < 0.4]
            if poor_actions:
                quality_issues.append(f"⚠️ Poor agreement on actions: {', '.join(poor_actions)}")

            if quality_issues:
                st.warning("**Quality Issues Detected:**")
                for issue in quality_issues:
                    st.write(f"  {issue}")
            else:
                st.success("✅ **Good Quality:** Annotations show strong agreement between annotators!")

            # Admin Actions
            st.subheader("🛠️ Admin Actions")
            approve_col, reject_col, clear_col = st.columns(3)

            if approve_col.button("✅ Approve Tasks", type="primary"):
                update_qc_status(pool, tasks_to_update, "approved")
                st.toast(f"✅ Tasks {tasks_to_update} approved!")
                del st.session_state['enhanced_qc_results']
                time.sleep(1)
                st.rerun()

            if reject_col.button("❌ Reject Tasks", type="secondary"):
                update_qc_status(pool, tasks_to_update, "rejected")
                st.toast(f"❌ Tasks {tasks_to_update} rejected!")
                del st.session_state['enhanced_qc_results']
                time.sleep(1)
                st.rerun()

            if clear_col.button("🔄 Clear Results"):
                del st.session_state['enhanced_qc_results']
                st.rerun()

    # --- Final Dataset Generation Section ---
    st.header("4. Generate Final Dataset")
    st.markdown("This will generate the final `train.csv` file from all **approved** annotations.")
    frame_dir = st.text_input("Path to Root Frames Directory", "data/frames")
    output_file = st.text_input("Output CSV File Path", "final_ava_dataset.csv")

    if st.button("📊 Generate Dataset"):
        with st.spinner("Generating dataset..."):
            generator = DatasetGenerator(db_params, frame_dir)
            generator.generate_ava_csv(output_file)
        st.success(f"✅ Dataset generation complete! File saved to: `{output_file}`")

        if os.path.exists(output_file):
            with open(output_file, "r") as f:
                st.download_button("📥 Download CSV", f, file_name=os.path.basename(output_file), mime='text/csv')
else:
    st.warning("Please configure the database connection in the sidebar.")