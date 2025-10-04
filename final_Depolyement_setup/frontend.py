# frontend_s3.py
import streamlit as st
import requests
import os
import pandas as pd
from collections import defaultdict
from datetime import datetime
from typing import Dict, Any, List, Union

# ---------------------------
# FastAPI backend URL
# ---------------------------
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://localhost:8000")

# ---------------------------
# Helpers
# ---------------------------
def safe_json_or_text(resp: requests.Response) -> Union[Dict[str, Any], str]:
    try:
        return resp.json()
    except Exception:
        return resp.text

def calculate_makespan_from_tasks(tasks: List[Dict[str, Any]]) -> float:
    if not tasks:
        return 0.0
    created_dates = [t.get("extra", {}).get("created_date", "").replace('Z', '+00:00') for t in tasks if t.get("extra", {}).get("created_date")]
    updated_dates = [t.get("extra", {}).get("updated_date", "").replace('Z', '+00:00') for t in tasks if t.get("extra", {}).get("updated_date")]
    dt_created = [datetime.fromisoformat(d) for d in created_dates if d]
    dt_updated = [datetime.fromisoformat(d) for d in updated_dates if d]
    if not dt_created or not dt_updated:
        return 0.0
    return (max(dt_updated) - min(dt_created)).total_seconds()

# ---------------------------
# Streamlit Page Config
# ---------------------------
st.set_page_config(page_title="AVA Unified Platform", layout="wide")

# ---------------------------
# Sidebar Navigation
# ---------------------------
st.sidebar.title("📊 AVA Unified Platform")
page = st.sidebar.radio(
    "Navigate",
    ["🏁 Home", "📌 Pre-Annotation Tool", "📝 Task Creator", "✅ Quality Control", "📈 Metrics Dashboard"],
)

# ---------------------------
# 1️⃣ Home
# ---------------------------
if page == "🏁 Home":
    st.title("📊 AVA Unified Platform")
    st.markdown("""
    Welcome to the **AVA Unified Platform Dashboard** 🎬  
    Manage the video annotation pipeline efficiently with S3-based storage.
    """)

# ---------------------------
# 2️⃣ Pre-Annotation Tool
# ---------------------------
elif page == "📌 Pre-Annotation Tool":
    st.title("📌 Pre-Annotation Tool")
    st.markdown("Upload your `dense_proposals.pkl` and `frames.zip` (directly to S3).")

    pickle_file = st.file_uploader("Upload dense_proposals.pkl", type=["pkl"])
    frames_zip = st.file_uploader("Upload frames.zip", type=["zip"])

    if st.button("🚀 Run Pre-Annotation"):
        if pickle_file and frames_zip:
            # 1️⃣ Request pre-signed URLs
            resp_urls = requests.post(f"{FASTAPI_URL}/pre-annotation/get-presigned-urls", json={
                "files": ["dense_proposals.pkl", frames_zip.name]
            })
            if resp_urls.status_code != 200:
                st.error(f"❌ Error fetching upload URLs: {safe_json_or_text(resp_urls)}")
                st.stop()
            urls = resp_urls.json()  # {'dense_proposals.pkl': '...', 'frames.zip': '...'}

            # 2️⃣ Upload directly to S3
            for name, url in urls.items():
                file_obj = pickle_file if name == "dense_proposals.pkl" else frames_zip
                requests.put(url, data=file_obj.getvalue())

            # 3️⃣ Trigger processing on backend
            payload = {"s3_paths": list(urls.values())}
            resp_proc = requests.post(f"{FASTAPI_URL}/pre-annotation/process-clips-s3", json=payload)
            if resp_proc.status_code == 200:
                download_url = resp_proc.json()["download_url"]
                st.success("✅ CVAT package generated successfully!")
                st.markdown(f"[⬇️ Download CVAT Package]({download_url})")
            else:
                st.error(f"❌ Error: {safe_json_or_text(resp_proc)}")
        else:
            st.warning("⚠️ Please upload both files.")

