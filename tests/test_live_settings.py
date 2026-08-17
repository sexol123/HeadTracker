import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from config import AppSettings, Profile
from camera import Camera
from tracker import HeadTracker
from mouse_output import MouseOutput
from worker import TrackingWorker
from ui.main_window import MainWindow

app = QApplication([])

# --- Part A: worker.update_live_settings applies everything live ---
settings = AppSettings()
settings.mirror = True
settings.camera_rotation = 90
settings.image_enhance = True
settings.pose_smoothing = 0.3
settings.mouse_mode = "absolute"
settings.mouse_speed = 77.0
settings.mouse_hotkey = "f8"

worker = TrackingWorker()
worker._camera = Camera()
worker._tracker = HeadTracker(smoothing=0.0)
worker._output = MouseOutput(mode="velocity", speed=25.0)
worker.update_live_settings(settings)
assert worker._camera._mirror is True, worker._camera._mirror
assert worker._camera._rotation == 90, worker._camera._rotation
assert worker._camera._enhance is True, worker._camera._enhance
assert worker._tracker._smoothing == 0.3, worker._tracker._smoothing
assert worker._output._mode == "absolute", worker._output._mode
assert worker._output._speed == 77.0, worker._output._speed
assert worker._key_listener is None, "UI-thread call must not touch the listener"
assert worker._hotkey_request is not None, "hotkey restart must be deferred"
worker._process_hotkey_request()
assert worker._key_listener is not None, "hotkey listener not started by worker thread"
worker._stop_mouse_hotkey()
print("A. worker.update_live_settings: image options, smoothing, mouse mode/speed, deferred hotkey OK")

# --- Part B: UI wiring — live widgets push settings to worker ---
win = MainWindow(Profile())
win.show()
app.processEvents()

calls = []
class FakeWorker:
    def update_live_settings(self, s):
        calls.append(s)
    def update_profile(self, p):
        pass
win.worker = FakeWorker()

win.tracking_active = False
win.chk_mirror.setChecked(True)
assert len(calls) == 0, "pushed while not tracking"
print("B1. not pushed when tracking inactive OK")

win.tracking_active = True
win.chk_mirror.setChecked(False)
win.chk_mirror.setChecked(True)
win.chk_enhance.setChecked(True)
win.combo_rotation.setCurrentIndex(win.combo_rotation.findData(180))
win.slider_smoothing.setValue(65)
win.spin_mouse_speed.setValue(50.0)
win.combo_mouse_mode.setCurrentIndex(win.combo_mouse_mode.findData("absolute"))
win.combo_mouse_stop.setCurrentIndex(win.combo_mouse_stop.findData("toggle"))
win.combo_mouse_hotkey.setCurrentIndex(win.combo_mouse_hotkey.findData("f9"))
app.processEvents()
assert len(calls) == 9, f"expected 9 pushes (8 widgets, mirror toggled twice), got {len(calls)}"
s = calls[-1]
assert s.mirror is True and s.image_enhance is True and s.camera_rotation == 180
assert s.pose_smoothing == 0.65 and s.mouse_speed == 50.0
assert s.mouse_mode == "absolute" and s.mouse_stop_mode == "toggle" and s.mouse_hotkey == "f9"
print("B2. all live widgets pushed correct values to worker OK")

# --- Part C: locks — camera source & protocol stay locked, live widgets free ---
win._set_controls_enabled(False)
for w in (win.combo_profile, win.combo_rotation, win.chk_mirror, win.chk_enhance,
          win.slider_smoothing, win.spin_mouse_speed, win.combo_mouse_mode,
          win.combo_mouse_stop, win.combo_mouse_hotkey):
    assert w.isEnabled(), f"{w} should stay enabled during tracking"
for w in (win.combo_cam_type, win.combo_camera, win.edit_url, win.spin_width,
          win.spin_height, win.spin_fps, win.combo_protocol, win.edit_udp_host,
          win.spin_udp_port):
    assert not w.isEnabled(), f"{w} should stay locked during tracking"
print("C. lock/unlock split correct OK")

# --- Part D: profile switch live-pushes profile ---
class FakeWorker2:
    def __init__(self):
        self.profiles = []
    def update_profile(self, p):
        self.profiles.append(p)
win.worker = FakeWorker2()
win.tracking_active = True
if win.combo_profile.count() > 1:
    win.combo_profile.setCurrentIndex(1)
    app.processEvents()
    assert win.worker.profiles, "profile change did not push update_profile"
    print("D. profile switch pushes update_profile while tracking OK")
else:
    print("D. skipped: only one profile in list")

# --- Part E: autosave — live changes schedule save, stop saves settings ---
import ui.main_window as mw
saved_settings = []
saved_profiles = []
orig_ss, orig_sp = mw.save_settings, mw.save_profile
mw.save_settings = lambda s: saved_settings.append(s)
mw.save_profile = lambda p, path: saved_profiles.append((p, str(path)))
try:
    win.worker = FakeWorker()
    win.tracking_active = True
    win.chk_enhance.setChecked(False)
    app.processEvents()
    assert win._autosave_timer.isActive(), "settings autosave timer not scheduled"
    win._autosave_settings()
    assert len(saved_settings) == 1
    assert saved_settings[-1].image_enhance is False
    print("E1. settings autosave (debounce timer -> save) OK")

    win._current_profile_path = os.path.join(tempfile.gettempdir(), "ht_autosave_test.json")
    win._axis_widgets["yaw"]["sensitivity"].setValue(7.0)
    app.processEvents()
    assert win._profile_autosave_timer.isActive(), "profile autosave timer not scheduled"
    win._autosave_profile()
    assert len(saved_profiles) == 1
    assert saved_profiles[-1][0].axes["yaw"].sensitivity == 7.0
    assert saved_profiles[-1][1].endswith("ht_autosave_test.json")
    print("E2. profile autosave (axes change -> profile save) OK")

    class StopWorker:
        def stop_tracking(self):
            pass
    win.worker = StopWorker()
    win.tracking_active = True
    win._stop_tracking()
    assert len(saved_settings) >= 2, "tracking stop did not save settings"
    print("E3. stop saves settings OK")
finally:
    mw.save_settings, mw.save_profile = orig_ss, orig_sp

print("ALL LIVE SETTINGS TESTS PASSED")
