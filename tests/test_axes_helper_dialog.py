import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from config import Profile
from pose import Pose
from ui.axes_helper_dialog import AxesHelperDialog, axis_curve, AxisPlot

app = QApplication([])

class FakeWorker:
    def __init__(self):
        self._raw = Pose()
        self._mapped = Pose()
        self._running = False
        self._last_profile = None
    def isRunning(self): return self._running
    def get_raw_pose(self): return self._raw
    def get_mapped_pose(self): return self._mapped
    def update_profile(self, p): self._last_profile = p

prof = Profile()
prof.axes["x"].sensitivity = 2.5
prof.axes["x"].deadzone = 4.0
worker = FakeWorker()

applied = []
dlg = AxesHelperDialog(prof, worker)
dlg.on_axis_applied = lambda n, s, d, c=None: applied.append((n, s, d))

p_yaw = dlg._plots["yaw"]
assert abs(p_yaw.sens - 6.0) < 0.01 and abs(p_yaw.dz - 2.0) < 0.01, (p_yaw.sens, p_yaw.dz)
p_x = dlg._plots["x"]
assert abs(p_x.sens - 2.5) < 0.01 and abs(p_x.dz - 4.0) < 0.01
print("1. plots initialized from profile OK")

c = axis_curve(10, 6, 2, False)
assert abs(c - 60.0) < 0.01, c
assert axis_curve(1.5, 6, 2, False) == 0.0
assert abs(axis_curve(5, 6, 2, True) + 30.0) < 0.01
print("2. curve math OK (matches worker._apply_mapping)")

dz_px = p_yaw._px(p_yaw.dz, 0)
QTest.mousePress(p_yaw, Qt.LeftButton, pos=QPoint(int(dz_px.x()), int(dz_px.y())))
tgt = p_yaw._px(8.0, 0)
QTest.mouseMove(p_yaw, QPoint(int(tgt.x()), int(tgt.y())))
QTest.mouseRelease(p_yaw, Qt.LeftButton, pos=QPoint(int(tgt.x()), int(tgt.y())))
assert abs(p_yaw.dz - 8.0) < 0.01, p_yaw.dz
assert applied and applied[-1][:1] == ("yaw",) and abs(applied[-1][2] - 8.0) < 0.01, applied[-1]
print("3. dz handle drag OK:", applied[-1])

pt = p_yaw._px(30.0, 0)
QTest.mousePress(p_yaw, Qt.LeftButton, pos=QPoint(int(pt.x()), int(pt.y())))
tgt = p_yaw._px(30.0, 120.0)
QTest.mouseMove(p_yaw, QPoint(int(tgt.x()), int(tgt.y())))
QTest.mouseRelease(p_yaw, Qt.LeftButton, pos=QPoint(int(tgt.x()), int(tgt.y())))
assert abs(p_yaw.sens - 4.0) < 0.3, p_yaw.sens
assert applied[-1][:2] == ("yaw", p_yaw.sens), applied[-1]
print("4. sens curve drag OK:", applied[-1])

worker._running = True
worker._raw = Pose(yaw=15.0, pitch=-3.0, roll=5.0, x=6.0, y=-2.0, z=30.0, confidence=0.9)
worker._mapped = Pose(yaw=90.0, pitch=0.0, roll=5.0, x=6.0, y=-2.0, z=0.0, confidence=0.9)
dlg._refresh_live()
assert abs(p_yaw.live_raw - 15.0) < 0.01 and abs(p_yaw.live_mapped - 90.0) < 0.01
assert dlg.lbl_status.text() != ""
print("5. live refresh OK, status:", dlg.lbl_status.text())

out_dir = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(out_dir, exist_ok=True)
png = os.path.join(out_dir, "axes_helper_dialog.png")
dlg.resize(dlg.sizeHint())
dlg.grab().save(png)
print("6. screenshot saved:", png)
print("ALL AXES DIALOG TESTS PASSED")
