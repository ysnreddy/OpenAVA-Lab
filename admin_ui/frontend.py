import streamlit as st
import requests

# ---------------- Streamlit Page Config ----------------
st.set_page_config(page_title="🎥 Video Processing App", page_icon="🎬", layout="wide")

BACKEND_URL = "http://127.0.0.1:8000"

st.title("🎬 Video Processing with Tracking & Dense Proposals")

# ---------------- Upload Video ----------------
st.header("📤 Upload Video")
uploaded_file = st.file_uploader("Choose a video file", type=["mp4", "avi", "mov"])

if uploaded_file:
    st.info("⏳ Uploading video to server...")
    files = {"file": (uploaded_file.name, uploaded_file, "video/mp4")}
    response = requests.post(f"{BACKEND_URL}/upload_video/", files=files)

    if response.status_code == 200:
        file_name = response.json()["filename"]
        st.success(f"✅ Uploaded: {file_name}")

        st.header("⚙️ Process Video")
        if st.button("Start Processing"):
            st.info("⏳ Processing video...")
            process_resp = requests.post(f"{BACKEND_URL}/process_video/", params={"file_name": file_name})

            if process_resp.status_code == 200:
                result = process_resp.json()
                st.success("🎉 Processing Complete")

                created_zips = result.get("created_zips", [])
                st.header("📥 Download Results")
                if created_zips:
                    for zip_name in created_zips:
                        st.markdown(f"[📦 Download {zip_name}]({BACKEND_URL}/static/{zip_name})")
                else:
                    st.warning("⚠️ No zip files were created.")
            else:
                st.error(f"❌ Error in processing: {process_resp.text}")
    else:
        st.error(f"❌ Upload failed: {response.text}")
