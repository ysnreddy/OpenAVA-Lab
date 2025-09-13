# metrics_logging/metrics.py
import time
from typing import Optional, List, Dict
from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field
import sys
import os 
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from .metrics_logger import log_metric, read_all

router = APIRouter(
    prefix="/metrics",
    tags=["4. Metrics"]
)

class AnnotationEvent(BaseModel):
    project_id: int = Field(-1, description="Project ID")
    task_id: int = Field(..., description="Task ID")
    annotator: Optional[str] = Field(None, description="Annotator username or id")
    details: Optional[dict] = Field({}, description="Extra details")

class TaskCompletedEvent(BaseModel):
    project_id: int = Field(-1)
    task_id: int = Field(...)
    annotator: Optional[str] = None
    annotation_duration_seconds: Optional[float] = None  # optional client-side measured duration
    details: Optional[dict] = Field({}, description="Extra details")

@router.post("/annotation-start", summary="Record when an annotator starts working on a task")
def annotation_start(payload: AnnotationEvent):
    # log first open / start of annotation
    log_metric("annotation_start", project_id=payload.project_id, task_id=payload.task_id, annotator=payload.annotator, extra=payload.details)
    return {"message": "annotation_start logged"}

@router.post("/annotation-end", summary="Record when an annotator finishes working on a task")
def annotation_end(payload: AnnotationEvent):
    log_metric("annotation_end", project_id=payload.project_id, task_id=payload.task_id, annotator=payload.annotator, extra=payload.details)
    return {"message": "annotation_end logged"}

@router.post("/task-completed", summary="Record when a task/clip is completed by an annotator (counts as a completed clip)")
def task_completed(payload: TaskCompletedEvent):
    extra = dict(payload.details or {})
    if payload.annotation_duration_seconds is not None:
        extra["annotation_duration_seconds"] = payload.annotation_duration_seconds
    log_metric("task_completed", project_id=payload.project_id, task_id=payload.task_id, annotator=payload.annotator, extra=extra)
    return {"message": "task_completed logged"}

