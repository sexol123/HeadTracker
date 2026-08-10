from PySide6.QtCore import Qt, QPointF, QRectF, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QGridLayout,
)

from i18n import t
from ui.cam_setup_dialog import BG_COLOR, GRID_COLOR, SCREEN_COLOR, FACE_COLOR, CAM_COLOR

AXIS_NAMES = ["yaw", "pitch", "roll", "x", "y", "z"]
AXIS_SPANS = {"yaw": 60.0, "pitch": 60.0, "roll": 60.0, "x": 50.0, "y": 50.0, "z": 50.0}

CURVE_COLOR = QColor("#f1c40f")
HANDLE_COLOR = QColor("#ffffff")
DZ_COLOR = QColor(255, 255, 255, 26)
LIVE_COLOR = FACE_COLOR
BAR_COLOR = QColor("#2ecc71")
GAUGE_BG = QColor("#10101f")


def axis_curve(x, sens, dz, inverted):
    if abs(x) < dz:
        return 0.0
    s = -1.0 if inverted else 1.0
    return s * x * sens


class AxisPlot(QWidget):
    def __init__(self, name: str, span: float, parent=None):
        super().__init__(parent)
        self.name = name
        self.span = span
        self.sens = 6.0
        self.dz = 2.0
        self.inverted = False
        self.live_raw = None
        self.live_mapped = None
        self.on_param_changed = None
        self._drag = None
        self.setFixedSize(216, 152)
        self.setMouseTracking(True)
        self._refit()

    def _refit(self):
        self._y_span = max(1.0, abs(self.sens * self.span)) * 1.15

    def _px(self, x, y):
        w, h = self.width(), self.height()
        return QPointF(w / 2 + x / self.span * (w / 2 - 16), h / 2 - y / self._y_span * (h / 2 - 16))

    def _inv(self, px, py):
        w, h = self.width(), self.height()
        return ((px - w / 2) / (w / 2 - 16) * self.span, (h / 2 - py) / (h / 2 - 16) * self._y_span)

    def mousePressEvent(self, event):
        pos = event.position()
        self._drag = None
        c = self._px(0, 0)
        for sign in (1.0, -1.0):
            h = self._px(sign * self.dz, 0)
            if (pos - QPointF(h.x(), h.y())).manhattanLength() <= 12:
                self._drag = ("dz", sign)
        if self._drag is None:
            x, y = self._inv(pos.x(), pos.y())
            if abs(x) > self.dz + 0.5:
                self._drag = ("sens", x)
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        pos = event.position()
        x, y = self._inv(pos.x(), pos.y())
        if self._drag[0] == "dz":
            dz = round(max(0.0, min(min(30.0, self.span), abs(x))) * 2) / 2
            self._apply(dz=dz)
        else:
            if abs(x) < 0.5:
                return
            sens = round(max(0.1, min(20.0, abs(y / x))) * 10) / 10
            self._apply(sens=sens)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self._refit()
            self.update()
        event.accept()

    def _apply(self, sens=None, dz=None):
        if sens is not None:
            self.sens = sens
        if dz is not None:
            self.dz = dz
        if self.on_param_changed is not None:
            self.on_param_changed(self.name, self.sens, self.dz)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG_COLOR)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Segoe UI", 8))
        w, h = self.width(), self.height()

        p.setPen(QPen(GRID_COLOR, 1))
        for fx in (-0.5, 0.5):
            gx = self._px(fx * self.span, 0).x()
            p.drawLine(int(gx), 12, int(gx), h - 12)
        for fy in (-0.5, 0.5):
            gy = self._px(0, fy * self._y_span).y()
            p.drawLine(16, int(gy), w - 16, int(gy))

        c = self._px(0, 0)
        cx, cy = c.x(), c.y()
        p.setPen(QPen(SCREEN_COLOR, 1))
        p.drawLine(int(cx), 12, int(cx), h - 12)
        p.drawLine(16, int(cy), w - 16, int(cy))

        dz_l = self._px(-self.dz, 0).x()
        dz_r = self._px(self.dz, 0).x()
        p.fillRect(QRectF(dz_l, 12, dz_r - dz_l, h - 24), DZ_COLOR)

        pen = QPen(CURVE_COLOR, 2)
        p.setPen(pen)
        prev = None
        for xi in range(-int(self.span), int(self.span) + 1):
            yi = axis_curve(xi, self.sens, self.dz, self.inverted)
            pt = self._px(xi, yi)
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt

        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(HANDLE_COLOR))
        for sign in (1.0, -1.0):
            h = self._px(sign * self.dz, 0)
            p.drawEllipse(QRectF(h.x() - 4, h.y() - 4, 8, 8))

        if self.live_raw is not None:
            l = self._px(self.live_raw, self.live_mapped)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(LIVE_COLOR))
            p.drawEllipse(QRectF(l.x() - 4, l.y() - 4, 8, 8))

        p.setPen(QPen(QColor("#cccccc")))
        p.drawText(8, 12, f"{self.name.upper()}  dz {self.dz:.1f}  sens {self.sens:.1f}")
        p.end()


