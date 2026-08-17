import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from config import Profile, AxisConfig, save_profile, load_profile, PROFILES_DIR
from ui.main_window import MainWindow

app = QApplication([])


def make_profile(name, sens_map, deadzone=0.5):
    p = Profile(name=name)
    for axis, sens in sens_map.items():
        p.axes[axis] = AxisConfig(enabled=True, sensitivity=sens, deadzone=deadzone)
    p.center_pose = {"yaw": 1.0, "pitch": 2.0, "roll": 0.0, "x": 0.0, "y": 0.0, "z": -500.0}
    return p


# --- Part A: startup must populate axis widgets from the loaded profile ---
loaded = load_profile(PROFILES_DIR / "default.json")
win = MainWindow(loaded)
win.show()
app.processEvents()

expected_sens = {"yaw": 6.0, "pitch": 6.0, "roll": 6.0, "x": 1.0, "y": 1.0, "z": 1.0}
widget_sens = {n: w["sensitivity"].value() for n, w in win._axis_widgets.items()}
assert widget_sens == expected_sens, f"widget sens {widget_sens} != {expected_sens}"
print("A1. axis widgets populated from loaded profile OK")

profile_sens = {n: a.sensitivity for n, a in win.profile.axes.items()}
assert profile_sens == expected_sens, f"profile corrupted to {profile_sens}"
for n, a in win.profile.axes.items():
    assert a.deadzone == 0.5, f"deadzone {n} corrupted to {a.deadzone}"
print("A2. in-memory profile not corrupted by widget population OK")

assert win._current_profile_path is not None, "profile path not set at startup"
assert os.path.basename(str(win._current_profile_path)) == "default.json"
print("A3. current profile path set at startup OK")
win._current_profile_path = os.path.join(tempfile.gettempdir(), "ht_widgets_guard.json")

# --- Part B: read-back at Start keeps profile values and center ---
rp = win._read_profile_from_ui()
rb_sens = {n: a.sensitivity for n, a in rp.axes.items()}
assert rb_sens == expected_sens, f"read-back sens {rb_sens}"
assert rp.center_pose == win.profile.center_pose, "center_pose dropped by read-back"
print("B1. read-back preserves sensitivity and center_pose OK")

# --- Part C: non-default profile with custom curve survives the round trip ---
tmp_path = os.path.join(tempfile.gettempdir(), "ht_widgets_test.json")
save_profile(make_profile("Widgets", {"yaw": 2.5, "pitch": 3.0, "roll": 1.0,
                                      "x": 2.0, "y": 1.5, "z": 1.0},
                          deadzone=1.0), tmp_path)
try:
    p2 = load_profile(tmp_path)
    win2 = MainWindow(p2)
    win2.show()
    app.processEvents()
    win2._current_profile_path = os.path.join(tempfile.gettempdir(), "ht_widgets_guard2.json")
    assert win2._axis_widgets["yaw"]["sensitivity"].value() == 2.5
    assert win2._axis_widgets["z"]["deadzone"].value() == 1.0
    assert win2.profile.axes["pitch"].sensitivity == 3.0
    assert win2.profile.center_pose == p2.center_pose
    print("C1. custom profile values survive init OK")
    win2.close()
finally:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass

win.close()
print("ALL PROFILE WIDGET TESTS PASSED")
