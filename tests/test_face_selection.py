import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from types import SimpleNamespace

import numpy as np

from PySide6.QtWidgets import QApplication

from filter import AdaptiveExponentialFilter
from tracker import HeadTracker
from pose import Pose
from ui.main_window import MainWindow

app = QApplication([])

# Landmark coordinate sets for the 6 PnP indices, shaped like a face
FACE_A = [(0.30, 0.35), (0.30, 0.70), (0.45, 0.32), (0.15, 0.32), (0.45, 0.55), (0.15, 0.55)]
FACE_B = [(0.70, 0.35), (0.70, 0.70), (0.85, 0.32), (0.55, 0.32), (0.85, 0.55), (0.55, 0.55)]

# PnP landmark indices (tracker.LANDMARK_INDICES) -> fake coordinate
_PNP_IDS = [1, 152, 263, 33, 291, 61]


def _mk_face(points):
    assert len(points) == len(_PNP_IDS)
    lm = [SimpleNamespace(x=0.5, y=0.5, z=0.0) for _ in range(478)]
    for idx, (x, y) in zip(_PNP_IDS, points):
        lm[idx] = SimpleNamespace(x=x, y=y, z=0.0)
    return lm


def _mk_landmarker(results):
    class FakeLandmarker:
        def __init__(self):
            self._results = list(results)
            self.calls = 0

        def detect_for_video(self, mp_image, ts_ms):
            self.calls += 1
            return SimpleNamespace(face_landmarks=self._results.pop(0) if self._results else [])

    return FakeLandmarker()


class FakeTracker(HeadTracker):
    """HeadTracker logic without mediapipe model initialization."""

    def __init__(self, landmarker=None):
        self._face_lost_time = 0.0
        self._face_hold_time = 1.0
        self._confidence_threshold = 0.3
        self._last_landmarks = None
        self._smoothing = 0.0
        self._smooth_state = None
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
        self._face_landmarker = landmarker


def _run(tracker, frames):
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    for faces in frames:
        tracker._face_landmarker._results.append(faces)
    pose = None
    while tracker._face_landmarker._results:
        pose = tracker.process_frame(frame, 0.033, 160, 120)
    return pose


def test_single_face_default_selection():
    a = _mk_face(FACE_A)
    t = FakeTracker(_mk_landmarker([]))
    _run(t, [[a]])
    assert t.get_selected_face_index() == 0
    assert len(t.get_face_boxes()) == 1
    assert t.get_last_landmarks() is a
    print("PASS: single face -> index 0, boxes tracked")


def test_two_faces_default_first():
    a, b = _mk_face(FACE_A), _mk_face(FACE_B)
    t = FakeTracker(_mk_landmarker([]))
    _run(t, [[a, b]])
    assert t.get_selected_face_index() == 0
    assert t.get_last_landmarks() is a
    assert len(t.get_face_boxes()) == 2
    print("PASS: two faces -> first by default")


def test_select_second_face():
    a, b = _mk_face(FACE_A), _mk_face(FACE_B)
    t = FakeTracker(_mk_landmarker([]))
    t.set_face_index(1)
    assert t._face_index == 1
    _run(t, [[a, b]])
    assert t.get_selected_face_index() == 1
    assert t.get_last_landmarks() is b
    print("PASS: set_face_index(1) tracks second face")


def test_nearest_center_stability_after_order_swap():
    a, b = _mk_face(FACE_A), _mk_face(FACE_B)
    t = FakeTracker(_mk_landmarker([]))
    t.set_face_index(1)
    _run(t, [[a, b], [b, a]])
    # Face B was selected first (index 1); after the order swap it is index 0,
    # but nearest-center tracking must keep the same physical face (B).
    assert t.get_selected_face_index() == 0
    assert t.get_last_landmarks() is b
    print("PASS: nearest-center keeps the same physical face across order swaps")


def test_face_lost_falls_back_to_index():
    a, b = _mk_face(FACE_A), _mk_face(FACE_B)
    t = FakeTracker(_mk_landmarker([]))
    t.set_face_index(1)
    _run(t, [[a, b], []])
    assert t.get_selected_face_index() == 1
    assert t.get_face_boxes() == []
    _run(t, [[a, b]])
    assert t.get_selected_face_index() == 1
    assert t.get_last_landmarks() is b
    print("PASS: lost face resets anchor, re-detection falls back to chosen index")


def test_face_index_clamped():
    a, b = _mk_face(FACE_A), _mk_face(FACE_B)
    t = FakeTracker(_mk_landmarker([]))
    t.set_face_index(-5)
    _run(t, [[a, b]])
    assert t.get_selected_face_index() == 0
    t2 = FakeTracker(_mk_landmarker([]))
    t2.set_face_index(99)
    _run(t2, [[a, b]])
    assert t2.get_selected_face_index() == 0
    print("PASS: face index clamped to valid range")


def test_ui_combo_populates_and_selects():
    win = MainWindow(Profile())
    win.tracking_active = True
    win._on_worker_faces((1, [(0.2, 0.3, 0.1, 0.1), (0.8, 0.3, 0.1, 0.1)]))
    assert win.combo_face.count() == 2
    assert win.combo_face.currentIndex() == 1
    assert win.combo_face.isEnabled()
    assert win._face_boxes == [(0.2, 0.3, 0.1, 0.1), (0.8, 0.3, 0.1, 0.1)]
    win._on_worker_faces((0, [(0.5, 0.5, 0.2, 0.2)]))
    assert win.combo_face.count() == 1
    assert not win.combo_face.isEnabled()
    print("PASS: face combo populated from worker signal")


def test_ui_combo_change_forwards_to_worker():
    win = MainWindow(Profile())
    calls = []
    win.worker.set_face_index = lambda i: calls.append(i)
    win.tracking_active = True
    win._on_worker_faces((0, [(0.2, 0.3, 0.1, 0.1), (0.8, 0.3, 0.1, 0.1)]))
    win.combo_face.setCurrentIndex(1)
    assert calls == [1], f"expected [1], got {calls}"
    print("PASS: combo change forwards index to worker")


def test_ui_stop_tracking_resets_combo():
    win = MainWindow(Profile())
    win.tracking_active = True
    win._on_worker_faces((1, [(0.2, 0.3, 0.1, 0.1), (0.8, 0.3, 0.1, 0.1)]))
    win._stop_tracking()
    assert win.combo_face.count() == 0
    assert not win.combo_face.isEnabled()
    assert win._face_boxes == []
    print("PASS: stopping tracking clears the face combo")


from config import Profile  # noqa: E402

if __name__ == "__main__":
    test_single_face_default_selection()
    test_two_faces_default_first()
    test_select_second_face()
    test_nearest_center_stability_after_order_swap()
    test_face_lost_falls_back_to_index()
    test_face_index_clamped()
    test_ui_combo_populates_and_selects()
    test_ui_combo_change_forwards_to_worker()
    test_ui_stop_tracking_resets_combo()
    print("FACE SELECTION TESTS PASSED")
