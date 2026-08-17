import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from types import SimpleNamespace

import numpy as np
import cv2

from filter import AdaptiveExponentialFilter
from cam_calib import euler_to_matrix, rotation_matrix_to_euler
from tracker import (
    HeadTracker,
    LANDMARK_INDICES,
    MAX_YAW_DEG,
    MODEL_POINTS,
    POSE_LANDMARK_INDICES,
    POSE_MODEL_POINTS,
    SIDE_MAX_YAW_DEG,
    SIDE_MAX_PITCH_DEG,
    SIDE_MAX_ROLL_DEG,
    _sane_failure,
)
from pose import Pose

CAM_W, CAM_H = 160, 120
K = np.array([[160.0, 0, 80.0], [0, 160.0, 60.0], [0, 0, 1]], dtype=np.float64)
D = np.zeros((4, 1), dtype=np.float64)


def _p(yaw=0.0, pitch=0.0, roll=0.0, x=0.0, y=0.0, z=500.0):
    return Pose(yaw=yaw, pitch=pitch, roll=roll, x=x, y=y, z=z, confidence=1.0)


def _yaw_rot(yaw_deg):
    yaw = np.deg2rad(yaw_deg)
    return np.array(
        [
            [np.cos(yaw), 0, np.sin(yaw)],
            [0, 1, 0],
            [-np.sin(yaw), 0, np.cos(yaw)],
        ],
        dtype=np.float64,
    )


def _mk_pose(yaw_deg, tz=500.0, vis=0.9):
    """BlazePose landmarks for a head rotated yaw_deg about the camera Y axis."""
    rvec, _ = cv2.Rodrigues(_yaw_rot(yaw_deg))
    pts, _ = cv2.projectPoints(
        POSE_MODEL_POINTS, rvec, np.array([0.0, 0.0, tz]), K, D
    )
    lm = [SimpleNamespace(x=0.5, y=0.5, z=0.0, visibility=0.5) for _ in range(33)]
    for idx, p in zip(POSE_LANDMARK_INDICES, pts):
        lm[idx] = SimpleNamespace(
            x=float(p[0][0] / CAM_W),
            y=float(p[0][1] / CAM_H),
            z=0.0,
            visibility=vis,
        )
    return lm


def _mk_face(yaw_deg, tz=500.0):
    """Face landmarks for the 6 PnP indices with the head at yaw_deg."""
    rvec, _ = cv2.Rodrigues(_yaw_rot(yaw_deg))
    pts, _ = cv2.projectPoints(
        MODEL_POINTS, rvec, np.array([0.0, 0.0, tz]), K, D
    )
    lm = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(478)]
    for idx, p in zip(LANDMARK_INDICES, pts):
        lm[idx] = SimpleNamespace(x=float(p[0][0] / CAM_W), y=float(p[0][1] / CAM_H), z=0.0)
    return lm


class FakeLandmarker:
    def __init__(self, results):
        self._results = list(results)

    def detect_for_video(self, mp_image, ts_ms):
        return SimpleNamespace(face_landmarks=self._results.pop(0) if self._results else [])


class FakePoseLandmarker:
    def __init__(self, results):
        self._results = list(results)

    def detect_for_video(self, mp_image, ts_ms):
        poses = [self._results.pop(0)] if self._results else []
        return SimpleNamespace(pose_landmarks=poses)


class FakeTracker(HeadTracker):
    def __init__(self, face_landmarker, pose_landmarker):
        self._face_lost_time = 0.0
        self._face_hold_time = 1.0
        self._confidence_threshold = 0.3
        self._last_landmarks = None
        self._smoothing = 0.0
        self._pose_filter = None
        self._calibration = None
        self._confidence_smoother = AdaptiveExponentialFilter(rise_alpha=0.8, fall_alpha=0.05)
        self._raw_confidence = 0.0
        self._last_valid_pose = Pose()
        self._face_index = 0
        self._selected_index = 0
        self._selected_center = None
        self._face_boxes = []
        self._blend_pose = Pose()
        self._blend_alpha = 0.0
        self._last_sane_pose = None
        self._last_good_time = time.perf_counter()
        self._reject_count = 0
        self._face_landmarker = face_landmarker
        self._pose_landmarker = pose_landmarker
        self._side_active = False