class AxisGauge(QWidget):
    def __init__(self, name: str, span: float, parent=None):
        super().__init__(parent)
        self.name = name
        self.span = span
        self.raw = None
        self.mapped = None
        self.dz = 0.0
        self.setFixedHeight(46)
        self.setMinimumWidth(240)

    def set_live(self, raw, mapped, dz):
        self.raw = raw
        self.mapped = mapped
        self.dz = dz
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), GAUGE_BG)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Segoe UI", 8))
        w, h = self.width(), self.height()
        cx = w / 2
        span_px = w / 2 - 58

        def px(v):
            return cx + v / self.span * span_px

        p.setPen(QPen(SCREEN_COLOR, 1))
        p.drawLine(int(cx), 6, int(cx), h - 6)
        dz_l, dz_r = px(-self.dz), px(self.dz)
        p.fillRect(QRectF(min(dz_l, dz_r), 6, abs(dz_r - dz_l), h - 12), DZ_COLOR)

        if self.mapped is not None:
            mx = px(self.mapped)
            mx = max(4.0, min(w - 4.0, mx))
            p.setPen(Qt.NoPen)
            bar = QColor(BAR_COLOR)
            bar.setAlpha(170)
            p.setBrush(QBrush(bar))
            if mx >= cx:
                p.drawRect(QRectF(cx, 14, mx - cx, h - 28))
            else:
                p.drawRect(QRectF(mx, 14, cx - mx, h - 28))

        if self.raw is not None:
            rx = px(self.raw)
            if 4 <= rx <= w - 4:
                p.setPen(QPen(LIVE_COLOR, 3))
                p.drawLine(int(rx), 8, int(rx), h - 8)

        p.setPen(QPen(QColor("#cccccc")))
        p.drawText(6, h - 10, self.name.upper())
        if self.raw is not None and self.mapped is not None:
            p.drawText(w - 6, h - 10, f"in {self.raw:+.1f}  out {self.mapped:+.1f}")
        p.end()


class TestView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mapped = None
        self.tracking = False
        self.dz_x = 0.0
        self.dz_y = 0.0
        self.setFixedSize(250, 160)

    def set_live(self, mapped, tracking, dz_x, dz_y):
        self.mapped = mapped
        self.tracking = tracking
        self.dz_x = dz_x
        self.dz_y = dz_y
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG_COLOR)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Segoe UI", 8))
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        k = 2.6

        p.setPen(QPen(GRID_COLOR, 1))
        p.drawLine(int(cx), 0, int(cx), h)
        p.drawLine(0, int(cy), w, int(cy))
        p.setPen(QPen(SCREEN_COLOR, 1))
        p.drawRect(0, 0, w - 1, h - 1)

        p.fillRect(QRectF(cx - self.dz_x * k, cy - self.dz_y * k,
                          max(0, self.dz_x * k * 2), max(0, self.dz_y * k * 2)), DZ_COLOR)

        if self.tracking and self.mapped is not None:
            x = max(2.0, min(w - 2.0, cx + self.mapped.x * k))
            y = max(2.0, min(h - 2.0, cy - self.mapped.y * k))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(LIVE_COLOR))
            p.drawEllipse(QRectF(x - 5, y - 5, 10, 10))

        p.setPen(QPen(QColor("#cccccc")))
        p.drawText(6, 12, "X / Y")
        p.end()


class AxesHelperDialog(QDialog):
    def __init__(self, profile, worker, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("axes_setup_title"))
        self.profile = profile
        self.worker = worker
        self.on_axis_applied = None

        self._plots = {}
        plots_grid = QGridLayout()
        for i, name in enumerate(AXIS_NAMES):
            plot = AxisPlot(name, AXIS_SPANS[name])
            ax = profile.axes.get(name)
            if ax is not None:
                plot.sens, plot.dz, plot.inverted = ax.sensitivity, ax.deadzone, ax.inverted
                plot._refit()
            plot.on_param_changed = self._apply_plot
            plots_grid.addWidget(plot, i // 3, i % 3)
            self._plots[name] = plot
        curves_group = QGroupBox(t("axes_setup_curves"))
        curves_group.setToolTip(t("axes_setup_hint"))
        curves_lay = QVBoxLayout(curves_group)
        curves_lay.addLayout(plots_grid)

        self._test_view = TestView()
        self._gauges = {}
        gauges_col = QVBoxLayout()
        for name in ("yaw", "pitch", "roll"):
            gauge = AxisGauge(name, 60.0)
            gauges_col.addWidget(gauge)
            self._gauges[name] = gauge
        gauges_col.addStretch()
        live_group = QGroupBox(t("axes_setup_live"))
        live_lay = QHBoxLayout(live_group)
        live_lay.addWidget(self._test_view)
        live_lay.addLayout(gauges_col)

        self.lbl_status = QLabel(t("axes_setup_no_tracking"))
        self.btn_close = QPushButton(t("cam_setup_close"))
        self.btn_close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(self.btn_close)

        main = QVBoxLayout(self)
        main.addWidget(live_group)
        main.addWidget(curves_group)
        main.addWidget(self.lbl_status)
        main.addLayout(btns)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_live)
        self._timer.start(33)

    def _apply_plot(self, name, sens, dz):
        plot = self._plots[name]
        plot.sens = sens
        plot.dz = dz
        plot.update()
        if self.on_axis_applied is not None:
            self.on_axis_applied(name, sens, dz)

    def _refresh_live(self):
        tracking = self.worker.isRunning()
        raw = self.worker.get_raw_pose()
        mapped = self.worker.get_mapped_pose()
        for name, plot in self._plots.items():
            plot.live_raw = getattr(raw, name) if tracking else None
            plot.live_mapped = getattr(mapped, name) if tracking else None
            plot.update()
        for name, gauge in self._gauges.items():
            ax = self.profile.axes.get(name)
            dz = ax.deadzone if ax is not None else 0.0
            gauge.set_live(getattr(raw, name) if tracking else None,
                           getattr(mapped, name) if tracking else None, dz)
        ax_x = self.profile.axes.get("x")
        ax_y = self.profile.axes.get("y")
        self._test_view.set_live(mapped if tracking else None, tracking,
                                 ax_x.deadzone if ax_x is not None else 0.0,
                                 ax_y.deadzone if ax_y is not None else 0.0)
        self.lbl_status.setText(t("axes_setup_tracking") if tracking else t("axes_setup_no_tracking"))
