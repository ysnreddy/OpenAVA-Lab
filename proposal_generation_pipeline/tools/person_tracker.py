import os
import cv2
import json
import torch
import numpy as np
from rfdetr import RFDETRMedium
from tqdm import tqdm
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ------------------- Kalman Filter and Tracker Implementation -------------------
class KalmanFilter:
    def __init__(self):
        self.ndim = 8;
        self.F = np.eye(self.ndim)
        for i in range(self.ndim // 2): self.F[i, i + 4] = 1
        self.H = np.eye(4, self.ndim);
        self.P = np.eye(self.ndim) * 10
        self.P[4:, 4:] *= 1000;
        self.Q = np.eye(self.ndim)
        self.Q[4:, 4:] *= 0.01;
        self.R = np.eye(4) * 0.1
        self.x = np.zeros((self.ndim, 1));
        self.is_initialized = False

    def predict(self):
        self.x = self.F @ self.x;
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x

    def update(self, z):
        if not self.is_initialized:
            self.x[:4] = z;
            self.is_initialized = True;
            return
        y = z - self.H @ self.x;
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S);
        self.x += K @ y
        self.P = (np.eye(self.ndim) - K @ self.H) @ self.P

    @staticmethod
    def bbox_to_z(bbox):
        w = bbox[2] - bbox[0];
        h = bbox[3] - bbox[1]
        return np.array([bbox[0] + w / 2, bbox[1] + h / 2, w / h if h > 0 else 0, h]).reshape(4, 1)

    def z_to_bbox(self, z=None):
        if z is None: z = self.x
        h = z[3, 0];
        w = z[2, 0] * h;
        x_center = z[0, 0];
        y_center = z[1, 0]
        return [x_center - w / 2, y_center - h / 2, x_center + w / 2, y_center + h / 2]


class KalmanTrack:
    track_id_counter = 0

    def __init__(self, bbox, score):
        self.track_id = KalmanTrack.track_id_counter;
        KalmanTrack.track_id_counter += 1
        self.score = score;
        self.kf = KalmanFilter()
        self.kf.update(KalmanFilter.bbox_to_z(bbox));
        self.bbox = self.kf.z_to_bbox()
        self.hits = 1;
        self.age = 1;
        self.time_since_update = 0

    def update(self, bbox, score):
        self.kf.update(KalmanFilter.bbox_to_z(bbox));
        self.bbox = self.kf.z_to_bbox()
        self.score = score;
        self.time_since_update = 0;
        self.hits += 1

    def predict(self):
        self.kf.predict();
        self.bbox = self.kf.z_to_bbox()
        self.age += 1;
        self.time_since_update += 1
        return self.bbox


class KalmanSORTTracker:
    # ✨ FIX: Increased max_age for better handling of occlusions in CCTV footage.
    def __init__(self, track_thresh=0.5, match_thresh=0.3, max_age=75, min_hits=5):
        self.track_thresh = track_thresh;
        self.match_thresh = match_thresh
        self.max_age = max_age;
        self.min_hits = min_hits;
        self.tracks = []
        KalmanTrack.track_id_counter = 0

    def update(self, detections):
        high_conf_dets = [det for det in detections if det[4] >= self.track_thresh]
        for track in self.tracks: track.predict()
        matched, unmatched_dets, _ = self._match(high_conf_dets)
        for t_idx, d_idx in matched: self.tracks[t_idx].update(high_conf_dets[d_idx][:4], high_conf_dets[d_idx][4])
        for d_idx in unmatched_dets: self.tracks.append(
            KalmanTrack(high_conf_dets[d_idx][:4], high_conf_dets[d_idx][4]))
        active, remaining = [], []
        for track in self.tracks:
            if track.time_since_update == 0 and track.hits >= self.min_hits: active.append(track)
            if track.time_since_update <= self.max_age: remaining.append(track)
        self.tracks = remaining
        return active

    def _match(self, detections):
        if not self.tracks or not detections: return [], list(range(len(detections))), list(range(len(self.tracks)))
        track_bboxes = [t.bbox for t in self.tracks];
        det_bboxes = [d[:4] for d in detections]
        iou_matrix = self._calculate_iou_matrix(track_bboxes, det_bboxes)
        matched, unmatched_dets, unmatched_tracks = [], list(range(len(detections))), list(range(len(self.tracks)))
        for t_idx, _ in enumerate(self.tracks):
            if not unmatched_dets: break
            iou_row = iou_matrix[t_idx, unmatched_dets]
            if len(iou_row) == 0: continue
            best_local_idx = np.argmax(iou_row)
            if iou_row[best_local_idx] >= self.match_thresh:
                best_det_idx = unmatched_dets[best_local_idx]
                matched.append((t_idx, best_det_idx))
                unmatched_dets.remove(best_det_idx);
                unmatched_tracks.remove(t_idx)
        return matched, unmatched_dets, unmatched_tracks

    def _calculate_iou_matrix(self, b1s, b2s):
        if not b1s or not b2s: return np.empty((len(b1s), len(b2s)))
        iou_matrix = np.zeros((len(b1s), len(b2s)))
        for i, b1 in enumerate(b1s):
            for j, b2 in enumerate(b2s): iou_matrix[i, j] = self._iou(b1, b2)
        return iou_matrix

    @staticmethod
    def _iou(b1, b2):
        x1, y1, x2, y2 = max(b1[0], b2[0]), max(b1[1], b2[1]), min(b1[2], b2[2]), min(b1[3], b2[3])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1]);
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        return inter / (area1 + area2 - inter + 1e-6)


