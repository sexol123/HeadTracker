import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QBrush
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox,
    QSlider, QPushButton, QGroupBox, QGridLayout,
)

from i18n import t

SCALE = 3.0
ORIGIN_SIDE = (60.0, 150.0)
ORIGIN_TOP = (210.0, 30.0)
HEAD_Z = 60.0
CAM_TOP_DEFAULT = QPointF(0.0, 50.0)
CAM_SIDE_DEFAULT = QPointF(50.0, 15.0)

FACE_COLOR = QColor("#00d4ff")
CAM_COLOR = QColor("#2ecc71")
GRID_COLOR = QColor(255, 255, 255, 28)
BG_COLOR = QColor("#1a1a2e")
SCREEN_COLOR = QColor("#7f8c8d")


class SetupView(QWidget):
    TOP = 0
    SIDE = 1

    def __init__(self, mode: int, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.cam = QPointF(0.0, 0.0)
        self.head = QPointF(0.0, HEAD_Z) if mode == self.TOP else QPointF(HEAD_Z, 0.0)
        self.angle = 0.0
        self.auto_aim = True
        self.drag = None
        self.on_changed = None
        self.on_head_moved = None
        self.on_cam_moved = None
        self.setFixedSize(420, 300)
        self.setMouseTracking(True)

    def _to_px(self, p: QPointF) -> QPointF:
        if self.mode == self.SIDE:
            return QPointF(ORIGIN_SIDE[0] + p.x() * SCALE, ORIGIN_SIDE[1] - p.y() * SCALE)
        return QPointF(ORIGIN_TOP[0] + p.x() * SCALE, ORIGIN_TOP[1] + p.y() * SCALE)

    def _from_px(self, px: QPointF) -> QPointF:
        if self.mode == self.SIDE:
            return QPointF((px.x() - ORIGIN_SIDE[0]) / SCALE, (ORIGIN_SIDE[1] - px.y()) / SCALE)
        return QPointF((px.x() - ORIGIN_TOP[0]) / SCALE, (px.y() - ORIGIN_TOP[1]) / SCALE)

    def clamp(self, p: QPointF) -> QPointF:
        if self.mode == self.SIDE:
            return QPointF(max(5.0, min(120.0, p.x())), max(-50.0, min(50.0, p.y())))
        return QPointF(max(-70.0, min(70.0, p.x())), max(5.0, min(120.0, p.y())))

    def head_z(self, px: QPointF) -> float:
        z = self._from_px(px).x() if self.mode == self.SIDE else self._from_px(px).y()
        return max(10.0, min(120.0, z))

    def angle_to_value(self) -> float:
        if self.mode == self.SIDE:
            return self.angle
        return 90.0 - self.angle

    def _aim_angle(self) -> float:
        cam_px = self._to_px(self.cam)
        head_px = self._to_px(self.head)
        return math.degrees(math.atan2(head_px.y() - cam_px.y(), head_px.x() - cam_px.x()))

    def _axis_dir(self) -> QPointF:
        return QPointF(math.cos(math.radians(self.angle)), math.sin(math.radians(self.angle)))

    def _axis_hit(self, pos: QPointF) -> bool:
        cam_px = self._to_px(self.cam)
        d = self._axis_dir()
        t = (pos - cam_px).x() * d.x() + (pos - cam_px).y() * d.y()
        t = max(-40.0, min(46.0, t))
        return (pos - (cam_px + d * t)).manhattanLength() <= 12

    def mousePressEvent(self, event):
        pos = event.position()
        cam_px = self._to_px(self.cam)
        head_px = self._to_px(self.head)
        self.drag = None
        if (pos - cam_px).manhattanLength() <= 34:
            self.drag = "cam"
        elif (pos - head_px).manhattanLength() <= 18:
            self.drag = "head"
        elif self._axis_hit(pos):
            self.drag = "rot"
        event.accept()

    def mouseMoveEvent(self, event):
        if self.drag is None:
            return
        pos = event.position()
        cam_px = self._to_px(self.cam)
        if self.drag == "cam":
            self.cam = self.clamp(self._from_px(pos))
            if self.on_cam_moved is not None:
                self.on_cam_moved(self)
            if self.auto_aim:
                self.angle = self._aim_angle()
        elif self.drag == "head":
            z = self.head_z(pos)
            self.head = QPointF(0.0, z) if self.mode == self.TOP else QPointF(z, 0.0)
            if self.on_head_moved is not None:
                self.on_head_moved(z)
            if self.auto_aim:
                self.angle = self._aim_angle()
        elif self.drag == "rot":
            self.angle = math.degrees(math.atan2(pos.y() - cam_px.y(), pos.x() - cam_px.x()))
        self.update()
        if self.on_changed is not None:
            self.on_changed()
        event.accept()

    def mouseReleaseEvent(self, event):
        self.drag = None
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), BG_COLOR)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Segoe UI", 8))
        p.setPen(QPen(GRID_COLOR, 1))
        if self.mode == self.SIDE:
            for z in range(25, 125, 25):
                x = ORIGIN_SIDE[0] + z * SCALE
                p.drawLine(int(x), 0, int(x), self.height())
            for y in range(-50, 51, 25):
                yy = ORIGIN_SIDE[1] - y * SCALE
                p.drawLine(0, int(yy), self.width(), int(yy))
            p.setPen(QPen(SCREEN_COLOR, 4))
            p.drawLine(int(ORIGIN_SIDE[0]), int(ORIGIN_SIDE[1] - 80), int(ORIGIN_SIDE[0]), int(ORIGIN_SIDE[1] + 80))
        else:
            for x in range(-50, 51, 25):
                xx = ORIGIN_TOP[0] + x * SCALE
                p.drawLine(int(xx), 0, int(xx), self.height())
            for z in range(25, 125, 25):
                yy = ORIGIN_TOP[1] + z * SCALE
                p.drawLine(0, int(yy), self.width(), int(yy))
            p.setPen(QPen(SCREEN_COLOR, 4))
            p.drawLine(int(ORIGIN_TOP[0] - 80), int(ORIGIN_TOP[1]), int(ORIGIN_TOP[0] + 80), int(ORIGIN_TOP[1]))

        head_px = self._to_px(self.head)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(FACE_COLOR))
        p.drawEllipse(head_px, 12, 12)
        p.setPen(QPen(FACE_COLOR))
        p.drawText(QRectF(head_px.x() - 30, head_px.y() - 40, 60, 20), Qt.AlignCenter, t("cam_setup_face"))

        cam_px = self._to_px(self.cam)
        d = self._axis_dir()
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(CAM_COLOR))
        p.drawRoundedRect(QRectF(cam_px.x() - 22, cam_px.y() - 15, 44, 30), 4, 4)
        p.setPen(QPen(CAM_COLOR, 3))
        p.drawLine(cam_px + d * 4, cam_px + d * 46)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor("#f1c40f")))
        p.drawEllipse(cam_px + d * 46, 5, 5)
        p.drawEllipse(cam_px + d * -40, 7, 7)
        p.setPen(QPen(CAM_COLOR))
        p.drawText(QRectF(cam_px.x() - 30, cam_px.y() - 45, 60, 20), Qt.AlignCenter, t("cam_setup_cam"))
        p.end()


