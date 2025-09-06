import streamlit as st
import requests



# ---------------- Backend API Base URL ----------------
BACKEND_URL = "http://127.0.0.1:8000"

st.title("🎬 Video Processing with Tracking & Dense Proposals")

# ---------------- Upload Video ----------------
st.header("📤 Upload Video")
uploaded_file = st.file_uploader("Choose a video file", type=["mp4", "avi", "mov"])

if uploaded_file:
    # Upload to backend
    st.info("⏳ Uploading video to server...")
    files = {"file": (uploaded_file.name, uploaded_file, "video/mp4")}
    response = requests.post(f"{BACKEND_URL}/upload_video/", files=files)

    if response.status_code == 200:
        upload_result = response.json()
        file_name = upload_result["filename"]
        st.success(f"✅ Uploaded: {file_name}")

        # ---------------- Process Video ----------------
        st.header("⚙️ Process Video")
        if st.button("Start Processing"):
            st.info("⏳ Processing video...")
            process_resp = requests.post(f"{BACKEND_URL}/process_video/", params={"file_name": file_name})

            if process_resp.status_code == 200:
                result = process_resp.json()
                st.success("🎉 Processing Complete")

                video_id = result["video_id"]
                clip_name = result["clip_name"]
                json_name = result["json_name"]

                # ---------------- Download Results ----------------
                st.header("📥 Download Results")

                st.markdown(f"[🎬 Download Video Clip]({BACKEND_URL}/download_clip/{video_id}/{clip_name})")
                st.markdown(f"[📑 Download JSON]({BACKEND_URL}/download_json/{video_id}/{json_name})")
                st.markdown(f"[🖼️ Download Frames]({BACKEND_URL}/download_frames/{video_id})")
                st.markdown(f"[📂 Download Dense Proposals]({BACKEND_URL}/download_dense_proposals/)")

            else:
                st.error(f"❌ Error in processing: {process_resp.text}")
    else:
        st.error(f"❌ Upload failed: {response.text}")