def nms(boxes, scores, thresh=0.6):
    if len(boxes) == 0: return [], []
    indices = np.argsort(scores)[::-1];
    keep = []
    while len(indices) > 0:
        i = indices[0];
        keep.append(i)
        if len(indices) == 1: break
        ious = np.array([KalmanSORTTracker._iou(boxes[i], boxes[j]) for j in indices[1:]])
        indices = indices[1:][ious < thresh]
    return boxes[keep], scores[keep]


class PersonTracker:
    def __init__(self, video_id: str, conf=0.5):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        # ✨ FIX: Pass the device directly to the model's constructor
        self.model = RFDETRMedium(device=self.device)
        self.conf = conf;
        self.person_class = 1
        self.tracker = KalmanSORTTracker(track_thresh=self.conf, max_age=75, min_hits=5)
        self.video_id = video_id

    def detect_persons(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        dets = self.model.predict(rgb, threshold=self.conf)
        results_raw = []
        boxes, scores, labels = dets.xyxy, dets.confidence, dets.class_id
        if torch.is_tensor(boxes): boxes = boxes.cpu().numpy()
        if torch.is_tensor(scores): scores = scores.cpu().numpy()
        if torch.is_tensor(labels): labels = labels.cpu().numpy()
        for box, score, label in zip(boxes, scores, labels):
            if int(label) == self.person_class and float(score) >= self.conf:
                results_raw.append([float(c) for c in box] + [float(score)])
        if not results_raw: return []
        boxes_raw = np.array([r[:4] for r in results_raw])
        scores_raw = np.array([r[4] for r in results_raw])
        boxes_nms, scores_nms = nms(boxes_raw, scores_raw)
        return [[b[0], b[1], b[2], b[3], s] for b, s in zip(boxes_nms, scores_nms)]

    def process_video(self, video_path: str, output_json_dir: str, output_frame_dir: str, sample_rate=1):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Cannot open video: {video_path}")
            return None

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        if video_fps == 0:
            logger.warning(f"FPS for {video_path} is 0. Defaulting to 30.")
            video_fps = 30
        frame_interval = int(video_fps / sample_rate)
        if frame_interval == 0: frame_interval = 1

        all_detections_data = []
        frame_count = 0
        saved_frame_idx = 0

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for _ in tqdm(range(total_frames), desc=f"Tracking {os.path.basename(video_path)}"):
            ret, frame = cap.read()
            if not ret: break

            if frame_count % frame_interval == 0:
                detections = self.detect_persons(frame)
                online_tracks = self.tracker.update(detections)

                frame_name = f"{self.video_id}_frame_{saved_frame_idx:04d}.jpg"

                frame_save_path = os.path.join(output_frame_dir, frame_name)
                cv2.imwrite(frame_save_path, frame)

                for track in online_tracks:
                    all_detections_data.append({
                        "video_id": self.video_id, "frame": frame_name,
                        "track_id": int(track.track_id), "bbox": [float(c) for c in track.bbox]
                    })
                saved_frame_idx += 1
            frame_count += 1

        cap.release()

        json_output_path = os.path.join(output_json_dir, f"{self.video_id}.json")
        with open(json_output_path, "w") as f:
            json.dump(all_detections_data, f, indent=2)

        logger.info(f"✅ Tracking complete for {self.video_id}. JSON saved.")
        return json_output_path

