import logging
import time
from pathlib import Path
import json
from typing import Optional, Dict, Any, List, Set, Tuple
import os
logger = logging.getLogger("metrics")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# ---------------- Metrics Directory ----------------
METRICS_DIR = Path("data/metrics")
METRICS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------- Track Seen Events ----------------
_seen_events: Set[Tuple[int, Optional[int], str, Optional[str], str, int]] = set()

# ---------------- Utilities ----------------
def _now() -> float:
    """Return current timestamp in seconds since epoch."""
    return time.time()

def _get_project_file(project_id: int) -> Path:
    """Return the per-project metrics JSONL file path."""
    return METRICS_DIR / f"{project_id}_metrics.jsonl"

# ---------------- S3 Archival Utility ----------------
def sync_metrics_to_s3(s3_client: Any, bucket_name: str, s3_prefix: str = "metrics_archive/") -> List[str]:
    """
    Archives all local JSONL metric files to S3.
    Requires a configured boto3 S3 client and bucket name.
    """
    if not s3_client or not bucket_name:
        logger.error("Cannot sync metrics: S3 client or bucket name is missing.")
        return []

    synced_files = []
    for metrics_file in METRICS_DIR.glob("*_metrics.jsonl"):
        local_path = str(metrics_file)
        s3_key = f"{s3_prefix}{metrics_file.name}"
        
        try:
            s3_client.upload_file(local_path, bucket_name, s3_key)
            
            # Optional: Delete the local file after successful upload to prevent re-uploading,
            # or rename it to indicate it's been archived (e.g., .archived).
            # We'll just log it for now, assuming the aggregation still needs it.
            # If aggregation is slow, consider moving the read logic to S3.
            
            synced_files.append(s3_key)
            logger.info(f"💾 Synced local metric file {metrics_file.name} to S3: {s3_key}")
            
        except Exception as e:
            logger.exception(f"Failed to upload {metrics_file.name} to S3: {e}")

    return synced_files

def log_metric(
    event_type: str,
    project_id: int = -1,
    task_id: Optional[int] = None,
    annotator: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None
) -> None:
    extra = extra or {}
    extra_str = json.dumps(extra, sort_keys=True)

    time_bucket = int(_now() // 5)
    key = (project_id, task_id, event_type, annotator, hash(extra_str), time_bucket) 
    if key in _seen_events:
        logger.info(f"[SKIP] Duplicate metric: {key}")
        return
    _seen_events.add(key)

    
    record = {
        "timestamp": _now(),
        "event_type": event_type,
        "project_id": project_id,
        "task_id": task_id,
        "annotator": annotator,
        "extra": extra
    }

    metrics_file = _get_project_file(project_id)
    try:
        with open(metrics_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(f"[METRIC] {event_type} project={project_id} task={task_id} annotator={annotator}")
    except Exception as e:
        logger.exception("Failed to write metric record: %s", e)

def read_by_project(project_id: int) -> List[Dict[str, Any]]:
    """Read all metric records for a specific project."""
    metrics_file = _get_project_file(project_id)
    records: List[Dict[str, Any]] = []
    if not metrics_file.exists():
        return records
    try:
        with open(metrics_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.exception("Skipping malformed metric line: %s", line[:200])
    except Exception as e:
        logger.exception("Failed to read metrics file: %s", e)
    return records

def read_all() -> List[Dict[str, Any]]:
    """Read all metric records from all projects."""
    records: List[Dict[str, Any]] = []
    for metrics_file in METRICS_DIR.glob("*_metrics.jsonl"):
        try:
            with open(metrics_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        logger.exception("Skipping malformed metric line: %s", line[:200])
        except Exception as e:
            logger.exception("Failed to read metrics file: %s", e)
    return records