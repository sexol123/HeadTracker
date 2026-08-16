import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

from ui.cockpit_view import CockpitRenderer

app = QApplication([])


def pixels_diff(img_a, img_b):
    a = img_a.constBits().asstring(img_a.width() * img_a.height() * 4) if hasattr(img_a.constBits(), "asstring") else bytes(img_a.bits())
    return sum(1 for i in range(0, len(a), 4) if a[i:i + 4] != b"\x00\x00\x00\x00")


def test_render_basic():
    r = CockpitRenderer(fov_deg=60.0)
    img = r.render(width=200, height=150)
    assert img.width() == 200 and img.height() == 150
    assert not img.isNull()


def test_render_neutral_has_reticle():
    r = CockpitRenderer()
    img = r.render(width=240, height=180)
    # Center reticle pixels should differ from background in the middle row
    px = img.pixel(120, 90)
    assert px != 0xFF0A0C16  # not pure background


def test_render_pose_changes_image():
    r = CockpitRenderer()
    neutral = r.render(width=240, height=180)
    yawed = r.render(yaw_deg=30.0, pitch_deg=10.0, roll_deg=5.0, width=240, height=180)
    assert neutral != yawed


def test_render_raw_sent_overlay_differs():
    r = CockpitRenderer()
    a = r.render(yaw_deg=5.0, width=240, height=180, raw={"yaw": 1.0, "pitch": 0.0, "roll": 0.0},
                 sent={"yaw": 5.0, "pitch": 0.0, "roll": 0.0})
    b = r.render(yaw_deg=0.0, width=240, height=180, raw={"yaw": -1.0, "pitch": 0.0, "roll": 0.0},
                 sent={"yaw": 0.0, "pitch": 0.0, "roll": 0.0})
    assert a != b


def test_render_fov_changes_scale():
    r = CockpitRenderer()
    n = r.render(width=240, height=180)
    r.set_fov(15.0)
    t = r.render(width=240, height=180)
    assert n != t


def test_render_all_axes_extremes():
    r = CockpitRenderer()
    img = r.render(yaw_deg=45.0, pitch_deg=30.0, roll_deg=20.0,
                   x_cm=5.0, y_cm=-3.0, z_cm=2.0, width=240, height=180)
    assert not img.isNull()


def test_translation_moves_view():
    r = CockpitRenderer()
    a = r.render(x_cm=0.0, y_cm=0.0, z_cm=0.0, width=240, height=180)
    b = r.render(x_cm=15.0, y_cm=0.0, z_cm=0.0, width=240, height=180)
    assert a != b


def test_legacy_fov_zero_does_not_crash():
    r = CockpitRenderer(fov_deg=0.0)  # legacy: 0 = use default
    img = r.render(width=240, height=180)
    assert not img.isNull()
    r2 = CockpitRenderer(fov_deg=200.0)  # degenerate
    img2 = r2.render(width=240, height=180)
    assert not img2.isNull()


if __name__ == "__main__":
    test_render_basic()
    print("PASS: neutral scene renders at requested size")
    test_render_neutral_has_reticle()
    print("PASS: center reticle present")
    test_render_pose_changes_image()
    print("PASS: yaw/pitch/roll visibly move the camera")
    test_render_fov_changes_scale()
    print("PASS: FOV changes the projection")
    test_render_all_axes_extremes()
    print("PASS: extreme pose + translation renders")
    test_translation_moves_view()
    print("PASS: translation shifts the view")
    test_legacy_fov_zero_does_not_crash()
    print("PASS: legacy FOV=0 and degenerate FOV do not crash")
    test_render_raw_sent_overlay_differs()
    print("PASS: raw/sent overlay text differs")
    print("ALL COCKPIT VIEW TESTS PASSED")