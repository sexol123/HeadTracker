import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from config import Profile
from pose import Pose
from worker import TrackingWorker
from ui.main_window import MainWindow
from ui.axes_helper_dialog import axis_curve

app = QApplication([])

prof = Profile()
prof.axes["yaw"].sensitivity = 6.0
prof.axes["yaw"].deadzone = 2.0
prof.axes["pitch"].inverted = True

raw = Pose(yaw=10.0, pitch=5.0, roll=3.0, x=4.0, y=6.0, z=8.0, confidence=0.9)
mapped = TrackingWorker._apply_mapping(raw, prof)
for name in ("yaw", "pitch", "roll", "x", "y", "z"):
    ax = prof.axes[name]
    exp = axis_curve(getattr(raw, name), ax.sensitivity, ax.deadzone, ax.inverted)
    assert abs(getattr(mapped, name) - exp) < 1e-9, (name, getattr(mapped, name), exp)
print("1. worker._apply_mapping == axis_curve for all 6 axes OK")

win = MainWindow(Profile())
win.show()
app.processEvents()
assert win.btn_axes_setup.text() != ""
print("2. button exists:", win.btn_axes_setup.text())

import ui.axes_helper_dialog as ahd
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

dlg.on_axis_applied("yaw", 12.0, 3.5)
assert abs(win._axis_widgets["yaw"]["sensitivity"].value() - 12.0) < 0.05
assert abs(win._axis_widgets["yaw"]["deadzone"].value() - 3.5) < 0.05
assert abs(win.profile.axes["yaw"].sensitivity - 12.0) < 0.01
assert abs(win.profile.axes["yaw"].deadzone - 3.5) < 0.01
print("3. plot drag -> spinbox -> profile chain OK")

dlg.on_axis_applied("z", 0.1, 0.0)
assert abs(win.profile.axes["z"].sensitivity - 0.1) < 0.01
assert abs(win.profile.axes["z"].deadzone - 0.0) < 0.01
print("4. edge values (sens 0.1, dz 0) OK")

win._refresh_ui_text()
print("5. refresh_ui_text OK")
out_dir = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(out_dir, exist_ok=True)
png = os.path.join(out_dir, "axes_helper_integration.png")
dlg.resize(dlg.sizeHint())
dlg.grab().save(png)
print("6. screenshot saved:", png)
print("INTEGRATION TEST PASSED")
