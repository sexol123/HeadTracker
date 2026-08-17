"""Calibration wizard: guided camera-position + center + 4-direction gain
calibration.

Flow: camera mounting (CamSetupWidget) -> start tracking -> set center ->
record left/right/up/down segments (TuningRecorder) -> analyze
(analyze_calibration) -> apply through the standard tuning apply path.

The wizard is meant to be created ONCE per main window and reused via exec():
recreating dialogs with text editors was the root cause of the historical
native access violations (see main_window._on_tuning_clicked)."""

import logging
import time

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog, QWidget, QLabel, QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QMessageBox, QSizePolicy,
)

from i18n import t
from qobject_diag import track_obj
from ui.cam_setup_dialog import CamSetupWidget
from ui.axes_helper_dialog import AxisGauge
from ui.tuning_assistant import (
    analyze_calibration, export_tuning,
    MIN_SAMPLES, CALIB_DIRS, CALIB_DIR_AXIS,
)

log = logging.getLogger("calibration")

PREVIEW_W = 340
PREVIEW_H = 255
PREVIEW_EVERY = 3   # refresh preview every N timer ticks (~30 ms each)


class CalibrationWizard(QDialog):
    def __init__(self, recorder, worker, start_tracking, stop_tracking, tracking_active,
                 recenter_save, apply_changes, apply_cam, profile_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("calib_title"))
        self.setMinimumSize(720, 560)

        self._worker = worker
        self._start_tracking = start_tracking
        self._stop_tracking = stop_tracking
        self._tracking_active = tracking_active
        self._recenter_save = recenter_save
        self._apply_changes = apply_changes
        self._apply_cam = apply_cam
        self._profile_name = profile_name

        # The recorder is owned by the main window, which feeds it from the
        # pose stream while it is recording (see _on_worker_pose).
        self._recorder = recorder
        self._segments: dict[str, list] = {}
        self._center_ok = False
        self._we_started_tracking = False
        self._finished = False
        self._last_analysis = None
        self._tick = 0

        self._stack = QStackedWidget()
        self._dir_buttons = {}
        self._pages = [
            self._build_camera_page(),
            self._build_tracking_page(),
        ]
        for direction in CALIB_DIRS:
            self._pages.append(self._build_dir_page(direction))
        self._pages.append(self._build_results_page())
        for page in self._pages:
            self._stack.addWidget(page)

        self._live_row = QWidget()
        live_lay = QHBoxLayout(self._live_row)
        live_lay.setContentsMargins(0, 0, 0, 0)
        self._gauges = {}
        for name in ("yaw", "pitch", "roll"):
            gauge = AxisGauge(name, 60.0)
            live_lay.addWidget(gauge)
            self._gauges[name] = gauge
        live_lay.addStretch()
        self.lbl_conf = QLabel(t("calib_conf_label") + " --")
        self.lbl_conf.setFixedWidth(150)
        live_lay.addWidget(self.lbl_conf)

        self.btn_back = QPushButton(t("calib_btn_back"))
        self.btn_back.clicked.connect(lambda: self._go_page(self._current_page() - 1))
        self.btn_next = QPushButton(t("calib_btn_next"))
        self.btn_next.clicked.connect(self._on_next)
        self.btn_cancel = QPushButton(t("btn_cancel"))
        self.btn_cancel.clicked.connect(self.close)
        btns = QHBoxLayout()
        btns.addWidget(self.btn_back)
        btns.addStretch()
        btns.addWidget(self.btn_next)
        btns.addWidget(self.btn_cancel)

        main = QVBoxLayout(self)
        main.addWidget(self._stack, 1)
        main.addWidget(self._live_row)
        main.addLayout(btns)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_live)

        track_obj(self, "calibration_wizard")

    # ── Pages ────────────────────────────────────────────────────────

    def _build_camera_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        hint = QLabel(t("calib_page_camera_hint"))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._cam_widget = CamSetupWidget()
        self._cam_widget.apply_callback = self._on_cam_values
        lay.addWidget(self._cam_widget)
        return page

    def _build_tracking_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        hint = QLabel(t("calib_tracking_hint"))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.lbl_preview = QLabel()
        self.lbl_preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        self.lbl_preview.setStyleSheet("background-color: #1a1a2e; color: #555;")
        self.lbl_preview.setText(t("calib_preview_wait"))
        lay.addWidget(self.lbl_preview, 0, Qt.AlignCenter)
        self.btn_center = QPushButton(t("calib_btn_center"))
        self.btn_center.setFixedHeight(40)
        self.btn_center.setStyleSheet(
            "QPushButton { background-color: #2ecc71; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #27ae60; }"
        )
        self.btn_center.clicked.connect(self._on_center)
        lay.addWidget(self.btn_center, 0, Qt.AlignCenter)
        self.lbl_status = QLabel(t("calib_center_pending"))
        self.lbl_status.setWordWrap(True)
        lay.addWidget(self.lbl_status)
        lay.addStretch()
        return page

    def _build_dir_page(self, direction: str) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        hint = QLabel(t(f"calib_dir_hint_{direction}"))
        hint.setWordWrap(True)
        hint.setStyleSheet("font-weight: bold;")
        lay.addWidget(hint)
        status = QLabel("")
        status.setWordWrap(True)
        lay.addWidget(status)
        btn_record = QPushButton(t("calib_btn_record"))
        btn_record.setFixedHeight(36)
        btn_record.clicked.connect(lambda: self._on_record(direction))
        btn_ready = QPushButton(t("calib_btn_ready"))
        btn_ready.setFixedHeight(36)
        btn_ready.setEnabled(False)
        btn_ready.clicked.connect(lambda: self._on_ready(direction))
        row = QHBoxLayout()
        row.addWidget(btn_record)
        row.addWidget(btn_ready)
        lay.addLayout(row)
        lay.addStretch()
        self._dir_buttons[direction] = {"record": btn_record, "ready": btn_ready, "status": status}
        return page

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        hint = QLabel(t("calib_results_hint"))
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.report = QTextEdit()
        self.report.setReadOnly(True)
        lay.addWidget(self.report, 1)
        self.lbl_results_status = QLabel("")
        self.lbl_results_status.setWordWrap(True)
        lay.addWidget(self.lbl_results_status)
        self.btn_apply = QPushButton(t("calib_btn_finish"))
        self.btn_apply.setFixedHeight(40)
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_retry = QPushButton(t("calib_btn_retry"))
        self.btn_retry.clicked.connect(self._on_retry)
        row = QHBoxLayout()
        row.addWidget(self.btn_retry)
        row.addWidget(self.btn_apply)
        lay.addLayout(row)
        return page

    # ── Navigation ───────────────────────────────────────────────────

    def exec(self):
        self.reset_state()
        return super().exec()

    def reset_state(self):
        self._segments = {}
        self._center_ok = False
        self._finished = False
        self._last_analysis = None
        self.report.clear()
        self.lbl_results_status.setText("")
        self.btn_apply.setEnabled(False)
        self.btn_retry.setVisible(True)
        self.lbl_status.setText(t("calib_center_pending"))
        for buttons in self._dir_buttons.values():
            buttons["record"].setText(t("calib_btn_record"))
            buttons["ready"].setEnabled(False)
            buttons["status"].setText("")
        if not self._tracking_active():
            self._start_tracking()
            self._we_started_tracking = True
        else:
            self._we_started_tracking = False
        self._timer.start(30)
        self._go_page(0)

    def _current_page(self) -> int:
        return self._stack.currentIndex()

    def _go_page(self, index: int):
        index = max(0, min(len(self._pages) - 1, index))
        self._stack.setCurrentIndex(index)
        self._live_row.setVisible(0 < index < len(self._pages) - 1)
        self.btn_back.setEnabled(index > 0)
        self.btn_next.setVisible(index < len(self._pages) - 1)
        if index == len(self._pages) - 1:
            self._build_results()

    def _on_next(self):
        index = self._current_page()
        if index == 1 and not self._center_ok:
            self.lbl_status.setText(t("calib_center_need_face"))
            return
        if 2 <= index <= 5:
            direction = CALIB_DIRS[index - 2]
            if len(self._segments.get(direction, [])) < MIN_SAMPLES:
                buttons = self._dir_buttons[direction]
                buttons["status"].setText(t("calib_insufficient"))
                return
        self._go_page(index + 1)

    # ── Actions ──────────────────────────────────────────────────────

    def _on_cam_values(self, ox, oy, oz, yaw, pitch, roll):
        try:
            self._apply_cam(ox, oy, oz, yaw, pitch, roll)
        except Exception as e:
            log.warning(f"Camera values apply failed: {e}")

    def _on_center(self):
        if self._recenter_save():
            self._center_ok = True
            self.lbl_status.setText(t("calib_center_ok"))
        else:
            self._center_ok = False
            self.lbl_status.setText(t("calib_center_need_face"))

    def _on_record(self, direction: str):
        self._recorder.start()
        buttons = self._dir_buttons[direction]
        buttons["ready"].setEnabled(True)
        buttons["status"].setText(t("calib_recording"))

    def _on_ready(self, direction: str):
        self._recorder.stop()
        self._segments[direction] = list(self._recorder.samples)
        buttons = self._dir_buttons[direction]
        buttons["ready"].setEnabled(False)
        buttons["status"].setText(t("calib_recorded").format(len(self._segments[direction])))

    def _ordered_segments(self) -> list[dict]:
        return [{"dir": d, "samples": self._segments.get(d, [])} for d in CALIB_DIRS]

    def _build_results(self):
        analysis = analyze_calibration(self._ordered_segments())
        self._last_analysis = analysis
        lines = []
        if not analysis["ok"]:
            lines.append(t("calib_insufficient"))
            for r in analysis["reports"]:
                lines.append(
                    f"  {t('calib_dir_' + r['dir'])}: n={r['count']}"
                    f"  range={r['raw_range']:.1f}  dropped={r['dropped']}"
                )
        else:
            for r in analysis["reports"]:
                lines.append(
                    t("calib_dir_result").format(
                        t("calib_dir_" + r["dir"]),
                        r["count"],
                        f"{r['raw_range']:.1f}",
                        f"{r['gain']:.2f}" if r["gain"] is not None else "--",
                        f"{r['corr']:+.2f}",
                        f"{r['deadzone_frac'] * 100:.0f}",
                    )
                )
            lines.append("")
            lines.append("== " + t("tuning_recommendations") + " ==")
            lines.extend(analysis["recommendations"])
        self.report.setPlainText("\n".join(lines))
        self.btn_apply.setEnabled(analysis["ok"] and bool(analysis["changes"]))

    def _on_apply(self):
        analysis = self._last_analysis
        if analysis is None or not analysis["ok"]:
            return
        if analysis["changes"]:
            self._apply_changes(analysis["changes"])
        try:
            merged = [s for seg in self._ordered_segments() for s in seg["samples"]]
            export_tuning(merged, self._profile_name(), analysis)
        except Exception as e:
            log.warning(f"Calibration export failed: {e}")
        self.lbl_results_status.setText(t("calib_applied"))
        self.btn_apply.setEnabled(False)
        self._finished = True
        QTimer.singleShot(600, self.accept)

    def _on_retry(self):
        self._segments = {}
        self._center_ok = False
        for buttons in self._dir_buttons.values():
            buttons["ready"].setEnabled(False)
            buttons["status"].setText("")
        self.lbl_status.setText(t("calib_center_pending"))
        self._go_page(1)

    # ── Live refresh ─────────────────────────────────────────────────

    def _refresh_live(self):
        self._tick += 1
        raw = self._worker.get_raw_pose()
        mapped = self._worker.get_mapped_pose()
        tracking = self._worker.isRunning()
        for name, gauge in self._gauges.items():
            gauge.set_live(
                getattr(raw, name) if tracking else None,
                getattr(mapped, name) if tracking else None,
                0.0,
            )
        self.lbl_conf.setText(t("calib_conf_label") + f" {raw.confidence:.0%}")
        if self._current_page() == 1 and self._tick % PREVIEW_EVERY == 0:
            frame = self._worker.get_last_frame()
            if frame is not None and getattr(frame, "image", None) is not None:
                try:
                    rgb = cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    buf = rgb.tobytes()
                    qimg = QImage(buf, w, h, ch * w, QImage.Format_RGB888)
                    scaled = QPixmap.fromImage(qimg).scaled(
                        PREVIEW_W, PREVIEW_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    self.lbl_preview.setPixmap(scaled)
                except Exception as e:
                    log.debug(f"Preview error: {e}")

    # ── Close handling ───────────────────────────────────────────────

    def _confirm_cancel(self) -> bool:
        reply = QMessageBox.question(
            self, t("warning"), t("calib_cancel_confirm"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return reply == QMessageBox.Yes

    def _cleanup(self):
        self._timer.stop()
        if self._we_started_tracking:
            try:
                self._stop_tracking()
            except Exception as e:
                log.warning(f"Stop tracking on cancel failed: {e}")

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if not self._finished:
            if not self._confirm_cancel():
                event.ignore()
                return
            self._cleanup()
        super().closeEvent(event)
