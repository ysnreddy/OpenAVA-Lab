# # webhook_listener.py
# from flask import Flask, request, jsonify
# import subprocess
# import json
# import logging

# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# logger = logging.getLogger(__name__)

# app = Flask(__name__)


# @app.route('/webhook', methods=['POST'])
# def cvat_webhook():
#     """
#     This endpoint receives webhook notifications from CVAT.
#     """
#     if request.is_json:
#         payload = request.get_json()
#         logger.info(f"Received webhook payload: {json.dumps(payload, indent=2)}")

#         event = payload.get("event")
#         job_status = payload.get("job", {}).get("state")
#         project_id = payload.get("job", {}).get("project_id")

#         # Check if the event is a job update and the new status is 'completed'
#         if event == "update:job" and job_status == "completed":
#             logger.info(
#                 f"✅ Job {payload['job']['id']} completed. Triggering post-annotation service for project {project_id}...")

#             # Trigger the post_annotation_service.py script as a background process
#             # This ensures the webhook returns a response quickly
#             try:
#                 subprocess.Popen(
#                                 ["python", "processing_pipeline/services/post_annotation_service.py",
#                                 "--project-id", str(project_id),
#                                 "--task-id", str(payload["job"]["task_id"]),
#                                 "--assignee", payload["job"].get("assignee", {}).get("username", "N/A")],
#                                 stdout=subprocess.DEVNULL,
#                                 stderr=subprocess.DEVNULL,
#                                 shell=True  # <-- useful on Windows
#                             )

#                 return jsonify({"status": "success", "message": "Post-annotation service triggered."}), 200
#             except Exception as e:
#                 logger.error(f"Failed to trigger post-annotation service: {e}")
#                 return jsonify({"status": "error", "message": "Failed to trigger service."}), 500

#         return jsonify({"status": "ignored", "message": "Event was not a job completion."}), 200
#     else:
#         return jsonify({"status": "error", "message": "Request must be JSON."}), 400


# if __name__ == '__main__':
#     # Make sure to run on host 0.0.0.0 to be accessible from Docker
#     app.run(host='0.0.0.0', port=5001, debug=True)



# webhook_listener.py
# webhook_listener.py
# webhook_listener.py
# webhook_listener.py (FIXED VERSION)
from flask import Flask, request, jsonify
import subprocess
import json
import logging
import os
import sys

# Ensure parent directory is in sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import the metrics logger
try:
    from metrics_logging.metrics_logger import log_metric
    print("✅ Successfully imported log_metric")
except ImportError as e:
    print(f"❌ Failed to import log_metric: {e}")
    # Create a dummy function for testing
    def log_metric(*args, **kwargs):
        print(f"DUMMY LOG_METRIC: {args}, {kwargs}")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def cvat_webhook():
    """
    This endpoint receives webhook notifications from CVAT.
    """
    if not request.is_json:
        return jsonify({"status": "error", "message": "Request must be JSON."}), 400

    payload = request.get_json()
    logger.info(f"🔔 Received webhook payload: {json.dumps(payload, indent=2)}")

    event = payload.get("event")
    
    # Handle different payload structures
    job = payload.get("job", {})
    task = payload.get("task", {})
    
    # Extract job information
    job_id = job.get("id")
    job_status = job.get("state")
    project_id = job.get("project_id") or task.get("project_id")
    task_id = job.get("task_id") or task.get("id")
    
    # Get assignee information
    assignee_info = job.get("assignee") or task.get("assignee")
    assignee = assignee_info.get("username") if assignee_info else "N/A"
    
    created_date = job.get("created_date") or task.get("created_date") or ""
    updated_date = job.get("updated_date") or task.get("updated_date") or ""

    logger.info(f"📊 Event: {event}, Job: {job_id}, Status: {job_status}, Assignee: {assignee}, Project: {project_id}, Task: {task_id}")

    # CRITICAL: Log annotation_start when job becomes "in progress"
    if event == "update:job" and job_status == "in progress":
        logger.info(f"🚀 Job {job_id} started by {assignee}")
        try:
            log_metric(
                "annotation_start",
                project_id=project_id,
                task_id=task_id,
                annotator=assignee,
                extra={"job_id": job_id, "started_at": updated_date}
            )
            logger.info(f"✅ Logged annotation_start for job {job_id}")
        except Exception as e:
            logger.error(f"❌ Failed to log annotation_start: {e}")

    # Log annotation completion when job is completed
    elif event == "update:job" and job_status == "completed":
        logger.info(f"✅ Job {job_id} completed by {assignee}")
        
        try:
            # Log annotation end
            log_metric(
                "annotation_end",
                project_id=project_id,
                task_id=task_id,
                annotator=assignee,
                extra={"job_id": job_id, "completed_at": updated_date}
            )
            logger.info(f"✅ Logged annotation_end for job {job_id}")
            
            # Log task completion
            log_metric(
                "task_completed",
                project_id=project_id,
                task_id=task_id,
                annotator=assignee,
                extra={
                    "job_id": job_id,
                    "created_date": created_date,
                    "updated_date": updated_date
                }
            )
            logger.info(f"✅ Logged task_completed for job {job_id}")
        except Exception as e:
            logger.error(f"❌ Failed to log completion metrics: {e}")

        # Trigger post-annotation service
        try:
            script_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "services", "post_annotation_service.py")
            )

            if not os.path.exists(script_path):
                # Try alternative path
                script_path = os.path.abspath(
                    os.path.join(os.path.dirname(__file__), "..", "metrics_logging", "post_annotation_service.py")
                )

            if not os.path.exists(script_path):
                logger.error(f"post_annotation_service.py not found at {script_path}")
                return jsonify({"status": "error", "message": "Script not found."}), 500

            cmd = [
                sys.executable,
                script_path,
                "--project-id", str(project_id),
            ]

            logger.info(f"🚀 Running command: {' '.join(cmd)}")

            subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )

            return jsonify({"status": "success", "message": "Post-annotation service triggered."}), 200

        except Exception as e:
            logger.error(f"Failed to trigger post-annotation service: {e}")
            return jsonify({"status": "error", "message": "Failed to trigger service."}), 500

    # Log other events for debugging
    elif event == "create:job":
        logger.info(f"🆕 New job {job_id} created and assigned to {assignee}")
    elif event == "update:job":
        logger.info(f"🔄 Job {job_id} status changed to '{job_status}' by {assignee}")
    elif event == "create:task":
        logger.info(f"🆕 New task {task_id} created")
    elif event == "update:task":
        logger.info(f"🔄 Task {task_id} updated")
    else:
        logger.info(f"ℹ️  Received event: {event}")

    return jsonify({"status": "received", "message": f"Webhook processed: {event}"}), 200


@app.route("/test", methods=["GET"])
def test_webhook():
    """Test endpoint to verify the webhook service is running."""
    return jsonify({"status": "ok", "message": "Webhook listener is running"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)