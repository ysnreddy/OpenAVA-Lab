import streamlit as st
import psycopg2
import psycopg2.pool
import pandas as pd
from typing import Dict, Any, List
import json
import time
import os

from services.quality_service import QualityService
from services.dataset_generator import DatasetGenerator

st.set_page_config(page_title="AVA QC Dashboard", layout="wide")
st.title("Annotation Quality Control Dashboard")


@st.cache_resource
def init_connection_pool(db_params: Dict[str, Any]) -> psycopg2.pool.SimpleConnectionPool:
    try:
        return psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=10, **db_params)
    except psycopg2.OperationalError as e:
        st.error(f"Could not connect to database: {e}")
        return None


@st.cache_data
def get_projects(_pool):
    if not _pool: return pd.DataFrame()
    with _pool.getconn() as conn:
        return pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)


@st.cache_data
def get_tasks_for_project(_pool, project_id):
    if not _pool: return pd.DataFrame()
    with _pool.getconn() as conn:
        query = "SELECT task_id, name, assignee, status, qc_status FROM tasks WHERE project_id = %s ORDER BY task_id"
        return pd.read_sql(query, conn, params=(project_id,))


def update_qc_status(_pool, task_ids: List[int], new_status: str):
    if not _pool: return
    with _pool.getconn() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE tasks SET qc_status = %s WHERE task_id = ANY(%s)", (new_status, task_ids))
        conn.commit()
    st.cache_data.clear()


st.sidebar.header("Database Connection")
db_params = {
    "dbname": st.sidebar.text_input("DB Name", "cvat_annotations"),
    "user": st.sidebar.text_input("DB User", "postgres"),
    "password": st.sidebar.text_input("DB Password", "mysecretpassword", type="password"),
    "host": st.sidebar.text_input("DB Host", "127.0.0.1"),
    "port": st.sidebar.text_input("DB Port", "5432")
}
pool = init_connection_pool(db_params)

if pool:
    st.header("1. Select a Project")
    projects_df = get_projects(pool)

    if projects_df.empty:
        st.warning("No projects found. Run the post-annotation service first.")
    else:
        selected_project_id = st.selectbox("Project ID", projects_df['project_id'])

        st.header("2. Project Tasks Overview")
        tasks_df = get_tasks_for_project(pool, selected_project_id)

        if tasks_df.empty:
            st.warning(f"No tasks found for project {selected_project_id}.")
        else:
            st.dataframe(tasks_df, use_container_width=True)

            st.header("3. Run Inter-Annotator Agreement Check")
            eligible_tasks = tasks_df[(tasks_df['status'] == 'completed') & (tasks_df['qc_status'] == 'pending')]

            if eligible_tasks.empty:
                st.info("No tasks are currently pending quality control.")
            else:
                task_names = eligible_tasks['name'].unique()
                clip_to_tasks = {name.split('_', 1)[1]: [] for name in task_names}
                for _, row in eligible_tasks.iterrows():
                    clip_to_tasks[row['name'].split('_', 1)[1]].append(row['task_id'])

                overlap_clips = {clip: tasks for clip, tasks in clip_to_tasks.items() if len(tasks) > 1}

                if not overlap_clips:
                    st.warning("No overlap clips found among the pending tasks.")
                else:
                    selected_clip = st.selectbox("Select an Overlap Clip to Compare:", list(overlap_clips.keys()))
                    selected_tasks = overlap_clips[selected_clip]

                    if st.button("Run Quality Check"):
                        qc_service = QualityService(db_params)
                        results = qc_service.run_quality_check(selected_tasks[0], selected_tasks[1])
                        st.session_state['qc_results'] = results
                        st.session_state['tasks_to_update'] = selected_tasks
                        st.rerun()

    if 'qc_results' in st.session_state:
        # Display results and actions here... (code omitted for brevity but is unchanged)
        pass  # Your existing results display logic goes here

    st.header("4. Generate Final Dataset")
    st.markdown("This will take all **approved** annotations, apply consensus, and generate the final `train.csv`.")

    # ✨ FIX: Add an input for the frames directory
    frame_dir = st.text_input("Path to Root Frames Directory", "data/frames")
    output_file = st.text_input("Output CSV File Path", "final_ava_dataset.csv")

    if st.button("Generate Dataset"):
        with st.spinner("Generating dataset..."):
            generator = DatasetGenerator(db_params, frame_dir)
            generator.generate_ava_csv(output_file)
        st.success(f"✅ Dataset generation complete! File saved to: `{output_file}`")

        with open(output_file, "r") as f:
            st.download_button("Download CSV", f, file_name=os.path.basename(output_file), mime='text/csv')
else:
    st.warning("Please configure the database connection in the sidebar.")