import streamlit as st
import requests
import os
import pandas as pd
from io import BytesIO
from collections import defaultdict

# ---------------------------
# Base URL of your FastAPI backend
# ---------------------------
FASTAPI_URL = os.getenv("FASTAPI_URL", "http://fastapi:8000")

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
    ["🏁 Home",  "📝 Task Creator", "✅ Quality Control"],
)

# ---------------------------
# Helper Functions
# ---------------------------
def safe_json_or_text(resp):
    """Return JSON or text safely for display."""
    try:
        return resp.json()
    except Exception:
        return resp.text

def upload_to_s3_via_presigned(file_obj, presigned_url, content_type="application/octet-stream"):
    """Upload a file directly to S3 using a presigned URL."""
    resp = requests.put(presigned_url, data=file_obj.getvalue(), headers={"Content-Type": content_type})
    return resp.status_code in (200, 201)

# ---------------------------
# 1. Home Page
# ---------------------------
if page == "🏁 Home":
    st.title("📊 AVA Unified Platform")
    st.markdown("""
        Welcome to the **AVA Unified Platform Dashboard** 🎬  

        This dashboard allows you to:
        - 📝 Create CVAT Projects & Tasks  
        - ✅ Perform Quality Control & Generate Dataset  

        Use the left sidebar to navigate.
    """)

# ---------------------------
# 2. Pre-Annotation Tool
# ---------------------------
# elif page == "📌 Pre-Annotation Tool":
#     st.title("📌 Pre-Annotation Tool")
#     st.markdown("Upload your `dense_proposals.pkl` and `frames.zip` to generate CVAT-ready packages.")

#     pickle_file = st.file_uploader("Upload dense_proposals.pkl", type=["pkl"])
#     frames_zip = st.file_uploader("Upload frames.zip", type=["zip"])

#     if st.button("🚀 Run Pre-Annotation"):
#         if pickle_file and frames_zip:
#             with st.spinner("Getting presigned URLs..."):
#                 presign_resp = requests.post(
#                     f"{FASTAPI_URL}/pre-annotation/get-upload-urls",
#                     json={"files": ["dense_proposals.pkl", frames_zip.name]},
#                 )
#                 if presign_resp.status_code != 200:
#                     st.error(f"❌ Error getting presigned URLs: {safe_json_or_text(presign_resp)}")
#                     st.stop()
#                 urls = presign_resp.json()

#             with st.spinner("Uploading files to S3..."):
#                 ok1 = upload_to_s3_via_presigned(BytesIO(pickle_file.read()), urls["dense_proposals.pkl"])
#                 ok2 = upload_to_s3_via_presigned(BytesIO(frames_zip.read()), urls[frames_zip.name])
#                 if not (ok1 and ok2):
#                     st.error("❌ Failed to upload files to S3.")
#                     st.stop()

#             with st.spinner("Processing on backend..."):
#                 resp = requests.post(f"{FASTAPI_URL}/pre-annotation/process-clips", json={
#                     "pickle_file": "dense_proposals.pkl",
#                     "frames_zip": frames_zip.name,
#                 })
#             if resp.status_code == 200:
#                 download_url = resp.json().get("download_url")
#                 st.success("✅ CVAT package generated successfully!")
#                 st.markdown(f"[⬇️ Download CVAT Package]({download_url})")
#             else:
#                 st.error(f"❌ Error: {safe_json_or_text(resp)}")
#         else:
#             st.warning("⚠️ Please upload both files.")

