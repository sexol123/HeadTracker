import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication

from config import Profile
import ui.main_window as mw
from ui.main_window import MainWindow

app = QApplication([])


class FakeWorker:
    def __init__(self):
        self.calls = []

    def start_tracking(self, profile, settings):
        self.calls.append("start")

    def stop_tracking(self):
        self.calls.append("stop")

    def get_raw_pose(self):
        from tracker import Pose
        return Pose()


saved_settings = 0
orig_ss, orig_sp = mw.save_settings, mw.save_profile
mw.save_settings = lambda s: saved_settings + 1
mw.save_profile = lambda p, path: None

win = MainWindow(Profile())
win.worker = FakeWorker()


def pump():
    for _ in range(10):
        app.processEvents()


# 1. minimize while tracking -> paused, worker stopped
win.tracking_active = True
win._paused_by_minimize = False
win.showMinimized()
pump()
assert not win.tracking_active, "tracking must stop on minimize"
assert win._paused_by_minimize, "pause flag must be set on minimize"
assert win.worker.calls[-1] == "stop", win.worker.calls
print("1. minimize pauses tracking OK")

# 2. restore -> tracking resumes
win.showNormal()
pump()
assert win.tracking_active, "tracking must resume on restore"
assert not win._paused_by_minimize, "pause flag must be cleared on restore"
assert win.worker.calls[-1] == "start", win.worker.calls
print("2. restore resumes tracking OK")

# 3. minimize while not tracking -> worker untouched
win._stop_tracking()
before = len(win.worker.calls)
win.showMinimized()
pump()
assert len(win.worker.calls) == before, win.worker.calls
assert not win._paused_by_minimize
print("3. minimize without tracking does nothing OK")

# 4. manual start while paused -> restore must not double-start
win.showNormal()
pump()
win.tracking_active = True
win.worker.calls = []
win._start_tracking()
win.showMinimized()
pump()
assert win._paused_by_minimize
win.worker.calls = []
win._btn_locked = False
win._on_start_stop()
assert win.tracking_active, "manual start must start tracking"
assert not win._paused_by_minimize, "manual start clears the pause flag"
win.showNormal()
pump()
assert win.worker.calls == ["start"], "restore must not start a second time"
print("4. no double start after manual start while paused OK")

# 5. stopped tracking -> minimize does not pause; restore does not resume
win.showNormal()
pump()
win.tracking_active = False
win.worker.calls = []
win._paused_by_minimize = False
win.showMinimized()
pump()
assert not win._paused_by_minimize
win.showNormal()
pump()
assert win.worker.calls == [], "no start/stop when tracking was already off"
print("5. no pause/resume when tracking was already off OK")

# 6. both preview labels exist, cockpit renders without mode combo
assert win.preview_label is not None
assert win.cockpit_label is not None
assert hasattr(win, "combo_preview_mode") is False, "mode combo must be gone"
from tracker import Pose
win.cockpit_label.resize(320, 180)
win._render_cockpit_preview(Pose(), Pose())
assert not win.cockpit_label.pixmap().isNull(), "cockpit must render into its label"
print("6. camera + cockpit labels both present, cockpit renders OK")

# 7. cockpit mirrors yaw like the in-game view
class SpyRenderer:
    def __init__(self):
        self.kwargs = None

    def set_fov(self, fov):
        pass

    def render(self, **kw):
        self.kwargs = dict(kw)
        from PySide6.QtGui import QImage
        return QImage(1, 1, QImage.Format_RGB32)

win._cockpit_renderer = SpyRenderer()
from tracker import Pose as P
win._render_cockpit_preview(P(yaw=15.0, pitch=2.0, roll=-1.0),
                            P(yaw=10.0, pitch=3.0, roll=-2.0))
k = win._cockpit_renderer.kwargs
assert k["yaw_deg"] == -10.0, k
assert k["sent"]["yaw"] == -10.0 and k["raw"]["yaw"] == -15.0, k
assert k["pitch_deg"] == 3.0 and k["sent"]["pitch"] == 3.0 and k["raw"]["pitch"] == 2.0
assert k["roll_deg"] == -2.0 and k["sent"]["roll"] == -2.0
print("7. cockpit mirrors yaw like the game OK")

win.close()
mw.save_settings, mw.save_profile = orig_ss, orig_sp
print("ALL MINIMIZE-PAUSE TESTS PASSED")