class CamSetupDialog(QDialog):
    def __init__(self, offset_x_cm=0.0, offset_y_cm=0.0, offset_z_cm=0.0,
                 yaw=0.0, pitch=0.0, roll=0.0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("cam_setup_title"))
        self.apply_callback = None

        self.view_top = SetupView(SetupView.TOP)
        self.view_side = SetupView(SetupView.SIDE)
        self.view_top.on_changed = self._on_any_changed
        self.view_side.on_changed = self._on_any_changed
        self.view_top.on_head_moved = self._on_head_moved
        self.view_side.on_head_moved = self._on_head_moved
        self.view_top.on_cam_moved = self._on_cam_moved
        self.view_side.on_cam_moved = self._on_cam_moved

        views_row = QHBoxLayout()
        top_group = QGroupBox(t("cam_setup_top"))
        top_lay = QVBoxLayout(top_group)
        top_lay.addWidget(self.view_top)
        side_group = QGroupBox(t("cam_setup_side"))
        side_lay = QVBoxLayout(side_group)
        side_lay.addWidget(self.view_side)
        views_row.addWidget(top_group)
        views_row.addWidget(side_group)

        self.chk_auto_aim = QCheckBox(t("cam_setup_aim"))
        self.chk_auto_aim.setChecked(True)
        self.chk_auto_aim.toggled.connect(self._on_aim_toggled)
        self.lbl_roll = QLabel(t("cam_tilt_roll"))
        self.slider_roll = QSlider(Qt.Horizontal)
        self.slider_roll.setRange(-45, 45)
        self.slider_roll.valueChanged.connect(self._on_any_changed)
        self.lbl_roll_val = QLabel("0°")
        self.lbl_roll_val.setFixedWidth(44)
        roll_row = QHBoxLayout()
        roll_row.addWidget(self.lbl_roll)
        roll_row.addWidget(self.slider_roll, 1)
        roll_row.addWidget(self.lbl_roll_val)

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
        self.btn_close = QPushButton(t("cam_setup_close"))
        self.btn_close.clicked.connect(self.accept)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_reset)
        btns.addStretch()
        btns.addWidget(self.btn_close)

        main = QVBoxLayout(self)
        main.addLayout(views_row)
        aim_row = QHBoxLayout()
        aim_row.addWidget(self.chk_auto_aim)
        aim_row.addLayout(roll_row)
        main.addLayout(aim_row)
        main.addLayout(self._values_grid)
        main.addLayout(btns)

        if offset_x_cm == 0.0 and offset_y_cm == 0.0 and offset_z_cm == 0.0:
            self.view_top.cam = QPointF(CAM_TOP_DEFAULT)
            self.view_side.cam = QPointF(CAM_SIDE_DEFAULT)
        else:
            self.view_top.cam = QPointF(offset_x_cm, offset_z_cm)
            self.view_side.cam = QPointF(offset_z_cm, offset_y_cm)

        aim_yaw, aim_pitch = self._aim_values()
        self.view_top.angle = self.view_top._aim_angle()
        self.view_side.angle = self.view_side._aim_angle()
        fresh = offset_x_cm == 0.0 and offset_y_cm == 0.0 and offset_z_cm == 0.0 \
            and yaw == 0.0 and pitch == 0.0 and roll == 0.0
        auto = fresh or (abs(aim_yaw - yaw) <= 0.5 and abs(aim_pitch - pitch) <= 0.5)
        self.chk_auto_aim.setChecked(auto)
        self.slider_roll.setValue(int(round(roll)))
        self.view_top.update()
        self.view_side.update()
        self._on_any_changed()

    def _aim_values(self):
        dx = -self.view_top.cam.x()
        dy = -self.view_side.cam.y()
        dz = self.view_top.head.y() - self.view_side.cam.x()
        yaw = math.degrees(math.asin(max(-1.0, min(1.0, dx / math.sqrt(dx * dx + dy * dy + dz * dz)))))
        pitch = math.degrees(math.atan2(-dy, dz))
        return yaw, pitch

    def _values(self):
        ox = self.view_top.cam.x()
        oy = self.view_side.cam.y()
        oz = self.view_side.cam.x()
        if self.chk_auto_aim.isChecked():
            yaw, pitch = self._aim_values()
        else:
            yaw = self.view_top.angle_to_value()
            pitch = self.view_side.angle_to_value()
        roll = self.slider_roll.value()
        return ox, oy, oz, yaw, pitch, roll

    def _on_head_moved(self, z):
        self.view_top.head.setY(z)
        self.view_side.head.setX(z)
        self.view_top.update()
        self.view_side.update()

    def _on_cam_moved(self, view):
        if view is self.view_top:
            x, z = view.cam.x(), view.cam.y()
            y = self.view_side.cam.y()
        else:
            z, y = view.cam.x(), view.cam.y()
            x = self.view_top.cam.x()
        self.view_top.cam = QPointF(x, z)
        self.view_side.cam = QPointF(z, y)
        self.view_top.update()
        self.view_side.update()

    def _on_any_changed(self, *_):
        if self.chk_auto_aim.isChecked():
            self.view_top.angle = self.view_top._aim_angle()
            self.view_side.angle = self.view_side._aim_angle()
            self.view_top.update()
            self.view_side.update()
        ox, oy, oz, yaw, pitch, roll = self._values()
        self._value_labels["X"].setText(f"{ox:+.1f} cm")
        self._value_labels["Y"].setText(f"{oy:+.1f} cm")
        self._value_labels["Z"].setText(f"{oz:+.1f} cm")
        self._value_labels["Yaw"].setText(f"{yaw:+.1f}°")
        self._value_labels["Pitch"].setText(f"{pitch:+.1f}°")
        self._value_labels["Roll"].setText(f"{roll:+.1f}°")
        self.lbl_roll_val.setText(f"{roll:+d}°")
        if self.apply_callback is not None:
            self.apply_callback(ox, oy, oz, yaw, pitch, roll)

    def _on_aim_toggled(self, checked):
        self.view_top.auto_aim = checked
        self.view_side.auto_aim = checked
        if checked:
            self.view_top.angle = self.view_top._aim_angle()
            self.view_side.angle = self.view_side._aim_angle()
            self.view_top.update()
            self.view_side.update()
            self._on_any_changed()

    def _on_reset(self):
        self.view_top.cam = QPointF(CAM_TOP_DEFAULT)
        self.view_side.cam = QPointF(CAM_SIDE_DEFAULT)
        self.view_top.head = QPointF(0.0, HEAD_Z)
        self.view_side.head = QPointF(HEAD_Z, 0.0)
        self.view_top.angle = self.view_top._aim_angle()
        self.view_side.angle = self.view_side._aim_angle()
        self.slider_roll.setValue(0)
        self.view_top.update()
        self.view_side.update()
        self._on_any_changed()
