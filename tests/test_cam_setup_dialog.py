import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QPoint
from PySide6.QtTest import QTest
from ui.cam_setup_dialog import CamSetupDialog, SetupView

app = QApplication([])

pitch_dlg = math.degrees(math.atan2(15.0, 10.0))     # 56.31
yaw_dlg = math.degrees(math.asin(30.0 / 35.0))       # 59.0
applied = []
dlg = CamSetupDialog(offset_x_cm=-30, offset_y_cm=15, offset_z_cm=50, yaw=round(yaw_dlg, 1), pitch=round(pitch_dlg, 1), roll=0)
dlg.apply_callback = lambda *v: applied.append(v)

ox, oy, oz, yaw, pitch, roll = dlg._values()
assert abs(ox + 30) < 0.01 and abs(oy - 15) < 0.01 and abs(oz - 50) < 0.01, (ox, oy, oz)
assert abs(yaw - yaw_dlg) < 0.5 and abs(pitch - pitch_dlg) < 0.5, (yaw, pitch)
assert dlg.chk_auto_aim.isChecked(), "auto-aim should be on for matched angles"
print("1. initial values OK:", tuple(round(v, 2) for v in dlg._values()))

v = dlg.view_top
QTest.mousePress(v, Qt.LeftButton, pos=QPoint(120, 180))
QTest.mouseMove(v, QPoint(210, 180))
QTest.mouseRelease(v, Qt.LeftButton, pos=QPoint(210, 180))
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert abs(ox) < 0.01 and abs(yaw) < 0.5, (ox, yaw)
print("2. drag cam top -> center OK, yaw:", round(yaw, 2))

v = dlg.view_side
a = math.radians(v.angle)
cam_px = v._to_px(v.cam)
d = v._axis_dir()
handle = QPoint(int(cam_px.x() - 40 * d.x()), int(cam_px.y() - 40 * d.y()))
dlg.chk_auto_aim.setChecked(False)
QTest.mousePress(v, Qt.LeftButton, pos=handle)
QTest.mouseMove(v, QPoint(int(cam_px.x()), int(cam_px.y() - 46)))
QTest.mouseRelease(v, Qt.LeftButton, pos=QPoint(int(cam_px.x()), int(cam_px.y() - 46)))
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert abs(pitch + 90) < 1.0, pitch
print("4. rot handle manual OK, pitch:", round(pitch, 2))

dlg.chk_auto_aim.setChecked(True)
v = dlg.view_side
QTest.mousePress(v, Qt.LeftButton, pos=QPoint(240, 150))
QTest.mouseMove(v, QPoint(300, 150))
QTest.mouseRelease(v, Qt.LeftButton, pos=QPoint(300, 150))
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert abs(v.head.x() - 80) < 0.01 and abs(v.head.y()) < 0.01, v.head
assert abs(pitch - 26.57) < 1.0, pitch
print("5. drag head side OK, pitch:", round(pitch, 2), "head:", (round(v.head.x(), 1), round(v.head.y(), 1)))

dlg.slider_roll.setValue(12)
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert roll == 12
print("5. roll slider OK:", roll)

dlg._on_reset()
ox, oy, oz, yaw, pitch, roll = dlg._values()
assert abs(ox) < 0.01 and abs(oy - 15) < 0.01 and abs(oz - 50) < 0.01 and roll == 0, dlg._values()
print("6. reset OK:", tuple(round(v, 2) for v in dlg._values()))

assert len(applied) > 0, "apply_callback never fired"
print("7. apply_callback fired", len(applied), "times")

print("-- consistency between views --")
d2 = CamSetupDialog()
vt, vs = d2.view_top, d2.view_side

def assert_synced(tag):
    assert abs(vt.cam.y() - vs.cam.x()) < 0.01, f"{tag}: cam z desync top={vt.cam.y():.2f} side={vs.cam.x():.2f}"
    assert abs(vt.head.y() - vs.head.x()) < 0.01, f"{tag}: head z desync"
    ox, oy, oz, *_ = d2._values()
    assert abs(oz - vt.cam.y()) < 0.01 and abs(oz - vs.cam.x()) < 0.01, f"{tag}: oz {oz} != cam z"
    assert abs(ox - vt.cam.x()) < 0.01, f"{tag}: ox {ox} != top x {vt.cam.x()}"
    assert abs(oy - vs.cam.y()) < 0.01, f"{tag}: oy {oy} != side y {vs.cam.y()}"

assert_synced("initial")
QTest.mousePress(vt, Qt.LeftButton, pos=QPoint(210, 180))
QTest.mouseMove(vt, QPoint(330, 240))
QTest.mouseRelease(vt, Qt.LeftButton, pos=QPoint(330, 240))
assert abs(vt.cam.x() - 40) < 0.01 and abs(vt.cam.y() - 70) < 0.01, vt.cam
assert abs(vs.cam.x() - 70) < 0.01 and abs(vs.cam.y() - 15) < 0.01, vs.cam
assert_synced("after top cam drag")
print("top cam drag -> side mirrored:", (round(vt.cam.x(), 1), round(vt.cam.y(), 1)), (round(vs.cam.x(), 1), round(vs.cam.y(), 1)))

QTest.mousePress(vs, Qt.LeftButton, pos=QPoint(270, 105))
QTest.mouseMove(vs, QPoint(360, 120))
QTest.mouseRelease(vs, Qt.LeftButton, pos=QPoint(360, 120))
assert abs(vs.cam.x() - 100) < 0.01 and abs(vs.cam.y() - 10) < 0.01, vs.cam
assert abs(vt.cam.y() - 100) < 0.01, vt.cam
assert_synced("after side cam drag")
print("side cam drag -> top mirrored:", (round(vt.cam.x(), 1), round(vt.cam.y(), 1)), (round(vs.cam.x(), 1), round(vs.cam.y(), 1)))

QTest.mousePress(vt, Qt.LeftButton, pos=QPoint(210, 210))
QTest.mouseMove(vt, QPoint(210, 300))
QTest.mouseRelease(vt, Qt.LeftButton, pos=QPoint(210, 300))
assert abs(vt.head.y() - 90) < 0.01 and abs(vs.head.x() - 90) < 0.01, (vt.head, vs.head)
assert_synced("after top head drag")
print("top head drag -> side mirrored:", (round(vt.head.x(), 1), round(vt.head.y(), 1)), (round(vs.head.x(), 1), round(vs.head.y(), 1)))

d2._on_reset()
assert_synced("after reset")
print("reset consistent:", tuple(round(v, 1) for v in d2._values())[:3])
print("CONSISTENCY TESTS PASSED")

out_dir = os.path.join(os.path.dirname(__file__), "out")
os.makedirs(out_dir, exist_ok=True)
png = os.path.join(out_dir, "cam_setup_dialog.png")
dlg.resize(dlg.sizeHint())
dlg.grab().save(png)
print("8. screenshot saved:", png)
print("ALL DIALOG TESTS PASSED")