# ---------------------------
# 3. Task Creator
# ---------------------------
elif page == "📝 Task Creator":
    st.title("📝 CVAT Task Creator")

    st.subheader("Step 1: Upload Assets")
    uploaded_zips = st.file_uploader("Upload Clip ZIPs", type=["zip"], accept_multiple_files=True)
    uploaded_xmls = st.file_uploader("Upload XMLs", type=["xml"], accept_multiple_files=True)

    if st.button("📤 Upload Assets"):
        files_to_upload = uploaded_zips + uploaded_xmls
        if files_to_upload:
            filenames = [f.name for f in files_to_upload]

            presign_resp = requests.post(f"{FASTAPI_URL}/task-creator/get-upload-urls", json={"files": filenames})
            if presign_resp.status_code != 200:
                st.error(f"❌ Error getting presigned URLs: {safe_json_or_text(presign_resp)}")
                st.stop()
            urls = presign_resp.json()

            success = True
            for f in files_to_upload:
                ctype = "application/zip" if f.type.endswith("zip") else "application/xml"
                ok = upload_to_s3_via_presigned(BytesIO(f.read()), urls[f.name], content_type=ctype)
                if not ok:
                    success = False
                    break

            if success:
                st.success("✅ Files uploaded successfully to S3.")
            else:
                st.error("❌ One or more uploads failed.")

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
# 4. Quality Control & Dataset Generation
# ---------------------------
elif page == "✅ Quality Control":
    st.title("✅ Quality Control & Dataset Generation")

    # List Projects
    st.subheader("📂 List Projects")
    resp = requests.get(f"{FASTAPI_URL}/quality-control/projects")
    projects = []
    if resp.status_code == 200:
        projects = safe_json_or_text(resp).get("projects", [])
        st.json(projects)
    else:
        st.error(f"❌ Error: {safe_json_or_text(resp)}")

    if not projects:
        st.info("No projects available.")
        st.stop()

    # Select Project & Load Tasks
    st.subheader("📂 Select Project")
    selected_project = st.selectbox("Select Project ID", projects)
    tasks_df = pd.DataFrame()
    if selected_project:
        resp = requests.get(f"{FASTAPI_URL}/quality-control/projects/{selected_project}/tasks")
        if resp.status_code == 200:
            tasks_df = pd.DataFrame(safe_json_or_text(resp))
            st.subheader(f"Tasks for Project {selected_project}")
            st.dataframe(tasks_df)
        else:
            st.error(f"❌ Error fetching tasks: {safe_json_or_text(resp)}")

    if tasks_df.empty:
        st.info("No tasks found for this project.")
        st.stop()

    # Detect overlaps & single-annotator tasks
    pending_tasks = tasks_df[tasks_df['qc_status'] == 'pending']
    clip_to_tasks = defaultdict(list)
    for _, row in pending_tasks.iterrows():
        parts = row['name'].split('_')
        if len(parts) >= 2:
            clip_name = '_'.join(parts[1:-1])
            clip_to_tasks[clip_name].append(row['task_id'])
    overlap_clips = {clip: ids for clip, ids in clip_to_tasks.items() if len(ids) > 1}
    single_tasks = [ids[0] for clip, ids in clip_to_tasks.items() if len(ids) == 1]

    # IAA Check
    st.subheader("📊 Inter-Annotator Agreement (Overlap Tasks)")
    if overlap_clips:
        selected_clip = st.selectbox("Select Clip to Compare", list(overlap_clips.keys()))
        selected_tasks = overlap_clips[selected_clip]
        st.write(f"Comparing Task IDs: **{selected_tasks[0]}** & **{selected_tasks[1]}**")
        if st.button("Run IAA Check"):
            resp = requests.post(f"{FASTAPI_URL}/quality-control/run-iaa-check", json=selected_tasks)
            if resp.status_code == 200:
                st.session_state['qc_results'] = safe_json_or_text(resp)
                st.session_state['tasks_to_update'] = selected_tasks
                st.success("✅ IAA Check completed.")
            else:
                st.error(f"❌ Error: {safe_json_or_text(resp)}")
    else:
        st.info("No overlapping tasks for IAA found.")

    if 'qc_results' in st.session_state:
        st.subheader("📈 IAA Results")
        results = st.session_state['qc_results']
        tasks_to_update = st.session_state['tasks_to_update']
        if "error" in results:
            st.error(results["error"])
        else:
            st.metric("Average IoU", f"{results['average_iou']:.2%}")
            st.write("Cohen's Kappa Scores:")
            st.dataframe(pd.DataFrame.from_dict(results['kappa_scores'], orient='index', columns=['Kappa']))

            col1, col2, col3 = st.columns(3)
            if col1.button("Approve Tasks"):
                payload = {"task_ids": tasks_to_update, "new_status": "approved"}
                resp = requests.post(f"{FASTAPI_URL}/quality-control/update-task-status", json=payload)
                if resp.status_code == 200:
                    st.success(f"✅ Tasks {tasks_to_update} approved.")
                    del st.session_state['qc_results']
                    del st.session_state['tasks_to_update']
            if col2.button("Reject Tasks"):
                payload = {"task_ids": tasks_to_update, "new_status": "rejected"}
                resp = requests.post(f"{FASTAPI_URL}/quality-control/update-task-status", json=payload)
                if resp.status_code == 200:
                    st.success(f"❌ Tasks {tasks_to_update} rejected.")
                    del st.session_state['qc_results']
                    del st.session_state['tasks_to_update']
            if col3.button("Clear Results"):
                del st.session_state['qc_results']
                del st.session_state['tasks_to_update']

    # Approve single-annotator tasks
    st.subheader("📝 Approve Single-Annotator Tasks")
    if single_tasks:
        tasks_to_approve = st.multiselect("Select tasks to approve", options=single_tasks)
        if st.button("Approve Selected Single Tasks") and tasks_to_approve:
            payload = {"task_ids": tasks_to_approve, "new_status": "approved"}
            resp = requests.post(f"{FASTAPI_URL}/quality-control/update-task-status", json=payload)
            if resp.status_code == 200:
                st.success(f"✅ Tasks {tasks_to_approve} approved.")
    else:
        st.info("No single-annotator tasks pending approval.")

    # Generate final dataset
    st.subheader("📑 Generate Final Dataset")
    output_filename = st.text_input("Output Filename", value="final_ava_dataset.csv")

    if st.button("🚀 Generate Dataset"):
        payload = {"output_filename": output_filename}
        resp = requests.post(f"{FASTAPI_URL}/quality-control/generate-dataset", json=payload)
        if resp.status_code == 200:
            download_url = resp.json().get("download_url")
            st.success("✅ Dataset generated successfully!")
            st.markdown(f"[⬇️ Download Dataset]({download_url})")
        else:
            st.error(f"❌ Error: {safe_json_or_text(resp)}")
