import math
import os
import random
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from pose import Pose
import ui.calibration_wizard as cw_mod
from ui.tuning_assistant import analyze_calibration, TuningRecorder, MIN_SAMPLES, CALIB_DIRS
from ui.calibration_wizard import CalibrationWizard

app = QApplication([])


def make_samples(n, axis, k=1.0, phase=0.0, offset=0.0, noise=0.0):
    """Synthetic tuning samples: raw = sin sweep, mapped = k * raw (+ noise)."""
    samples = []
    for i in range(n):
        t = i / 60.0
        raw = 25.0 * math.sin(2 * math.pi * 0.5 * t + phase) + offset
        mapped = k * raw + noise * (i % 7 - 3)
        samples.append({
            "t": t,
            "raw": {a: (raw if a == axis else 0.0) for a in ("yaw", "pitch", "roll", "x", "y", "z")},
            "mapped": {a: (mapped if a == axis else 0.0) for a in ("yaw", "pitch", "roll", "x", "y", "z")},
            "confidence": 1.0,
        })
    return samples


def segments_for(**kwargs):
    return [{"dir": d, "samples": make_samples(120, axis, **kwargs)}
            for d, axis in (("left", "yaw"), ("right", "yaw"), ("up", "pitch"), ("down", "pitch"))]


print("--- analyze_calibration (pure) ---")

# 1. gain 0.5 -> sensitivity factor 2.0; pitch gain 1.0 -> untouched
segments = [{"dir": d, "samples": make_samples(120, "yaw", k=0.5)} for d in ("left", "right")]
segments += [{"dir": d, "samples": make_samples(120, "pitch", k=1.0)} for d in ("up", "down")]
a = analyze_calibration(segments)
assert a["ok"], a["recommendations"]
assert a["changes"]["axes"]["yaw"]["sensitivity"] == 2.0, a["changes"]
assert "pitch" not in a["changes"].get("axes", {}), a["changes"]
print("1. gain 0.5 -> yaw factor 2.0, pitch untouched OK")

# 2. inverted -> change
a = analyze_calibration(segments_for(k=-0.5))
assert a["ok"]
assert a["changes"]["axes"]["yaw"].get("inverted") is True, a["changes"]
print("2. inverted detection OK:", a["changes"]["axes"]["yaw"])

# 3. insufficient data -> ok False, empty changes
poor = [{"dir": d, "samples": make_samples(5, axis)} for d, axis in (("left", "yaw"), ("right", "yaw"), ("up", "pitch"), ("down", "pitch"))]
a = analyze_calibration(poor)
assert not a["ok"] and not a["changes"], (a["ok"], a["changes"])
print("3. insufficient samples -> not ok OK")

# 4. drift -> recenter
a = analyze_calibration(segments_for(k=1.0, offset=8.0))
assert a["changes"].get("recenter") is True, a["changes"]
print("4. drift -> recenter OK")

# 5. noise destroys correlation -> no gain change on that axis
a = analyze_calibration(segments_for(k=0.5, phase=0.0))
# replace yaw samples (left+right) with pure noise -> corr ~ 0 -> no change
noise = [{"dir": d, "samples": make_samples(120, "yaw", k=0.5, phase=0.0)} for d in ("left", "right")]
pts = [{"dir": d, "samples": make_samples(120, "pitch", k=1.0)} for d in ("up", "down")]
segments = noise + pts
for seg in segments[:2]:
    for s in seg["samples"]:
        s["raw"]["yaw"] = random.uniform(-25, 25)
        s["mapped"]["yaw"] = random.uniform(-25, 25)
a = analyze_calibration(segments)
assert a["ok"]
assert a["changes"].get("axes", {}).get("yaw") is None, a["changes"]
print("5. low correlation -> axis untouched OK")

# 6c. apply never pollutes the app logs: export is intercepted
exports = []


def fake_export(samples, profile_name, analysis, out_dir=None):
    exports.append((profile_name, analysis, list(samples)))
    return "logs/fake.json"


cw_mod.export_tuning = fake_export

print("6. injected recorder + export interception OK")

print("PURE ANALYSIS TESTS PASSED")


print("--- CalibrationWizard smoke ---")

class FakeWorker:
    def __init__(self):
        self._raw = Pose()
        self._mapped = Pose()
        self._running = False
        self._frame = None
    def isRunning(self): return self._running
    def get_raw_pose(self): return self._raw
    def get_mapped_pose(self): return self._mapped
    def get_last_frame(self): return self._frame


