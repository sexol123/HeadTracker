import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QColor
from config import Profile
from pose import Pose
from ui.axes_helper_dialog import AxesHelperDialog, axis_curve

app = QApplication([])

class FakeWorker:
    def __init__(self):
        self._raw = Pose(yaw=20.0, pitch=-5.0, roll=10.0, x=8.0, y=-3.0, z=15.0, confidence=0.9)
        self._mapped = Pose(yaw=120.0, pitch=0.0, roll=60.0, x=20.0, y=-7.5, z=37.5, confidence=0.9)
        self._running = True
    def isRunning(self): return self._running
    def get_raw_pose(self): return self._raw
    def get_mapped_pose(self): return self._mapped

dlg = AxesHelperDialog(Profile(), FakeWorker())
dlg.show()
app.processEvents()
dlg._refresh_live()

def grab_px(w, x, y):
    img = w.grab().toImage()
    if img.format() != QImage.Format_ARGB32:
        img = img.convertToFormat(QImage.Format_ARGB32)
    return img.pixelColor(x, y)

def near(c, ref, tol=70):
    return abs(c.red() - ref.red()) <= tol and abs(c.green() - ref.green()) <= tol \
        and abs(c.blue() - ref.blue()) <= tol

ok = True
p = dlg._plots["yaw"]
h = p._px(-p.dz, 0)
ok &= near(grab_px(p, int(h.x()), int(h.y())), QColor("#ffffff"))
print("dz handle:", grab_px(p, int(h.x()), int(h.y())).name())
curve_pt = p._px(30.0, axis_curve(30.0, p.sens, p.dz, p.inverted))
ok &= near(grab_px(p, int(curve_pt.x()), int(curve_pt.y())), QColor("#f1c40f"))
print("curve:", grab_px(p, int(curve_pt.x()), int(curve_pt.y())).name())
dz_l = p._px(-p.dz, 0).x(); dz_r = p._px(p.dz, 0).x()
band = grab_px(p, int((dz_l + dz_r) / 2), 40)
ok &= band.alpha() > 0
print("dz band:", band.name())
live = p._px(20.0, 120.0)
c = grab_px(p, int(live.x()), int(live.y()))
ok &= near(c, QColor("#00d4ff"))
print("live dot:", c.name())
g = dlg._gauges["yaw"]
bar_pt = g.width() / 2 + (120.0 / 60.0) * (g.width() / 2 - 58)
c2 = grab_px(g, int(min(bar_pt, g.width() - 6)), 24)
ok &= near(c2, QColor("#2ecc71"))
print("gauge bar:", c2.name())
tv = dlg._test_view
c3 = grab_px(tv, int(tv.width() / 2 + 20.0 * 2.6), int(tv.height() / 2 - (-7.5) * 2.6))
ok &= near(c3, QColor("#00d4ff"))
print("test view dot:", c3.name())
print("RENDER", "OK" if ok else "FAILED")
if not ok:
    sys.exit(1)
