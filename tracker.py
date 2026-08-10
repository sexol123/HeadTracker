import math
import time
import os
import logging
import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions

from filter import AdaptiveExponentialFilter
from pose import Pose
from cam_calib import CameraCalibration, rotation_matrix_to_euler

log = logging.getLogger("tracker")


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
# Eye/mouth corner pairs are swapped: MediaPipe's 33/61 are the subject's
# left eye/mouth (image-left for a mirrored view), the PnP model expects
# the opposite pairing — without the swap solvePnP yields a ~180° roll.
LANDMARK_INDICES = [1, 152, 263, 33, 291, 61]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "face_landmarker.task")


class HeadTracker:
    def __init__(
        self,
        face_hold_time: float = 1.0,
        confidence_threshold: float = 0.3,
        smoothing: float = 0.0,
        calibration: CameraCalibration | None = None,
    ):
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
        self._face_hold_time: float = face_hold_time
        self._confidence_threshold: float = confidence_threshold
        self._last_landmarks = None
        self._smoothing: float = max(0.0, min(1.0, smoothing))
        self._smooth_state: dict | None = None
        self._calibration: CameraCalibration | None = calibration

        # Smooth confidence: fast rise, slow fall
        self._confidence_smoother = AdaptiveExponentialFilter(
            rise_alpha=0.8,
            fall_alpha=0.05,
        )
        self._raw_confidence: float = 0.0

        # Pose blending state
        self._blend_pose = Pose()
        self._blend_alpha: float = 0.0

    def get_last_landmarks(self):
        return self._last_landmarks

    def set_smoothing(self, smoothing: float):
        self._smoothing = max(0.0, min(1.0, smoothing))
        if self._smoothing <= 0.0:
            self._smooth_state = None

    def set_calibration(self, calibration: CameraCalibration | None):
        self._calibration = calibration

    def _apply_smoothing(self, pose: Pose) -> Pose:
        if self._smoothing <= 0.0:
            self._smooth_state = None
            return pose
        alpha = 1.0 - self._smoothing
        state = self._smooth_state
        if state is None:
            self._smooth_state = {
                "yaw": pose.yaw, "pitch": pose.pitch, "roll": pose.roll,
                "x": pose.x, "y": pose.y, "z": pose.z,
            }
            return pose
        vals = {
            "yaw": pose.yaw, "pitch": pose.pitch, "roll": pose.roll,
            "x": pose.x, "y": pose.y, "z": pose.z,
        }
        for k, v in vals.items():
            state[k] = state[k] + (v - state[k]) * alpha
        return Pose(
            yaw=state["yaw"], pitch=state["pitch"], roll=state["roll"],
            x=state["x"], y=state["y"], z=state["z"],
            confidence=pose.confidence, timestamp=pose.timestamp,
        )

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
            self._raw_confidence = 0.0
            return self._build_pose(0.0, timestamp)
        except Exception as e:
            log.error(f"Error during face detection: {e}", exc_info=True)
            self._face_lost_time = time.perf_counter()
            self._raw_confidence = 0.0
            return self._build_pose(0.0, timestamp)

        if not result.face_landmarks:
            self._last_landmarks = None
            self._raw_confidence = 0.0
            self._smooth_state = None
            # Check hold time before fully losing
            elapsed = time.perf_counter() - self._face_lost_time
            if elapsed < self._face_hold_time:
                # Still within hold window — keep last pose but fade confidence
                hold_frac = 1.0 - (elapsed / self._face_hold_time)
                return self._build_pose(hold_frac, timestamp)
            else:
                # Hold expired — return zero with smooth confidence decay
                return self._build_pose(0.0, timestamp)

        # Face detected — reset lost timer
        self._face_lost_time = time.perf_counter()

        face_landmarks = result.face_landmarks[0]
        self._last_landmarks = face_landmarks

        # Calculate landmark visibility for partial occlusion detection
        visible_count = sum(
            1 for idx in LANDMARK_INDICES
            if 0 <= face_landmarks[idx].x <= 1 and 0 <= face_landmarks[idx].y <= 1
        )
        visibility_ratio = visible_count / len(LANDMARK_INDICES)

        # Raw confidence: based on landmark visibility
        self._raw_confidence = visibility_ratio

        # Extract 2D image points for PnP
        image_points = np.array(
            [
                [face_landmarks[idx].x * camera_width, face_landmarks[idx].y * camera_height]
                for idx in LANDMARK_INDICES
            ],
            dtype=np.float64,
        )

        # Camera intrinsics (approximate for webcam, FOV-adjustable)
        focal_length = (
            self._calibration.focal_length(camera_width)
            if self._calibration is not None
            else float(camera_width)
        )
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
            self._raw_confidence = 0.0
            return self._build_pose(0.0, timestamp)

        # Convert rotation vector to Euler angles
        rot_matrix, _ = cv2.Rodrigues(rvec)
        pose_angles = self._rotation_matrix_to_euler(rot_matrix)

        # Translation in mm
        tx, ty, tz = tvec.flatten()

        raw_pose = Pose(
            yaw=pose_angles["yaw"],
            pitch=pose_angles["pitch"],
            roll=pose_angles["roll"],
            x=tx,
            y=ty,
            z=tz,
            confidence=visibility_ratio,
            timestamp=timestamp,
        )

        if self._calibration is not None:
            raw_pose = self._calibration.apply(raw_pose)

        raw_pose = self._apply_smoothing(raw_pose)

        self._last_valid_pose = raw_pose

        # Blend with last valid pose based on confidence
        # Low confidence = more of last_valid_pose, high = more of current
        conf = self._confidence_smoother(visibility_ratio, timestamp)
        return self._build_pose(conf, timestamp, raw_pose)

    def _build_pose(
        self,
        confidence: float,
        timestamp: float,
        raw_pose: Pose | None = None,
    ) -> Pose:
        """Build final pose by blending raw_pose with last_valid_pose based on confidence.
        confidence is already smoothed by the caller."""
        if raw_pose is not None and confidence > 0.01:
            # Blend: low confidence → keep more of last_valid, high → trust current
            t = confidence
            pose = Pose(
                yaw=self._last_valid_pose.yaw * (1 - t) + raw_pose.yaw * t,
                pitch=self._last_valid_pose.pitch * (1 - t) + raw_pose.pitch * t,
                roll=self._last_valid_pose.roll * (1 - t) + raw_pose.roll * t,
                x=self._last_valid_pose.x * (1 - t) + raw_pose.x * t,
                y=self._last_valid_pose.y * (1 - t) + raw_pose.y * t,
                z=self._last_valid_pose.z * (1 - t) + raw_pose.z * t,
                confidence=confidence,
                timestamp=timestamp,
            )
            self._blend_pose = pose
            return pose
        else:
            # No detection or very low confidence — hold last pose, fade out
            pose = self._last_valid_pose.copy()
            pose.confidence = confidence
            pose.timestamp = timestamp
            self._blend_pose = pose
            return pose

    @staticmethod
    def _rotation_matrix_to_euler(R: np.ndarray) -> dict:
        yaw, pitch, roll = rotation_matrix_to_euler(R)
        return {"yaw": yaw, "pitch": pitch, "roll": roll}

    def close(self):
        log.info("Closing HeadTracker...")
        if self._face_landmarker:
            try:
                self._face_landmarker.close()
            except Exception as e:
                log.warning(f"Error closing FaceLandmarker: {e}")
            self._face_landmarker = None
