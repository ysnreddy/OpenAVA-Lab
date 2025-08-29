import streamlit as st
import psycopg2
import psycopg2.pool
import pandas as pd
from typing import Dict, Any, List
import json

# Assume quality_service is in the same services directory
from services.quality_service import QualityService

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
@st.cache_data(ttl=10) # Cache data for 10 seconds to improve performance
def get_projects(_pool):
    """Fetches all projects from the database using a connection from the pool."""
    if not _pool: return pd.DataFrame()
    with _pool.getconn() as conn:
        df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
    return df


@st.cache_data(ttl=10)
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
    # Clear the cache to force a data refresh on the next run
    st.cache_data.clear()


# --- Sidebar for DB Connection ---
st.sidebar.header("Database Connection")
db_params = {
    "dbname": st.sidebar.text_input("DB Name", "cvat_annotations_db"),
    "user": st.sidebar.text_input("DB User", "admin"),
    "password": st.sidebar.text_input("DB Password", "admin", type="password"),
    "host": st.sidebar.text_input("DB Host", "127.0.0.1"),
    "port": st.sidebar.text_input("DB Port", "5432")
}
pool = init_connection_pool(db_params)

# --- Main Page Layout ---
if pool:
    st.header("1. Select a Project")
    projects_df = get_projects(pool)

    if projects_df.empty:
        st.warning("No projects with completed tasks found in the database. Run the post-annotation service first.")
    else:
        selected_project_id = st.selectbox("Project ID", projects_df['project_id'])

        st.header("2. Project Tasks Overview")
        st.markdown("This table shows all tasks retrieved for the selected project.")
        tasks_df = get_tasks_for_project(pool, selected_project_id)

        if tasks_df.empty:
            st.warning(f"No tasks found for project {selected_project_id}.")
        else:
            # ✨ FIX: Display the full, unfiltered task list here so you can see status changes.
            st.dataframe(tasks_df, use_container_width=True)

            # --- Quality Check Section ---
            st.header("3. Run Inter-Annotator Agreement Check")

            # Filter for tasks that are completed and still need a quality check
            eligible_tasks = tasks_df[(tasks_df['status'] == 'completed') & (tasks_df['qc_status'] == 'pending')]

            if eligible_tasks.empty:
                st.info("No tasks are currently pending quality control.")
            else:
                selected_tasks = st.multiselect(
                    "Select exactly two overlap tasks to compare:",
                    options=eligible_tasks['task_id'],
                    max_selections=2
                )

                if len(selected_tasks) == 2:
                    if st.button("Run Quality Check"):
                        with st.spinner("Calculating IAA and Kappa scores..."):
                            qc_service = QualityService(db_params)
                            results = qc_service.run_quality_check(selected_tasks[0], selected_tasks[1])

                        st.subheader("Quality Check Results")
                        if "error" in results:
                            st.error(results["error"])
                        else:
                            col1, col2 = st.columns(2)
                            col1.metric("Average IoU (Box Agreement)", f"{results['average_iou']:.2%}")
                            col2.metric("Compared Annotations", results['compared_annotations'])

                            st.write("Cohen's Kappa (Attribute Agreement):")
                            kappa_df = pd.DataFrame.from_dict(
                                results['kappa_scores'], orient='index', columns=['Kappa Score']
                            )
                            st.dataframe(kappa_df)

                            st.subheader("Admin Actions")
                            approve_col, reject_col = st.columns(2)
                            if approve_col.button("Approve Tasks"):
                                update_qc_status(pool, selected_tasks, "approved")
                                # ✨ FIX: Show a confirmation toast before re-running
                                st.toast(f"✅ Tasks {selected_tasks} approved!")
                                time.sleep(2) # Give time for the toast to be seen
                                st.rerun()

                            if reject_col.button("Reject Tasks"):
                                update_qc_status(pool, selected_tasks, "rejected")
                                st.toast(f"❌ Tasks {selected_tasks} rejected!")
                                time.sleep(2)
                                st.rerun()
else:
    st.warning("Please configure the database connection in the sidebar.")