class FakeWindow:
    def __init__(self):
        self.calls = []
        self.applied = []
        self.cam_values = None
    def start_tracking(self): self.calls.append("start")
    def stop_tracking(self): self.calls.append("stop")
    def tracking_active(self): return False
    def recenter_save(self): return True
    def apply_changes(self, changes): self.applied.append(changes)
    def apply_cam(self, ox, oy, oz, yaw, pitch, roll): self.cam_values = (ox, oy, oz, yaw, pitch, roll)
    def profile_name(self): return "Default"


win = FakeWindow()
worker = FakeWorker()
rec = TuningRecorder()
w = CalibrationWizard(rec, worker, win.start_tracking, win.stop_tracking, win.tracking_active,
                      win.recenter_save, win.apply_changes, win.apply_cam, win.profile_name)

w.reset_state()
assert win.calls == ["start"], win.calls
assert w._we_started_tracking and w._timer.isActive()
assert w._stack.count() == 7, w._stack.count()
assert w._recorder is rec, "wizard must use the recorder supplied by the main window"
print("7. wizard built, tracking auto-started OK")

# camera page: cam widget present, values forwarded
assert w._cam_widget is not None
w._on_cam_values(-3.0, 1.5, 50.0, 10.0, 20.0, 0.0)
assert win.cam_values == (-3.0, 1.5, 50.0, 10.0, 20.0, 0.0), win.cam_values
print("8. camera values forwarded OK")

# 8b. the wizard records through the recorder injected by the main window,
# fed exactly like main_window._on_worker_pose feeds it
w2 = CalibrationWizard(rec, worker, win.start_tracking, win.stop_tracking,
                       win.tracking_active, win.recenter_save, win.apply_changes,
                       win.apply_cam, win.profile_name)
assert w2._recorder is rec, "wizard must use the main-window recorder"
rec.start()
for i in range(3):
    rec.add(Pose(yaw=i, pitch=0.0, confidence=1.0), Pose(yaw=i * 0.5, pitch=0.0, confidence=1.0))
rec.stop()
w2._on_ready("left")
assert len(w2._segments["left"]) == 3, w2._segments["left"]
del w2
print("8b. injected recorder fed from pose stream OK")

# center step: blocked until center; then Next to left
w._go_page(1)
w._on_next()
assert w._current_page() == 1, w._current_page()
w._on_center()
assert w._center_ok and "Center" in w.lbl_status.text()
w._on_next()
assert w._current_page() == 2, w._current_page()
print("9. center gate and navigation OK")

# direction step: gated on data; record/ready flow stores segment
buttons = w._dir_buttons["left"]
w._on_next()
assert w._current_page() == 2, w._current_page()
records = []
w._recorder.samples = make_samples(80, "yaw", k=0.5, phase=0.0)
w._on_ready("left")
assert len(w._segments["left"]) == 80 and not w._recorder.recording
w._on_next()
assert w._current_page() == 3, w._current_page()
print("10. direction record/ready gate OK")

for idx, direction in enumerate(CALIB_DIRS):
    w._recorder.samples = make_samples(
        80, "pitch" if direction in ("up", "down") else "yaw",
        k=0.5 if direction in ("left", "right") else 1.0,
        phase=float(idx))
    w._on_ready(direction)

w._go_page(5)
w._on_next()
assert w._current_page() == 6, w._current_page()
assert w.btn_apply.isEnabled(), "apply should be enabled with changes"
w._on_apply()
assert exports, "apply must export the merged session (intercepted)"
assert exports[0][0] == "Default", exports[0][0]
assert len(exports[0][2]) == 320, len(exports[0][2])
assert win.applied, "apply_changes never called"
assert win.applied[0]["axes"]["yaw"]["sensitivity"] == 2.0, win.applied[0]
assert w._finished
print("11. results -> apply OK:", win.applied[0])

# retry resets segments and jumps to tracking page
w._on_retry()
assert not w._segments and not w._center_ok and w._current_page() == 1
print("12. retry resets state OK")

# live refresh with running worker does not throw
worker._running = True
worker._raw = Pose(yaw=10.0, pitch=-5.0, roll=2.0, x=3.0, y=-1.0, z=20.0, confidence=0.9)
worker._mapped = Pose(yaw=30.0, pitch=-15.0, roll=2.0, x=3.0, y=-1.0, z=0.0, confidence=0.9)
w._refresh_live()
assert "90%" in w.lbl_conf.text(), w.lbl_conf.text()
print("13. live refresh OK:", w.lbl_conf.text())

out_dir = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(out_dir, exist_ok=True)
png = os.path.join(out_dir, "calibration_wizard.png")
w.resize(760, 600)
w.grab().save(png)
print("14. screenshot saved:", png)
print("ALL WIZARD TESTS PASSED")