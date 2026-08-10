import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

WINDOW_SEC = 10.0


class StatsGraph(QWidget):
    """Mini performance graph: FPS, frame time, tracking latency + event markers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fps: list[tuple[float, float]] = []
        self._frame_time: list[tuple[float, float]] = []
        self._latency: list[tuple[float, float]] = []
        self._markers: list[tuple[float, str]] = []
        self._t0: float | None = None
        self._max_fps: float = 0.0
        self._clock = time.perf_counter
        self.setMinimumHeight(140)

    # ── data ────────────────────────────────────────────────────────
    def add_sample(self, fps: float, frame_time_ms: float, latency_ms: float):
        now = self._clock()
        if self._t0 is None:
            self._t0 = now
        t = now - self._t0
        self._fps.append((t, fps))
        self._frame_time.append((t, frame_time_ms))
        self._latency.append((t, latency_ms))
        self._max_fps = max(self._max_fps, fps)
        self._trim()
        self.update()

    def add_marker(self, code: str):
        now = self._clock()
        if self._t0 is None:
            self._t0 = now
        self._markers.append((now - self._t0, code))
        self._trim()
        self.update()

    def clear(self):
        self._fps.clear()
        self._frame_time.clear()
        self._latency.clear()
        self._markers.clear()
        self._t0 = None
        self._max_fps = 0.0
        self.update()

    def sample_count(self) -> int:
        return len(self._fps)

    def _trim(self):
        if self._t0 is None:
            return
        t_now = self._clock() - self._t0
        cutoff = t_now - WINDOW_SEC
        for buf in (self._fps, self._frame_time, self._latency, self._markers):
            while buf and buf[0][0] < cutoff:
                buf.pop(0)
        if len(self._fps) > 2000:
            self._fps = self._fps[-2000:]
        if len(self._frame_time) > 2000:
            self._frame_time = self._frame_time[-2000:]
        if len(self._latency) > 2000:
            self._latency = self._latency[-2000:]

    # ── painting ────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#141428"))

        margin = 6
        pad_bottom = 16
        pad_top = 10
        w = self.width() - 2 * margin
        h = self.height() - pad_top - pad_bottom
        plot = (margin, pad_top, w, h)

        t_min, t_max = self._view_range()
        t_span = max(t_max - t_min, 1e-3)
        fps_max = max(self._max_fps, 1.0)

        p.setPen(QPen(QColor("#2a2a4e"), 1))
        for i in range(5):
            y = pad_top + int(h * i / 4)
            p.drawLine(margin, y, margin + w, y)
        for i in range(5):
            x = margin + int(w * i / 4)
            p.drawLine(x, pad_top, x, pad_top + h)

        def x_px(t):
            return margin + int((t - t_min) / t_span * w)

        def y_px(v, v_max):
            return pad_top + h - int(min(v / v_max, 1.0) * h)

        for t, code in self._markers:
            x = x_px(t)
            p.setPen(QPen(QColor("#e74c3c"), 1, Qt.DashLine))
            p.drawLine(x, pad_top, x, pad_top + h)
            p.setPen(QColor("#e74c3c"))
            p.setFont(QFont("Consolas", 7))
            p.drawText(x + 3, pad_top + 8, code)

        self._draw_series(p, self._fps, x_px, y_px, QColor("#2ecc71"), fps_max)
        self._draw_series(p, self._frame_time, x_px, y_px, QColor("#3498db"), max(fps_max * 10.0, 100.0))
        self._draw_series(p, self._latency, x_px, y_px, QColor("#e67e22"), max(fps_max * 10.0, 100.0))

        p.setPen(QColor("#8888aa"))
        p.setFont(QFont("Consolas", 8))
        if self._fps:
            p.drawText(margin + 4, pad_top + h + 13, f"FPS {self._fps[-1][1]:.0f}")
        if self._frame_time:
            p.drawText(margin + 90, pad_top + h + 13, f"Frame {self._frame_time[-1][1]:.0f}ms")
        if self._latency:
            p.drawText(margin + 190, pad_top + h + 13, f"Latency {self._latency[-1][1]:.1f}ms")

    def _draw_series(self, p, points, x_px, y_px, color, v_max):
        if len(points) < 2:
            return
        pen = QPen(color, 1.5)
        p.setPen(pen)
        pts = []
        for t, v in points:
            pts.append((x_px(t), y_px(v, v_max)))
        for i in range(1, len(pts)):
            p.drawLine(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])

    def _view_range(self):
        if self._t0 is None:
            return 0.0, WINDOW_SEC
        t_now = self._clock() - self._t0
        if t_now < WINDOW_SEC:
            return 0.0, max(t_now, 1.0)
        return t_now - WINDOW_SEC, t_now
