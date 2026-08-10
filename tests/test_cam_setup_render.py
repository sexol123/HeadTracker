import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from ui.cam_setup_dialog import CamSetupDialog, SetupView, SCALE, ORIGIN_TOP, ORIGIN_SIDE, BG_COLOR

app = QApplication([])
d = CamSetupDialog(offset_x_cm=-30, offset_y_cm=15, offset_z_cm=50, yaw=71.6, pitch=56.3, roll=0)
d.resize(d.sizeHint())
d.show()
app.processEvents()

def grab_px(widget, x, y):
    img = widget.grab().toImage()
    if img.format() != QImage.Format_ARGB32:
        img = img.convertToFormat(QImage.Format_ARGB32)
    return img.pixelColor(x, y)

def near(c, ref, tol=60):
    return (abs(c.red() - ref.red()) <= tol and abs(c.green() - ref.green()) <= tol
            and abs(c.blue() - ref.blue()) <= tol)

def check(name, got, ref, tol=60):
    ok = near(got, ref, tol)
    print(("PASS" if ok else "FAIL"), name, got.name())
    return ok

ok = True
side, top = d.view_side, d.view_top

ok &= check("side bg", grab_px(side, 5, 5), BG_COLOR)
cam_px = side._to_px(side.cam)
head_px = side._to_px(side.head)
ok &= check("side screen bar", grab_px(side, int(ORIGIN_SIDE[0]), int(ORIGIN_SIDE[1])), QColor("#7f8c8d"), 90)
ok &= check("side face", grab_px(side, int(head_px.x()), int(head_px.y())), QColor("#00d4ff"))
ok &= check("side cam rect", grab_px(side, int(cam_px.x()), int(cam_px.y())), QColor("#2ecc71"))
dd = side._axis_dir()
tip = cam_px + dd * 46
rear = cam_px + dd * -40
ok &= check("side tip knob", grab_px(side, int(tip.x()), int(tip.y())), QColor("#f1c40f"))
ok &= check("side rear knob", grab_px(side, int(rear.x()), int(rear.y())), QColor("#f1c40f"))

cam_px = top._to_px(top.cam)
head_px = top._to_px(top.head)
ok &= check("top screen bar", grab_px(top, int(ORIGIN_TOP[0]), int(ORIGIN_TOP[1])), QColor("#7f8c8d"), 90)
ok &= check("top face", grab_px(top, int(head_px.x()), int(head_px.y())), QColor("#00d4ff"))
ok &= check("top cam rect", grab_px(top, int(cam_px.x()), int(cam_px.y())), QColor("#2ecc71"))
dd = top._axis_dir()
tip = cam_px + dd * 46
rear = cam_px + dd * -40
ok &= check("top tip knob", grab_px(top, int(tip.x()), int(tip.y())), QColor("#f1c40f"))
ok &= check("top rear knob", grab_px(top, int(rear.x()), int(rear.y())), QColor("#f1c40f"))

print("RENDER", "OK" if ok else "FAILED")
if not ok:
    sys.exit(1)
