# routers/metrics.py

import os
from fastapi import APIRouter, Query, Request, HTTPException
from typing import Optional, Dict
import boto3 # Used for clarity, actual client comes from request.app.state
import logging

# Assuming the logger and utility imports are correct relative to the new structure
from .metrics_logger import read_all, read_by_project, sync_metrics_to_s3 # NEW import

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/metrics",
    tags=["4. Metrics"]
)

@router.get("/summary", summary="Compute metrics summary from logs")
def metrics_summary(project_id: Optional[int] = Query(None)):
    """
    Computes and returns a summary of operational and annotation metrics.
    """
    # 🔹 Load records filtered by project if project_id is provided
    if project_id is not None:
        records = read_by_project(project_id)
        logger.info(f"Loaded {len(records)} records for project {project_id}.")
    else:
        records = read_all()
        logger.info(f"Loaded {len(records)} total records.")

    # helpers
    by_event = {}
    for r in records:
        by_event.setdefault(r["event_type"], []).append(r)

    # --------------------
    # Clips per annotator
    # --------------------
    completed = by_event.get("task_completed", []) + by_event.get("job_completed", [])
    annotation_starts = by_event.get("annotation_start", [])
    annotation_ends = by_event.get("annotation_end", [])

    # DEDUPLICATION: Remove duplicate tasks
    seen_tasks = set()
    deduplicated_completed = []
    for c in completed:
        task_key = (c.get("project_id"), c.get("task_id"), c.get("annotator"))
        if task_key not in seen_tasks:
            seen_tasks.add(task_key)
            deduplicated_completed.append(c)
    completed = deduplicated_completed

    # build start_map (earliest start per project/task/annotator)
    start_map = {}
    for s in annotation_starts:
        key = (s.get("project_id", -1), s.get("task_id"), s.get("annotator"))
        if key not in start_map or s["timestamp"] < start_map[key]:
            start_map[key] = s["timestamp"]

    # build end_map (latest end per project/task/annotator)
    end_map = {}
    for e in annotation_ends:
        key = (e.get("project_id", -1), e.get("task_id"), e.get("annotator"))
        if key not in end_map or e["timestamp"] > end_map[key]:
            end_map[key] = e["timestamp"]

    active_seconds_per_annotator = {}
    for key, start_ts in start_map.items():
        end_ts = end_map.get(key)
        if end_ts and end_ts >= start_ts:
            annotator = key[2] or "unknown"
            active_seconds_per_annotator.setdefault(annotator, 0.0)
            active_seconds_per_annotator[annotator] += (end_ts - start_ts)

    # Count actual clips using annotation_count from extra data
    completed_clips_per_annotator = {}
    for c in completed:
        annot = c.get("annotator") or "unknown"
        extra = c.get("extra", {}) or {}
        clip_count = extra.get("annotation_count", 1)  # Default to 1 if not specified
        completed_clips_per_annotator.setdefault(annot, 0)
        completed_clips_per_annotator[annot] += clip_count

    clips_per_annotator_hour = {}
    for annot, clips in completed_clips_per_annotator.items():
        active_hours = (active_seconds_per_annotator.get(annot, 0.0) / 3600.0) or 0.0
        clips_per_annotator_hour[annot] = clips / active_hours if active_hours > 0 else None

    # --------------------
    # Makespan
    # --------------------
    ingest_events = by_event.get("ingest_time", [])
    export_events = by_event.get("export_time", [])
    makespans = []

    ingest_by_file = {}
    for ing in ingest_events:
        extra = ing.get("extra", {}) or {}
        files = extra.get("files", {}) or {}
        zips = files.get("zips", []) if isinstance(files.get("zips", []), list) else []
        for z in zips:
            key = os.path.basename(z) if isinstance(z, str) else str(z)
            if key not in ingest_by_file or ing["timestamp"] < ingest_by_file[key]:
                ingest_by_file[key] = ing["timestamp"]

    for exp in export_events:
        extra = exp.get("extra", {}) or {}
        output_file = extra.get("output_file")
        if output_file:
            candidate = os.path.basename(output_file)
            ts_ing = ingest_by_file.get(candidate) or ingest_by_file.get(candidate + ".zip")
            if ts_ing:
                makespans.append({
                    "project_id": exp.get("project_id", -1),
                    "output_file": output_file,
                    "makespan_seconds": exp["timestamp"] - ts_ing
                })

    # Fallback: Pipeline-wide makespan if no per-file matches found
    if not makespans and ingest_events and export_events:
        min_ingest = min(i["timestamp"] for i in ingest_events)
        max_export = max(e["timestamp"] for e in export_events)
        makespans.append({
            "project_id": project_id if project_id is not None else -1,
            "output_file": None,
            "makespan_seconds": max_export - min_ingest
        })

    # --------------------
    # Queue waits
    # --------------------
    queue_waits_summary = {}
    task_ready_events = by_event.get("task_ready", [])
    earliest_task_ready_per_task = {}
    earliest_annotation_start_per_task = {}

    for tr in task_ready_events:
        task_id = tr.get("task_id")
        if task_id:
            ts = tr["timestamp"]
            if task_id not in earliest_task_ready_per_task or ts < earliest_task_ready_per_task[task_id]:
                earliest_task_ready_per_task[task_id] = ts

    for s in annotation_starts:
        task_id = s.get("task_id")
        if task_id:
            ts = s["timestamp"]
            if task_id not in earliest_annotation_start_per_task or ts < earliest_annotation_start_per_task[task_id]:
                earliest_annotation_start_per_task[task_id] = ts

    for task_id, ready_ts in earliest_task_ready_per_task.items():
        start_ts = earliest_annotation_start_per_task.get(task_id)
        if start_ts and ready_ts is not None:
             queue_waits_summary[task_id] = start_ts - ready_ts

    # --------------------
    # Ops overhead per project
    # --------------------
    ops_overhead_per_project = {}
    for tr in task_ready_events:
        p = tr.get("project_id", -1)
        extra = tr.get("extra", {}) or {}
        ttc = extra.get("time_on_task_creation", 0)
        ops_overhead_per_project.setdefault(p, {"time_on_task_creation": 0.0, "time_on_export": 0.0})
        ops_overhead_per_project[p]["time_on_task_creation"] += float(ttc)

    for ex in export_events:
        p = ex.get("project_id", -1)
        extra = ex.get("extra", {}) or {}
        teo = extra.get("time_on_export", 0)
        ops_overhead_per_project.setdefault(p, {"time_on_task_creation": 0.0, "time_on_export": 0.0})
        ops_overhead_per_project[p]["time_on_export"] += float(teo)

    for p, v in ops_overhead_per_project.items():
        v["ops_overhead"] = v.get("time_on_task_creation", 0.0) + v.get("time_on_export", 0.0)

    # --------------------
    # Task-level detailed metrics (deduped)
    # --------------------
    tasks = []
    for c in completed:
        task_id = c.get("task_id")
        proj_id = c.get("project_id", -1)
        annotator = c.get("annotator")
        extra = c.get("extra", {}) or {}
        start_ts = start_map.get((proj_id, task_id, annotator))
        end_ts = end_map.get((proj_id, task_id, annotator))
        
        # Use annotation_duration_seconds from extra if available, otherwise calculate
        annotation_duration_seconds = extra.get("duration_seconds")
        if annotation_duration_seconds is None and start_ts and end_ts:
            annotation_duration_seconds = end_ts - start_ts

        tasks.append({
            "project_id": proj_id,
            "task_id": task_id,
            "annotator": annotator,
            "annotation_duration_seconds": annotation_duration_seconds,
            "clips_per_hour": clips_per_annotator_hour.get(annotator),
            "queue_wait_seconds": queue_waits_summary.get(task_id),
            "ops_overhead": ops_overhead_per_project.get(proj_id, {}).get("ops_overhead"),
            "extra": extra
        })

    return {
        "tasks": tasks,
        "makespans": makespans,
        "clips_per_annotator_hour": clips_per_annotator_hour,
        "queue_waits_summary": queue_waits_summary,
        "ops_overhead_per_project": ops_overhead_per_project
    }

# --------------------
# NEW S3 SYNC ENDPOINT
# --------------------
@router.post("/sync-s3", summary="Manually sync local metrics files to S3")
def sync_metrics_to_s3_endpoint(request: Request):
    """
    Triggers the synchronization of all local metrics JSONL files to S3 for durable storage.
    Requires S3 client and bucket name to be configured in app state.
    """
    try:
        s3_client = request.app.state.s3_client
        s3_bucket = request.app.state.s3_bucket
    except AttributeError:
        raise HTTPException(status_code=500, detail="S3 client is not configured in application state.")
    
    synced_files = sync_metrics_to_s3(s3_client, s3_bucket)

    if not synced_files:
        return {"message": "No new metric files found to sync or S3 sync failed.", "files_synced": 0}

    return {
        "message": f"Successfully synced {len(synced_files)} metric files to S3.",
        "files_synced": len(synced_files),
        "keys": synced_files
    }