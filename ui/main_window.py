import logging
import time
import math
import cv2
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox,
    QDoubleSpinBox, QGroupBox, QFormLayout, QSplitter,
    QTabWidget, QTextEdit, QLineEdit, QMessageBox,
    QFileDialog, QScrollArea,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QImage, QPixmap, QFont

from worker import TrackingWorker
from camera import Camera
from tracker import Pose
from freetrack import IS_WINDOWS
from config import (
    Profile, AxisConfig, AppSettings,
    load_profile, save_profile,
    load_settings, save_settings,
    list_profiles, PROFILES_DIR,
)
from pathlib import Path
from ui.center_dialog import CenterDialog

log = logging.getLogger("ui")


class MainWindow(QMainWindow):
    FACE_MESH_TESSELATION = [
        (127, 34), (34, 139), (139, 127), (11, 0), (0, 37), (37, 11),
        (232, 231), (231, 120), (120, 232), (72, 37), (37, 39), (39, 72),
        (128, 121), (121, 47), (47, 128), (232, 121), (121, 128), (128, 232),
        (104, 69), (69, 67), (67, 104), (175, 171), (171, 148), (148, 175),
        (118, 50), (50, 101), (101, 118), (73, 39), (39, 40), (40, 73),
        (9, 151), (151, 108), (108, 9), (48, 115), (115, 131), (131, 48),
        (194, 204), (204, 211), (211, 194), (74, 40), (40, 185), (185, 74),
        (80, 42), (42, 183), (183, 80), (40, 92), (92, 186), (186, 40),
        (230, 229), (229, 119), (119, 230), (226, 130), (130, 247), (247, 226),
        (63, 53), (53, 52), (52, 63), (238, 20), (20, 242), (242, 238),
        (46, 70), (70, 156), (156, 46), (78, 62), (62, 96), (96, 78),
        (46, 53), (53, 63), (63, 46), (143, 34), (34, 127), (127, 143),
        (123, 117), (117, 111), (111, 123), (44, 125), (125, 19), (19, 44),
        (236, 134), (134, 51), (51, 236), (216, 206), (206, 205), (205, 216),
        (154, 153), (153, 155), (155, 154), (110, 24), (24, 23), (23, 110),
        (75, 60), (60, 166), (166, 75), (247, 246), (246, 91), (91, 247),
        (226, 113), (113, 46), (46, 226),
    ]

    def __init__(self, profile: Profile):
        super().__init__()
        self.profile = profile
        self.app_settings = load_settings()
        self.worker = TrackingWorker()
        self.worker.frame_ready.connect(self._on_worker_frame)
        self.worker.pose_ready.connect(self._on_worker_pose)
        self.worker.confidence_ready.connect(self._on_worker_confidence)
        self.worker.error_occurred.connect(self._on_worker_error)
        self.worker.stopped.connect(self._on_worker_stopped)
        self.tracking_active = False
        self.center_pose = Pose()
        self.current_pose = Pose()
        self.raw_pose = Pose()
        self.frame_count = 0
        self.last_fps_time = 0.0
        self.display_fps = 0.0
        self._last_landmarks = None
        self._current_profile_path: Path | None = None
        self._was_minimized = False

        self._init_ui()
        self._populate_profiles()
        self._apply_profile()

    def _init_ui(self):
        self.setWindowTitle("HeadTracker v0.1")
        self.setMinimumSize(960, 640)
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left: camera preview
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(4, 4, 4, 4)
        self.preview_label = QLabel("Camera preview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(480, 360)
        self.preview_label.setStyleSheet("background-color: #1a1a2e; color: #888;")
        left_layout.addWidget(self.preview_label)

        controls_layout = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self._on_start_stop)
        controls_layout.addWidget(self.btn_start)
        self.btn_center = QPushButton("Center (F12)")
        self.btn_center.setFixedHeight(36)
        self.btn_center.clicked.connect(self._on_center)
        controls_layout.addWidget(self.btn_center)
        self.btn_reset = QPushButton("Reset (F11)")
        self.btn_reset.setFixedHeight(36)
        self.btn_reset.clicked.connect(self._on_reset)
        controls_layout.addWidget(self.btn_reset)
        left_layout.addLayout(controls_layout)
        splitter.addWidget(left_panel)

        # Right: tabs
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)
        self._build_profile_tab()
        self._build_status_tab()
        self._build_camera_tab()
        self._build_axes_tab()
        self._build_output_tab()
        self._build_log_tab()
        splitter.addWidget(right_panel)
        splitter.setSizes([520, 440])

    def _build_profile_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        sel_layout = QHBoxLayout()
        self.combo_profile = QComboBox()
        self.combo_profile.currentIndexChanged.connect(self._on_profile_changed)
        sel_layout.addWidget(self.combo_profile, 1)
        self.btn_save = QPushButton("Save")
        self.btn_save.setFixedWidth(80)
        self.btn_save.clicked.connect(self._on_save)
        sel_layout.addWidget(self.btn_save)
        layout.addLayout(sel_layout)

        act_layout = QHBoxLayout()
        self.btn_new = QPushButton("New")
        self.btn_new.clicked.connect(self._on_profile_new)
        act_layout.addWidget(self.btn_new)
        btn_delete = QPushButton("Delete")
        btn_delete.clicked.connect(self._on_profile_delete)
        act_layout.addWidget(btn_delete)
        self.btn_delete = btn_delete
        self.btn_duplicate = QPushButton("Duplicate")
        self.btn_duplicate.clicked.connect(self._on_profile_duplicate)
        act_layout.addWidget(self.btn_duplicate)
        self.btn_export = QPushButton("Export")
        self.btn_export.clicked.connect(self._on_profile_export)
        act_layout.addWidget(self.btn_export)
        self.btn_import = QPushButton("Import")
        self.btn_import.clicked.connect(self._on_profile_import)
        act_layout.addWidget(self.btn_import)
        layout.addLayout(act_layout)
        layout.addStretch()
        self.tabs.addTab(tab, "Profile")

    def _build_status_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        pose_group = QGroupBox("Head Pose")
        pose_form = QFormLayout()
        self.lbl_yaw = QLabel("0.00"); self.lbl_yaw.setFont(QFont("Consolas", 14))
        pose_form.addRow("Yaw:", self.lbl_yaw)
        self.lbl_pitch = QLabel("0.00"); self.lbl_pitch.setFont(QFont("Consolas", 14))
        pose_form.addRow("Pitch:", self.lbl_pitch)
        self.lbl_roll = QLabel("0.00"); self.lbl_roll.setFont(QFont("Consolas", 14))
        pose_form.addRow("Roll:", self.lbl_roll)
        self.lbl_x = QLabel("0.00"); self.lbl_x.setFont(QFont("Consolas", 14))
        pose_form.addRow("X:", self.lbl_x)
        self.lbl_y = QLabel("0.00"); self.lbl_y.setFont(QFont("Consolas", 14))
        pose_form.addRow("Y:", self.lbl_y)
        self.lbl_z = QLabel("0.00"); self.lbl_z.setFont(QFont("Consolas", 14))
        pose_form.addRow("Z:", self.lbl_z)
        pose_group.setLayout(pose_form)
        layout.addWidget(pose_group)

        info_group = QGroupBox("Info")
        info_form = QFormLayout()
        self.lbl_confidence = QLabel("0.0")
        info_form.addRow("Confidence:", self.lbl_confidence)
        self.lbl_fps = QLabel("0")
        info_form.addRow("FPS:", self.lbl_fps)
        self.lbl_profile = QLabel(self.profile.name)
        info_form.addRow("Profile:", self.lbl_profile)
        self.lbl_status = QLabel("Stopped")
        info_form.addRow("Status:", self.lbl_status)
        info_group.setLayout(info_form)
        layout.addWidget(info_group)
        layout.addStretch()
        self.tabs.addTab(tab, "Status")

    def _build_camera_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._cam_form = form = QFormLayout()
        self.combo_cam_type = QComboBox()
        self.combo_cam_type.addItems(["Local Webcam", "IP Camera (RTSP/HTTP)"])
        self.combo_cam_type.currentIndexChanged.connect(self._on_cam_type_changed)
        form.addRow("Source:", self.combo_cam_type)
        self.combo_camera = QComboBox()
        cameras = Camera.list_cameras(max_count=5)
        for cam in cameras:
            self.combo_camera.addItem(
                f"Camera {cam['index']} ({cam['width']}x{cam['height']})", cam["index"])
        self._lbl_camera = QLabel("Camera:")
        form.addRow(self._lbl_camera, self.combo_camera)
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("rtsp://192.168.1.100:554/stream")
        self._lbl_url = QLabel("URL:")
        form.addRow(self._lbl_url, self.edit_url)
        self.spin_width = QSpinBox(); self.spin_width.setRange(160, 1920); self.spin_width.setSingleStep(32)
        form.addRow("Width:", self.spin_width)
        self.spin_height = QSpinBox(); self.spin_height.setRange(120, 1080); self.spin_height.setSingleStep(32)
        form.addRow("Height:", self.spin_height)
        self.spin_fps = QSpinBox(); self.spin_fps.setRange(15, 120)
        form.addRow("FPS:", self.spin_fps)
        self.chk_mirror = QCheckBox("Mirror")
        form.addRow("Mirror:", self.chk_mirror)
        self.chk_enhance = QCheckBox("Enhance low light (CLAHE)")
        form.addRow("Enhance:", self.chk_enhance)
        layout.addLayout(form)

        # IP camera stats (hidden by default)
        self._ip_stats_group = QGroupBox("Stream Stats")
        stats_form = QFormLayout()
        self.lbl_ip_fps = QLabel("--")
        self.lbl_ip_fps.setFont(QFont("Consolas", 11))
        stats_form.addRow("FPS:", self.lbl_ip_fps)
        self.lbl_ip_frame_time = QLabel("--")
        self.lbl_ip_frame_time.setFont(QFont("Consolas", 11))
        stats_form.addRow("Frame time:", self.lbl_ip_frame_time)
        self.lbl_ip_bandwidth = QLabel("--")
        self.lbl_ip_bandwidth.setFont(QFont("Consolas", 11))
        stats_form.addRow("Bandwidth:", self.lbl_ip_bandwidth)
        self.lbl_ip_resolution = QLabel("--")
        self.lbl_ip_resolution.setFont(QFont("Consolas", 11))
        stats_form.addRow("Resolution:", self.lbl_ip_resolution)
        self.lbl_ip_frames = QLabel("--")
        self.lbl_ip_frames.setFont(QFont("Consolas", 11))
        stats_form.addRow("Frames:", self.lbl_ip_frames)
        self._ip_stats_group.setLayout(stats_form)
        self._ip_stats_group.setVisible(False)
        layout.addWidget(self._ip_stats_group)

        layout.addStretch()
        self.tabs.addTab(tab, "Camera")

    def _build_axes_tab(self):
        tab = QWidget()
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); layout = QVBoxLayout(inner)
        self._axis_widgets = {}
        for axis_name in ["yaw", "pitch", "roll", "x", "y", "z"]:
            group = QGroupBox(axis_name.upper()); form = QFormLayout()
            chk_enabled = QCheckBox("Enabled"); form.addRow("Enabled:", chk_enabled)
            spin_sensitivity = QDoubleSpinBox(); spin_sensitivity.setRange(0.1, 20.0); spin_sensitivity.setSingleStep(0.1)
            form.addRow("Sensitivity:", spin_sensitivity)
            spin_deadzone = QDoubleSpinBox(); spin_deadzone.setRange(0.0, 30.0); spin_deadzone.setSingleStep(0.5)
            form.addRow("Deadzone:", spin_deadzone)
            chk_inverted = QCheckBox("Inverted"); form.addRow("Inverted:", chk_inverted)
            group.setLayout(form); layout.addWidget(group)
            self._axis_widgets[axis_name] = {"enabled": chk_enabled, "sensitivity": spin_sensitivity,
                                              "deadzone": spin_deadzone, "inverted": chk_inverted}
        layout.addStretch()
        scroll.setWidget(inner)
        tab_layout = QVBoxLayout(tab); tab_layout.addWidget(scroll)
        self.tabs.addTab(tab, "Axes")

    def _build_output_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.combo_protocol = QComboBox()
        protocols = ["FreeTrack (Windows)", "UDP (Cross-platform)"] if IS_WINDOWS else ["UDP"]
        self.combo_protocol.addItems(protocols)
        self.combo_protocol.currentIndexChanged.connect(self._on_protocol_changed)
        form.addRow("Protocol:", self.combo_protocol)
        self.lbl_ft_status = QLabel("Not running"); form.addRow("Status:", self.lbl_ft_status)

        # UDP settings
        self._udp_widget = QWidget()
        udp_form = QFormLayout(self._udp_widget)
        udp_form.setContentsMargins(0, 0, 0, 0)
        self.edit_udp_host = QLineEdit("127.0.0.1")
        udp_form.addRow("Host:", self.edit_udp_host)
        self.spin_udp_port = QSpinBox(); self.spin_udp_port.setRange(1, 65535); self.spin_udp_port.setValue(4242)
        udp_form.addRow("Port:", self.spin_udp_port)
        layout.addWidget(self._udp_widget)

        layout.addLayout(form); layout.addStretch()
        self.tabs.addTab(tab, "Output")

    def _build_log_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        self.log_text = QTextEdit(); self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.log_text)
        btn_clear = QPushButton("Clear Log"); btn_clear.clicked.connect(self.log_text.clear)
        layout.addWidget(btn_clear)
        self.tabs.addTab(tab, "Log")

    def append_log(self, message: str):
        self.log_text.append(message)
        if self.log_text.document().blockCount() > 500:
            cursor = self.log_text.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, 100)
            cursor.removeSelectedText()

    # ── Profile Management ───────────────────────────────────────
    def _populate_profiles(self):
        self.combo_profile.blockSignals(True)
        self.combo_profile.clear()
        for p in list_profiles():
            self.combo_profile.addItem(p.stem, str(p))
        # Select current
        for i in range(self.combo_profile.count()):
            if self.combo_profile.itemData(i) and Path(self.combo_profile.itemData(i)).stem == self.profile.name:
                self.combo_profile.setCurrentIndex(i)
                break
        self.combo_profile.blockSignals(False)
        self._update_buttons_for_default()

    def _on_profile_changed(self, index):
        path = self.combo_profile.currentData()
        if not path:
            return
        try:
            self.profile = load_profile(path)
            self._current_profile_path = Path(path)
            self._apply_profile()
            self.lbl_profile.setText(self.profile.name)
            log.info(f"Profile loaded: {self.profile.name}")
        except Exception as e:
            log.error(f"Failed to load profile: {e}", exc_info=True)
            QMessageBox.warning(self, "Error", f"Failed to load profile:\n{e}")
        self._update_buttons_for_default()

    def _update_buttons_for_default(self):
        is_default = self.profile.name == "Default"
        self.btn_save.setEnabled(not is_default)
        self.btn_delete.setEnabled(not is_default)

    def _apply_profile(self):
        p = self.profile
        self.chk_mirror.setChecked(p.mirror)
        self.chk_enhance.setChecked(p.image_enhance)
        self.spin_width.setValue(p.camera_width)
        self.spin_height.setValue(p.camera_height)
        self.spin_fps.setValue(p.camera_fps)
        self.edit_url.setText(p.camera_url)

        # Camera type
        if p.camera_url:
            self.combo_cam_type.setCurrentIndex(1)
        else:
            self.combo_cam_type.setCurrentIndex(0)
        self._on_cam_type_changed(self.combo_cam_type.currentIndex())

        for i in range(self.combo_camera.count()):
            if self.combo_camera.itemData(i) == p.camera_index:
                self.combo_camera.setCurrentIndex(i); break
        for name, widgets in self._axis_widgets.items():
            if name in p.axes:
                ax = p.axes[name]
                widgets["enabled"].setChecked(ax.enabled)
                widgets["sensitivity"].setValue(ax.sensitivity)
                widgets["deadzone"].setValue(ax.deadzone)
                widgets["inverted"].setChecked(ax.inverted)
        self.lbl_profile.setText(p.name)

        # Output protocol
        if IS_WINDOWS:
            self.combo_protocol.setCurrentIndex(0 if p.output_protocol == "freetrack" else 1)
        else:
            self.combo_protocol.setCurrentIndex(0)
        self._on_protocol_changed(self.combo_protocol.currentIndex())
        self.edit_udp_host.setText(p.udp_host)
        self.spin_udp_port.setValue(p.udp_port)

    def _on_cam_type_changed(self, index):
        is_ip = index == 1
        self.combo_camera.setVisible(not is_ip)
        self._lbl_camera.setVisible(not is_ip)
        self.edit_url.setVisible(is_ip)
        self._lbl_url.setVisible(is_ip)
        self._ip_stats_group.setVisible(is_ip)
        self.preview_label.setVisible(not is_ip)

    def _on_protocol_changed(self, index):
        self._udp_widget.setVisible(not IS_WINDOWS or index == 1)

    def _read_profile_from_ui(self) -> Profile:
        is_ip = self.combo_cam_type.currentIndex() == 1
        # Determine protocol
        if IS_WINDOWS:
            protocol = "freetrack" if self.combo_protocol.currentIndex() == 0 else "udp"
        else:
            protocol = "udp"
        p = Profile(
            name=self.profile.name,
            camera_index=self.combo_camera.currentData() or 0,
            camera_width=self.spin_width.value(),
            camera_height=self.spin_height.value(),
            camera_fps=self.spin_fps.value(),
            mirror=self.chk_mirror.isChecked(),
            camera_url=self.edit_url.text().strip() if is_ip else "",
            image_enhance=self.chk_enhance.isChecked(),
            output_protocol=protocol,
            udp_host=self.edit_udp_host.text().strip() or "127.0.0.1",
            udp_port=self.spin_udp_port.value(),
            hotkeys=self.profile.hotkeys.copy(),
        )
        for name, widgets in self._axis_widgets.items():
            p.axes[name] = AxisConfig(
                enabled=widgets["enabled"].isChecked(),
                sensitivity=widgets["sensitivity"].value(),
                deadzone=widgets["deadzone"].value(),
                inverted=widgets["inverted"].isChecked(),
            )
        return p

    def _on_save(self):
        self.profile = self._read_profile_from_ui()
        # Default profile is immutable - save as new profile instead
        if self.profile.name == "Default":
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "Save As", "Save as new profile:",
                                             text="My Default")
            if ok and name:
                self.profile.name = name
                path = PROFILES_DIR / f"{name.lower().replace(' ', '_')}.json"
                try:
                    save_profile(self.profile, path)
                    self._current_profile_path = path
                    self._populate_profiles()
                    # Select the new profile
                    for i in range(self.combo_profile.count()):
                        if self.combo_profile.itemData(i) == str(path):
                            self.combo_profile.setCurrentIndex(i); break
                    log.info(f"Default profile saved as: {name}")
                    QMessageBox.information(self, "Saved", f"Profile '{name}' created.")
                except Exception as e:
                    log.error(f"Failed to save profile: {e}", exc_info=True)
                    QMessageBox.warning(self, "Error", f"Failed to save profile:\n{e}")
            return
        try:
            if self._current_profile_path:
                save_profile(self.profile, self._current_profile_path)
                log.info(f"Profile saved: {self._current_profile_path.name}")
            else:
                path = PROFILES_DIR / f"{self.profile.name.lower().replace(' ', '_')}.json"
                save_profile(self.profile, path)
                self._current_profile_path = path
                self._populate_profiles()
                log.info(f"Profile saved as: {path.name}")
            QMessageBox.information(self, "Saved", f"Profile '{self.profile.name}' saved.")
        except Exception as e:
            log.error(f"Failed to save profile: {e}", exc_info=True)
            QMessageBox.warning(self, "Error", f"Failed to save profile:\n{e}")

    def _on_profile_new(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "New Profile", "Profile name:")
        if ok and name:
            new_profile = Profile(name=name)
            path = PROFILES_DIR / f"{name.lower().replace(' ', '_')}.json"
            try:
                save_profile(new_profile, path)
                self._populate_profiles()
                # Select new
                for i in range(self.combo_profile.count()):
                    if self.combo_profile.itemData(i) == str(path):
                        self.combo_profile.setCurrentIndex(i); break
                log.info(f"New profile created: {name}")
            except Exception as e:
                log.error(f"Failed to create profile: {e}", exc_info=True)
                QMessageBox.warning(self, "Error", f"Failed to create profile:\n{e}")

    def _on_profile_delete(self):
        if not self._current_profile_path:
            return
        if self.profile.name == "Default":
            QMessageBox.information(self, "Cannot Delete", "The 'Default' profile cannot be deleted.")
            return
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{self.profile.name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._current_profile_path.unlink(missing_ok=True)
            log.info(f"Profile deleted: {self.profile.name}")
            self._populate_profiles()
            if self.combo_profile.count() > 0:
                self.combo_profile.setCurrentIndex(0)
            self.profile = load_profile(self.combo_profile.currentData())
            self._update_buttons_for_default()

    def _on_profile_duplicate(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Duplicate Profile", "New name:",
                                         text=f"{self.profile.name} (copy)")
        if ok and name:
            new_profile = self._read_profile_from_ui()
            new_profile.name = name
            path = PROFILES_DIR / f"{name.lower().replace(' ', '_')}.json"
            try:
                save_profile(new_profile, path)
                self._populate_profiles()
                log.info(f"Profile duplicated: {name}")
            except Exception as e:
                log.error(f"Failed to duplicate profile: {e}", exc_info=True)
                QMessageBox.warning(self, "Error", f"Failed to duplicate profile:\n{e}")

    def _on_profile_export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Profile", f"{self.profile.name}.json", "JSON Files (*.json)")
        if path:
            try:
                save_profile(self._read_profile_from_ui(), path)
                log.info(f"Profile exported: {path}")
            except Exception as e:
                log.error(f"Failed to export profile: {e}", exc_info=True)
                QMessageBox.warning(self, "Error", f"Failed to export profile:\n{e}")

    def _on_profile_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Profile", "", "JSON Files (*.json)")
        if path:
            try:
                imported = load_profile(path)
                dest = PROFILES_DIR / Path(path).name
                save_profile(imported, dest)
                self._populate_profiles()
                log.info(f"Profile imported: {imported.name}")
            except Exception as e:
                log.error(f"Failed to import profile: {e}", exc_info=True)
                QMessageBox.warning(self, "Error", f"Failed to import profile:\n{e}")

    # ── Tracking ─────────────────────────────────────────────────
    @Slot(object)
    def _on_worker_frame(self, frame):
        try:
            self._last_landmarks = self.worker._tracker.get_last_landmarks() if self.worker._tracker else None
            display_frame = self._draw_overlay(frame.image, self.current_pose)
            rgb = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimg)
            scaled = pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.FastTransformation)
            self.preview_label.setPixmap(scaled)
        except Exception as e:
            log.warning(f"Display update error: {e}")

    @Slot(object)
    def _on_worker_pose(self, pose):
        self.current_pose = pose
        self.lbl_yaw.setText(f"{pose.yaw:+.2f}")
        self.lbl_pitch.setText(f"{pose.pitch:+.2f}")
        self.lbl_roll.setText(f"{pose.roll:+.2f}")
        self.lbl_x.setText(f"{pose.x:+.1f}")
        self.lbl_y.setText(f"{pose.y:+.1f}")
        self.lbl_z.setText(f"{pose.z:+.1f}")

    @Slot(float)
    def _on_worker_confidence(self, confidence):
        self.lbl_confidence.setText(f"{confidence:.2f}")
        self.frame_count += 1
        now = time.perf_counter()
        if now - self.last_fps_time >= 1.0:
            self.display_fps = self.frame_count / (now - self.last_fps_time)
            self.frame_count = 0
            self.last_fps_time = now
            self.lbl_fps.setText(f"{self.display_fps:.0f}")

    @Slot(str)
    def _on_worker_error(self, msg):
        log.error(f"Worker error: {msg}")
        self.lbl_status.setText("Error!")
        QMessageBox.warning(self, "Error", msg)

    @Slot()
    def _on_worker_stopped(self):
        self.tracking_active = False
        self.btn_start.setText("Start")
        self.lbl_status.setText("Stopped")
        self.lbl_ft_status.setText("Not running")
        self.preview_label.clear()
        self.preview_label.setText("Camera preview")
        is_ip = self.combo_cam_type.currentIndex() == 1
        self.preview_label.setVisible(not is_ip)
        self._set_controls_enabled(True)
        log.info("Tracking stopped")

    def _draw_overlay(self, frame, pose):
        h, w = frame.shape[:2]
        if self._last_landmarks is not None:
            landmarks = self._last_landmarks
            for i, j in self.FACE_MESH_TESSELATION:
                if i < len(landmarks) and j < len(landmarks):
                    pt1 = (int(landmarks[i].x * w), int(landmarks[i].y * h))
                    pt2 = (int(landmarks[j].x * w), int(landmarks[j].y * h))
                    cv2.line(frame, pt1, pt2, (0, 180, 0), 1, cv2.LINE_AA)
            key_indices = [1, 152, 33, 263, 61, 291, 10, 338, 297, 332, 284, 251,
                           389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377]
            for idx in key_indices:
                if idx < len(landmarks):
                    cv2.circle(frame, (int(landmarks[idx].x * w), int(landmarks[idx].y * h)), 2, (0, 255, 0), -1, cv2.LINE_AA)
            if 1 < len(landmarks):
                cv2.circle(frame, (int(landmarks[1].x * w), int(landmarks[1].y * h)), 5, (0, 0, 255), -1, cv2.LINE_AA)

        if pose.confidence > 0:
            if self._last_landmarks and len(self._last_landmarks) > 1:
                ox = int(self._last_landmarks[1].x * w)
                oy = int(self._last_landmarks[1].y * h)
            else:
                ox, oy = w // 2, h // 2
            axis_len = 60
            yaw_rad = math.radians(pose.yaw)
            pitch_rad = math.radians(pose.pitch)
            roll_rad = math.radians(pose.roll)
            cv2.arrowedLine(frame, (ox, oy), (ox + int(axis_len * math.sin(yaw_rad)), oy), (0, 0, 255), 2, tipLength=0.3)
            cv2.arrowedLine(frame, (ox, oy), (ox, oy - int(axis_len * math.sin(pitch_rad))), (0, 255, 0), 2, tipLength=0.3)
            cv2.arrowedLine(frame, (ox, oy), (ox + int(axis_len * math.sin(roll_rad) * 0.7), oy + int(axis_len * math.cos(roll_rad) * 0.7)), (255, 0, 0), 2, tipLength=0.3)
            cv2.putText(frame, f"Y:{pose.yaw:+.1f} P:{pose.pitch:+.1f} R:{pose.roll:+.1f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.putText(frame, f"X:{pose.x:+.1f} Y:{pose.y:+.1f} Z:{pose.z:+.1f}", (10, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1, cv2.LINE_AA)

        conf = pose.confidence
        bar_w, bar_h = 100, 12
        bx, by = w - bar_w - 10, 10
        cv2.rectangle(frame, (bx, by), (bx + bar_w, by + bar_h), (50, 50, 50), -1)
        cv2.rectangle(frame, (bx, by), (bx + int(bar_w * conf), by + bar_h), (0, 255, 0) if conf > 0.5 else (0, 0, 255), -1)
        cv2.putText(frame, f"{conf:.0%}", (bx + bar_w + 5, by + bar_h - 1), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        return frame

    @Slot()
    def _on_start_stop(self):
        if self.tracking_active: self._stop_tracking()
        else: self._start_tracking()

    def _start_tracking(self):
        self.profile = self._read_profile_from_ui()
        log.info(f"Starting tracking: {self.profile.name}")
        self.worker.start_tracking(self.profile)
        self.tracking_active = True
        self.btn_start.setText("Stop")
        self.lbl_status.setText("Running")
        self.lbl_ft_status.setText("Running")
        self._set_controls_enabled(False)

    def _stop_tracking(self):
        log.info("Stopping tracking...")
        self.worker.stop_tracking()
        self.tracking_active = False
        self.btn_start.setText("Start")
        self.lbl_status.setText("Stopped")
        self.lbl_ft_status.setText("Not running")
        self.preview_label.clear()
        self.preview_label.setText("Camera preview")
        is_ip = self.combo_cam_type.currentIndex() == 1
        self.preview_label.setVisible(not is_ip)
        self._set_controls_enabled(True)
        log.info("Tracking stopped")

    def _set_controls_enabled(self, enabled: bool):
        self.combo_profile.setEnabled(enabled)
        self.btn_save.setEnabled(enabled)
        self.btn_new.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)
        self.btn_duplicate.setEnabled(enabled)
        self.btn_export.setEnabled(enabled)
        self.btn_import.setEnabled(enabled)
        self.combo_cam_type.setEnabled(enabled)
        self.combo_camera.setEnabled(enabled)
        self.edit_url.setEnabled(enabled)
        self.spin_width.setEnabled(enabled)
        self.spin_height.setEnabled(enabled)
        self.spin_fps.setEnabled(enabled)
        self.chk_mirror.setEnabled(enabled)
        self.chk_enhance.setEnabled(enabled)
        self.combo_protocol.setEnabled(enabled)
        self.edit_udp_host.setEnabled(enabled)
        self.spin_udp_port.setEnabled(enabled)
        if enabled:
            self._update_buttons_for_default()

    @Slot()
    def _on_center(self):
        if not self.tracking_active:
            return
        try:
            dialog = CenterDialog(
                get_pose_func=lambda: self.worker.get_raw_pose(),
                get_frame_func=lambda: self.worker.get_last_frame().image if self.worker.get_last_frame() else None,
                on_centered=self._apply_center,
            )
            dialog.exec()
        except Exception as e:
            log.error(f"Center dialog error: {e}", exc_info=True)

    def _apply_center(self, pose: Pose | None):
        if pose is None:
            log.info("Center cancelled")
            return
        self.center_pose = Pose(
            yaw=pose.yaw,
            pitch=pose.pitch,
            roll=pose.roll,
            x=pose.x,
            y=pose.y,
            z=pose.z,
        )
        self.worker.set_center_pose(self.center_pose)
        log.info(f"Center set: yaw={self.center_pose.yaw:+.1f} pitch={self.center_pose.pitch:+.1f} roll={self.center_pose.roll:+.1f}")

    @Slot()
    def _on_reset(self):
        self.center_pose = Pose()
        self.worker.set_center_pose(Pose())
        log.info("Center reset")

    def closeEvent(self, event):
        try:
            self._stop_tracking()
            save_settings(self.app_settings)
        except Exception as e:
            log.error(f"Error during shutdown: {e}", exc_info=True)
        event.accept()
