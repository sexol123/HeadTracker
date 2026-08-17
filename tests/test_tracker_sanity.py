import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from types import SimpleNamespace

import numpy as np

from filter import AdaptiveExponentialFilter
from tracker import (
    HeadTracker,
    MAX_YAW_DEG,
    MAX_PITCH_DEG,
    MAX_ROLL_DEG,
    MAX_STEP_DEG,
    MAX_STEP_MM,
    Z_MAX_MM,
    SANITY_HOLD_TIME,
)
from pose import Pose


def _p(yaw=0.0, pitch=0.0, roll=0.0, x=0.0, y=0.0, z=500.0):
    return Pose(yaw=yaw, pitch=pitch, roll=roll, x=x, y=y, z=z, confidence=1.0)


def test_absolute_limits():
    assert HeadTracker._pose_is_sane(_p())
    assert not HeadTracker._pose_is_sane(_p(yaw=MAX_YAW_DEG + 1))
    assert not HeadTracker._pose_is_sane(_p(pitch=MAX_PITCH_DEG + 1))
    assert not HeadTracker._pose_is_sane(_p(roll=MAX_ROLL_DEG + 1))
    assert not HeadTracker._pose_is_sane(_p(z=49.0))
    assert not HeadTracker._pose_is_sane(_p(z=-49.0))
    assert not HeadTracker._pose_is_sane(_p(z=Z_MAX_MM + 1))
    assert not HeadTracker._pose_is_sane(_p(z=-(Z_MAX_MM + 1)))
    assert HeadTracker._pose_is_sane(_p(z=Z_MAX_MM))
    print("PASS: absolute yaw/pitch/roll/z limits")


def test_negative_depth_mirrored_stream():
    # Mirrored camera streams solve with z < 0 consistently; a stable mirror
    # solution is valid, not a spike
    assert HeadTracker._pose_is_sane(_p(z=-500.0))
    assert HeadTracker._pose_is_sane(_p(z=-527.0, y=57.0, x=-9.0))
    # But a flip between mirror and normal solve is a teleport
    assert not HeadTracker._pose_is_sane(_p(z=500.0), _p(z=-500.0))
    print("PASS: negative depth accepted, mirror flip rejected as step")


def test_step_limits():
    prev = _p()
    assert HeadTracker._pose_is_sane(_p(yaw=MAX_STEP_DEG), prev)
    assert not HeadTracker._pose_is_sane(_p(yaw=MAX_STEP_DEG + 1), prev)
    assert not HeadTracker._pose_is_sane(_p(pitch=-MAX_STEP_DEG - 1), prev)
    assert not HeadTracker._pose_is_sane(_p(roll=MAX_STEP_DEG + 5), prev)
    assert HeadTracker._pose_is_sane(_p(y=MAX_STEP_MM), prev)
    assert not HeadTracker._pose_is_sane(_p(y=MAX_STEP_MM + 1), prev)
    assert not HeadTracker._pose_is_sane(_p(x=-MAX_STEP_MM - 50), prev)
    print("PASS: per-frame step limits")


def test_step_wraparound():
    # Sign flips near the absolute limit are huge rotations: +89 -> -89
    # (178 deg) and +70 -> -70 (140 deg) must both be rejected as teleports
    assert not HeadTracker._pose_is_sane(_p(yaw=-89.0), _p(yaw=89.0))
    assert not HeadTracker._pose_is_sane(_p(yaw=-70.0), _p(yaw=70.0))
    print("PASS: large angular flips across the sign boundary rejected")


def test_no_prev_skips_step_check():
    # Without a reference pose only absolute limits apply
    assert HeadTracker._pose_is_sane(_p(yaw=40.0, x=900.0, y=-700.0))
    print("PASS: first frame (no prev) skips step check")


class FakeTracker(HeadTracker):
    """HeadTracker logic without mediapipe model initialization."""

    def __init__(self, landmarker=None):
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
        self._last_good_time = 0.0
        self._reject_count = 0
        self._face_landmarker = landmarker
        self._pose_landmarker = None
        self._side_active = False


class FakeLandmarker:
    def __init__(self, results):
        self._results = list(results)

    def detect_for_video(self, mp_image, ts_ms):
        return SimpleNamespace(face_landmarks=self._results.pop(0) if self._results else [])


def _mk_face():
    lm = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(478)]
    for idx, (x, y) in zip([1, 152, 263, 33, 291, 61],
                           [(0.30, 0.35), (0.30, 0.70), (0.45, 0.32),
                            (0.15, 0.32), (0.45, 0.55), (0.15, 0.55)]):
        lm[idx] = SimpleNamespace(x=x, y=y, z=0.0)
    return lm


def test_reject_path_holds_last_pose():
    t = FakeTracker(FakeLandmarker([]))
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    face = _mk_face()

    # Control the gate explicitly: first frame accepted, then all rejected
    t._pose_is_sane = lambda pose, prev, **kw: True
    t._face_landmarker._results = [[face]]
    good = t.process_frame(frame, 0.033, 160, 120)
    assert t._last_sane_pose is not None
    assert t._reject_count == 0

    t._pose_is_sane = lambda pose, prev, **kw: False
    t._face_landmarker._results = [[face]]
    first_rejected = t.process_frame(frame, 0.066, 160, 120)
    assert t._reject_count == 1
    # Hold: pose is the last valid one, confidence fading from 1.0
    assert first_rejected.confidence <= 1.0
    assert first_rejected.confidence > 0.0
    assert abs(first_rejected.yaw - good.yaw) < 1e-9
    print("PASS: rejected frames hold last valid pose with fading confidence")

    # After the hold window confidence hits 0 (worker will stop sending)
    t._last_good_time = 0.0
    t._face_landmarker._results = [[face]]
    later = t.process_frame(frame, 0.099, 160, 120)
    assert later.confidence == 0.0
    print("PASS: prolonged rejection fades confidence to 0 (send blocked)")


test_absolute_limits()
test_step_limits()
test_step_wraparound()
test_no_prev_skips_step_check()
test_reject_path_holds_last_pose()
print("ALL PASS: tracker sanity gate")
