import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np

from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from config import Profile
from pose import Pose
from i18n import t

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


def test_splash_layout_no_overlap():
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QFontMetrics

    import main

    old_icon = main.ICON_PATH
    try:
        pix = main.draw_splash("......")
        assert not pix.isNull()
        fm_title = QFontMetrics(QFont("Segoe UI", 22, QFont.Bold))
        fm_status = QFontMetrics(QFont("Segoe UI", 11))
        title_rect = pix.rect().adjusted(0, 118, 0, -90)
        tb = fm_title.boundingRect(title_rect, Qt.AlignCenter, "HeadTracker")
        sb = fm_status.boundingRect(
            pix.rect().adjusted(0, 205, 0, 0),
            Qt.AlignHCenter | Qt.AlignTop,
            t("splash_loading") + "......",
        )
        assert not tb.intersects(sb), f"title {tb.getRect()} overlaps loading {sb.getRect()}"
        assert sb.left() >= 0 and sb.right() <= 420, "loading text must fit the splash width"

        # No-icon variant uses different title placement — still no overlap
        main.ICON_PATH = main.ICON_PATH.with_name("__no_icon__.png")
        pix2 = main.draw_splash("......")
        assert not pix2.isNull()
        tb2 = fm_title.boundingRect(pix2.rect().adjusted(0, 60, 0, -60), Qt.AlignCenter, "HeadTracker")
        assert not tb2.intersects(sb), f"no-icon title {tb2.getRect()} overlaps loading {sb.getRect()}"
    finally:
        main.ICON_PATH = old_icon
    print("PASS: splash title and loading text do not overlap (icon and no-icon)")


if __name__ == "__main__":
    test_window_title_shows_profile()
    test_preview_overlay_draws_fps()
    test_preview_overlay_without_tracking_no_fps()
    test_splash_layout_no_overlap()
    print("UI POLISH TESTS PASSED")
