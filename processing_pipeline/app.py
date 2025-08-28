import streamlit as st
import os
import sys
from pathlib import Path

# Add the parent directory to the system path to allow imports from services
sys.path.append(str(Path(__file__).parent.parent))

# Import the core services
from services.cvat_integration import CVATClient, get_default_labels
from services.assignment_generator import AssignmentGenerator

# --- App Configuration ---
st.set_page_config(page_title="AVA Task Creator", layout="wide")
st.title("Automated AVA Annotation Task Creator")
st.markdown("Use this tool to create CVAT projects and tasks from prepared clip ZIP files.")

# --- Data Paths ---
DATA_PATH = Path("data/uploads")
XML_PATH = Path("data/cvat_xmls")

# --- Sidebar for CVAT Credentials ---
st.sidebar.header("CVAT Connection Settings")
cvat_host = st.sidebar.text_input("CVAT Host URL", "http://localhost:8080")
cvat_username = st.sidebar.text_input("CVAT Username")
cvat_password = st.sidebar.text_input("CVAT Password", type="password")

# --- Main Interface for Task Generation ---
st.header("1. Upload and Prepare Data")
st.info("Upload your prepared ZIP files (with frames ONLY) and corresponding XML files.")
uploaded_files = st.file_uploader("Choose ZIP files", type="zip", accept_multiple_files=True, key="zip_uploader")
uploaded_xmls = st.file_uploader("Choose XML files", type="xml", accept_multiple_files=True, key="xml_uploader")

if st.button("Save Uploaded Files"):
    os.makedirs(DATA_PATH, exist_ok=True)
    os.makedirs(XML_PATH, exist_ok=True)
    for uploaded_file in uploaded_files:
        with open(DATA_PATH / uploaded_file.name, "wb") as f:
            f.write(uploaded_file.getbuffer())
    for uploaded_xml in uploaded_xmls:
        with open(XML_PATH / uploaded_xml.name, "wb") as f:
            f.write(uploaded_xml.getbuffer())
    st.success("Successfully saved all files.")

st.header("2. Define Task Parameters")

org_slug = st.text_input("Organization Slug (optional, leave blank for personal workspace)", "")
project_name = st.text_input("Project Name", f"AVA_Project_{os.urandom(4).hex()}")
annotator_list = st.text_area("Annotators (one username per line)", "annotator1\nannotator2\nannotator3")
overlap_percentage = st.slider("Overlap Percentage", min_value=0, max_value=100, value=20, step=5)

# --- Main Task Generation Logic ---
if st.button("Generate & Upload Tasks", key="generate_button"):
    if not all([cvat_host, cvat_username, cvat_password]):
        st.error("❌ Please fill in all CVAT connection details in the sidebar.")
    else:
        with st.spinner("Connecting to CVAT..."):
            client = CVATClient(host=cvat_host, username=cvat_username, password=cvat_password)

        if not client.authenticated:
            st.error("❌ Failed to connect or authenticate. Check credentials.")
        else:
            st.success("✅ Successfully connected to CVAT!")
            try:
                all_zip_files = [f for f in os.listdir(DATA_PATH) if f.endswith('.zip')]
                if not all_zip_files:
                    st.error(f"❌ No ZIP files found in {DATA_PATH}. Please upload and save some clips.")
                    st.stop()

                annotators = [a.strip() for a in annotator_list.split('\n') if a.strip()]
                if not annotators:
                    st.error("❌ Please provide a list of annotators.")
                    st.stop()

                st.info("🧠 Generating random assignments...")
                assignment_generator = AssignmentGenerator()
                assignments = assignment_generator.generate_random_assignments(
                    clips=all_zip_files,
                    annotators=annotators,
                    overlap_percentage=overlap_percentage
                )
                st.success("✅ Assignment plan generated!")
                st.json(assignments)

                st.info("🚀 Creating project and uploading tasks to CVAT...")
                labels = get_default_labels()
                project_id = client.create_project(project_name, labels, org_slug=org_slug if org_slug else None)

                if project_id:
                    st.info(f"✅ Project '{project_name}' created with ID: {project_id}")

                    # ✨ FIX: Removed the redundant 'labels' argument from this call
                    results = client.create_tasks_from_assignments(
                        project_id=project_id,
                        assignments=assignments,
                        zip_dir=DATA_PATH,
                        xml_dir=XML_PATH
                    )

                    if results:
                        st.success(f"🎉 Process complete! Created {len(results)} tasks.")
                        st.json(results)
                    else:
                        st.error("❌ Task creation failed. No tasks were created. Check the console logs for details.")
                else:
                    st.error("❌ Failed to create project. Check the console logs for details.")

            except Exception as e:
                st.error(f"An unexpected error occurred: {e}")
                st.exception(e)