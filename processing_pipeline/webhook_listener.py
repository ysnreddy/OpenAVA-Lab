# webhook_listener.py
from flask import Flask, request, jsonify
import subprocess
import json
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)


@app.route('/webhook', methods=['POST'])
def cvat_webhook():
    """
    This endpoint receives webhook notifications from CVAT.
    """
    if request.is_json:
        payload = request.get_json()
        logger.info(f"Received webhook payload: {json.dumps(payload, indent=2)}")

        event = payload.get("event")
        job_status = payload.get("job", {}).get("state")
        project_id = payload.get("job", {}).get("project_id")

        # Check if the event is a job update and the new status is 'completed'
        if event == "update:job" and job_status == "completed":
            logger.info(
                f"✅ Job {payload['job']['id']} completed. Triggering post-annotation service for project {project_id}...")

            # Trigger the post_annotation_service.py script as a background process
            # This ensures the webhook returns a response quickly
            try:
                subprocess.Popen(
                    ["python", "services/post_annotation_service.py", "--project-id", str(project_id)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                return jsonify({"status": "success", "message": "Post-annotation service triggered."}), 200
            except Exception as e:
                logger.error(f"Failed to trigger post-annotation service: {e}")
                return jsonify({"status": "error", "message": "Failed to trigger service."}), 500

        return jsonify({"status": "ignored", "message": "Event was not a job completion."}), 200
    else:
        return jsonify({"status": "error", "message": "Request must be JSON."}), 400


if __name__ == '__main__':
    # Make sure to run on host 0.0.0.0 to be accessible from Docker
    app.run(host='0.0.0.0', port=5001, debug=True)