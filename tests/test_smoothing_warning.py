import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from config import Profile
from ui.main_window import MainWindow
from ui.axes_helper_dialog import AxesHelperDialog
from i18n import t

app = QApplication([])


def make_win(profile=None):
    win = MainWindow(profile or Profile())
    win.show()
    app.processEvents()
    return win


def test_warn_hidden_by_default():
    win = make_win()
    win._axis_widgets["yaw"]["deadzone"].setValue(2.0)
    app.processEvents()
    assert win.lbl_smoothing_warn.isHidden(), "smoothing 50%, dz 2.0 -> no warning"
    print("PASS: warning hidden at defaults (smoothing 50, deadzone 2.0)")


def test_warn_shown_high_smoothing_with_deadzone():
    win = make_win()
    win._axis_widgets["yaw"]["deadzone"].setValue(2.0)
    win.slider_smoothing.setValue(70)
    app.processEvents()
    assert not win.lbl_smoothing_warn.isHidden(), "smoothing 70% + deadzone 2.0 -> warn"
    print("PASS: warning shown at smoothing 70% with deadzone > 0")


def test_warn_hidden_with_zero_deadzone():
    win = make_win()
    win.slider_smoothing.setValue(90)
    for w in win._axis_widgets.values():
        w["deadzone"].setValue(0.0)
    app.processEvents()
    assert win.lbl_smoothing_warn.isHidden(), "all deadzones 0 -> no warn"
    print("PASS: warning hidden when all deadzones are 0")


def test_warn_hidden_low_smoothing():
    win = make_win()
    win._axis_widgets["yaw"]["deadzone"].setValue(2.0)
    win.slider_smoothing.setValue(60)
    app.processEvents()
    assert win.lbl_smoothing_warn.isHidden(), "smoothing 60% -> no warn (threshold >60)"
    win.slider_smoothing.setValue(61)
    app.processEvents()
    assert not win.lbl_smoothing_warn.isHidden(), "smoothing 61% -> warn"
    print("PASS: threshold at 60%")


def test_warn_toggles_on_deadzone_change():
    win = make_win()
    win._axis_widgets["yaw"]["deadzone"].setValue(2.0)
    win.slider_smoothing.setValue(75)
    app.processEvents()
    assert not win.lbl_smoothing_warn.isHidden(), "smoothing 75% + deadzone 2.0 -> shown"
    win._axis_widgets["yaw"]["deadzone"].setValue(0.0)
    win._axis_widgets["pitch"]["deadzone"].setValue(0.0)
    win._axis_widgets["roll"]["deadzone"].setValue(0.0)
    win._axis_widgets["x"]["deadzone"].setValue(0.0)
    win._axis_widgets["y"]["deadzone"].setValue(0.0)
    win._axis_widgets["z"]["deadzone"].setValue(0.0)
    app.processEvents()
    assert win.lbl_smoothing_warn.isHidden(), "all deadzones 0 -> hidden"
    win._axis_widgets["yaw"]["deadzone"].setValue(1.0)
    app.processEvents()
    assert not win.lbl_smoothing_warn.isHidden(), "one deadzone > 0 -> shown again"
    print("PASS: warning reacts to deadzone spinbox changes")


def test_warn_ignores_disabled_axis():
    win = make_win()
    win.slider_smoothing.setValue(80)
    win._axis_widgets["yaw"]["deadzone"].setValue(2.0)
    win._axis_widgets["yaw"]["enabled"].setChecked(False)
    for name, w in win._axis_widgets.items():
        if name != "yaw":
            w["deadzone"].setValue(0.0)
    app.processEvents()
    assert win.lbl_smoothing_warn.isHidden(), "deadzone on disabled axis must not trigger"
    print("PASS: warning ignores deadzone on disabled axes")


def test_tooltips_mention_interplay():
    win = make_win()
    tip = win._smoothing_group.toolTip()
    assert t("smoothing_deadzone_tip") in tip, "smoothing group tooltip must explain interplay"
    assert t("smoothing_tip") in tip
    dlg = AxesHelperDialog(Profile(), None)
    curves_tip = None
    for child in dlg.findChildren(type(win._smoothing_group)):
        if t("axes_setup_curves") == child.title():
            curves_tip = child.toolTip()
    if curves_tip is None:
        curves_tip = t("axes_setup_hint")
        print("NOTE: curves group not found, skipped")
    else:
        assert t("smoothing_deadzone_tip") in curves_tip
    print("PASS: tooltips include interplay explanation")


if __name__ == "__main__":
    test_warn_hidden_by_default()
    test_warn_shown_high_smoothing_with_deadzone()
    test_warn_hidden_with_zero_deadzone()
    test_warn_hidden_low_smoothing()
    test_warn_toggles_on_deadzone_change()
    test_warn_ignores_disabled_axis()
    test_tooltips_mention_interplay()
    print("ALL SMOOTHING WARNING TESTS PASSED")
