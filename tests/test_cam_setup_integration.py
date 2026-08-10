import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QPoint
from config import Profile, PROFILES_DIR
from ui.main_window import MainWindow
import ui.cam_setup_dialog as csd

app = QApplication([])

win = MainWindow(Profile())
win.show()
app.processEvents()

calls = []
CamSetupDialog = csd.CamSetupDialog
orig_init = CamSetupDialog.__init__
orig_exec = CamSetupDialog.exec

def fake_init(self, *a, **kw):
    orig_init(self, *a, **kw)
    calls.append(self)

def fake_exec(self):
    return 0

CamSetupDialog.__init__ = fake_init
CamSetupDialog.exec = fake_exec
try:
    win._on_cam_setup()
finally:
    CamSetupDialog.__init__ = orig_init
    CamSetupDialog.exec = orig_exec

assert len(calls) == 1, len(calls)
dlg = calls[0]

dlg.apply_callback(win.spin_cam_offset_x.value(), win.spin_cam_offset_y.value(),
                   win.spin_cam_offset_z.value(), win.spin_cam_yaw.value(),
                   win.spin_cam_pitch.value(), win.spin_cam_roll.value())
app.processEvents()

dlg.apply_callback(-30.0, 15.0, 50.0, 71.6, 56.3, 8.0)
assert abs(win.spin_cam_offset_x.value() + 30.0) < 0.05, win.spin_cam_offset_x.value()
assert abs(win.spin_cam_offset_y.value() - 15.0) < 0.05
assert abs(win.spin_cam_offset_z.value() - 50.0) < 0.05
assert abs(win.spin_cam_yaw.value() - 71.6) < 0.05
assert abs(win.spin_cam_pitch.value() - 56.3) < 0.05
assert abs(win.spin_cam_roll.value() - 8.0) < 0.05
print("spinboxes updated by dialog callback OK")

assert win.btn_cam_setup.text() != ""
assert win._cam_adapt_group.title() != ""
print("button text OK:", win.btn_cam_setup.text())
win._refresh_ui_text()
print("refresh_ui_text OK")
print("INTEGRATION TEST PASSED")
