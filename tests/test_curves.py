import os
import sys
import json
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest

from config import Profile, AxisConfig, save_profile, load_profile
from pose import Pose
from worker import TrackingWorker, _apply_curve
from ui.axes_helper_dialog import AxesHelperDialog, axis_curve
from ui.main_window import MainWindow

app = QApplication([])


def test_linear_when_no_curve():
    assert abs(axis_curve(10, 6, 2, False) - 60.0) < 1e-9
    assert abs(_apply_curve(10.0, 6.0, None) - 60.0) < 1e-9
    print("PASS: curve=None keeps linear mapping")


def test_piecewise_math():
    curve = [20.0, 60.0]  # steeper at small angles (60/20 = 3 vs sens 6? no: 3 < 6, flatter)
    assert abs(axis_curve(10, 6, 0, False, curve) - 30.0) < 1e-9, axis_curve(10, 6, 0, False, curve)
    assert abs(axis_curve(20, 6, 0, False, curve) - 60.0) < 1e-9
    assert abs(axis_curve(30, 6, 0, False, curve) - (60.0 + 6 * 10)) < 1e-9
    assert abs(axis_curve(-10, 6, 0, False, curve) + 30.0) < 1e-9, "negative side must mirror"
    assert abs(axis_curve(-30, 6, 0, False, curve) + 120.0) < 1e-9
    print("PASS: piecewise through (0,0)->(x2,y2)->sens slope, mirrored for negatives")


def test_curve_boost_small_movements():
    curve = [10.0, 90.0]  # slope 9 > sens 6 -> boost near center
    assert axis_curve(10, 6, 0, False, curve) > 6 * 10, "must exceed linear at small x"
    assert abs(axis_curve(10, 6, 0, False, curve) - 90.0) < 1e-9
    assert abs(axis_curve(30, 6, 0, False, curve) - (90.0 + 6 * 20)) < 1e-9
    print("PASS: curve above linear line boosts small movements")


def test_curve_with_deadzone_and_inverted():
    curve = [20.0, 60.0]
    assert axis_curve(1.0, 6, 2, False, curve) == 0.0, "deadzone still applies"
    assert abs(axis_curve(10, 6, 2, True, curve) + 30.0) < 1e-9, "inverted flips sign"
    print("PASS: deadzone and inverted combine with curve")


def test_bad_curve_falls_back_to_linear():
    for bad in ([0.0, 5.0], [1.0], [], "x"):
        assert abs(axis_curve(10, 6, 0, False, bad) - 60.0) < 1e-9, bad
    assert abs(_apply_curve(10.0, 6.0, [0.0, 5.0]) - 60.0) < 1e-9
    assert abs(_apply_curve(10.0, 6.0, []) - 60.0) < 1e-9
    print("PASS: malformed curve values fall back to linear")


def test_worker_mapping_matches_axis_curve_with_curve():
    prof = Profile()
    prof.axes["yaw"].curve = [20.0, 60.0]
    prof.axes["pitch"].curve = [10.0, 90.0]
    prof.axes["roll"].curve = [30.0, 30.0]
    prof.axes["yaw"].inverted = True
    raw = Pose(yaw=10.0, pitch=5.0, roll=40.0, x=4.0, y=6.0, z=8.0, confidence=0.9)
    mapped = TrackingWorker._apply_mapping(raw, prof)
    for name in ("yaw", "pitch", "roll", "x", "y", "z"):
        ax = prof.axes[name]
        exp = axis_curve(getattr(raw, name), ax.sensitivity, ax.deadzone, ax.inverted, ax.curve)
        assert abs(getattr(mapped, name) - exp) < 1e-9, (name, getattr(mapped, name), exp)
    print("PASS: worker._apply_mapping == axis_curve with curves on all axes")


def test_profile_roundtrip_with_curve():
    p = Profile(name="Curved")
    p.axes["yaw"].curve = [15.0, 45.0]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "c.json"
        save_profile(p, path)
        loaded = load_profile(path)
    assert loaded.axes["yaw"].curve == [15.0, 45.0]
    print("PASS: profile roundtrip keeps curve")


def test_old_profile_without_curve_backward_compat():
    raw = {"name": "Old", "axes": {"yaw": {"sensitivity": 7.0, "deadzone": 1.0, "inverted": False}}}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "old.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        loaded = load_profile(path)
    assert loaded.axes["yaw"].curve is None
    assert loaded.axes["yaw"].sensitivity == 7.0
    assert AxisConfig(enabled=True, sensitivity=6.0, deadzone=2.0).curve is None
    print("PASS: profiles without curve field load fine")


class FakeWorker:
    def isRunning(self):
        return False

    def get_raw_pose(self):
        return Pose()

    def get_mapped_pose(self):
        return Pose()


def test_dialog_loads_curve_and_drags_handle():
    prof = Profile()
    prof.axes["yaw"].curve = [20.0, 60.0]
    dlg = AxesHelperDialog(prof, FakeWorker())
    p_yaw = dlg._plots["yaw"]
    assert p_yaw.curve == [20.0, 60.0]

    applied = []
    dlg.on_axis_applied = lambda n, s, d, c=None: applied.append((n, s, d, c))

    h = p_yaw._px(20.0, 60.0)
    QTest.mousePress(p_yaw, Qt.LeftButton, pos=QPoint(int(h.x()), int(h.y())))
    tgt = p_yaw._px(30.0, 90.0)
    QTest.mouseMove(p_yaw, QPoint(int(tgt.x()), int(tgt.y())))
    QTest.mouseRelease(p_yaw, Qt.LeftButton, pos=QPoint(int(tgt.x()), int(tgt.y())))
    assert p_yaw.curve[0] == 30.0, p_yaw.curve
    assert abs(p_yaw.curve[1] - 90.0) < 10.0, p_yaw.curve
    assert applied[-1][3] == p_yaw.curve, applied[-1]
    print("PASS: curve handle drag updates plot and fires callback")


def test_apply_axis_chain_to_profile():
    import ui.axes_helper_dialog as ahd
    win = MainWindow(Profile())
    win.show()
    app.processEvents()

    instances = []
    orig_exec = ahd.AxesHelperDialog.exec
    def fake_exec(self):
        instances.append(self)
        return 0
    ahd.AxesHelperDialog.exec = fake_exec
    try:
        win._on_axes_setup()
    finally:
        ahd.AxesHelperDialog.exec = orig_exec
    assert len(instances) == 1
    dlg = instances[0]

    dlg.on_axis_applied("yaw", 12.0, 3.5, [25.0, 75.0])
    assert win.profile.axes["yaw"].curve == [25.0, 75.0]
    assert abs(win.profile.axes["yaw"].sensitivity - 12.0) < 0.01
    dlg.on_axis_applied("yaw", 12.0, 3.5, None)
    assert win.profile.axes["yaw"].curve is None, "None curve clears it"
    print("PASS: dialog -> main window -> profile chain keeps curve")


if __name__ == "__main__":
    test_linear_when_no_curve()
    test_piecewise_math()
    test_curve_boost_small_movements()
    test_curve_with_deadzone_and_inverted()
    test_bad_curve_falls_back_to_linear()
    test_worker_mapping_matches_axis_curve_with_curve()
    test_profile_roundtrip_with_curve()
    test_old_profile_without_curve_backward_compat()
    test_dialog_loads_curve_and_drags_handle()
    test_apply_axis_chain_to_profile()
    print("ALL CURVE TESTS PASSED")
