import math
import time
import os
import logging
import cv2
import numpy as np
from dataclasses import dataclass

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions

log = logging.getLogger("tracker")


@dataclass
class Pose:
    yaw: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    confidence: float = 0.0
    timestamp: float = 0.0

    def copy(self) -> "Pose":
        return Pose(
            yaw=self.yaw,
            pitch=self.pitch,
            roll=self.roll,
            x=self.x,
            y=self.y,
            z=self.z,
            confidence=self.confidence,
            timestamp=self.timestamp,
        )


# Canonical 3D face model points (mm) for PnP
MODEL_POINTS = np.array(
    [
        [0.0, 0.0, 0.0],  # Nose tip
        [0.0, -63.6, -12.5],  # Chin
        [-43.3, 32.7, -26.0],  # Left eye corner
        [43.3, 32.7, -26.0],  # Right eye corner
        [-28.9, -28.9, -24.1],  # Left mouth corner
        [28.9, -28.9, -24.1],  # Right mouth corner
    ],
    dtype=np.float64,
)

# MediaPipe FaceLandmarker landmark indices corresponding to MODEL_POINTS
LANDMARK_INDICES = [1, 152, 33, 263, 61, 291]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "face_landmarker.task")


class HeadTracker:
    def __init__(self):
        log.info("Initializing HeadTracker...")
        if not os.path.isfile(MODEL_PATH):
            raise FileNotFoundError(
                f"Face landmark model not found at: {MODEL_PATH}\n"
                "Download it from https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/latest/face_landmarker.task"
            )
        try:
            options = FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._face_landmarker = FaceLandmarker.create_from_options(options)
            log.info("FaceLandmarker initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize FaceLandmarker: {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize face tracking model: {e}") from e
        self._last_valid_pose = Pose()
        self._face_lost_time: float = 0.0
        self._face_lost_threshold: float = 0.5
        self._last_landmarks = None

    def get_last_landmarks(self):
        return self._last_landmarks

    def process_frame(
        self,
        frame: np.ndarray,
        timestamp: float,
        camera_width: int,
        camera_height: int,
    ) -> Pose:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            # MediaPipe expects timestamp in milliseconds
            ts_ms = int(timestamp * 1000)

            result = self._face_landmarker.detect_for_video(mp_image, ts_ms)
        except cv2.error as e:
            log.error(f"OpenCV error during face detection: {e}")
            self._face_lost_time = time.perf_counter()
            return Pose(confidence=0.0, timestamp=timestamp)
        except Exception as e:
            log.error(f"Error during face detection: {e}", exc_info=True)
            self._face_lost_time = time.perf_counter()
            return Pose(confidence=0.0, timestamp=timestamp)

        if not result.face_landmarks:
            self._last_landmarks = None
            if time.perf_counter() - self._face_lost_time > self._face_lost_threshold:
                return Pose(confidence=0.0, timestamp=timestamp)
            pose = self._last_valid_pose.copy()
            pose.confidence = 0.0
            pose.timestamp = timestamp
            return pose

        face_landmarks = result.face_landmarks[0]
        self._last_landmarks = face_landmarks

        # Extract 2D image points for PnP
        image_points = np.array(
            [
                [face_landmarks[idx].x * camera_width, face_landmarks[idx].y * camera_height]
                for idx in LANDMARK_INDICES
            ],
            dtype=np.float64,
        )

        # Camera intrinsics (approximate for webcam)
        focal_length = camera_width
        center = (camera_width / 2.0, camera_height / 2.0)
        camera_matrix = np.array(
            [
                [focal_length, 0, center[0]],
                [0, focal_length, center[1]],
                [0, 0, 1],
            ],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)

        success, rvec, tvec = cv2.solvePnP(
            MODEL_POINTS,
            image_points,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )

        if not success:
            self._face_lost_time = time.perf_counter()
            return Pose(confidence=0.0, timestamp=timestamp)

        # Convert rotation vector to Euler angles
        rot_matrix, _ = cv2.Rodrigues(rvec)
        pose_angles = self._rotation_matrix_to_euler(rot_matrix)

        # Translation in mm
        tx, ty, tz = tvec.flatten()

        pose = Pose(
            yaw=pose_angles["yaw"],
            pitch=pose_angles["pitch"],
            roll=pose_angles["roll"],
            x=tx,
            y=ty,
            z=tz,
            confidence=1.0,
            timestamp=timestamp,
        )

        self._last_valid_pose = pose
        return pose

    @staticmethod
    def _rotation_matrix_to_euler(R: np.ndarray) -> dict:
        sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
        singular = sy < 1e-6

        if not singular:
            pitch = math.atan2(-R[2, 0], sy)
            yaw = math.atan2(R[1, 0], R[0, 0])
            roll = math.atan2(R[2, 1], R[2, 2])
        else:
            pitch = math.atan2(-R[2, 0], sy)
            yaw = math.atan2(-R[1, 2], R[1, 1])
            roll = 0.0

        return {
            "yaw": math.degrees(yaw),
            "pitch": math.degrees(pitch),
            "roll": math.degrees(roll),
        }

    def close(self):
        log.info("Closing HeadTracker...")
        if self._face_landmarker:
            try:
                self._face_landmarker.close()
            except Exception as e:
                log.warning(f"Error closing FaceLandmarker: {e}")
            self._face_landmarker = None