# ---------------------------
# 3️⃣ Task Creator
# ---------------------------
elif page == "📝 Task Creator":
    st.title("📝 CVAT Task Creator")

    uploaded_zips = st.file_uploader("Upload Clip ZIPs", type=["zip"], accept_multiple_files=True)
    uploaded_xmls = st.file_uploader("Upload XMLs", type=["xml"], accept_multiple_files=True)

    if st.button("📤 Upload Assets"):
        if uploaded_zips and uploaded_xmls:
            # 1️⃣ Get pre-signed URLs
            filenames = [f.name for f in uploaded_zips + uploaded_xmls]
            resp_urls = requests.post(f"{FASTAPI_URL}/task-creator/get-presigned-urls", json={"files": filenames})
            if resp_urls.status_code != 200:
                st.error(f"❌ Error fetching upload URLs: {safe_json_or_text(resp_urls)}")
                st.stop()
            urls = resp_urls.json()  # dict: {filename: presigned_url}

            # 2️⃣ Upload each file directly to S3
            for f in uploaded_zips + uploaded_xmls:
                requests.put(urls[f.name], data=f.getvalue())

            # 3️⃣ Trigger backend task creation
            payload = {"s3_paths": list(urls.values())}
            resp_create = requests.post(f"{FASTAPI_URL}/task-creator/upload-assets-s3", json=payload)
            if resp_create.status_code == 200:
                st.success("✅ Files uploaded successfully.")
                st.json(safe_json_or_text(resp_create))
            else:
                st.error(f"❌ Error: {safe_json_or_text(resp_create)}")
        else:
            st.warning("⚠️ Please upload both ZIPs and XMLs.")

    # Project creation
    st.subheader("Step 2: Create Project & Tasks")
    project_name = st.text_input("Project Name", value="AVA_Project")
    annotators = st.text_area("Annotators (comma-separated)", value="annotator1,annotator2")
    overlap = st.slider("Overlap Percentage", 0, 100, 20)
    org_slug = st.text_input("Organization Slug (optional)", value="").strip()

    if st.button("🚀 Create Project"):
        payload = {
            "project_name": project_name,
            "annotators": [a.strip() for a in annotators.split(",") if a.strip()],
            "overlap_percentage": overlap,
            "org_slug": org_slug if org_slug != "" else ""
        }
        resp = requests.post(f"{FASTAPI_URL}/task-creator/create-project", json=payload)
        if resp.status_code in (200, 201):
            st.success("✅ Project created successfully!")
            st.json(safe_json_or_text(resp))
        else:
            st.error(f"❌ Error: {safe_json_or_text(resp)}")

# ---------------------------
# 4️⃣ Quality Control & Dataset Generation
# ---------------------------
elif page == "✅ Quality Control":
    st.title("✅ Quality Control & Dataset Generation")

    # List projects
    resp = requests.get(f"{FASTAPI_URL}/quality-control/projects")
    projects = []
    if resp.status_code == 200:
        projects_data = safe_json_or_text(resp)
        projects = projects_data.get("projects", []) if isinstance(projects_data, dict) else projects_data
    else:
        st.error(f"❌ Error fetching projects: {safe_json_or_text(resp)}")

    if not projects:
        st.info("No projects available.")
        st.stop()

    selected_project = st.selectbox("Select Project ID", projects)
    if not selected_project:
        st.stop()

    # Fetch tasks
    resp_tasks = requests.get(f"{FASTAPI_URL}/quality-control/projects/{selected_project}/tasks")
    tasks_df = pd.DataFrame(safe_json_or_text(resp_tasks)) if resp_tasks.status_code == 200 else pd.DataFrame()
    st.dataframe(tasks_df)

    # ---------------------
    # Generate final dataset (S3)
    st.subheader("📑 Generate Final Dataset")
    output_filename = st.text_input("Output Filename", value="final_ava_dataset.csv")

    if st.button("🚀 Generate Dataset"):
        payload = {"output_filename": output_filename, "project_id": selected_project}
        resp_gen = requests.post(f"{FASTAPI_URL}/quality-control/generate-dataset-s3", json=payload)
        if resp_gen.status_code == 200:
            download_url = resp_gen.json()["download_url"]
            st.success("✅ Dataset generated successfully!")
            st.markdown(f"[📥 Download Dataset]({download_url})")
        else:
            st.error(f"❌ Error: {safe_json_or_text(resp_gen)}")

# ---------------------------
# 5️⃣ Metrics Dashboard
# ---------------------------
elif page == "📈 Metrics Dashboard":
    st.title("📈 Metrics Dashboard")
    resp_projects = requests.get(f"{FASTAPI_URL}/quality-control/projects")
    projects = safe_json_or_text(resp_projects).get("projects", []) if resp_projects.status_code == 200 else []
    if not projects:
        st.info("No projects available. Create a project first.")
        st.stop()

    selected_project = st.selectbox("Select Project", projects)

    if st.button("🔄 Refresh Metrics"):
        params = {"project_id": selected_project} if selected_project else {}
        resp = requests.get(f"{FASTAPI_URL}/metrics/summary", params=params)
        if resp.status_code == 200:
            data = safe_json_or_text(resp)
            st.json(data)
        else:
            st.error(f"❌ Error fetching metrics: {safe_json_or_text(resp)}")
