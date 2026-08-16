"""Software-rendered cockpit preview: shows what the game camera sees
from the FT values actually sent to FreeTrack, so the user can tune
sensitivity/range/drift without launching the game.

Pure math + QPainter, no OpenGL. Fully deterministic and testable.
"""
import math

import numpy as np
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen

EYE_HEIGHT = 1.2      # meters, camera height above ground
HALF_TRACK = 6.0      # road half-width, meters
LOOK_AHEAD = 60.0     # grid extent forward, meters
GRID_STEP = 4.0


class CockpitRenderer:
    """Projects a simple cockpit + road scene with the same yaw/pitch/roll
    the game receives over FreeTrack and paints it into a QImage."""

    def __init__(self, fov_deg: float = 60.0):
        self._fov_deg = float(fov_deg)

    @property
    def fov_deg(self) -> float:
        return self._fov_deg

    def set_fov(self, fov_deg: float):
        self._fov_deg = float(fov_deg)

    def render(
        self,
        yaw_deg: float = 0.0,
        pitch_deg: float = 0.0,
        roll_deg: float = 0.0,
        x_cm: float = 0.0,
        y_cm: float = 0.0,
        z_cm: float = 0.0,
        width: int = 480,
        height: int = 360,
        raw: dict | None = None,
        sent: dict | None = None,
    ) -> QImage:
        img = QImage(width, height, QImage.Format_RGB32)
        img.fill(QColor(10, 12, 22))

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            self._draw_scene(painter, yaw_deg, pitch_deg, roll_deg, x_cm, y_cm, z_cm, width, height)
            self._draw_overlay(painter, width, height, yaw_deg, pitch_deg, roll_deg, raw, sent)
        finally:
            painter.end()
        return img

    # ── scene ────────────────────────────────────────────────────────
    def _view_matrix(self, yaw_deg, pitch_deg, roll_deg):
        """Rotation from game-space to camera space.

        FreeTrack sends Yaw/Pitch negated and Roll as-is (see freetrack.py);
        the game then rotates the camera with those values. Mirroring that
        here shows exactly the game's view."""
        d2r = math.pi / 180.0
        yaw = -yaw_deg * d2r
        pitch = -pitch_deg * d2r
        roll = roll_deg * d2r
        cy, sy = math.cos(yaw), math.sin(yaw)
        cp, sp = math.cos(pitch), math.sin(pitch)
        cr, sr = math.cos(roll), math.sin(roll)
        return np.array([
            [cr * cy + sr * sp * sy,  sr * cp,  cr * -sy + sr * sp * cy],
            [-sr * cy + cr * sp * sy, cr * cp, -sr * -sy + cr * sp * cy],
            [cp * sy,                 -sp,      cp * cy],
        ], dtype=np.float64)

    def _project(self, points, view, eye, f, cx, cy):
        """points: (N,3) world coords; eye: (3,) camera position (meters).
        Returns (N,2) screen coords and (N,) depth; points behind the
        near plane are excluded."""
        rel = points - eye
        cam = rel @ view.T
        z = cam[:, 2]
        ok = z > 0.15
        out = np.full((len(points), 2), np.nan, dtype=np.float64)
        if ok.any():
            x = cx + f * cam[ok, 0] / z[ok]
            y = cy - f * cam[ok, 1] / z[ok]
            out[ok] = np.column_stack([x, y])
        return out, z

    def _draw_scene(self, painter, yaw_deg, pitch_deg, roll_deg, x_cm, y_cm, z_cm, width, height):
        w, h = float(width), float(height)
        f = (h / 2.0) / math.tan(math.radians(self._fov_deg) / 2.0)
        cx, cy = w / 2.0, h / 2.0
        view = self._view_matrix(yaw_deg, pitch_deg, roll_deg)
        eye = np.array([x_cm / 100.0, EYE_HEIGHT + y_cm / 100.0, z_cm / 100.0])

        def project(pts):
            return self._project(np.array(pts, dtype=np.float64), view, eye, f, cx, cy)

        def line(pts, color, width_px=2, pen_style=Qt.SolidLine):
            pts, depth = project(pts)
            pts = pts[~np.isnan(pts[:, 0])]
            if len(pts) < 2:
                return
            pen = QPen(QColor(color), width_px, pen_style)
            pen.setCosmetic(True)
            painter.setPen(pen)
            path = [QPointF(float(p[0]), float(p[1])) for p in pts]
            painter.drawPolyline(path)

        # Sky / ground split (drawn as two fills using the pitch-rotated eye ray)
        painter.fillRect(0, 0, width, max(0, int(cy)), QColor(16, 24, 48))
        painter.fillRect(0, max(0, int(cy)), width, height - max(0, int(cy)), QColor(20, 26, 20))

        # Ground grid: lateral lines and longitudinal lines
        for z in np.arange(2.0, LOOK_AHEAD + GRID_STEP, GRID_STEP):
            line([(-HALF_TRACK, 0.0, z), (HALF_TRACK, 0.0, z)], "#2a332a", 1)
        for x in np.arange(-HALF_TRACK, HALF_TRACK + 1.0, 2.0):
            line([(x, 0.0, 2.0), (x, 0.0, LOOK_AHEAD)], "#2a332a", 1)

        # Road edges + center dashes
        line([(-2.0, 0.0, 2.0), (-2.0, 0.0, LOOK_AHEAD)], "#555", 2)
        line([(2.0, 0.0, 2.0), (2.0, 0.0, LOOK_AHEAD)], "#555", 2)
        for z in np.arange(4.0, LOOK_AHEAD, 6.0):
            line([(0.0, 0.0, z), (0.0, 0.0, z + 2.4)], "#888", 2)

        # Hood
        line([(-0.55, 0.32, 2.6), (-0.55, 0.40, 1.35)], "#333a45", 3)
        line([(0.55, 0.32, 2.6), (0.55, 0.40, 1.35)], "#333a45", 3)
        line([(-0.55, 0.32, 2.6), (0.55, 0.32, 2.6)], "#333a45", 3)

        # Cowl + dashboard
        line([(-0.85, 0.42, 1.30), (0.85, 0.42, 1.30)], "#3d4654", 3)
        line([(-0.80, 0.30, 1.10), (-0.80, 0.42, 1.30)], "#3d4654", 2)
        line([(0.80, 0.30, 1.10), (0.80, 0.42, 1.30)], "#3d4654", 2)
        line([(-0.80, 0.30, 1.10), (0.80, 0.30, 1.10)], "#3d4654", 2)

        # A-pillars + roof
        line([(-0.85, 0.42, 1.30), (-0.80, 1.15, 1.55)], "#11161f", 4)
        line([(0.85, 0.42, 1.30), (0.80, 1.15, 1.55)], "#11161f", 4)
        line([(-0.80, 1.15, 1.55), (0.80, 1.15, 1.55)], "#11161f", 4)
        line([(-0.80, 1.15, 1.55), (-0.85, 0.42, 1.30)], "#0c1018", 5)
        line([(0.80, 1.15, 1.55), (0.85, 0.42, 1.30)], "#0c1018", 5)

        # Steering wheel: ring in the (x, y) plane at z = 0.95
        pts = []
        for k in range(0, 25):
            a = 2.0 * math.pi * k / 24.0
            pts.append((0.18 * math.cos(a), 0.42 + 0.18 * math.sin(a), 0.95))
        line(pts, "#b8c4d4", 3)
        line([(0.0, 0.42, 0.95), (0.0, 0.60, 0.95)], "#b8c4d4", 3)

        # Side mirrors
        line([(-0.85, 0.55, 1.15), (-1.15, 0.55, 1.05)], "#333a45", 2)
        line([(0.85, 0.55, 1.15), (1.15, 0.55, 1.05)], "#333a45", 2)

    def _draw_overlay(self, painter, width, height, yaw_deg, pitch_deg, roll_deg, raw, sent):
        painter.setPen(QColor("#00d4ff"))
        painter.setFont(painter.font())

        def txt(line, y):
            painter.drawText(8, y, line)

        if raw is not None:
            txt(f"RAW  y {raw.get('yaw', 0):+7.1f}  p {raw.get('pitch', 0):+7.1f}  r {raw.get('roll', 0):+7.1f}", 18)
        if sent is not None:
            txt(f"SENT y {sent.get('yaw', 0):+7.1f}  p {sent.get('pitch', 0):+7.1f}  r {sent.get('roll', 0):+7.1f}", 36)
        else:
            txt(f"OUT  y {yaw_deg:+7.1f}  p {pitch_deg:+7.1f}  r {roll_deg:+7.1f}", 36)

        # Center reticle
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
        cx, cy = width / 2.0, height / 2.0
        painter.drawLine(int(cx - 8), int(cy), int(cx + 8), int(cy))
        painter.drawLine(int(cx), int(cy - 8), int(cx), int(cy + 8))
