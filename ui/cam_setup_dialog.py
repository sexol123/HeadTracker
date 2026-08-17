import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QGridLayout,
)

from i18n import t

# ── monitor front view (cm); origin = screen center ─────────────────────────
VIEW_W, VIEW_H = 380, 300
PAD = 24.0
BEZEL = 10.0
MON_X_MIN, MON_X_MAX = -62.0, 62.0
MON_Y_MIN, MON_Y_MAX = -35.0, 35.0
HEAD_Z = 60.0
CAM_DEFAULT = (0.0, 35.0, 50.0)   # attached to the top edge, centered

BG_COLOR = QColor("#1a1a2e")
BEZEL_COLOR = QColor("#2b2b40")
SCREEN_DARK = QColor("#1b1b2f")
# shared palette (also used by the axes helper dialogs)
GRID_COLOR = QColor(255, 255, 255, 28)
SCREEN_COLOR = QColor("#7f8c8d")
FACE_COLOR = QColor("#00d4ff")
GRID_TINT = QColor(120, 140, 220, 24)
CAM_COLOR = QColor("#2ecc71")
LENS_COLOR = QColor("#0e8a4d")
MARKER_W, MARKER_H = 24.0, 16.0
MARKER_RADIUS = 16.0


class CamView2D(QWidget):
    """Front view of the monitor. Click or drag anywhere on the screen area
    to place the camera marker; its position defines the camera offset
    relative to the screen."""

    def __init__(self, cam_x=0.0, cam_y=0.0, parent=None):
        super().__init__(parent)
        self.cam = QPointF(cam_x, cam_y)
        self.on_moved = None
        self._drag = False
        self.setFixedSize(VIEW_W, VIEW_H)

    # ── geometry helpers (used by painting, tests) ───────────────────────────
    def screen_rect(self) -> QRectF:
        return QRectF(PAD, PAD, VIEW_W - 2.0 * PAD, VIEW_H - 2.0 * PAD)

    def bezel_rect(self) -> QRectF:
        b = PAD - BEZEL
        return QRectF(b, b, VIEW_W - 2.0 * b, VIEW_H - 2.0 * b)

    def _to_px(self, x, y) -> QPointF:
        sc = self.screen_rect()
        fx = (x - MON_X_MIN) / (MON_X_MAX - MON_X_MIN)
        fy = (y - MON_Y_MIN) / (MON_Y_MAX - MON_Y_MIN)
        return QPointF(sc.left() + fx * sc.width(), sc.top() + fy * sc.height())

    def _from_px(self, pos: QPointF) -> QPointF:
        sc = self.screen_rect()
        fx = (pos.x() - sc.left()) / sc.width()
        fy = (pos.y() - sc.top()) / sc.height()
        return QPointF(MON_X_MIN + fx * (MON_X_MAX - MON_X_MIN),
                       MON_Y_MIN + fy * (MON_Y_MAX - MON_Y_MIN))

    def _emit(self):
        self.update()
        if self.on_moved is not None:
            self.on_moved()

    # ── interaction ──────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        pos = event.position()
        if self.screen_rect().contains(pos):
            self._drag = True
            self.cam = self._from_px(pos)
            self._emit()
        event.accept()

    def mouseMoveEvent(self, event):
        if not self._drag:
            return
        pos = event.position()
        if self.screen_rect().contains(pos):
            self.cam = self._from_px(pos)
        self._emit()
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag = False
        event.accept()

    # ── painting ─────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG_COLOR)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Segoe UI", 8))

        br = self.bezel_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(BEZEL_COLOR))
        p.drawRoundedRect(br, 6, 6)

        sr = self.screen_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(SCREEN_DARK))
        p.drawRect(sr)

        p.setPen(QPen(GRID_TINT, 1))
        for i in range(1, 3):
            x = sr.left() + sr.width() * i / 3.0
            y = sr.top() + sr.height() * i / 3.0
            p.drawLine(QPointF(x, sr.top()), QPointF(x, sr.bottom()))
            p.drawLine(QPointF(sr.left(), y), QPointF(sr.right(), y))

        cx = sr.center()
        p.setPen(QPen(SCREEN_COLOR, 2))
        p.drawLine(QPointF(cx.x() - 8.0, cx.y()), QPointF(cx.x() + 8.0, cx.y()))
        p.drawLine(QPointF(cx.x(), cx.y() - 8.0), QPointF(cx.x(), cx.y() + 8.0))

        px = self._to_px(self.cam.x(), self.cam.y())
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(CAM_COLOR))
        p.drawRoundedRect(QRectF(px.x() - MARKER_W / 2.0, px.y() - MARKER_H / 2.0,
                                 MARKER_W, MARKER_H), 4, 4)
        p.setBrush(QBrush(LENS_COLOR))
        p.drawEllipse(px, 3.0, 3.0)

        label_y = max(PAD, px.y() - MARKER_H / 2.0 - 21.0)
        p.setPen(QPen(CAM_COLOR))
        p.drawText(QRectF(px.x() - 40.0, label_y, 80.0, 18.0),
                   Qt.AlignCenter, t("cam_setup_cam"))
        p.end()


