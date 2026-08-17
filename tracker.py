import time
import math
import os
import logging
import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    FaceLandmarker,
    FaceLandmarkerOptions,
    PoseLandmarker,
    PoseLandmarkerOptions,
)

from filter import AdaptiveExponentialFilter, AdaptivePoseFilter
from pose import Pose
from cam_calib import CameraCalibration, rotation_matrix_to_euler, euler_to_matrix

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
LANDMARK_INDICES = [1, 152, 263, 33, 291, 61]

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "face_landmarker.task")

# Canonical head points (mm) for PnP when the face itself is not visible
# (side/rear views). Same convention as MODEL_POINTS: nose tip origin,
# +Y down, -Z into the head.
POSE_MODEL_POINTS = np.array(
    [
        [0.0, 0.0, 0.0],      # Nose tip
        [-36.0, 26.0, -22.0],  # Left eye
        [36.0, 26.0, -22.0],   # Right eye
        [-72.0, 12.0, -28.0],  # Left ear
        [72.0, 12.0, -28.0],   # Right ear
        [-28.9, -28.9, -24.1], # Left mouth corner
        [28.9, -28.9, -24.1],  # Right mouth corner
    ],
    dtype=np.float64,
)

# BlazePose landmark indices corresponding to POSE_MODEL_POINTS rows
POSE_LANDMARK_INDICES = [0, 2, 5, 7, 8, 9, 10]

POSE_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "pose_landmarker_full.task"
)

# Side-view (pose fallback) sanity limits: the face landmark model cannot see
# beyond ~±90° yaw, but BlazePose tracks the head around the full circle.
SIDE_MAX_YAW_DEG = 175.0
SIDE_MAX_PITCH_DEG = 85.0
SIDE_MAX_ROLL_DEG = 85.0
MIN_POSE_VISIBILITY = 0.3  # average head-landmark visibility to trust pose fallback

# Sanity gate: solvePnP occasionally degenerates to physically impossible
# poses (roll ~160 deg, pitch ~-170 deg, z ~1.7 m) while landmarks stay fully
# visible (conf=1.0). These limits reject such frames before they reach the
# game: single-frame "flip" jerks in the preview and output.
MAX_YAW_DEG = 90.0
MAX_PITCH_DEG = 80.0
MAX_ROLL_DEG = 60.0
MAX_STEP_DEG = 30.0        # max angular step vs last accepted frame
MAX_STEP_MM = 200.0        # max translation step vs last accepted frame (mm)
Z_MIN_MM = 50.0            # plausible camera distance range (abs value)
Z_MAX_MM = 3000.0
SANITY_HOLD_TIME = 0.6     # seconds to fade confidence while rejecting frames


def _sane_failure(
    pose: Pose,
    prev: Pose | None = None,
    *,
    max_yaw: float = MAX_YAW_DEG,
    max_pitch: float = MAX_PITCH_DEG,
    max_roll: float = MAX_ROLL_DEG,
    skip_step: bool = False,
) -> str | None:
    """Human-readable reason a pose fails the sanity gate, None when sane."""
    if abs(pose.yaw) > max_yaw:
        return f"yaw {pose.yaw:+.1f} exceeds {max_yaw:.0f} deg"
    if abs(pose.pitch) > max_pitch:
        return f"pitch {pose.pitch:+.1f} exceeds {max_pitch:.0f} deg"
    if abs(pose.roll) > max_roll:
        return f"roll {pose.roll:+.1f} exceeds {max_roll:.0f} deg"
    if not (Z_MIN_MM <= abs(pose.z) <= Z_MAX_MM):
        return f"depth |z|={abs(pose.z):.0f} outside [{Z_MIN_MM:.0f}, {Z_MAX_MM:.0f}] mm"
    if prev is not None and not skip_step:
        d_yaw = abs((pose.yaw - prev.yaw + 180.0) % 360.0 - 180.0)
        ang = max(d_yaw, abs(pose.pitch - prev.pitch), abs(pose.roll - prev.roll))
        if ang > MAX_STEP_DEG:
            return f"angular step {ang:.1f} exceeds {MAX_STEP_DEG:.0f} deg"
        dist = max(abs(pose.x - prev.x), abs(pose.y - prev.y), abs(pose.z - prev.z))
        if dist > MAX_STEP_MM:
            return f"translation step {dist:.0f} exceeds {MAX_STEP_MM:.0f} mm"
    return None


