import streamlit as st
import requests
import time
from pathlib import Path
import os

# --- App Configuration ---
st.set_page_config(page_title="Video Processing Pipeline", page_icon="🚀", layout="wide")
BACKEND_URL = "http://127.0.0.1:8000"

st.title("🚀 Automated Video Pre-processing Pipeline")
st.markdown("This tool processes large video collections by reading directly from the server's upload directory.")

# --- Session State Initialization ---
if 'job_id' not in st.session_state:
    st.session_state.job_id = None
if 'job_status' not in st.session_state:
    st.session_state.job_status = None
if 'result_paths' not in st.session_state:
    st.session_state.result_paths = None

# --- UI for Selecting a Video ZIP ---
st.header("1. Select a Video ZIP to Process")

# This is a placeholder path. The backend will have the actual path.
# We'll ask the backend for a list of available files.
try:
    response = requests.get(f"{BACKEND_URL}/list_videos/")
    if response.status_code == 200:
        available_files = response.json().get("files", [])
        if not available_files:
            st.warning(
                "No video ZIP files found in the upload directory on the server. Please add files to the `uploads` folder.")
            st.stop()
    else:
        st.error("Could not connect to the backend to list available files.")
        st.stop()
except requests.exceptions.RequestException as e:
    st.error(f"Connection to backend failed: {e}")
    st.stop()

selected_file = st.selectbox(
    "Choose a ZIP file from the server's upload directory:",
    options=available_files
)

if selected_file and st.button("Start Processing Pipeline"):
    # Reset state for a new job
    st.session_state.job_id = None
    st.session_state.job_status = None
    st.session_state.result_paths = None

    with st.spinner("Starting job on the backend..."):
        try:
            # Send the FILENAME to the backend, not the file itself
            payload = {"filename": selected_file}
            response = requests.post(f"{BACKEND_URL}/start_processing/", json=payload, timeout=30)

            if response.status_code == 200:
                job_data = response.json()
                st.session_state.job_id = job_data.get("job_id")
                st.success(f"✅ Job started successfully! Job ID: `{st.session_state.job_id}`")
                st.info("The process is running in the background. This page will now poll for status updates.")
            else:
                st.error(f"Failed to start job: {response.status_code} - {response.text}")
        except requests.exceptions.RequestException as e:
            st.error(f"Connection to backend failed: {e}")

# --- UI for Checking Job Status ---
if st.session_state.job_id:
    st.header("2. Processing Status")

    status_placeholder = st.empty()
    progress_bar = st.progress(0, "Pending...")

    status_map = {
        "pending": (0, "Pending..."),
        "unzipping": (5, "Step 1/7: Unzipping master file..."),
        "resizing": (10, "Step 2/7: Renaming and Resizing Videos..."),
        "clipping": (30, "Step 3/7: Clipping Videos..."),
        "extracting_frames": (50, "Step 4/7: Extracting Frames..."),
        "tracking": (70, "Step 5/7: Running Person Tracking..."),
        "generating_proposals": (90, "Step 6/7: Generating Dense Proposals..."),
        "packaging": (95, "Step 7/7: Packaging Final Outputs..."),
        "completed": (100, "✅ Processing Complete!"),
        "failed": (100, "❌ Processing Failed.")
    }

    while st.session_state.job_status not in ["completed", "failed"]:
        try:
            status_response = requests.get(f"{BACKEND_URL}/status/{st.session_state.job_id}")
            if status_response.status_code == 200:
                status_data = status_response.json()
                st.session_state.job_status = status_data.get("status")

                progress_value, progress_text = status_map.get(st.session_state.job_status, (0, "Unknown state..."))

                status_placeholder.info(f"**Current Status:** {st.session_state.job_status}")
                progress_bar.progress(progress_value, text=progress_text)

                if st.session_state.job_status == "failed":
                    st.error(f"Error details: {status_data.get('error')}")
                    break
                if st.session_state.job_status == "completed":
                    st.session_state.result_paths = status_data.get('result_paths')
                    break

                time.sleep(5)  # Poll every 5 seconds
            else:
                st.error("Could not get job status from backend.")
                break
        except requests.exceptions.RequestException:
            st.error("Connection to backend lost. Will retry...")
            time.sleep(10)

    if st.session_state.job_status == "completed":
        st.header("3. Download Final Outputs")
        st.success("Your files are ready for download.")

        if st.session_state.result_paths:
            job_id = st.session_state.job_id

            proposals_url = f"{BACKEND_URL}/download/{job_id}/proposals_pkl"
            frames_url = f"{BACKEND_URL}/download/{job_id}/frames_zip"

            st.markdown(f"**📦 [Download dense_proposals.pkl]({proposals_url})**")
            st.markdown(f"**🖼️ [Download frames.zip]({frames_url})**")

