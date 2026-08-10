import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication

from config import Profile, save_profile, load_profile
from cam_calib import CameraCalibration
from worker import TrackingWorker
from pose import Pose
from ui.main_window import MainWindow
from i18n import t

app = QApplication([])

CENTRE = {"yaw": 12.5, "pitch": -3.0, "roll": 1.5, "x": 10.0, "y": -5.0, "z": 55.0}


def test_profile_roundtrip_with_center():
    p = Profile(name="Pilot")
    p.center_pose = dict(CENTRE)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "p.json"
        save_profile(p, path)
        loaded = load_profile(path)
    assert loaded.center_pose == CENTRE
    print("PASS: profile roundtrip keeps center_pose")


def test_profile_without_center_backward_compat():
    raw = {"name": "Old", "axes": {"yaw": {"sensitivity": 7.0, "deadzone": 1.0}}}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        loaded = load_profile(path)
    assert loaded.center_pose is None
    assert loaded.axes["yaw"].sensitivity == 7.0
    print("PASS: profiles without center_pose load fine (backward compatible)")


def test_worker_applies_profile_center():
    cal = CameraCalibration()
    prof = Profile(name="P")
    prof.center_pose = dict(CENTRE)
    assert TrackingWorker._apply_profile_center(cal, prof) is True
    assert cal.has_center()
    neutral = cal.apply(Pose(yaw=CENTRE["yaw"], pitch=CENTRE["pitch"], roll=CENTRE["roll"],
                             x=CENTRE["x"], y=CENTRE["y"], z=CENTRE["z"], confidence=1.0))
    assert abs(neutral.yaw) < 1.0 and abs(neutral.pitch) < 1.0, "center pose must become neutral"
    print("PASS: worker applies profile center at start (center pose -> neutral)")


def test_worker_skips_without_center():
    cal = CameraCalibration()
    prof = Profile(name="P")
    assert TrackingWorker._apply_profile_center(cal, prof) is False
    assert not cal.has_center()
    assert TrackingWorker._apply_profile_center(cal, None) is False
    print("PASS: no center in profile -> nothing applied")


def test_ui_checkbox_exists():
    win = MainWindow(Profile())
    win.show()
    app.processEvents()
    assert hasattr(win, "chk_save_center")
    assert t("save_center_to_profile") == win.chk_save_center.text()
    assert win.chk_save_center.toolTip() == t("save_center_to_profile_tip")
    print("PASS: checkbox exists with i18n text and tooltip")


def test_ui_set_center_saves_to_profile():
    win = MainWindow(Profile())
    win.show()
    app.processEvents()

    class FakeWorker:
        def recenter_camera(self):
            return True

        def get_raw_pose(self):
            return Pose(yaw=5.0, pitch=-2.0, roll=0.5, x=1.0, y=-1.0, z=50.0,
                        confidence=0.9)

        def reset_camera_center(self):
            pass

    win.worker = FakeWorker()
    win.tracking_active = True
    win.chk_save_center.setChecked(True)
    win._on_cam_center()
    cp = win.profile.center_pose
    assert cp is not None
    assert cp["yaw"] == 5.0 and cp["z"] == 50.0
    print("PASS: Set center stores raw pose into profile when checkbox on")


def test_ui_set_center_skips_when_checkbox_off():
    win = MainWindow(Profile())
    win.show()
    app.processEvents()

    class FakeWorker:
        def recenter_camera(self):
            return True

        def get_raw_pose(self):
            return Pose(yaw=5.0, pitch=0.0, roll=0.0, x=0.0, y=0.0, z=50.0, confidence=0.9)

        def reset_camera_center(self):
            pass

    win.worker = FakeWorker()
    win.tracking_active = True
    win.chk_save_center.setChecked(False)
    win._on_cam_center()
    assert win.profile.center_pose is None
    print("PASS: Set center does not touch profile when checkbox off")


def test_ui_reset_center_clears_profile():
    win = MainWindow(Profile())
    win.show()
    app.processEvents()
    win.chk_save_center.setChecked(True)
    win.profile.center_pose = dict(CENTRE)

    class FakeWorker:
        def reset_camera_center(self):
            pass

    win.worker = FakeWorker()
    win._on_cam_center_reset()
    assert win.profile.center_pose is None
    print("PASS: Reset center clears profile center when checkbox on")


def test_unchecking_checkbox_clears_profile_center():
    win = MainWindow(Profile())
    win.show()
    app.processEvents()
    win.profile.center_pose = dict(CENTRE)
    win.chk_save_center.setChecked(True)
    win.chk_save_center.setChecked(False)
    assert win.profile.center_pose is None
    print("PASS: unchecking removes center from profile")


if __name__ == "__main__":
    test_profile_roundtrip_with_center()
    test_profile_without_center_backward_compat()
    test_worker_applies_profile_center()
    test_worker_skips_without_center()
    test_ui_checkbox_exists()
    test_ui_set_center_saves_to_profile()
    test_ui_set_center_skips_when_checkbox_off()
    test_ui_reset_center_clears_profile()
    test_unchecking_checkbox_clears_profile_center()
    print("ALL CENTER PROFILE TESTS PASSED")
