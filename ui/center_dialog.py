import cv2
import logging
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget, QStackedLayout
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap, QFont, QKeyEvent

from tracker import Pose

log = logging.getLogger("center_dialog")


class CenterDialog(QDialog):
    def __init__(self, get_pose_func, get_frame_func, on_centered):
        super().__init__()
        self._get_pose = get_pose_func
        self._get_frame = get_frame_func
        self._on_centered = on_centered
        self._current_pose = Pose()

        self.setWindowTitle("Center")
        self.showFullScreen()
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background-color: #0a0a1a;")

        # Camera preview
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(400, 300)
        self.preview.setAttribute(Qt.WA_TransparentForMouseEvents)

        # Center overlay
        center_widget = QWidget()
        center_widget.setStyleSheet("background: transparent;")
        center_layout = QVBoxLayout(center_widget)
        center_layout.setAlignment(Qt.AlignCenter)

        self.lbl_instruction = QLabel("Look at the target and press the button")
        self.lbl_instruction.setAlignment(Qt.AlignCenter)
        self.lbl_instruction.setFont(QFont("Segoe UI", 18))
        self.lbl_instruction.setStyleSheet("color: #cccccc; background: transparent;")
        center_layout.addWidget(self.lbl_instruction)

        self.lbl_status = QLabel("")
        self.lbl_status.setAlignment(Qt.AlignCenter)
        self.lbl_status.setFont(QFont("Consolas", 14))
        self.lbl_status.setStyleSheet("color: #ffff00; background: transparent;")
        center_layout.addWidget(self.lbl_status)

        self.btn_center = QPushButton("CENTER")
        self.btn_center.setFixedSize(200, 200)
        self.btn_center.setFont(QFont("Segoe UI", 22, QFont.Bold))
        self.btn_center.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 120, 255, 200);
                color: white;
                border: 4px solid rgba(255, 255, 255, 150);
                border-radius: 100px;
            }
            QPushButton:hover {
                background-color: rgba(0, 150, 255, 240);
            }
            QPushButton:pressed {
                background-color: rgba(0, 200, 100, 240);
            }
        """)
        self.btn_center.clicked.connect(self._on_button_clicked)
        center_layout.addWidget(self.btn_center, alignment=Qt.AlignCenter)

        self.lbl_hint = QLabel("ESC to cancel")
        self.lbl_hint.setAlignment(Qt.AlignCenter)
        self.lbl_hint.setFont(QFont("Segoe UI", 11))
        self.lbl_hint.setStyleSheet("color: #888888; background: transparent;")
        center_layout.addWidget(self.lbl_hint)

        # Layout: preview background, center overlay
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackAll)
        self.preview.setParent(self)
        stack.addWidget(self.preview)
        center_widget.setParent(self)
        stack.addWidget(center_widget)
        main_layout.addLayout(stack)

        # Timer
        self._timer = QTimer()
        self._timer.timeout.connect(self._update_frame)
        self._timer.start(33)
        self._update_frame()

    def _update_frame(self):
        try:
            frame = self._get_frame()
            if frame is None:
                return

            pose = self._get_pose()
            self._current_pose = pose

            h, w = frame.shape[:2]
            overlay = frame.copy()

            # Crosshair
            cx, cy = w // 2, h // 2
            cl = 40
            cv2.line(overlay, (cx - cl, cy), (cx + cl, cy), (0, 200, 255), 2)
            cv2.line(overlay, (cx, cy - cl), (cx, cy + cl), (0, 200, 255), 2)
            cv2.circle(overlay, (cx, cy), cl, (0, 200, 255), 2)

            # Face status
            if pose.confidence > 0:
                cv2.putText(overlay, f"Face OK  Y:{pose.yaw:+.1f} P:{pose.pitch:+.1f}",
                            (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)
            else:
                cv2.putText(overlay, "No face - look at camera",
                            (10, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)

            rgb = cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB)
            qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview.setPixmap(scaled)
        except Exception as e:
            log.warning(f"Center dialog frame update error: {e}")

    def _on_button_clicked(self):
        if self._current_pose.confidence <= 0:
            self.lbl_status.setText("No face detected! Look at the camera.")
            log.info("Center button pressed but no face detected")
            return
        log.info(f"Center button pressed, confidence={self._current_pose.confidence:.2f}")
        self._on_centered(self._current_pose)
        self.accept()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            self._on_centered(None)
            self.reject()
        elif event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._on_button_clicked()

    def closeEvent(self, event):
        self._timer.stop()
        event.accept()
