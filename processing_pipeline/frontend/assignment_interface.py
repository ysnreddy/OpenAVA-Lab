import streamlit as st
import os
import sys
from pathlib import Path

# Add the parent directory to the system path to allow imports from services
sys.path.append(str(Path(__file__).parent.parent))

# Import the core services
from processing_pipeline.services.cvat_integration import CVATClient, get_default_labels
from processing_pipeline.services.assignment_generator import AssignmentGenerator

# --- App Configuration ---
st.set_page_config(page_title="AVA Task Creator", layout="wide")
st.title("Automated AVA Annotation Task Creator")
st.markdown("Use this tool to create CVAT projects and tasks from prepared clip ZIP files.")

# --- Data Path and Service Initialization ---
DATA_PATH = Path("data/uploads")  # Path to store uploaded ZIPs. Change as needed.

if 'client' not in st.session_state:
    st.session_state.client = None

# --- Sidebar for CVAT Credentials and Connection ---
st.sidebar.header("CVAT Connection Settings")
cvat_host = st.sidebar.text_input("CVAT Host URL", "http://localhost:8080")
cvat_username = st.sidebar.text_input("CVAT Username")
cvat_password = st.sidebar.text_input("CVAT Password", type="password")

if st.sidebar.button("Connect to CVAT"):
    st.session_state.client = CVATClient(
        host=cvat_host,
        username=cvat_username,
        password=cvat_password
    )
    if st.session_state.client.authenticated:
        st.sidebar.success("✅ Successfully connected to CVAT!")
    else:
        st.sidebar.error("❌ Failed to connect or authenticate. Check credentials.")

# --- Main Interface for Task Generation ---
st.header("1. Upload Clips")
st.info("Upload your prepared ZIP files (containing frames and annotations.xml).")
uploaded_files = st.file_uploader("Choose ZIP files", type="zip", accept_multiple_files=True)

if uploaded_files:
    if st.button("Save Uploaded Files"):
        os.makedirs(DATA_PATH, exist_ok=True)
        for uploaded_file in uploaded_files:
            file_path = DATA_PATH / uploaded_file.name
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
        st.success(f"Successfully saved {len(uploaded_files)} files to {DATA_PATH}")

st.header("2. Define Task Parameters")

project_name = st.text_input("Project Name", f"AVA_Project_{os.urandom(4).hex()}")
annotator_list = st.text_area("Annotators (one username per line)", "annotator1\nannotator2\nannotator3")
overlap_percentage = st.slider("Overlap Percentage", min_value=0, max_value=100, value=20, step=5)
# Using a fixed overlap value from the slider, not a JSON config

# --- Main Task Generation Logic ---
if st.button("Generate & Upload Tasks", key="generate_button"):
    if st.session_state.client is None or not st.session_state.client.authenticated:
        st.error("❌ Please connect to CVAT first.")
    else:
        try:
            # 1. Get a list of all available clips
            all_zip_files = [f for f in os.listdir(DATA_PATH) if f.endswith('.zip')]
            if not all_zip_files:
                st.error(f"❌ No ZIP files found in {DATA_PATH}. Please upload some clips.")
                st.stop()

            # 2. Get annotators from the text area
            annotators = [a.strip() for a in annotator_list.split('\n') if a.strip()]
            if not annotators:
                st.error("❌ Please provide a list of annotators.")
                st.stop()

            # 3. Create an assignment plan dynamically
            st.info("🧠 Generating random assignments...")
            assignment_generator = AssignmentGenerator()
            assignments = assignment_generator.generate_random_assignments(
                clips=all_zip_files,
                annotators=annotators,
                overlap_percentage=overlap_percentage
            )
            st.success("✅ Assignment plan generated!")

            st.json(assignments)  # Show the generated assignment plan

            # 4. Use CVAT Integration to create tasks
            st.info("🚀 Creating project and uploading tasks to CVAT...")
            # We pass the full labels to ensure they are correctly registered
            labels = get_default_labels()
            project_id = st.session_state.client.create_project(project_name, labels)

            if project_id:
                st.info(f"✅ Project '{project_name}' created with ID: {project_id}")

                # Create and upload tasks based on the assignment plan
                results = st.session_state.client.create_tasks_from_assignments(
                    project_id=project_id,
                    assignments=assignments,
                    zip_dir=DATA_PATH,
                    labels=labels
                )

                st.success("🎉 All tasks created and data uploaded successfully!")
                st.json(results)
            else:
                st.error("❌ Failed to create project. Check CVAT logs.")

        except Exception as e:
            st.error(f"An unexpected error occurred: {e}")
            st.exception(e)