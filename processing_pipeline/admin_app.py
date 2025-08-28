import streamlit as st
import psycopg2
import pandas as pd
from typing import Dict, Any

# Assuming quality_service is in the same services directory
from services.quality_service import QualityService

# --- App Configuration ---
st.set_page_config(page_title="AVA QC Dashboard", layout="wide")
st.title("Annotation Quality Control Dashboard")


# --- Database Connection ---
@st.cache_resource
def get_db_connection(db_params: Dict[str, Any]):
    """Creates and caches a database connection."""
    try:
        conn = psycopg2.connect(**db_params)
        return conn
    except psycopg2.OperationalError as e:
        st.error(f"Could not connect to database: {e}")
        return None


# --- Data Fetching Functions ---
def get_projects(conn):
    """Fetches all projects from the database."""
    if not conn: return pd.DataFrame()
    df = pd.read_sql("SELECT DISTINCT project_id FROM tasks ORDER BY project_id DESC", conn)
    return df


def get_tasks_for_project(conn, project_id):
    """Fetches all tasks for a given project."""
    if not conn: return pd.DataFrame()
    query = "SELECT task_id, name, assignee, status, qc_status FROM tasks WHERE project_id = %s ORDER BY task_id"
    df = pd.read_sql(query, conn, params=(project_id,))
    return df


def update_qc_status(conn, task_ids, new_status):
    """Updates the qc_status for a list of tasks."""
    if not conn: return
    with conn.cursor() as cur:
        cur.execute("UPDATE tasks SET qc_status = %s WHERE task_id = ANY(%s)", (new_status, task_ids))
    conn.commit()
    st.success(f"Updated QC status for tasks {task_ids} to '{new_status}'.")


# --- Sidebar for DB Connection ---
st.sidebar.header("Database Connection")
db_params = {
    "dbname": st.sidebar.text_input("DB Name", "cvat_annotations"),
    "user": st.sidebar.text_input("DB User", "postgres"),
    "password": st.sidebar.text_input("DB Password", type="password"),
    "host": st.sidebar.text_input("DB Host", "localhost"),
    "port": st.sidebar.text_input("DB Port", "5432")
}
conn = get_db_connection(db_params)

# --- Main Page Layout ---
if conn:
    st.header("1. Select a Project")
    projects_df = get_projects(conn)

    if projects_df.empty:
        st.warning("No projects with completed tasks found in the database.")
    else:
        selected_project_id = st.selectbox("Project ID", projects_df['project_id'])

        st.header("2. View Tasks and Select for QC")
        tasks_df = get_tasks_for_project(conn, selected_project_id)

        if tasks_df.empty:
            st.warning(f"No tasks found for project {selected_project_id}.")
        else:
            st.dataframe(tasks_df, use_container_width=True)

            # --- Quality Check Section ---
            st.subheader("Run Inter-Annotator Agreement Check")

            # Filter for tasks that are completed and pending QC
            eligible_tasks = tasks_df[(tasks_df['status'] == 'completed') & (tasks_df['qc_status'] == 'pending')]

            # Allow user to select exactly two tasks for comparison
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
                        col1.metric("Average IoU (Bounding Box Agreement)", f"{results['average_iou']:.2%}")
                        col2.metric("Compared Annotations", results['compared_annotations'])

                        st.write("Cohen's Kappa (Attribute Agreement):")
                        kappa_df = pd.DataFrame.from_dict(
                            results['kappa_scores'], orient='index', columns=['Kappa Score']
                        )
                        st.dataframe(kappa_df)

                        # --- Admin Actions ---
                        st.subheader("Admin Actions")
                        approve_col, reject_col = st.columns(2)
                        if approve_col.button("Approve Tasks"):
                            update_qc_status(conn, selected_tasks, "approved")
                            st.rerun()
                        if reject_col.button("Reject Tasks"):
                            update_qc_status(conn, selected_tasks, "rejected")
                            st.rerun()
else:
    st.warning("Please configure the database connection in the sidebar.")
