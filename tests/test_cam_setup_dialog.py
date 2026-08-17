import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtTest import QTest
from ui.cam_setup_dialog import CamSetupDialog, CAM_DEFAULT

app = QApplication([])

pitch_dlg = math.degrees(math.atan2(15.0, 10.0))     # 56.31
yaw_dlg = math.degrees(math.asin(30.0 / 35.0))       # 59.0
applied = []
dlg = CamSetupDialog(offset_x_cm=-30, offset_y_cm=15, offset_z_cm=50,
                     yaw=round(yaw_dlg, 1), pitch=round(pitch_dlg, 1), roll=4)
dlg.apply_callback = lambda *v: applied.append(v)
v = dlg.view

# 1. initial values: point from offsets, auto-aim + passthrough oz/roll
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert abs(ox + 30) < 0.01 and abs(oy - 15) < 0.01 and abs(oz - 50) < 0.01, (ox, oy, oz)
assert abs(yaw - yaw_dlg) < 0.5 and abs(pitch - pitch_dlg) < 0.5, (yaw, pitch)
assert roll == 4.0, roll
print("1. initial values OK:", tuple(round(x, 2) for x in dlg._values()))

# 2. pixel <-> cm mapping round-trip
p = v._to_px(10.0, 20.0)
r = v._from_px(p)
assert abs(r.x() - 10.0) < 0.5 and abs(r.y() - 20.0) < 0.5, r
print("2. mapping round-trip OK:", (round(r.x(), 1), round(r.y(), 1)))

# 2b. clicking the screen center places the marker at the origin
sc = v.screen_rect()
center_px = QPoint(int(sc.center().x()), int(sc.center().y()))
QTest.mousePress(v, Qt.LeftButton, pos=center_px)
QTest.mouseRelease(v, Qt.LeftButton, pos=center_px)
ox, oy, *_ = dlg._values()
assert abs(ox) < 0.5 and abs(oy) < 0.5, (ox, oy)
print("2b. screen center -> origin OK:", (round(ox, 2), round(oy, 2)))

# 3. click on the screen moves the camera point
goal = QPoint(int(v._to_px(40.0, -5.0).x()), int(v._to_px(40.0, -5.0).y()))
QTest.mousePress(v, Qt.LeftButton, pos=goal)
QTest.mouseRelease(v, Qt.LeftButton, pos=goal)
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert abs(ox - 40.0) < 1.0 and abs(oy + 5.0) < 1.0, (ox, oy)
assert abs(oz - 50.0) < 0.01, "oz must pass through untouched"
assert abs(roll - 4.0) < 0.01, "roll must pass through untouched"
print("3. click places camera OK:", (round(ox, 1), round(oy, 1)))

# 4. drag follows the cursor
px0 = v._to_px(v.cam.x(), v.cam.y())
drag_goal = QPoint(int(px0.x()) + 50, int(px0.y()) + 40)
exp = v._from_px(QPointF(drag_goal))
QTest.mousePress(v, Qt.LeftButton, pos=QPoint(int(px0.x()), int(px0.y())))
QTest.mouseMove(v, drag_goal)
QTest.mouseRelease(v, Qt.LeftButton, pos=drag_goal)
ox, oy, *_ = dlg._values()
assert abs(ox - exp.x()) < 0.5 and abs(oy - exp.y()) < 0.5, (ox, oy, exp)
print("4. drag moves camera OK:", (round(ox, 1), round(oy, 1)))

# 5. clicks outside the monitor are ignored
QTest.mousePress(v, Qt.LeftButton, pos=QPoint(5, 150))
QTest.mouseRelease(v, Qt.LeftButton, pos=QPoint(5, 150))
ox, oy, *_ = dlg._values()
assert abs(ox - exp.x()) < 0.5, "camera must not move on outside click"
print("5. outside click ignored OK")

# 6. reset -> top-center default
dlg._on_reset()
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert ox == CAM_DEFAULT[0] and abs(oy - CAM_DEFAULT[1]) < 0.01, (ox, oy)
assert oz == CAM_DEFAULT[2] and roll == 0.0, (oz, roll)
print("6. reset OK:", tuple(round(x, 2) for x in dlg._values()))

# 7. fresh dialog -> defaults
d2 = CamSetupDialog()
ox, oy, oz, *_ = d2._values()
assert abs(ox - CAM_DEFAULT[0]) < 0.01 and abs(oy - CAM_DEFAULT[1]) < 0.01 and oz == CAM_DEFAULT[2]
print("7. fresh defaults OK")

assert len(applied) > 0, "apply_callback never fired"
print("8. apply_callback fired", len(applied), "times")

out_dir = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(out_dir, exist_ok=True)
png = os.path.join(out_dir, "cam_setup_dialog.png")
dlg.resize(dlg.sizeHint())
dlg.grab().save(png)
print("9. screenshot saved:", png)
print("ALL DIALOG TESTS PASSED")