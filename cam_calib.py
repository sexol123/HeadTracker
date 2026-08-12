import math
import threading
import logging

import numpy as np

from pose import Pose

log = logging.getLogger("cam_calib")

DEG2RAD = math.pi / 180.0
CM_TO_MM = 10.0


def rotation_matrix_to_euler(R: np.ndarray) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees, sim convention (positive yaw = turn right,
    positive pitch = look up, positive roll = tilt right). ZYX decomposition as
    used by tracker.py."""
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    singular = sy < 1e-6
    if not singular:
        yaw = -math.atan2(-R[2, 0], sy)
        pitch = -math.atan2(R[2, 1], R[2, 2])
        roll = -math.atan2(R[1, 0], R[0, 0])
    else:
        yaw = -math.atan2(-R[2, 0], sy)
        pitch = 0.0
        roll = -math.atan2(-R[1, 2], R[1, 1])
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)


def euler_to_matrix(yaw: float, pitch: float, roll: float) -> np.ndarray:
    """Rotation matrix for (yaw, pitch, roll) in degrees — exact inverse of
    rotation_matrix_to_euler: R = Rz(-roll) @ Ry(-yaw) @ Rx(-pitch)."""
    y, p, r = (math.radians(a) for a in (yaw, pitch, roll))
    cy, sy = math.cos(y), math.sin(y)
    cp, sp = math.cos(p), math.sin(p)
    cr, sr = math.cos(r), math.sin(r)
    Rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, sp], [0.0, -sp, cp]], dtype=np.float64)
    Ry = np.array([[cy, 0.0, -sy], [0.0, 1.0, 0.0], [sy, 0.0, cy]], dtype=np.float64)
    Rz = np.array([[cr, sr, 0.0], [-sr, cr, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    return Rz @ Ry @ Rx


class CameraCalibration:
    """Compensates camera mounting geometry so the head pose is expressed
    relative to the monitor (and the neutral center), not the camera.

    - offset_x/y/z: camera position relative to the monitor origin, in cm
      (+X right, +Y up, +Z toward the user). Translation is rotated and shifted
      accordingly.
    - yaw/pitch/roll: tilt of the camera itself in degrees (+pitch = camera
      looks down at the face). Applied to the head rotation matrix before
      angle extraction.
    - fov: horizontal FOV in degrees; 0 = legacy behavior (focal = width).
    - center: captured neutral pose — everything is expressed relative to it.

    All parameters are read/written under a lock so the UI thread can update
    them live while the worker thread keeps calling apply().
    """

    def __init__(
        self,
        offset_x_cm: float = 0.0,
        offset_y_cm: float = 0.0,
        offset_z_cm: float = 0.0,
        yaw: float = 0.0,
        pitch: float = 0.0,
        roll: float = 0.0,
        fov: float = 0.0,
    ):
        self._lock = threading.Lock()
        self._offset = np.array(
            [offset_x_cm, offset_y_cm, offset_z_cm], dtype=np.float64
        ) * CM_TO_MM
        self._R_cam = euler_to_matrix(yaw, pitch, roll)
        self._fov = float(fov)
        self._R_center = None
        self._t_center = None

    def update(
        self,
        offset_x_cm: float,
        offset_y_cm: float,
        offset_z_cm: float,
        yaw: float,
        pitch: float,
        roll: float,
        fov: float,
    ):
        with self._lock:
            self._offset = np.array(
                [offset_x_cm, offset_y_cm, offset_z_cm], dtype=np.float64
            ) * CM_TO_MM
            self._R_cam = euler_to_matrix(yaw, pitch, roll)
            self._fov = float(fov)

    def set_center(self, yaw: float, pitch: float, roll: float, x: float, y: float, z: float):
        with self._lock:
            self._R_center = euler_to_matrix(yaw, pitch, roll)
            self._t_center = np.array([x, y, z], dtype=np.float64)

    def clear_center(self):
        with self._lock:
            self._R_center = None
            self._t_center = None

    def has_center(self) -> bool:
        with self._lock:
            return self._R_center is not None

    def focal_length(self, camera_width: int) -> float:
        """Focal length in pixels for the PnP camera matrix. fov=0 keeps the
        legacy focal = camera_width (~53° horizontal for 16:9)."""
        with self._lock:
            fov = self._fov
        # The UI limits FOV to 120°, but settings can also be edited by hand.
        # Values at/over 180° make the pinhole focal-length formula degenerate.
        if 0.0 < fov < 179.0:
            return (camera_width / 2.0) / math.tan(math.radians(fov) / 2.0)
        return float(camera_width)

    def apply(self, pose: Pose) -> Pose:
        R_head_cam = euler_to_matrix(pose.yaw, pose.pitch, pose.roll)
        t_cam = np.array([pose.x, pose.y, pose.z], dtype=np.float64)

        with self._lock:
            R_cam = self._R_cam
            offset = self._offset
            R_center = self._R_center
            t_center = self._t_center

        # R_cam = camera orientation in the app frame; its transpose maps
        # camera-frame vectors to monitor-frame vectors (verified against
        # real projectPoints/solvePnP: R_cam.T @ R_head_cam = R_head_mon).
        R_mon = R_cam.T @ R_head_cam
        t_mon = R_cam.T @ t_cam + offset

        if R_center is not None and t_center is not None:
            R_mon = R_center.T @ R_mon
            t_mon = t_mon - t_center

        yaw, pitch, roll = rotation_matrix_to_euler(R_mon)
        return Pose(
            yaw=yaw, pitch=pitch, roll=roll,
            x=t_mon[0], y=t_mon[1], z=t_mon[2],
            confidence=pose.confidence, timestamp=pose.timestamp,
        )
