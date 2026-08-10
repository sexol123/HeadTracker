import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from config import Profile
from pose import Pose

app = QApplication([])


def test_window_title_shows_profile():
    win = MainWindow(Profile())
    assert win.profile.name in win.windowTitle(), f"title: {win.windowTitle()}"
    names = [win.combo_profile.itemText(i) for i in range(win.combo_profile.count())]
    if len(names) > 1:
        win.select_profile_by_name(names[1])
        assert win.profile.name in win.windowTitle(), f"title: {win.windowTitle()}"
    print("PASS: window title shows current profile and follows profile switch")


def test_preview_overlay_draws_fps():
    win = MainWindow(Profile())
    win.display_fps = 30.0
    frame = np.zeros((100, 160, 3), dtype=np.uint8)
    out = win._draw_overlay(frame, Pose())
    assert out is frame
    found = np.any(np.all(out == (0, 255, 255), axis=2))
    assert found, "FPS text (yellow) must appear on the preview frame"
    print("PASS: preview overlay draws FPS counter")


def test_preview_overlay_without_tracking_no_fps():
    win = MainWindow(Profile())
    win.display_fps = 0.0
    frame = np.zeros((100, 160, 3), dtype=np.uint8)
    out = win._draw_overlay(frame, Pose())
    assert np.any(np.all(out == (0, 255, 255), axis=2))  # still drawn as 0 FPS
    print("PASS: overlay draws 0 FPS when not tracking")


if __name__ == "__main__":
    test_window_title_shows_profile()
    test_preview_overlay_draws_fps()
    test_preview_overlay_without_tracking_no_fps()
    print("UI POLISH TESTS PASSED")