# -------------------------
# Simple metrics aggregation
# -------------------------
@router.get("/summary", summary="Compute metrics summary from logs")
def metrics_summary():
    """
    Returns:
      - clips_per_annotator_hour (dict: annotator -> clips/hour)
      - makespan list (per ingest/export match)
      - queue_wait list (per task if task_ready+annotation_start available)
      - ops_overhead (sum or per project: time_on_task_creation + time_on_export)
    """
    records = read_all()

    # helpers
    by_event = {}
    for r in records:
        by_event.setdefault(r["event_type"], []).append(r)

    # 1) clips_per_annotator_hour
    # We'll compute per-annotator:
    # - completed_clips = count of task_completed events
    # - active_annotation_hours = sum(annotation_end - annotation_start) where pairs exist for that task+annotator
    completed = by_event.get("task_completed", [])
    annotation_starts = by_event.get("annotation_start", [])
    annotation_ends = by_event.get("annotation_end", [])

    # build a map (project,task,annotator)->start_ts (if multiple starts, keep earliest)
    start_map = {}
    for s in annotation_starts:
        key = (s.get("project_id", -1), s.get("task_id"), s.get("annotator"))
        if key not in start_map or s["timestamp"] < start_map[key]:
            start_map[key] = s["timestamp"]

    # build end_map similarly (latest end)
    end_map = {}
    for e in annotation_ends:
        key = (e.get("project_id", -1), e.get("task_id"), e.get("annotator"))
        if key not in end_map or e["timestamp"] > end_map[key]:
            end_map[key] = e["timestamp"]

    # compute active seconds per annotator by summing (end-start) for matched keys
    active_seconds_per_annotator = {}
    for key, start_ts in start_map.items():
        end_ts = end_map.get(key)
        if end_ts and end_ts >= start_ts:
            annotator = key[2] or "unknown"
            active_seconds_per_annotator.setdefault(annotator, 0.0)
            active_seconds_per_annotator[annotator] += (end_ts - start_ts)

    completed_clips_per_annotator = {}
    for c in completed:
        annot = c.get("annotator") or "unknown"
        completed_clips_per_annotator.setdefault(annot, 0)
        completed_clips_per_annotator[annot] += 1

    clips_per_annotator_hour = {}
    for annot, clips in completed_clips_per_annotator.items():
        active_hours = (active_seconds_per_annotator.get(annot, 0.0) / 3600.0) or 0.0
        # avoid division by zero - if no active hours reported but there are completed clips, we show None
        if active_hours > 0:
            clips_per_annotator_hour[annot] = clips / active_hours
        else:
            clips_per_annotator_hour[annot] = None  # implies missing start/end data

    # 2) makespan = export_time - ingest_time (per filename if possible)
    ingest_events = by_event.get("ingest_time", [])
    export_events = by_event.get("export_time", [])

    # attempt to match by filename contained in extra.files.zips (ingest) and extra.output_file (export)
    makespans = []
    # build map filename -> ingest_ts (use earliest ingest per filename)
    ingest_by_file = {}
    for ing in ingest_events:
        extra = ing.get("extra", {}) or {}
        files = extra.get("files", {}) or {}
        zips = files.get("zips", []) if isinstance(files.get("zips", []), list) else []
        for z in zips:
            key = z.split(os.sep)[-1] if isinstance(z, str) else str(z)
            if key not in ingest_by_file or ing["timestamp"] < ingest_by_file[key]:
                ingest_by_file[key] = ing["timestamp"]

    # for each export event, try to match output_file to ingest files
    import os
    for exp in export_events:
        extra = exp.get("extra", {}) or {}
        output_file = extra.get("output_file")
        if output_file:
            # if output_file name contains a filename that matches any ingest zip name, use that
            candidate = os.path.basename(output_file)
            # if ingest_by_file has candidate (or candidate + .zip), compute makespan
            ts_ing = ingest_by_file.get(candidate)
            if not ts_ing:
                # try adding .zip
                ts_ing = ingest_by_file.get(candidate + ".zip")
            if ts_ing:
                makespans.append({
                    "project_id": exp.get("project_id", -1),
                    "output_file": output_file,
                    "makespan_seconds": exp["timestamp"] - ts_ing
                })
    # fallback: if no file matches, compute makespan as (min export - min ingest) per project
    if not makespans and ingest_events and export_events:
        min_ingest = min(i["timestamp"] for i in ingest_events)
        max_export = max(e["timestamp"] for e in export_events)
        makespans.append({
            "project_id": -1,
            "output_file": None,
            "makespan_seconds": max_export - min_ingest
        })

    # 3) queue_wait = first_annotation_start - task_ready
    queue_waits = []
    task_ready_events = by_event.get("task_ready", [])
    # build map task_ready per project/task (task_ready often has project_id + num_tasks, not per task;
    # we measure per-project queue_wait using earliest task_ready and earliest annotation_start)
    earliest_task_ready_per_project = {}
    for tr in task_ready_events:
        p = tr.get("project_id", -1)
        ts = tr["timestamp"]
        if p not in earliest_task_ready_per_project or ts < earliest_task_ready_per_project[p]:
            earliest_task_ready_per_project[p] = ts

    earliest_annotation_start_per_project = {}
    for s in annotation_starts:
        p = s.get("project_id", -1)
        ts = s["timestamp"]
        if p not in earliest_annotation_start_per_project or ts < earliest_annotation_start_per_project[p]:
            earliest_annotation_start_per_project[p] = ts

    for p, tr_ts in earliest_task_ready_per_project.items():
        start_ts = earliest_annotation_start_per_project.get(p)
        if start_ts:
            queue_waits.append({"project_id": p, "queue_wait_seconds": start_ts - tr_ts})

    # 4) ops_overhead = time_on_task_creation + time_on_export (per project if available)
    ops = []
    # collect task_ready extras time_on_task_creation by project
    for tr in task_ready_events:
        p = tr.get("project_id", -1)
        extra = tr.get("extra", {}) or {}
        ttc = extra.get("time_on_task_creation")
        if ttc:
            ops.append({"project_id": p, "time_on_task_creation": ttc})

    # collect export_time time_on_export
    for ex in export_events:
        p = ex.get("project_id", -1)
        extra = ex.get("extra", {}) or {}
        teo = extra.get("time_on_export")
        if teo:
            # attach to same project entry if exists
            ops.append({"project_id": p, "time_on_export": teo})

    # combine into per-project ops_overhead
    ops_overhead_per_project = {}
    for o in ops:
        p = o.get("project_id", -1)
        ops_overhead_per_project.setdefault(p, {"time_on_task_creation": 0.0, "time_on_export": 0.0})
        if "time_on_task_creation" in o:
            ops_overhead_per_project[p]["time_on_task_creation"] += float(o["time_on_task_creation"])
        if "time_on_export" in o:
            ops_overhead_per_project[p]["time_on_export"] += float(o["time_on_export"])

    for p, v in ops_overhead_per_project.items():
        v["ops_overhead"] = v.get("time_on_task_creation", 0.0) + v.get("time_on_export", 0.0)

    return {
        "clips_per_annotator_hour": clips_per_annotator_hour,
        "makespans": makespans,
        "queue_waits": queue_waits,
        "ops_overhead_per_project": ops_overhead_per_project
    }
