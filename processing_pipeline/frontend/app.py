# streamlit_cvat.py
import streamlit as st
import requests

st.set_page_config(page_title="CVAT Pre-annotation Tool", layout="centered")

st.title("CVAT Pre-annotation Tool 📦")
st.write("Upload a dense_proposals.pkl and frames.zip folder to generate CVAT ZIP archives.")

# Upload files
pickle_file = st.file_uploader("Upload dense_proposals.pkl", type="pkl")
frames_zip_file = st.file_uploader("Upload frames.zip", type="zip")

if st.button("Generate CVAT ZIP"):
    if not pickle_file or not frames_zip_file:
        st.error("Please upload both pickle and frames zip files.")
    else:
        st.info("Processing... This may take a few minutes depending on the number of frames.")

        try:
            # Send files to FastAPI
            files = {
                "pickle_file": (pickle_file.name, pickle_file.getvalue(), "application/octet-stream"),
                "frames_zip": (frames_zip_file.name, frames_zip_file.getvalue(), "application/zip"),
            }

            response = requests.post("http://localhost:8000/process_clips/", files=files)

            if response.status_code == 200:
                st.success("🎉 CVAT ZIP generated successfully!")
                st.download_button(
                    label="Download CVAT Packages",
                    data=response.content,
                    file_name="cvat_packages.zip",
                    mime="application/zip"
                )
            else:
                st.error(f"Error: Server returned status code {response.status_code}")
                st.json(response.json())
        except requests.exceptions.ConnectionError:
            st.error("❌ Could not connect to FastAPI backend. Make sure it is running at http://localhost:8000")
        except Exception as e:
            st.error(f"Unexpected error: {e}")