def _run(t, pose_frames, ts_start=0.033):
    frame = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)
    t._pose_landmarker._results = list(pose_frames)
    poses = []
    while t._pose_landmarker._results:
        poses.append(t.process_frame(frame, ts_start, CAM_W, CAM_H))
        ts_start += 0.033
    return poses


def test_gate_side_limits():
    # Default (face) gate still caps yaw at 90
    assert not HeadTracker._pose_is_sane(_p(yaw=MAX_YAW_DEG + 1))
    # Side limits allow a full profile and beyond, but not full flip
    assert HeadTracker._pose_is_sane(_p(yaw=SIDE_MAX_YAW_DEG), max_yaw=SIDE_MAX_YAW_DEG)
    assert not HeadTracker._pose_is_sane(_p(yaw=SIDE_MAX_YAW_DEG + 1), max_yaw=SIDE_MAX_YAW_DEG)
    assert not HeadTracker._pose_is_sane(_p(pitch=SIDE_MAX_PITCH_DEG + 1), max_pitch=SIDE_MAX_PITCH_DEG)
    assert not HeadTracker._pose_is_sane(_p(roll=SIDE_MAX_ROLL_DEG + 1), max_roll=SIDE_MAX_ROLL_DEG)
    print("PASS: side-view gate limits (face default unchanged)")


def test_full_circle_yaw_and_residual():
    # rotation_matrix_to_euler dodges through pitch/roll ±180 past 90 deg;
    # _full_circle_yaw must recover the true heading everywhere and leave
    # only a small residual after it is removed.
    for theta in (0.0, 30.0, -30.0, 80.0, 115.0, 135.0, 170.0, -115.0):
        R = euler_to_matrix(theta, 0.0, 0.0)
        y = HeadTracker._full_circle_yaw(R)
        assert abs(y - theta) < 1e-9, (theta, y)
        _, p, r = rotation_matrix_to_euler(euler_to_matrix(y, 0.0, 0.0).T @ R)
        assert abs(p) < 1e-9 and abs(r) < 1e-9, (theta, p, r)
    # A side view with a genuine nod/tilt: heading exact, residual bounded
    R = euler_to_matrix(100.0, 15.0, -10.0)
    y = HeadTracker._full_circle_yaw(R)
    assert abs(y - 100.0) < 0.5
    _, p, r = rotation_matrix_to_euler(euler_to_matrix(y, 0.0, 0.0).T @ R)
    assert abs(p) < 20.0 and abs(r) < 10.0
    print("PASS: full-circle yaw matches face path within ±90, continuous beyond")


def test_fallback_tracks_profile_yaw():
    t = FakeTracker(FakeLandmarker([]), FakePoseLandmarker([]))
    poses = _run(t, [_mk_pose(115.0)])
    assert len(poses) == 1
    assert t._side_active is True
    assert t._last_landmarks is None
    assert poses[0].confidence > 0.5
    assert abs(poses[0].yaw) > 90.0
    assert abs(poses[0].yaw) < SIDE_MAX_YAW_DEG
    assert abs(poses[0].z) > 400.0  # tvec recovered from tz=500 projection
    print(f"PASS: profile yaw ~{poses[0].yaw:.0f} deg accepted via pose fallback")


def test_fallback_absurd_yaw_rejected():
    t = FakeTracker(FakeLandmarker([]), FakePoseLandmarker([]))
    poses = _run(t, [_mk_pose(178.0)])
    assert t._reject_count == 1
    assert poses[0].confidence > 0.0  # sanity hold: last valid pose fading
    assert abs(poses[0].yaw) < 1e-9  # held pose was the initial zero pose
    print("PASS: fallback yaw beyond side limit rejected")


def test_step_limit_applies_within_fallback():
    t = FakeTracker(FakeLandmarker([]), FakePoseLandmarker([]))
    poses = _run(t, [_mk_pose(115.0), _mk_pose(152.0)])
    assert t._reject_count == 1
    assert poses[0].confidence > 0.5
    assert abs(poses[1].yaw - poses[0].yaw) < 1e-6  # held last accepted pose
    print("PASS: per-frame step gate active between consecutive fallback frames")


