# metrics_logging/metrics_logger.py
import logging
import time
from pathlib import Path
import json
from typing import Optional, Dict, Any, List
import os
import sys
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

logger = logging.getLogger("metrics")
logger.setLevel(logging.INFO)

METRICS_LOG_FILE = Path("data/metrics_log.jsonl")
METRICS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

def _now() -> float:
    return time.time()

def log_metric(event_type: str,
               project_id: int = -1,
               task_id: Optional[int] = None,
               annotator: Optional[str] = None,
               extra: Optional[Dict[str, Any]] = None) -> None:
    """
    Append a metric event as a JSON line.
    event_type examples: ingest_time, task_ready, export_time,
                        annotation_start, annotation_end, task_completed
    extra: free-form dictionary (e.g. {"files": [...], "time_on_task_creation": 2.3})
    """
    record = {
        "timestamp": _now(),
        "event_type": event_type,
        "project_id": project_id,
        "task_id": task_id,
        "annotator": annotator,
        "extra": extra or {}
    }
    try:
        with open(METRICS_LOG_FILE, "a") as f:
            f.write(json.dumps(record) + "\n")
        logger.info(f"[METRIC] {event_type} project={project_id} task={task_id} annotator={annotator} extra_keys={list((extra or {}).keys())}")
    except Exception as e:
        logger.exception("Failed to write metric record: %s", e)

def read_all() -> List[Dict]:
    """Return all metric records from the JSONL file (may be large)."""
    records = []
    if not METRICS_LOG_FILE.exists():
        return records
    with open(METRICS_LOG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                logger.exception("Skipping malformed metric line: %s", line[:200])
    return records