class CamSetupWidget(QWidget):
    """Simplified camera-position editor: pick the camera spot on a front
    view of the monitor. The camera-to-user distance is left to calibration,
    yaw/pitch auto-aim at the face, roll passes through unchanged.
    Emits values through apply_callback(ox, oy, oz, yaw, pitch, roll)."""

    def __init__(self, offset_x_cm=0.0, offset_y_cm=0.0, offset_z_cm=0.0,
                 yaw=0.0, pitch=0.0, roll=0.0, parent=None):
        super().__init__(parent)
        self.apply_callback = None

        fresh = offset_x_cm == 0.0 and offset_y_cm == 0.0 and offset_z_cm == 0.0 \
            and yaw == 0.0 and pitch == 0.0 and roll == 0.0
        cx, cy = (CAM_DEFAULT[0], CAM_DEFAULT[1]) if fresh else (offset_x_cm, offset_y_cm)
        cx = max(MON_X_MIN, min(MON_X_MAX, cx))
        cy = max(MON_Y_MIN, min(MON_Y_MAX, cy))
        self.oz = CAM_DEFAULT[2] if fresh else offset_z_cm
        self.roll_val = 0.0 if fresh else roll

        self.view = CamView2D(cx, cy)
        self.view.on_moved = self._on_any_changed
        self.view.setToolTip(t("cam_setup_hint"))

        self._value_labels = {}
        self._values_grid = QGridLayout()
        for i, name in enumerate(("X", "Y", "Z", "Yaw", "Pitch", "Roll")):
            self._values_grid.addWidget(QLabel(name), i // 3, (i % 3) * 2)
            lbl = QLabel("0.0")
            lbl.setFont(QFont("Consolas", 11))
            self._values_grid.addWidget(lbl, i // 3, (i % 3) * 2 + 1)
            self._value_labels[name] = lbl

        self.btn_reset = QPushButton(t("cam_setup_reset"))
        self.btn_reset.clicked.connect(self._on_reset)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_reset)
        btns.addStretch()

        main = QVBoxLayout(self)
        main.addWidget(self.view, 0, Qt.AlignHCenter)
        main.addLayout(self._values_grid)
        main.addLayout(btns)
        self._on_any_changed()

    def _aim_values(self):
        dx = -self.view.cam.x()
        dy = -self.view.cam.y()
        dz = HEAD_Z - self.oz
        length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
        yaw = math.degrees(math.asin(max(-1.0, min(1.0, dx / length))))
        pitch = math.degrees(math.atan2(-dy, dz))
        return yaw, pitch

    def _values(self):
        ox, oy = self.view.cam.x(), self.view.cam.y()
        yaw, pitch = self._aim_values()
        return ox, oy, self.oz, yaw, pitch, self.roll_val

    def _on_any_changed(self, *_):
        ox, oy, oz, yaw, pitch, roll = self._values()
        self._value_labels["X"].setText(f"{ox:+.1f} cm")
        self._value_labels["Y"].setText(f"{oy:+.1f} cm")
        self._value_labels["Z"].setText(f"{oz:+.1f} cm")
        self._value_labels["Yaw"].setText(f"{yaw:+.1f}°")
        self._value_labels["Pitch"].setText(f"{pitch:+.1f}°")
        self._value_labels["Roll"].setText(f"{roll:+.1f}°")
        if self.apply_callback is not None:
            self.apply_callback(ox, oy, oz, yaw, pitch, roll)

    def _on_reset(self):
        self.view.cam = QPointF(CAM_DEFAULT[0], CAM_DEFAULT[1])
        self.oz = CAM_DEFAULT[2]
        self.roll_val = 0.0
        self.view.update()
        self._on_any_changed()


class CamSetupDialog(QDialog):
    """Thin dialog wrapper around CamSetupWidget. Public API is unchanged:
    constructor offsets, apply_callback(ox, oy, oz, yaw, pitch, roll),
    view attribute."""

    def __init__(self, offset_x_cm=0.0, offset_y_cm=0.0, offset_z_cm=0.0,
                 yaw=0.0, pitch=0.0, roll=0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("cam_setup_title"))
        self.apply_callback = None

        self.widget = CamSetupWidget(
            offset_x_cm=offset_x_cm, offset_y_cm=offset_y_cm, offset_z_cm=offset_z_cm,
            yaw=yaw, pitch=pitch, roll=roll, parent=self,
        )
        self.view = self.widget.view
        self._values = self.widget._values
        self._on_reset = self.widget._on_reset

        def forward(*values):
            if self.apply_callback is not None:
                self.apply_callback(*values)

        self.widget.apply_callback = forward
        self.btn_close = QPushButton(t("cam_setup_close"))
        self.btn_close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(self.btn_close)

        main = QVBoxLayout(self)
        main.addWidget(self.widget)
        main.addLayout(btns)