def test_fallback_disabled_without_pose_model():
    t = FakeTracker(FakeLandmarker([]), None)
    p = t.process_frame(np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8), 0.033, CAM_W, CAM_H)
    assert t._reject_count == 0
    assert p.confidence == 0.0  # no fallback -> normal lose path
    print("PASS: no pose model -> previous behavior (hold fades to zero)")


def test_sane_failure_reports_reason():
    assert _sane_failure(_p()) is None
    assert "yaw" in _sane_failure(_p(yaw=95.0))
    assert "depth" in _sane_failure(_p(z=4999.0))
    assert "angular step" in _sane_failure(_p(yaw=50.0), _p(yaw=-50.0))
    assert "translation step" in _sane_failure(_p(x=500.0), _p())
    print("PASS: sanity gate failure reasons are descriptive")


def test_fallback_aligns_depth_branch():
    """PnP can solve the mirror branch (depth sign flipped). The fallback must
    align to the branch the face path is on, otherwise every fallback frame
    is rejected as a ~2 m depth teleport."""
    t = FakeTracker(FakeLandmarker([]), FakePoseLandmarker([]))
    frame = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)

    # Face path establishes the +z branch
    t._face_landmarker._results = [[_mk_face(20.0, tz=500.0)]]
    p_face = t.process_frame(frame, 0.033, CAM_W, CAM_H)
    assert t._reject_count == 0 and t._last_sane_pose.z > 0.0

    # Fallback solves on the mirror branch (tz = -500) - must be aligned
    t._pose_landmarker._results = [_mk_pose(30.0, tz=-500.0)]
    p1 = t.process_frame(frame, 0.066, CAM_W, CAM_H)
    assert t._reject_count == 0
    assert p1.z > 0.0
    assert p1.confidence > 0.5

    # Consecutive fallback frames stay on the aligned branch
    t._pose_landmarker._results = [_mk_pose(35.0, tz=-500.0)]
    p2 = t.process_frame(frame, 0.099, CAM_W, CAM_H)
    assert t._reject_count == 0
    assert p2.z > 0.0
    print(f"PASS: mirror-branch fallback aligned to face branch (z={p2.z:+.0f})")


def test_mixed_sources_continuous_switch():
    t = FakeTracker(FakeLandmarker([]), FakePoseLandmarker([]))
    frame = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)
    ts = 0.033

    # 1) Fallback at 100 deg (face absent)
    t._pose_landmarker._results = [_mk_pose(100.0)]
    p1 = t.process_frame(frame, ts, CAM_W, CAM_H)
    ts += 0.033
    assert abs(p1.yaw) > 90.0 and t._side_active

    # 2) Face returns at 85 deg — step gate skipped for the switch frame
    t._face_landmarker._results = [[_mk_face(85.0)]]
    p2 = t.process_frame(frame, ts, CAM_W, CAM_H)
    ts += 0.033
    assert t._reject_count == 0
    assert not t._side_active
    assert abs(p2.yaw) > 80.0

    # 3) Fallback re-acquires at 100 deg — fresh acquisition, no step gate
    t._pose_landmarker._results = [_mk_pose(100.0)]
    p3 = t.process_frame(frame, ts, CAM_W, CAM_H)
    assert t._reject_count == 0
    assert abs(p3.yaw) > 90.0 and t._side_active
    print("PASS: face <-> pose source switches stay continuous")


def test_face_gate_regression_yaw_95():
    # Face path must still reject yaw beyond 90 even though the pose path allows it
    t = FakeTracker(FakeLandmarker([]), FakePoseLandmarker([]))
    t._face_landmarker._results = [[_mk_face(95.0)]]
    p = t.process_frame(np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8), 0.033, CAM_W, CAM_H)
    assert t._reject_count == 1
    assert abs(p.yaw) < 1e-9  # initial zero held pose
    print("PASS: face gate regression — yaw 95 still rejected on face path")


test_gate_side_limits()
test_full_circle_yaw_and_residual()
test_fallback_tracks_profile_yaw()
test_fallback_absurd_yaw_rejected()
test_step_limit_applies_within_fallback()
test_fallback_disabled_without_pose_model()
test_sane_failure_reports_reason()
test_fallback_aligns_depth_branch()
test_mixed_sources_continuous_switch()
test_face_gate_regression_yaw_95()
print("ALL PASS: pose fallback")