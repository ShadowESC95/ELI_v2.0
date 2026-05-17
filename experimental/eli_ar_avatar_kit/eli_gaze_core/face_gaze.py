from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np


@dataclass
class GazeSample:
    features: np.ndarray
    confidence: float
    face_box: Tuple[int, int, int, int]
    left_eye: Tuple[float, float]
    right_eye: Tuple[float, float]
    method: str
    timestamp: float


def open_camera(camera: str | int = "auto", width: int = 1280, height: int = 720, fps: int = 30):
    candidates = []
    if str(camera).lower() == "auto":
        candidates = list(range(0, 8))
    else:
        candidates = [int(camera)]
    for idx in candidates:
        cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
            ok, frame = cap.read()
            if ok and frame is not None:
                return cap, idx
        cap.release()
    raise RuntimeError("No usable webcam found. Check v4l2-ctl --list-devices and camera permissions.")


class FaceGazeExtractor:
    """
    Extracts high-dimensional, calibration-friendly gaze features.

    Preferred backend: MediaPipe FaceMesh with refine_landmarks=True so iris landmarks are available.
    Fallback backend: OpenCV Haar face/eye estimates, enough for coarse head/eye steering but not accurate gaze.
    """

    def __init__(self, mirror: bool = True, prefer_mediapipe: bool = True):
        self.mirror = mirror
        self.method = "none"
        self.backend_error = ""
        self.mp_face_mesh = None
        self.face_mesh = None
        self.face_cascade = None
        self.eye_cascade = None
        if prefer_mediapipe:
            try:
                import mediapipe as mp  # type: ignore
                self.mp_face_mesh = mp.solutions.face_mesh
                self.face_mesh = self.mp_face_mesh.FaceMesh(
                    static_image_mode=False,
                    refine_landmarks=True,
                    max_num_faces=1,
                    min_detection_confidence=0.50,
                    min_tracking_confidence=0.50,
                )
                self.method = "mediapipe_facemesh_iris"
            except Exception as exc:
                self.backend_error = repr(exc)
                self.face_mesh = None
        if self.face_mesh is None:
            self.face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            self.eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye_tree_eyeglasses.xml")
            self.method = "opencv_haar_fallback"

    def extract(self, frame_bgr: np.ndarray) -> Optional[GazeSample]:
        if self.mirror:
            frame_bgr = cv2.flip(frame_bgr, 1)
        if self.face_mesh is not None:
            return self._extract_mediapipe(frame_bgr)
        return self._extract_haar(frame_bgr)

    def _extract_mediapipe(self, frame_bgr: np.ndarray) -> Optional[GazeSample]:
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        res = self.face_mesh.process(rgb)
        if not res.multi_face_landmarks:
            return None
        lm = res.multi_face_landmarks[0].landmark

        pts = np.array([[p.x * w, p.y * h, p.z] for p in lm], dtype=np.float64)
        xs, ys = pts[:, 0], pts[:, 1]
        x0, x1 = float(np.min(xs)), float(np.max(xs))
        y0, y1 = float(np.min(ys)), float(np.max(ys))
        fw = max(x1 - x0, 1.0)
        fh = max(y1 - y0, 1.0)
        fc_x = (x0 + x1) * 0.5 / w
        fc_y = (y0 + y1) * 0.5 / h
        fs_w = fw / w
        fs_h = fh / h

        # MediaPipe landmarks: eye contours + iris centres when refine_landmarks=True
        left_eye_ids = [33, 133, 159, 145, 160, 144, 158, 153]
        right_eye_ids = [362, 263, 386, 374, 387, 373, 385, 380]
        left_iris_ids = [468, 469, 470, 471, 472]
        right_iris_ids = [473, 474, 475, 476, 477]

        def centre(ids):
            p = pts[ids, :2]
            return p.mean(axis=0)

        def eye_bounds(ids):
            p = pts[ids, :2]
            return p[:, 0].min(), p[:, 0].max(), p[:, 1].min(), p[:, 1].max()

        # refine_landmarks=True should expose 478 landmarks, including iris rings.
        # If it does not, the result is not suitable for desktop gaze control.
        has_iris = len(pts) >= 478
        left_iris = centre(left_iris_ids) if has_iris else centre(left_eye_ids)
        right_iris = centre(right_iris_ids) if has_iris else centre(right_eye_ids)
        le_x0, le_x1, le_y0, le_y1 = eye_bounds(left_eye_ids)
        re_x0, re_x1, re_y0, re_y1 = eye_bounds(right_eye_ids)

        # Normalized iris positions inside each eye. These are the core calibration inputs.
        le_rx = (left_iris[0] - le_x0) / max(le_x1 - le_x0, 1.0)
        le_ry = (left_iris[1] - le_y0) / max(le_y1 - le_y0, 1.0)
        re_rx = (right_iris[0] - re_x0) / max(re_x1 - re_x0, 1.0)
        re_ry = (right_iris[1] - re_y0) / max(re_y1 - re_y0, 1.0)

        # Head pose proxies. Not exact PnP; stable enough to help calibration separate eye vs head motion.
        nose = pts[1, :2]
        chin = pts[152, :2]
        left_face = pts[234, :2]
        right_face = pts[454, :2]
        face_mid_x = (left_face[0] + right_face[0]) * 0.5
        yaw_proxy = (nose[0] - face_mid_x) / max(abs(right_face[0] - left_face[0]), 1.0)
        pitch_proxy = (nose[1] - ((pts[10, 1] + chin[1]) * 0.5)) / max(abs(chin[1] - pts[10, 1]), 1.0)
        roll_proxy = np.arctan2(right_face[1] - left_face[1], right_face[0] - left_face[0])

        # Pupil distance and asymmetry stabilize multiple distances from webcam.
        eye_dist = np.linalg.norm(centre(left_eye_ids) - centre(right_eye_ids)) / max(w, h)
        iris_mid = (left_iris + right_iris) * 0.5
        iris_mid_x = iris_mid[0] / w
        iris_mid_y = iris_mid[1] / h

        # Feature vector deliberately includes redundant signals; ridge regression handles correlation.
        features = np.array([
            le_rx, le_ry, re_rx, re_ry,
            (le_rx + re_rx) * 0.5, (le_ry + re_ry) * 0.5,
            iris_mid_x, iris_mid_y,
            fc_x, fc_y, fs_w, fs_h,
            eye_dist, yaw_proxy, pitch_proxy, roll_proxy,
            le_rx - re_rx, le_ry - re_ry,
        ], dtype=np.float64)

        confidence = 0.88 if has_iris else 0.52
        if not (0.05 <= le_rx <= 0.95 and 0.05 <= re_rx <= 0.95):
            confidence *= 0.72
        if fs_w < 0.08 or fs_h < 0.08:
            confidence *= 0.65
        if abs(roll_proxy) > 0.38:
            confidence *= 0.80
        return GazeSample(
            features=features,
            confidence=float(confidence),
            face_box=(int(x0), int(y0), int(fw), int(fh)),
            left_eye=(float(left_iris[0]), float(left_iris[1])),
            right_eye=(float(right_iris[0]), float(right_iris[1])),
            method=self.method,
            timestamp=time.time(),
        )

    def _extract_haar(self, frame_bgr: np.ndarray) -> Optional[GazeSample]:
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = self.face_cascade.detectMultiScale(gray, 1.2, 5, minSize=(80, 80))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
        roi = gray[y:y + h, x:x + w]
        eyes = self.eye_cascade.detectMultiScale(roi, 1.15, 4, minSize=(20, 20))
        eyes = sorted(eyes, key=lambda e: e[0])[:2]
        if len(eyes) < 2:
            # Head-only fallback.
            cx = (x + w * 0.5) / frame_bgr.shape[1]
            cy = (y + h * 0.42) / frame_bgr.shape[0]
            features = np.array([cx, cy, w / frame_bgr.shape[1], h / frame_bgr.shape[0], 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], dtype=np.float64)
            return GazeSample(features, 0.25, (x, y, w, h), (x + w * 0.35, y + h * 0.4), (x + w * 0.65, y + h * 0.4), self.method, time.time())
        centres = []
        for ex, ey, ew, eh in eyes:
            centres.append((x + ex + ew * 0.5, y + ey + eh * 0.5, ew, eh))
        left, right = centres[0], centres[1]
        fw, fh = frame_bgr.shape[1], frame_bgr.shape[0]
        features = np.array([
            left[0] / fw, left[1] / fh, right[0] / fw, right[1] / fh,
            ((left[0] + right[0]) * 0.5) / fw, ((left[1] + right[1]) * 0.5) / fh,
            (x + w * 0.5) / fw, (y + h * 0.5) / fh,
            w / fw, h / fh,
            abs(right[0] - left[0]) / fw,
            0, 0, 0, 0, 0, 0, 0,
        ], dtype=np.float64)
        return GazeSample(features, 0.38, (x, y, w, h), (left[0], left[1]), (right[0], right[1]), self.method, time.time())
