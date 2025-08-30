import streamlit as st
import psycopg2
import psycopg2.pool
import pandas as pd
from typing import Dict, Any, List
import json
import time
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Import both of your backend services
from services.quality_service import QualityService
from services.dataset_generator import DatasetGenerator  

# --- App Configuration ---
st.set_page_config(page_title="AVA QC Dashboard", layout="wide")
st.title("Annotation Quality Control Dashboard")


# --- Database Connection Pool ---
@st.cache_resource
def init_connection_pool(db_params: Dict[str, Any]) -> psycopg2.pool.SimpleConnectionPool:
    """Creates and caches a PostgreSQL connection pool."""
    try:
        return psycopg2.pool.SimpleConnectionPool(minconn=1, maxconn=10, **db_params)
    except psycopg2.OperationalError as e:
        st.error(f"Could not connect to database: {e}")
        return None


# --- Data Fetching Functions (Now using the pool) ---
@st.cache_data
def get_projects(_pool):
    """Fetches all projects from the database."""
    if not _pool: return pd.DataFrame()
    with _pool.getconn() as conn:
        df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
    return df


@st.cache_data
def get_tasks_for_project(_pool, project_id):
    """Fetches all tasks for a given project."""
    if not _pool: return pd.DataFrame()
    with _pool.getconn() as conn:
        query = "SELECT task_id, name, assignee, status, qc_status FROM tasks WHERE project_id = %s ORDER BY task_id"
        df = pd.read_sql(query, conn, params=(project_id,))
    return df


def update_qc_status(_pool, task_ids: List[int], new_status: str):
    """Updates the qc_status for a list of tasks."""
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
    projects_df = get_projects(pool)

    if projects_df.empty:
        st.warning("No projects with completed tasks found. Run the post-annotation service first.")
    else:
        selected_project_id = st.selectbox("Project ID", projects_df['project_id'])

        st.header("2. Project Tasks Overview")
        st.markdown("This table shows all tasks retrieved for the selected project.")
        tasks_df = get_tasks_for_project(pool, selected_project_id)

        if tasks_df.empty:
            st.warning(f"No tasks found for project {selected_project_id}.")
        else:
            st.dataframe(tasks_df, use_container_width=True)

            # --- QC Section ---
            # --- QC Section ---
        st.header("3. Run Inter-Annotator Agreement Check")
        eligible_tasks = tasks_df[(tasks_df['status'] == 'completed') & (tasks_df['qc_status'] == 'pending')]

        if eligible_tasks.empty:
            st.info("No tasks are currently pending quality control.")
        else:
            st.markdown("Find two tasks that represent the **same clip** (overlap work) to compare them.")
            task_names = eligible_tasks['name'].unique()

            # Create a map of clip names to their task IDs (safe split)
            clip_to_tasks = {}
            for _, row in eligible_tasks.iterrows():
                name = row['name']
                parts = name.split("_", 1)
                if len(parts) > 1:
                    clip_name = parts[1]   # remove annotator prefix
                else:
                    clip_name = name       # fallback if no underscore
                clip_to_tasks.setdefault(clip_name, []).append(row['task_id'])

            # Find clips that have more than one task (these are the overlap clips)
            overlap_clips = {clip: tasks for clip, tasks in clip_to_tasks.items() if len(tasks) > 1}

            if not overlap_clips:
                st.warning("No overlap clips found among the pending tasks.")
            else:
                selected_clip = st.selectbox("Select an Overlap Clip to Compare:", list(overlap_clips.keys()))
                selected_tasks = overlap_clips[selected_clip]

                st.write(f"Comparing Task ID **{selected_tasks[0]}** and Task ID **{selected_tasks[1]}**.")

                if st.button("Run Quality Check"):
                    with st.spinner("Calculating IAA and Kappa scores..."):
                        qc_service = QualityService(db_params)
                        results = qc_service.run_quality_check(selected_tasks[0], selected_tasks[1])

                    st.session_state['qc_results'] = results
                    st.session_state['tasks_to_update'] = selected_tasks
                    st.rerun()


    # Display results and actions outside of the main "if" block for persistence
    if 'qc_results' in st.session_state:
        results = st.session_state['qc_results']
        tasks_to_update = st.session_state['tasks_to_update']

        st.subheader("Quality Check Results")
        if "error" in results:
            st.error(results["error"])
        else:
            col1, col2 = st.columns(2)
            col1.metric("Average IoU (Box Agreement)", f"{results['average_iou']:.2%}")
            col2.metric("Compared Annotations", results['compared_annotations'])

            st.write("Cohen's Kappa (Attribute Agreement):")
            kappa_df = pd.DataFrame.from_dict(results['kappa_scores'], orient='index', columns=['Kappa Score'])
            st.dataframe(kappa_df)

            st.subheader("Admin Actions")
            approve_col, reject_col, clear_col = st.columns(3)
            if approve_col.button("Approve Tasks"):
                update_qc_status(pool, tasks_to_update, "approved")
                st.toast(f"✅ Tasks {tasks_to_update} approved!")
                del st.session_state['qc_results']
                del st.session_state['tasks_to_update']
                time.sleep(1)
                st.rerun()

            if reject_col.button("Reject Tasks"):
                update_qc_status(pool, tasks_to_update, "rejected")
                st.toast(f"❌ Tasks {tasks_to_update} rejected!")
                del st.session_state['qc_results']
                del st.session_state['tasks_to_update']
                time.sleep(1)
                st.rerun()

            if clear_col.button("Clear Results"):
                del st.session_state['qc_results']
                del st.session_state['tasks_to_update']
                st.rerun()

    # --- Final Dataset Generation Section ---
    st.header("4. Generate Final Dataset")
    st.markdown(
        "This will take all **approved** annotations, apply consensus logic, and generate the final `train.csv` file.")

    output_file = st.text_input("Output CSV File Path", "final_ava_dataset.csv")

    if st.button("Generate Dataset"):
        with st.spinner("Fetching approved annotations and generating dataset..."):
            generator = DatasetGenerator(db_params)
            generator.generate_ava_csv(output_file)
        st.success(f"✅ Dataset generation complete! File saved to: `{output_file}`")

        # Provide a download button for the generated file
        with open(output_file, "r") as f:
            st.download_button(
                label="Download CSV",
                data=f,
                file_name=os.path.basename(output_file),
                mime='text/csv',
            )
else:
    st.warning("Please configure the database connection in the sidebar.")