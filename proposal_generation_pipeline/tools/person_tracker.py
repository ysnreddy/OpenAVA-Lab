# In tools/person_tracker.py

import os
import cv2
import json
import torch
import numpy as np
from rfdetr import RFDETRMedium
from tqdm import tqdm
import logging
from argparse import Namespace

from .byte_tracker import BYTETracker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PersonTracker:
    def __init__(self, video_id: str, conf=0.5, person_class_id=1):  # Defaulting person_class_id to 1 as a safer bet
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = RFDETRMedium(device=self.device)
        self.model.optimize_for_inference()
        self.conf = conf
        self.person_class_id = person_class_id
        self.video_id = video_id

        tracker_args = Namespace(
            track_thresh=0.5,
            track_buffer=75,
            match_thresh=0.8,
            mot20=False
        )

        self.tracker = BYTETracker(tracker_args, frame_rate=30)

    def _parse_detections(self, dets):
        if hasattr(dets, 'xyxy'):
            boxes, scores, labels = dets.xyxy, dets.confidence, dets.class_id
        elif isinstance(dets, (list, tuple)) and len(dets) == 3:
            boxes, scores, labels = dets
        else:
            # Add a fallback for empty or unexpected formats
            return np.empty((0, 5))

        if torch.is_tensor(boxes): boxes = boxes.cpu().numpy()
        if torch.is_tensor(scores): scores = scores.cpu().numpy()
        if torch.is_tensor(labels): labels = labels.cpu().numpy()

        boxes, scores, labels = np.array(boxes), np.array(scores), np.array(labels)
        if labels.size == 0:
            return np.empty((0, 5))

        mask = (labels == self.person_class_id) & (scores >= self.conf)

        person_boxes = boxes[mask]
        person_scores = scores[mask]

        if len(person_boxes) == 0:
            return np.empty((0, 5))

        return np.hstack((person_boxes, person_scores[:, np.newaxis]))

    # FIX: Renamed `sample_rate` to `output_fps` to be more explicit. Default is 1 FPS.
    def process_video(self, video_path: str, output_json_dir: str, output_frame_dir: str, output_fps=1):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Cannot open video: {video_path}")
            return None

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        if video_fps == 0: video_fps = 30

        # Calculate how many frames to skip to achieve the target output_fps
        frame_save_interval = max(1, round(video_fps / output_fps))

        all_detections_data = []
        saved_frame_idx = 0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # NEW LOGIC: We loop through every single frame
        for frame_count in tqdm(range(total_frames), desc=f"Tracking {os.path.basename(video_path)}"):
            ret, frame = cap.read()
            if not ret: break

            # --- STEP 1: ALWAYS track on the current frame for maximum accuracy ---
            raw_detections = self.model.predict(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), threshold=self.conf)
            detections = self._parse_detections(raw_detections)
            frame_shape = [frame.shape[0], frame.shape[1]]
            online_tracks = self.tracker.update(detections, frame_shape, frame_shape)

            # --- STEP 2: ONLY save the frame and data at the desired interval ---
            if frame_count % frame_save_interval == 0:
                frame_name = f"{self.video_id}_frame_{saved_frame_idx:04d}.jpg"
                frame_save_path = os.path.join(output_frame_dir, frame_name)
                cv2.imwrite(frame_save_path, frame)

                # Append the tracking data for this specific saved frame
                for track in online_tracks:
                    bbox = track.tlbr
                    track_id = track.track_id

                    all_detections_data.append({
                        "video_id": self.video_id,
                        "frame": frame_name,
                        "track_id": int(track_id),
                        "bbox": [float(c) for c in bbox]
                    })
                saved_frame_idx += 1

        cap.release()

        json_output_path = os.path.join(output_json_dir, f"{self.video_id}.json")
        with open(json_output_path, "w") as f:
            json.dump(all_detections_data, f, indent=2)

        logger.info(f"✅ Tracking complete for {self.video_id}. JSON saved.")
        return json_output_path