class HeadTracker:
    def __init__(
        self,
        face_hold_time: float = 1.0,
        confidence_threshold: float = 0.3,
        smoothing: float = 0.0,
        calibration: CameraCalibration | None = None,
        num_faces: int = 1,
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
                num_faces=max(1, int(num_faces)),
                min_face_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._face_landmarker = FaceLandmarker.create_from_options(options)
            log.info("FaceLandmarker initialized successfully")
        except Exception as e:
            log.error(f"Failed to initialize FaceLandmarker: {e}", exc_info=True)
            raise RuntimeError(f"Failed to initialize face tracking model: {e}") from e

        # Optional side/rear-view fallback: BlazePose keeps seeing the head
        # when the face detector gives up (profile, back of the head).
        self._pose_landmarker: PoseLandmarker | None = None
        self._side_active: bool = False
        if os.path.isfile(POSE_MODEL_PATH):
            try:
                pose_options = PoseLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=POSE_MODEL_PATH),
                    running_mode=mp.tasks.vision.RunningMode.VIDEO,
                    num_poses=1,
                    min_pose_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                self._pose_landmarker = PoseLandmarker.create_from_options(pose_options)
                log.info("PoseLandmarker side-view fallback initialized")
            except Exception as e:
                log.warning(f"Failed to initialize PoseLandmarker fallback: {e}")
        else:
            log.info(
                "Pose landmark model not found at %s — side-view fallback "
                "disabled (optional; see setup.bat / setup.sh)",
                POSE_MODEL_PATH,
            )
        self._last_valid_pose = Pose()
        self._last_pnp_pose = Pose()
        self._last_calibrated_pose = Pose()
        self._face_lost_time: float = 0.0
        self._face_hold_time: float = face_hold_time
        self._confidence_threshold: float = confidence_threshold
        self._last_landmarks = None
        self._smoothing: float = max(0.0, min(1.0, smoothing))
        self._pose_filter: AdaptivePoseFilter | None = (
            AdaptivePoseFilter(self._smoothing) if self._smoothing > 0.0 else None
        )
        self._calibration: CameraCalibration | None = calibration

        # Smooth confidence: fast rise, slow fall
        self._confidence_smoother = AdaptiveExponentialFilter(
            rise_alpha=0.8,
            fall_alpha=0.05,
        )
        self._raw_confidence: float = 0.0

        # Multi-face selection state
        self._face_index: int = 0
        self._selected_index: int = 0
        self._selected_center: tuple[float, float] | None = None
        self._face_boxes: list[tuple[float, float, float, float]] = []

        # Pose blending state
        self._blend_pose = Pose()
        self._blend_alpha: float = 0.0

        # Sanity gate state
        self._last_sane_pose: Pose | None = None
        self._last_good_time: float = time.perf_counter()
        self._reject_count: int = 0

    def get_last_landmarks(self):
        return self._last_landmarks

    def get_last_pnp_pose(self) -> Pose:
        """Most recent pose directly from solvePnP (degrees, millimetres)."""
        return self._last_pnp_pose.copy()

    def get_last_calibrated_pose(self) -> Pose:
        """Pose after camera compensation, before smoothing and axis mapping."""
        return self._last_calibrated_pose.copy()

    def set_face_index(self, index: int):
        """Select which detected face to track (0-based, clamped)."""
        self._face_index = max(0, int(index))

    def get_selected_face_index(self) -> int:
        """Index of the face actually used in the last processed frame."""
        return self._selected_index

    def get_face_boxes(self) -> list[tuple[float, float, float, float]]:
        """Normalized (cx, cy, half_w, half_h) boxes of all detected faces."""
        return list(self._face_boxes)

    def set_smoothing(self, smoothing: float):
        self._smoothing = max(0.0, min(1.0, smoothing))
        self._pose_filter = (
            AdaptivePoseFilter(self._smoothing) if self._smoothing > 0.0 else None
        )

    def set_calibration(self, calibration: CameraCalibration | None):
        self._calibration = calibration

    def _apply_smoothing(self, pose: Pose) -> Pose:
        if self._pose_filter is None:
            return pose
        return self._pose_filter(pose)

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
            self._face_boxes = []
            self._selected_center = None

            # Side/rear-view fallback: face invisible, still track via BlazePose
            pose = self._try_pose_fallback(frame, ts_ms, camera_width, camera_height, timestamp)
            if pose is not None:
                return pose

            self._raw_confidence = 0.0
            self._last_sane_pose = None
            if self._pose_filter is not None:
                self._pose_filter.reset()
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

        # Per-face bounding boxes from landmark extents
        boxes = []
        for lm in result.face_landmarks:
            xs = [p.x for p in lm]
            ys = [p.y for p in lm]
            boxes.append((
                (min(xs) + max(xs)) / 2.0,
                (min(ys) + max(ys)) / 2.0,
                (max(xs) - min(xs)) / 2.0,
                (max(ys) - min(ys)) / 2.0,
            ))
        self._face_boxes = boxes

        # Keep the selected physical face across frames (nearest-center ID
        # stability), fall back to the user-chosen index for fresh detections.
        if len(boxes) > 1 and self._selected_center is not None:
            px, py = self._selected_center
            idx = min(
                range(len(boxes)),
                key=lambda i: (boxes[i][0] - px) ** 2 + (boxes[i][1] - py) ** 2,
            )
        else:
            idx = self._face_index
        if idx >= len(boxes):
            idx = 0
        self._selected_index = idx
        self._selected_center = (boxes[idx][0], boxes[idx][1])

        face_landmarks = result.face_landmarks[idx]
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
        camera_matrix = self._camera_matrix(camera_width, camera_height)
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

        # Sanity gate: reject physically impossible PnP solutions. Landmarks
        # stay visible during degenerate solves, so confidence alone cannot
        # catch them — a garbage frame must not reach the output. The step
        # check is skipped for the first face frame after a side-view fallback
        # segment: the two pose sources are continuous, not comparable.
        if not self._pose_is_sane(
            raw_pose,
            self._last_sane_pose,
            skip_step=self._side_active,
        ):
            return self._reject_pose(
                raw_pose,
                timestamp,
                _sane_failure(raw_pose, self._last_sane_pose, skip_step=self._side_active),
            )

        self._side_active = False
        self._last_good_time = time.perf_counter()
        self._last_sane_pose = raw_pose.copy()
        self._last_pnp_pose = raw_pose.copy()

        if self._calibration is not None:
            raw_pose = self._calibration.apply(raw_pose)
        self._last_calibrated_pose = raw_pose.copy()

        raw_pose = self._apply_smoothing(raw_pose)

        # Blend with last valid pose based on confidence
        # Low confidence = more of last_valid_pose, high = more of current
        conf = self._confidence_smoother(visibility_ratio, timestamp)
        pose = self._build_pose(
            conf,
            timestamp,
            raw_pose if visibility_ratio >= self._confidence_threshold else None,
        )
        # Keep the blended output as the next frame's reference.  Updating this
        # before _build_pose would make both blend inputs identical.
        if visibility_ratio >= self._confidence_threshold:
            self._last_valid_pose = pose.copy()
        return pose

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

    def _camera_matrix(self, camera_width: int, camera_height: int) -> np.ndarray:
        """Approximate camera intrinsics (FOV-adjustable via calibration)."""
        focal_length = (
            self._calibration.focal_length(camera_width)
            if self._calibration is not None
            else float(camera_width)
        )
        center = (camera_width / 2.0, camera_height / 2.0)
        return np.array(
            [
                [focal_length, 0, center[0]],
                [0, focal_length, center[1]],
                [0, 0, 1],
            ],
            dtype=np.float64,
        )

    def _reject_pose(self, raw_pose: Pose, timestamp: float, reason: str) -> Pose:
        """Sanity-gate rejection: log, count, and fade confidence out."""
        self._reject_count += 1
        if self._reject_count == 1 or self._reject_count % 120 == 0:
            log.warning(
                "Sanity gate: rejecting impossible pose "
                "yaw=%+.1f pitch=%+.1f roll=%+.1f x=%+.0f y=%+.0f z=%+.0f "
                "(total rejected: %d, reason: %s)",
                raw_pose.yaw, raw_pose.pitch, raw_pose.roll,
                raw_pose.x, raw_pose.y, raw_pose.z, self._reject_count, reason,
            )
        elapsed = time.perf_counter() - self._last_good_time
        hold_frac = max(0.0, 1.0 - elapsed / SANITY_HOLD_TIME)
        return self._build_pose(hold_frac, timestamp)

    def _try_pose_fallback(
        self,
        frame: np.ndarray,
        ts_ms: int,
        camera_width: int,
        camera_height: int,
        timestamp: float,
    ) -> Pose | None:
        """Track the head via BlazePose when no face is visible.

        Uses nose, eyes, ears and mouth corners — BlazePose regresses these
        even in profile and from behind. Yaw is allowed up to ±175° here
        (SIDE_MAX_YAW_DEG); absolute pitch/roll limits are slightly relaxed.
        The step gate applies between consecutive fallback frames only: the
        first frame after the face source switches does a fresh acquisition.
        """
        if self._pose_landmarker is None:
            return None
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            result = self._pose_landmarker.detect_for_video(mp_image, ts_ms)
        except Exception as e:
            log.warning(f"Pose fallback failed: {e}")
            return None
        if not result.pose_landmarks:
            return None

        lm = result.pose_landmarks[0]
        vis_values = [
            float(getattr(lm[i], "visibility", 1.0)) for i in POSE_LANDMARK_INDICES
        ]
        visibility = float(np.mean(vis_values))
        if visibility < MIN_POSE_VISIBILITY:
            return None

        image_points = np.array(
            [
                [lm[i].x * camera_width, lm[i].y * camera_height]
                for i in POSE_LANDMARK_INDICES
            ],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1), dtype=np.float64)
        success, rvec, tvec = cv2.solvePnP(
            POSE_MODEL_POINTS,
            image_points,
            self._camera_matrix(camera_width, camera_height),
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            return None

        rot_matrix, _ = cv2.Rodrigues(rvec)
        tx, ty, tz = tvec.flatten()

        # PnP can land on the mirrored branch (identical pixels, depth sign
        # flipped). The face path is consistent on one branch, so align the
        # fallback to it for a continuous depth across the source switch.
        # The mirror of a rotation is another valid rotation: R' = M R M.
        if self._last_sane_pose is not None and (tz < 0.0) != (self._last_sane_pose.z < 0.0):
            flip = np.diag([1.0, 1.0, -1.0])
            rot_matrix = flip @ rot_matrix @ flip
            tz = -tz

        # Full-circle extraction: rotation_matrix_to_euler clamps yaw to ±90
        # (past a profile view it dodges through pitch/roll ±180 and the sanity
        # gate rejects the result). Read the heading from the head's forward
        # axis instead, then extract the residual pitch/roll after removing it.
        yaw = self._full_circle_yaw(rot_matrix)
        _, pitch, roll = rotation_matrix_to_euler(
            euler_to_matrix(yaw, 0.0, 0.0).T @ rot_matrix
        )

        raw_pose = Pose(
            yaw=yaw,
            pitch=pitch,
            roll=roll,
            x=tx,
            y=ty,
            z=tz,
            confidence=visibility,
            timestamp=timestamp,
        )
        if not self._pose_is_sane(
            raw_pose,
            self._last_sane_pose,
            max_yaw=SIDE_MAX_YAW_DEG,
            max_pitch=SIDE_MAX_PITCH_DEG,
            max_roll=SIDE_MAX_ROLL_DEG,
            skip_step=not self._side_active,
        ):
            return self._reject_pose(
                raw_pose,
                timestamp,
                _sane_failure(
                    raw_pose,
                    self._last_sane_pose,
                    max_yaw=SIDE_MAX_YAW_DEG,
                    max_pitch=SIDE_MAX_PITCH_DEG,
                    max_roll=SIDE_MAX_ROLL_DEG,
                    skip_step=not self._side_active,
                ),
            )

        self._side_active = True
        self._face_lost_time = time.perf_counter()
        self._last_good_time = time.perf_counter()
        self._last_sane_pose = raw_pose.copy()
        self._last_pnp_pose = raw_pose.copy()
        self._raw_confidence = visibility

        if self._calibration is not None:
            raw_pose = self._calibration.apply(raw_pose)
        self._last_calibrated_pose = raw_pose.copy()

        raw_pose = self._apply_smoothing(raw_pose)

        conf = self._confidence_smoother(visibility, timestamp)
        pose = self._build_pose(
            conf,
            timestamp,
            raw_pose if visibility >= self._confidence_threshold else None,
        )
        if visibility >= self._confidence_threshold:
            self._last_valid_pose = pose.copy()
        return pose

    @staticmethod
    def _full_circle_yaw(R: np.ndarray) -> float:
        """Unclamped heading (degrees) in the face path's sign convention.

        rotation_matrix_to_euler clamps yaw to ±90: past a profile view the
        equivalent triplet dodges through (pitch, roll) = (±180, ±180), which
        the sanity gate correctly rejects. The pose fallback instead reads the
        head's forward axis (-R[:, 2]) and recovers the heading around the
        full circle. Matches the face path exactly for |yaw| <= 90, so the
        face <-> pose source switch stays continuous.
        """
        w0, w2 = -R[0, 2], -R[2, 2]
        yaw = -(180.0 + math.degrees(math.atan2(w0, w2)))
        return (yaw + 180.0) % 360.0 - 180.0

    @staticmethod
    def _rotation_matrix_to_euler(R: np.ndarray) -> dict:
        yaw, pitch, roll = rotation_matrix_to_euler(R)
        return {"yaw": yaw, "pitch": pitch, "roll": roll}

    @staticmethod
    def _pose_is_sane(
        pose: Pose,
        prev: Pose | None = None,
        *,
        max_yaw: float = MAX_YAW_DEG,
        max_pitch: float = MAX_PITCH_DEG,
        max_roll: float = MAX_ROLL_DEG,
        skip_step: bool = False,
    ) -> bool:
        """True when a raw PnP pose is physically plausible.

        Absolute limits catch degenerate solves; step limits catch single-frame
        teleports (a real head cannot move 140 deg or 1.6 m in one frame).
        ``prev`` should be the last *accepted* raw pose, None on first frame.
        ``max_*`` let the pose fallback use wider side-view limits;
        ``skip_step`` disables the step checks for the first frame after a
        tracking-source switch (face <-> pose), where continuity is defined
        within each source, not across them.

        Depth is compared by magnitude: mirrored camera streams (selfie view)
        produce a stable mirror solve with z < 0 — a consistent, valid
        configuration. Flipping between the two solutions is a huge step and is
        caught by the step limits instead."""
        return _sane_failure(
            pose, prev, max_yaw=max_yaw, max_pitch=max_pitch,
            max_roll=max_roll, skip_step=skip_step,
        ) is None

    def close(self):
        log.info("Closing HeadTracker...")
        if self._face_landmarker:
            try:
                self._face_landmarker.close()
            except Exception as e:
                log.warning(f"Error closing FaceLandmarker: {e}")
            self._face_landmarker = None
        if self._pose_landmarker:
            try:
                self._pose_landmarker.close()
            except Exception as e:
                log.warning(f"Error closing PoseLandmarker: {e}")
            self._pose_landmarker = None
