# app_person_tracker.py
import os
import cv2
import json
import torch
import numpy as np
from rfdetr import RFDETRMedium
from collections import deque

# ------------------- Kalman Filter -------------------
class KalmanFilter:
    def __init__(self):
        self.ndim = 8
        self.F = np.eye(self.ndim)
        for i in range(self.ndim // 2):
            self.F[i, i + 4] = 1
        self.H = np.eye(4, self.ndim)
        self.P = np.eye(self.ndim) * 10
        self.P[4:, 4:] *= 1000
        self.Q = np.eye(self.ndim)
        self.Q[4:, 4:] *= 0.01
        self.R = np.eye(4) * 0.1
        self.x = np.zeros((self.ndim, 1))
        self.is_initialized = False

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return self.x

    def update(self, z):
        if not self.is_initialized:
            self.x[:4] = z
            self.is_initialized = True
            return
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        self.P = (np.eye(self.ndim) - K @ self.H) @ self.P

    @staticmethod
    def bbox_to_z(bbox):
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        x_center = bbox[0] + w / 2
        y_center = bbox[1] + h / 2
        aspect_ratio = w / h if h > 0 else 0
        return np.array([x_center, y_center, aspect_ratio, h]).reshape(4, 1)

    def z_to_bbox(self, z=None):
        if z is None:
            z = self.x
        h = z[3, 0]
        w = z[2, 0] * h
        x_center = z[0, 0]
        y_center = z[1, 0]
        x1 = x_center - w / 2
        y1 = y_center - h / 2
        return [x1, y1, x1 + w, y1 + h]


class KalmanTrack:
    track_id_counter = 0

    def __init__(self, bbox, score):
        self.track_id = KalmanTrack.track_id_counter
        KalmanTrack.track_id_counter += 1
        self.score = score
        self.kf = KalmanFilter()
        self.kf.update(KalmanFilter.bbox_to_z(bbox))
        self.bbox = self.kf.z_to_bbox()
        self.hits = 1
        self.age = 1
        self.time_since_update = 0

    def update(self, bbox, score):
        self.kf.update(KalmanFilter.bbox_to_z(bbox))
        self.bbox = self.kf.z_to_bbox()
        self.score = score
        self.time_since_update = 0
        self.hits += 1

    def predict(self):
        self.kf.predict()
        self.bbox = self.kf.z_to_bbox()
        self.age += 1
        self.time_since_update += 1
        return self.bbox

    @property
    def tlbr(self):
        return np.array(self.bbox)


class KalmanSORTTracker:
    def __init__(self, track_thresh=0.5, match_thresh=0.3, max_age=30, min_hits=3):
        self.track_thresh = track_thresh
        self.match_thresh = match_thresh
        self.max_age = max_age
        self.min_hits = min_hits
        self.tracks = []
        KalmanTrack.track_id_counter = 0

    def update(self, detections, img_shape):
        high_conf_dets = [det for det in detections if det[4] >= self.track_thresh]
        for track in self.tracks:
            track.predict()
        matched_indices, unmatched_det_indices, unmatched_track_indices = self._match(high_conf_dets)
        for track_idx, det_idx in matched_indices:
            self.tracks[track_idx].update(high_conf_dets[det_idx][:4], high_conf_dets[det_idx][4])
        for det_idx in unmatched_det_indices:
            det = high_conf_dets[det_idx]
            new_track = KalmanTrack(det[:4], det[4])
            self.tracks.append(new_track)
        active_tracks = []
        remaining_tracks = []
        for track in self.tracks:
            if track.time_since_update == 0 and track.hits >= self.min_hits:
                active_tracks.append(track)
            if track.time_since_update <= self.max_age:
                remaining_tracks.append(track)
        self.tracks = remaining_tracks
        return active_tracks

    def _match(self, detections):
        if not self.tracks or not detections:
            return [], list(range(len(detections))), list(range(len(self.tracks)))
        track_bboxes = [t.bbox for t in self.tracks]
        det_bboxes = [d[:4] for d in detections]
        iou_matrix = self._calculate_iou_matrix(track_bboxes, det_bboxes)
        matched_indices, unmatched_dets, unmatched_tracks = [], list(range(len(detections))), list(range(len(self.tracks)))
        for t_idx, track in enumerate(self.tracks):
            if not unmatched_dets:
                break
            iou_row = iou_matrix[t_idx, unmatched_dets]
            if len(iou_row) == 0:
                continue
            best_match_local_idx = np.argmax(iou_row)
            if iou_row[best_match_local_idx] >= self.match_thresh:
                best_match_det_idx = unmatched_dets[best_match_local_idx]
                matched_indices.append((t_idx, best_match_det_idx))
                unmatched_dets.remove(best_match_det_idx)
                unmatched_tracks.remove(t_idx)
        return matched_indices, unmatched_dets, unmatched_tracks

    def _calculate_iou_matrix(self, bboxes1, bboxes2):
        if not bboxes1 or not bboxes2:
            return np.empty((len(bboxes1), len(bboxes2)))
        n1, n2 = len(bboxes1), len(bboxes2)
        iou_matrix = np.zeros((n1, n2))
        for i, bbox1 in enumerate(bboxes1):
            for j, bbox2 in enumerate(bboxes2):
                iou_matrix[i, j] = self._calculate_iou(bbox1, bbox2)
        return iou_matrix

    @staticmethod
    def _calculate_iou(b1, b2):
        x1, y1, x2, y2 = max(b1[0], b2[0]), max(b1[1], b2[1]), min(b1[2], b2[2]), min(b1[3], b2[3])
        inter = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        return inter / (area1 + area2 - inter + 1e-6)


def non_max_suppression(boxes, scores, iou_threshold=0.6):
    if len(boxes) == 0:
        return [], []
    boxes, scores = np.array(boxes), np.array(scores)
    indices, keep = scores.argsort()[::-1], []
    while len(indices) > 0:
        current = indices[0]
        keep.append(current)
        if len(indices) == 1:
            break
        ious = np.array([KalmanSORTTracker._calculate_iou(boxes[current], boxes[i]) for i in indices[1:]])
        indices = indices[1:][ious < iou_threshold]
    return boxes[keep], scores[keep]


# ------------------- Main Tracker -------------------
class PersonTracker:
    def __init__(self, video_id: str, conf=0.5):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"[INIT] Using device: {self.device}")
        try:
            self.model = RFDETRMedium()
        except NameError:
            print("[WARNING] RFDETRMedium not found. Using mock model.")
            class MockRFDETRMedium:
                def predict(self, frame, threshold):
                    class MockDetections:
                        def __init__(self):
                            self.xyxy = torch.tensor([[50, 50, 150, 150]])
                            self.confidence = torch.tensor([0.9])
                            self.class_id = torch.tensor([1])
                    return MockDetections()
            self.model = MockRFDETRMedium()
        self.conf = conf
        self.person_class = 1
        self.tracker = KalmanSORTTracker(track_thresh=self.conf, match_thresh=0.3, max_age=30, min_hits=3)
        self.video_id = video_id
        self.colors = {}

    def get_color(self, track_id):
        if track_id not in self.colors:
            np.random.seed(track_id)
            self.colors[track_id] = tuple(np.random.randint(0, 255, size=3).tolist())
        return self.colors[track_id]

    def detect_persons(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        detections = self.model.predict(rgb, threshold=self.conf)
        results = []
        boxes, scores, labels = detections.xyxy, detections.confidence, detections.class_id
        if torch.is_tensor(boxes): boxes = boxes.cpu().numpy()
        if torch.is_tensor(scores): scores = scores.cpu().numpy()
        if torch.is_tensor(labels): labels = labels.cpu().numpy()
        for box, score, label in zip(boxes, scores, labels):
            if int(label) == self.person_class and float(score) >= self.conf:
                results.append([float(b) for b in box] + [float(score)])
        if len(results) > 0:
            boxes_nms, scores_nms = non_max_suppression([r[:4] for r in results], [r[4] for r in results])
            results = [[float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(s)] for b, s in zip(boxes_nms, scores_nms)]
        return results

    def process_video(self, video_path: str, output_json_dir: str, fps=1):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"❌ Error: Cannot open {video_path}")
            return

        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        video_fps = cap.get(cv2.CAP_PROP_FPS)

        output_video_path = f"{self.video_id}_output_kalman.mp4"
        out = cv2.VideoWriter(output_video_path, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))

        frame_count = 0
        saved_frame_idx = 0
        all_detections_data = []

        print(f"[PROCESS] Tracking video {self.video_id}...")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            detections = self.detect_persons(frame)
            online_tracks = self.tracker.update(detections, frame.shape[:2])

            if frame_count % (max(1, int(video_fps // fps))) == 0:
                frame_name = f"{self.video_id}_frame_{saved_frame_idx:04d}.jpg"
                for track in online_tracks:
                    x1, y1, x2, y2 = [float(c) for c in track.bbox]
                    all_detections_data.append({
                        "video_id": self.video_id,
                        "frame": frame_name,
                        "track_id": int(track.track_id),
                        "bbox": [x1, y1, x2, y2]
                    })
                frame_to_write = frame.copy()
                for track in online_tracks:
                    x1, y1, x2, y2 = [int(c) for c in track.bbox]
                    color = self.get_color(track.track_id)
                    cv2.rectangle(frame_to_write, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame_to_write, f"ID:{track.track_id}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                out.write(frame_to_write)
                saved_frame_idx += 1
                if saved_frame_idx >= 15:
                    break
            frame_count += 1

        cap.release()
        out.release()
        print(f"✅ Video saved: {output_video_path}")

        os.makedirs(output_json_dir, exist_ok=True)
        json_output_path = os.path.join(output_json_dir, f"{self.video_id}.json")
        with open(json_output_path, "w") as f:
            json.dump(all_detections_data, f, indent=4)
        print(f"✅ JSON saved: {json_output_path}")


# ------------------- Main -------------------
if __name__ == "__main__":
    VIDEO_PATH = "tracker/Testing_videos/1_clip_000.mp4"
    VIDEO_ID = "1_clip_000"
    OUTPUT_JSON_DIR = "tracking_json_output"

    os.makedirs(OUTPUT_JSON_DIR, exist_ok=True)

    tracker = PersonTracker(video_id=VIDEO_ID, conf=0.5)
    tracker.process_video(video_path=VIDEO_PATH, output_json_dir=OUTPUT_JSON_DIR, fps=1)
