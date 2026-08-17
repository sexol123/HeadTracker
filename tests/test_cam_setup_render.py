import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from ui.cam_setup_dialog import CamSetupDialog, BG_COLOR, BEZEL_COLOR, CAM_COLOR

app = QApplication([])
d = CamSetupDialog(offset_x_cm=-30, offset_y_cm=15, offset_z_cm=50)
d.resize(d.sizeHint())
d.show()
app.processEvents()
view = d.view


def grab_px(pt):
    img = view.grab().toImage()
    if img.format() != QImage.Format_ARGB32:
        img = img.convertToFormat(QImage.Format_ARGB32)
    return img.pixelColor(int(pt.x()), int(pt.y()))


def near(c, ref, tol=60):
    return (abs(c.red() - ref.red()) <= tol and abs(c.green() - ref.green()) <= tol
            and abs(c.blue() - ref.blue()) <= tol)


def check(name, got, ref, tol=60):
    ok = near(got, ref, tol)
    print(("PASS" if ok else "FAIL"), name, got.name())
    return ok


ok = True
ok &= check("bg", grab_px(QPointF(5, 5)), BG_COLOR)

bezel = view.bezel_rect()
ok &= check("bezel", grab_px(QPointF(bezel.center().x(), bezel.top() + 3.0)), BEZEL_COLOR)

sr = view.screen_rect()
ok &= check("screen", grab_px(QPointF(sr.center().x() + 30.0, sr.center().y())), QColor("#1b1b2f"))

marker = view._to_px(view.cam.x(), view.cam.y())
ok &= check("camera marker", grab_px(QPointF(marker.x() - 6.0, marker.y())), CAM_COLOR)

print("RENDER", "OK" if ok else "FAILED")
if not ok:
    sys.exit(1)