import logging
import time
import math
import cv2
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QSpinBox, QCheckBox,
    QDoubleSpinBox, QGroupBox, QFormLayout, QSplitter,
    QTabWidget, QTextEdit, QLineEdit, QMessageBox,
    QFileDialog, QScrollArea, QSystemTrayIcon, QMenu, QSlider,
)
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtGui import QImage, QPixmap, QFont, QIcon, QFontMetricsF

from worker import TrackingWorker
from camera import Camera
from tracker import Pose
from freetrack import IS_WINDOWS
from i18n import t, set_language, get_language, available_languages
from config import (
    Profile, AxisConfig, AppSettings,
    load_profile, save_profile,
    load_settings, save_settings,
    list_profiles, PROFILES_DIR,
)
from pathlib import Path

log = logging.getLogger("ui")
ICON_PATH = Path(__file__).parent.parent / "HeadTrackerIcon.png"
MOUSE_HOTKEYS = (
    [f"f{i}" for i in range(1, 13)] + ["space", "insert", "delete"]
    + [
        "ctrl+f8", "ctrl+f9", "ctrl+f10",
        "alt+f8", "alt+f9", "alt+f10",
        "ctrl+shift+f8", "ctrl+shift+f9", "ctrl+shift+f10",
        "ctrl+space", "ctrl+insert", "ctrl+delete",
    ]
)


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
        self._pulse_splash()
        self.worker = TrackingWorker()
        self.worker.connecting.connect(self._on_worker_connecting)
        self.worker.started_signal.connect(self._on_worker_started)
        self.worker.frame_ready.connect(self._on_worker_frame)
        self.worker.pose_ready.connect(self._on_worker_pose)
        self.worker.confidence_ready.connect(self._on_worker_confidence)
        self.worker.output_log.connect(self._on_protocol_log)
        self.worker.error_occurred.connect(self._on_worker_error)
        self.worker.stopped.connect(self._on_worker_stopped)
        self.tracking_active = False
        self.current_pose = Pose()
        self.raw_pose = Pose()
        self.frame_count = 0
        self.last_fps_time = 0.0
        self.display_fps = 0.0
        self._last_landmarks = None
        self._current_profile_path: Path | None = None
        self._was_minimized = False

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(2000)
        self._autosave_timer.timeout.connect(self._autosave_settings)
        self._profile_autosave_timer = QTimer(self)
        self._profile_autosave_timer.setSingleShot(True)
        self._profile_autosave_timer.setInterval(2000)
        self._profile_autosave_timer.timeout.connect(self._autosave_profile)

        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))

        self._init_ui()
        self._init_tray_icon()
        self._pulse_splash()
        self._populate_profiles()
        self._pulse_splash()
        self._apply_profile()
        self._pulse_splash()

        if self.app_settings.first_run:
            self.tabs.setCurrentIndex(4)
            self.app_settings.first_run = False

    @staticmethod
    def _pulse_splash():
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

    def _debounce(self, button, delay=800):
        self._btn_locked = True
        button.setEnabled(False)
        QTimer.singleShot(delay, self._debounce_end)

    def _debounce_end(self):
        self._btn_locked = False
        self.btn_start.setEnabled(True)

    def _init_tray_icon(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = QIcon(str(ICON_PATH)) if ICON_PATH.exists() else self.windowIcon()
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("HeadTracker")

        tray_menu = QMenu(self)
        self._tray_action_show = tray_menu.addAction(t("tray_show"))
        self._tray_action_show.triggered.connect(self._toggle_window_visibility)

        self._tray_action_start = tray_menu.addAction(t("btn_start"))
        self._tray_action_start.triggered.connect(self._on_start_stop)

        tray_menu.addSeparator()
        self._tray_action_exit = tray_menu.addAction(t("tray_exit"))
        self._tray_action_exit.triggered.connect(self.close)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_icon_activated)
        self.tray_icon.show()

    def _toggle_window_visibility(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.showNormal()
            self.activateWindow()

    def _on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_window_visibility()

    def _init_ui(self):
        self.setWindowTitle(t("window_title"))
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
        self.preview_label = QLabel(t("camera_preview"))
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(480, 360)
        self.preview_label.setStyleSheet("background-color: #1a1a2e; color: #888;")
        left_layout.addWidget(self.preview_label)

        controls_layout = QHBoxLayout()
        self.btn_start = QPushButton(t("btn_start"))
        self.btn_start.setFixedHeight(36)
        self.btn_start.setStyleSheet("QPushButton { background-color: #2ecc71; color: white; font-weight: bold; } QPushButton:hover { background-color: #27ae60; }")
        self.btn_start.clicked.connect(self._on_start_stop)
        controls_layout.addWidget(self.btn_start)
        left_layout.addLayout(controls_layout)

        self._pose_group = QGroupBox(t("head_pose"))
        self._pose_form = QFormLayout()
        self.lbl_yaw = QLabel("0.00"); self.lbl_yaw.setFont(QFont("Consolas", 14))
        self.lbl_yaw.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_yaw_title = QLabel(t("yaw"))
        self._pose_form.addRow(self._lbl_yaw_title, self.lbl_yaw)
        self.lbl_pitch = QLabel("0.00"); self.lbl_pitch.setFont(QFont("Consolas", 14))
        self.lbl_pitch.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_pitch_title = QLabel(t("pitch"))
        self._pose_form.addRow(self._lbl_pitch_title, self.lbl_pitch)
        self.lbl_roll = QLabel("0.00"); self.lbl_roll.setFont(QFont("Consolas", 14))
        self.lbl_roll.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_roll_title = QLabel(t("roll"))
        self._pose_form.addRow(self._lbl_roll_title, self.lbl_roll)
        self.lbl_x = QLabel("0.00"); self.lbl_x.setFont(QFont("Consolas", 14))
        self.lbl_x.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_x_title = QLabel(t("x_axis"))
        self._pose_form.addRow(self._lbl_x_title, self.lbl_x)
        self.lbl_y = QLabel("0.00"); self.lbl_y.setFont(QFont("Consolas", 14))
        self.lbl_y.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_y_title = QLabel(t("y_axis"))
        self._pose_form.addRow(self._lbl_y_title, self.lbl_y)
        self.lbl_z = QLabel("0.00"); self.lbl_z.setFont(QFont("Consolas", 14))
        self.lbl_z.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl_z_title = QLabel(t("z_axis"))
        self._pose_form.addRow(self._lbl_z_title, self.lbl_z)
        self._pose_group.setLayout(self._pose_form)
        self._fix_pose_group_width()

        self._info_group = QGroupBox(t("info"))
        self._info_form = QFormLayout()
        self.lbl_confidence = QLabel("0.0")
        self._lbl_conf_title = QLabel(t("confidence"))
        self._info_form.addRow(self._lbl_conf_title, self.lbl_confidence)
        self.lbl_fps = QLabel("0")
        self._lbl_fps_title = QLabel(t("fps"))
        self._info_form.addRow(self._lbl_fps_title, self.lbl_fps)
        self.lbl_profile = QLabel(self.profile.name)
        self._lbl_profile_title = QLabel(t("profile_name"))
        self._info_form.addRow(self._lbl_profile_title, self.lbl_profile)
        self.lbl_status = QLabel(t("status_stopped"))
        self._lbl_status_title = QLabel(t("tab_status") + ":")
        self._info_form.addRow(self._lbl_status_title, self.lbl_status)
        self._info_group.setLayout(self._info_form)

        status_layout = QHBoxLayout()
        status_layout.addWidget(self._pose_group)
        status_layout.addWidget(self._info_group)
        left_layout.addLayout(status_layout)

        left_panel.setMinimumWidth(400)
        splitter.addWidget(left_panel)

        # Right: tabs
        right_panel = QWidget()
        right_panel.setMinimumWidth(420)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 4, 4, 4)
        self.tabs = QTabWidget()
        right_layout.addWidget(self.tabs)
        self._build_camera_tab()
        self._build_axes_tab()
        self._build_output_tab()
        self._build_log_tab()
        self._build_about_tab()
        splitter.addWidget(right_panel)
        splitter.setSizes([520, 440])

    def _build_profile_tab(self):
        pass

    def _build_camera_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self._cam_form = form = QFormLayout()
        self.combo_cam_type = QComboBox()
        self.combo_cam_type.addItems([t("local_webcam"), t("ip_camera"), t("websocket")])
        self.combo_cam_type.currentIndexChanged.connect(self._on_cam_type_changed)
        self._lbl_source = QLabel(t("source"))
        form.addRow(self._lbl_source, self.combo_cam_type)
        self.combo_camera = QComboBox()
        cameras = Camera.list_cameras(max_count=5)
        self._pulse_splash()
        for cam in cameras:
            self.combo_camera.addItem(
                t("camera_item").format(cam['index'], cam['width'], cam['height']), cam["index"])
        self._lbl_camera = QLabel(t("camera"))
        form.addRow(self._lbl_camera, self.combo_camera)
        self.edit_url = QLineEdit()
        self.edit_url.setPlaceholderText("rtsp://192.168.1.100:554/stream")
        self._lbl_url = QLabel(t("url"))
        form.addRow(self._lbl_url, self.edit_url)
        self.spin_width = QSpinBox(); self.spin_width.setRange(160, 1920); self.spin_width.setSingleStep(32)
        self._lbl_width = QLabel(t("width"))
        form.addRow(self._lbl_width, self.spin_width)
        self.spin_height = QSpinBox(); self.spin_height.setRange(120, 1080); self.spin_height.setSingleStep(32)
        self._lbl_height = QLabel(t("height"))
        form.addRow(self._lbl_height, self.spin_height)
        self.spin_fps = QSpinBox(); self.spin_fps.setRange(15, 120)
        self._lbl_fps_cam = QLabel(t("fps"))
        form.addRow(self._lbl_fps_cam, self.spin_fps)
        self.combo_rotation = QComboBox()
        self.combo_rotation.addItem("0°", 0)
        self.combo_rotation.addItem("90°", 90)
        self.combo_rotation.addItem("180°", 180)
        self.combo_rotation.addItem("270°", 270)
        self._lbl_rotation = QLabel(t("rotation"))
        form.addRow(self._lbl_rotation, self.combo_rotation)
        self.chk_mirror = QCheckBox(t("mirror"))
        form.addRow(self.chk_mirror)
        self.chk_enhance = QCheckBox(t("enhance"))
        form.addRow(self.chk_enhance)
        self.combo_rotation.currentIndexChanged.connect(self._on_live_setting_changed)
        self.chk_mirror.toggled.connect(self._on_live_setting_changed)
        self.chk_enhance.toggled.connect(self._on_live_setting_changed)
        layout.addLayout(form)

        self._cam_adapt_group = QGroupBox(t("cam_adaptation"))
        adapt_form = QFormLayout()

        def _adapt_spin(min_val, max_val, step, decimals, suffix):
            sp = QDoubleSpinBox()
            sp.setRange(min_val, max_val)
            sp.setSingleStep(step)
            sp.setDecimals(decimals)
            if suffix:
                sp.setSuffix(suffix)
            return sp

        self.spin_cam_offset_x = _adapt_spin(-100, 100, 1.0, 1, " cm")
        self.spin_cam_offset_y = _adapt_spin(-100, 100, 1.0, 1, " cm")
        self.spin_cam_offset_z = _adapt_spin(0, 300, 1.0, 1, " cm")
        self._lbl_cam_offset_x = QLabel(t("cam_offset_x"))
        adapt_form.addRow(self._lbl_cam_offset_x, self.spin_cam_offset_x)
        self._lbl_cam_offset_y = QLabel(t("cam_offset_y"))
        adapt_form.addRow(self._lbl_cam_offset_y, self.spin_cam_offset_y)
        self._lbl_cam_offset_z = QLabel(t("cam_offset_z"))
        adapt_form.addRow(self._lbl_cam_offset_z, self.spin_cam_offset_z)

        self.spin_cam_yaw = _adapt_spin(-90, 90, 1.0, 1, "°")
        self.spin_cam_pitch = _adapt_spin(-90, 90, 1.0, 1, "°")
        self.spin_cam_roll = _adapt_spin(-90, 90, 1.0, 1, "°")
        self._lbl_cam_yaw = QLabel(t("cam_tilt_yaw"))
        adapt_form.addRow(self._lbl_cam_yaw, self.spin_cam_yaw)
        self._lbl_cam_pitch = QLabel(t("cam_tilt_pitch"))
        adapt_form.addRow(self._lbl_cam_pitch, self.spin_cam_pitch)
        self._lbl_cam_roll = QLabel(t("cam_tilt_roll"))
        adapt_form.addRow(self._lbl_cam_roll, self.spin_cam_roll)

        self.spin_cam_fov = _adapt_spin(0, 120, 1.0, 1, "°")
        self.spin_cam_fov.setSpecialValueText("0")
        self._lbl_cam_fov = QLabel(t("cam_fov"))
        adapt_form.addRow(self._lbl_cam_fov, self.spin_cam_fov)

        center_layout = QHBoxLayout()
        self.btn_cam_center = QPushButton(t("btn_set_center"))
        self.btn_cam_center.clicked.connect(self._on_cam_center)
        center_layout.addWidget(self.btn_cam_center)
        self.btn_cam_center_reset = QPushButton(t("btn_reset_center"))
        self.btn_cam_center_reset.clicked.connect(self._on_cam_center_reset)
        center_layout.addWidget(self.btn_cam_center_reset)
        adapt_form.addRow(center_layout)
        self.chk_save_center = QCheckBox(t("save_center_to_profile"))
        self.chk_save_center.setToolTip(t("save_center_to_profile_tip"))
        self.chk_save_center.toggled.connect(self._on_save_center_toggled)
        adapt_form.addRow(self.chk_save_center)

        self.btn_cam_setup = QPushButton(t("cam_setup_btn"))
        self.btn_cam_setup.clicked.connect(self._on_cam_setup)
        adapt_form.addRow(self.btn_cam_setup)

        for sp in (self.spin_cam_offset_x, self.spin_cam_offset_y, self.spin_cam_offset_z,
                   self.spin_cam_yaw, self.spin_cam_pitch, self.spin_cam_roll, self.spin_cam_fov):
            sp.valueChanged.connect(self._on_cam_adapt_changed)
        self._cam_adapt_group.setLayout(adapt_form)
        layout.addWidget(self._cam_adapt_group)

        # IP camera stats (hidden by default)
        self._ip_stats_group = QGroupBox(t("stream_stats"))
        self._stats_form = QFormLayout()
        self.lbl_ip_fps = QLabel("--")
        self.lbl_ip_fps.setFont(QFont("Consolas", 11))
        self._lbl_stat_fps = QLabel(t("fps"))
        self._stats_form.addRow(self._lbl_stat_fps, self.lbl_ip_fps)
        self.lbl_ip_frame_time = QLabel("--")
        self.lbl_ip_frame_time.setFont(QFont("Consolas", 11))
        self._lbl_stat_ft = QLabel(t("frame_time"))
        self._stats_form.addRow(self._lbl_stat_ft, self.lbl_ip_frame_time)
        self.lbl_ip_bandwidth = QLabel("--")
        self.lbl_ip_bandwidth.setFont(QFont("Consolas", 11))
        self._lbl_stat_bw = QLabel(t("bandwidth"))
        self._stats_form.addRow(self._lbl_stat_bw, self.lbl_ip_bandwidth)
        self.lbl_ip_resolution = QLabel("--")
        self.lbl_ip_resolution.setFont(QFont("Consolas", 11))
        self._lbl_stat_res = QLabel(t("resolution"))
        self._stats_form.addRow(self._lbl_stat_res, self.lbl_ip_resolution)
        self.lbl_ip_frames = QLabel("--")
        self.lbl_ip_frames.setFont(QFont("Consolas", 11))
        self._lbl_stat_frames = QLabel(t("frames"))
        self._stats_form.addRow(self._lbl_stat_frames, self.lbl_ip_frames)
        self._ip_stats_group.setLayout(self._stats_form)
        self._ip_stats_group.setVisible(False)
        layout.addWidget(self._ip_stats_group)

        layout.addStretch()
        self.tabs.addTab(tab, t("tab_camera"))

    def _build_axes_tab(self):
        tab = QWidget()
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        inner = QWidget(); layout = QVBoxLayout(inner)

        self._smoothing_group = QGroupBox(t("smoothing"))
        self._smoothing_group.setToolTip(t("smoothing_tip") + "\n" + t("smoothing_deadzone_tip"))
        smoothing_outer = QVBoxLayout(self._smoothing_group)
        smoothing_layout = QHBoxLayout()
        self.slider_smoothing = QSlider(Qt.Horizontal)
        self.slider_smoothing.setRange(0, 100)
        self.slider_smoothing.setValue(50)
        self.slider_smoothing.valueChanged.connect(self._on_smoothing_changed)
        self.slider_smoothing.valueChanged.connect(self._on_live_setting_changed)
        self.lbl_smoothing_val = QLabel("50%")
        self.lbl_smoothing_val.setFixedWidth(40)
        smoothing_layout.addWidget(self.slider_smoothing, 1)
        smoothing_layout.addWidget(self.lbl_smoothing_val)
        smoothing_outer.addLayout(smoothing_layout)
        self.lbl_smoothing_warn = QLabel(t("smoothing_deadzone_warn"))
        self.lbl_smoothing_warn.setStyleSheet("color: #e67e22;")
        self.lbl_smoothing_warn.setWordWrap(True)
        self.lbl_smoothing_warn.setVisible(False)
        smoothing_outer.addWidget(self.lbl_smoothing_warn)
        layout.addWidget(self._smoothing_group)

        profile_layout = QHBoxLayout()
        self.combo_profile = QComboBox()
        self.combo_profile.currentIndexChanged.connect(self._on_profile_changed)
        profile_layout.addWidget(self.combo_profile, 1)
        self.btn_new = QPushButton(t("btn_new"))
        self.btn_new.setFixedWidth(80)
        self.btn_new.clicked.connect(self._on_profile_new)
        profile_layout.addWidget(self.btn_new)
        btn_delete = QPushButton(t("btn_delete"))
        btn_delete.setFixedWidth(80)
        btn_delete.clicked.connect(self._on_profile_delete)
        profile_layout.addWidget(btn_delete)
        self.btn_delete = btn_delete
        layout.addLayout(profile_layout)

        self.btn_axes_setup = QPushButton(t("axes_setup_btn"))
        self.btn_axes_setup.clicked.connect(self._on_axes_setup)
        layout.addWidget(self.btn_axes_setup)

        self._axis_widgets = {}
        self._axis_form_labels = {}
        for axis_name in ["yaw", "pitch", "roll", "x", "y", "z"]:
            group = QGroupBox(axis_name.upper()); form = QFormLayout()
            chk_enabled = QCheckBox(t("enabled"))
            form.addRow(chk_enabled)
            spin_sensitivity = QDoubleSpinBox(); spin_sensitivity.setRange(0.1, 20.0); spin_sensitivity.setSingleStep(0.1)
            lbl_sensitivity = QLabel(t("sensitivity"))
            form.addRow(lbl_sensitivity, spin_sensitivity)
            spin_deadzone = QDoubleSpinBox(); spin_deadzone.setRange(0.0, 30.0); spin_deadzone.setSingleStep(0.5)
            lbl_deadzone = QLabel(t("deadzone"))
            form.addRow(lbl_deadzone, spin_deadzone)
            chk_inverted = QCheckBox(t("inverted"))
            form.addRow(chk_inverted)
            group.setLayout(form); layout.addWidget(group)
            self._axis_widgets[axis_name] = {"enabled": chk_enabled, "sensitivity": spin_sensitivity,
                                               "deadzone": spin_deadzone, "inverted": chk_inverted}
            self._axis_form_labels[axis_name] = {"sensitivity": lbl_sensitivity,
                                                   "deadzone": lbl_deadzone}
            spin_sensitivity.valueChanged.connect(lambda _, n=axis_name: self._on_axis_changed(n))
            spin_deadzone.valueChanged.connect(lambda _, n=axis_name: self._on_axis_changed(n))
            chk_enabled.toggled.connect(lambda _, n=axis_name: self._on_axis_changed(n))
            chk_inverted.toggled.connect(lambda _, n=axis_name: self._on_axis_changed(n))

        layout.addStretch()
        scroll.setWidget(inner)
        tab_layout = QVBoxLayout(tab); tab_layout.addWidget(scroll)
        self.tabs.addTab(tab, t("tab_axes"))

    def _build_output_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        self._output_form = QFormLayout()
        self.combo_protocol = QComboBox()
        if IS_WINDOWS:
            self.combo_protocol.addItem(t("freetrack"), "freetrack")
            self.combo_protocol.addItem(t("udp"), "udp")
        else:
            self.combo_protocol.addItem(t("udp"), "udp")
        self.combo_protocol.addItem(t("mouse"), "mouse")
        self.combo_protocol.currentIndexChanged.connect(self._on_protocol_changed)
        self._lbl_protocol = QLabel(t("protocol"))
        self._output_form.addRow(self._lbl_protocol, self.combo_protocol)
        self.lbl_ft_status = QLabel(t("status_not_running"))
        self._lbl_ft_status_title = QLabel(t("tab_status") + ":")
        self._output_form.addRow(self._lbl_ft_status_title, self.lbl_ft_status)

        # UDP settings
        self._udp_widget = QWidget()
        self._udp_form = QFormLayout(self._udp_widget)
        self._udp_form.setContentsMargins(0, 0, 0, 0)
        self.edit_udp_host = QLineEdit("127.0.0.1")
        self._lbl_host = QLabel(t("host"))
        self._udp_form.addRow(self._lbl_host, self.edit_udp_host)
        self.spin_udp_port = QSpinBox(); self.spin_udp_port.setRange(1, 65535); self.spin_udp_port.setValue(4242)
        self._lbl_port = QLabel(t("port"))
        self._udp_form.addRow(self._lbl_port, self.spin_udp_port)
        layout.addWidget(self._udp_widget)

        # Mouse settings
        self._mouse_widget = QWidget()
        self._mouse_form = QFormLayout(self._mouse_widget)
        self._mouse_form.setContentsMargins(0, 0, 0, 0)
        self.combo_mouse_mode = QComboBox()
        self.combo_mouse_mode.addItem(t("mouse_mode_velocity"), "velocity")
        self.combo_mouse_mode.addItem(t("mouse_mode_absolute"), "absolute")
        self._lbl_mouse_mode = QLabel(t("mouse_mode"))
        self._mouse_form.addRow(self._lbl_mouse_mode, self.combo_mouse_mode)
        self.spin_mouse_speed = QDoubleSpinBox()
        self.spin_mouse_speed.setRange(1.0, 200.0)
        self.spin_mouse_speed.setSingleStep(1.0)
        self.spin_mouse_speed.setValue(25.0)
        self.spin_mouse_speed.setToolTip(t("mouse_speed_tip"))
        self._lbl_mouse_speed = QLabel(t("mouse_speed"))
        self._mouse_form.addRow(self._lbl_mouse_speed, self.spin_mouse_speed)
        self.combo_mouse_stop = QComboBox()
        self.combo_mouse_stop.addItem(t("mouse_stop_hold"), "hold")
        self.combo_mouse_stop.addItem(t("mouse_stop_toggle"), "toggle")
        self._lbl_mouse_stop = QLabel(t("mouse_stop_mode"))
        self._mouse_form.addRow(self._lbl_mouse_stop, self.combo_mouse_stop)
        self.combo_mouse_hotkey = QComboBox()
        for k in MOUSE_HOTKEYS:
            self.combo_mouse_hotkey.addItem(k.upper(), k)
        self.combo_mouse_hotkey.setToolTip(t("mouse_hotkey_hint"))
        self._lbl_mouse_hotkey = QLabel(t("mouse_hotkey"))
        self._mouse_form.addRow(self._lbl_mouse_hotkey, self.combo_mouse_hotkey)
        self.combo_mouse_mode.currentIndexChanged.connect(self._on_live_setting_changed)
        self.spin_mouse_speed.valueChanged.connect(self._on_live_setting_changed)
        self.combo_mouse_stop.currentIndexChanged.connect(self._on_live_setting_changed)
        self.combo_mouse_hotkey.currentIndexChanged.connect(self._on_live_setting_changed)
        layout.addWidget(self._mouse_widget)

        layout.addLayout(self._output_form)
        layout.addStretch(1)

        self._proto_log_title = QLabel(t("protocol_log"))
        layout.addWidget(self._proto_log_title)
        self.protocol_log = QTextEdit()
        self.protocol_log.setReadOnly(True)
        self.protocol_log.setFont(QFont("Consolas", 9))
        self.protocol_log.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.protocol_log)

        self.tabs.addTab(tab, t("tab_output"))

    def _build_log_tab(self):
        tab = QWidget(); layout = QVBoxLayout(tab)
        self.log_text = QTextEdit(); self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        self.log_text.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4;")
        layout.addWidget(self.log_text)
        btn_clear = QPushButton(t("btn_clear_log")); btn_clear.clicked.connect(self.log_text.clear)
        layout.addWidget(btn_clear)
        self.tabs.addTab(tab, t("tab_log"))

    def _build_about_tab(self):
        import sys
        tab = QWidget(); layout = QVBoxLayout(tab)
        layout.setAlignment(Qt.AlignCenter)

        if ICON_PATH.exists():
            logo_label = QLabel()
            pix = QPixmap(str(ICON_PATH)).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pix)
            logo_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(logo_label)
            layout.addSpacing(8)

        self._about_title = QLabel(t("about_title"))
        self._about_title.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self._about_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._about_title)

        self._about_version = QLabel(t("about_version"))
        self._about_version.setFont(QFont("Segoe UI", 12))
        self._about_version.setAlignment(Qt.AlignCenter)
        self._about_version.setStyleSheet("color: #888;")
        layout.addWidget(self._about_version)

        layout.addSpacing(16)

        self._about_desc = QLabel(t("about_desc"))
        self._about_desc.setFont(QFont("Segoe UI", 10))
        self._about_desc.setAlignment(Qt.AlignCenter)
        self._about_desc.setWordWrap(True)
        layout.addWidget(self._about_desc)

        layout.addSpacing(16)

        self._about_info = QLabel(
            f"Python {sys.version.split()[0]}  |  "
            f"PySide6  |  MediaPipe  |  OpenCV\n"
            f"{t('platform')} {sys.platform}"
        )
        self._about_info.setFont(QFont("Consolas", 9))
        self._about_info.setAlignment(Qt.AlignCenter)
        self._about_info.setStyleSheet("color: #aaa;")
        layout.addWidget(self._about_info)

        layout.addSpacing(16)

        lang_layout = QHBoxLayout()
        lang_layout.setAlignment(Qt.AlignCenter)
        self._about_lang_label = QLabel(t("lang"))
        lang_layout.addWidget(self._about_lang_label)
        self.combo_language = QComboBox()
        for code, name in available_languages().items():
            self.combo_language.addItem(name, code)
        # Select current language
        current = get_language()
        for i in range(self.combo_language.count()):
            if self.combo_language.itemData(i) == current:
                self.combo_language.setCurrentIndex(i)
                break
        self.combo_language.currentIndexChanged.connect(self._on_language_changed)
        lang_layout.addWidget(self.combo_language)
        layout.addLayout(lang_layout)

        layout.addSpacing(16)

        self._about_links = QLabel(
            '<a href="https://github.com">' + t("about_github") + '</a>'
        )
        self._about_links.setFont(QFont("Segoe UI", 10))
        self._about_links.setAlignment(Qt.AlignCenter)
        self._about_links.setOpenExternalLinks(True)
        layout.addWidget(self._about_links)

        layout.addStretch()
        self.tabs.addTab(tab, t("tab_about"))

    def _on_language_changed(self, index):
        lang = self.combo_language.currentData()
        if lang:
            set_language(lang)
            self.app_settings.language = lang
            self._refresh_ui_text()

    @staticmethod
    def _retranslate_combo(combo, items):
        data = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for text, key in items:
            combo.addItem(text, key)
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx != -1 else 0)
        combo.blockSignals(False)

    def _refresh_ui_text(self):
        self.setWindowTitle(t("window_title"))
        self.preview_label.setText(t("camera_preview"))
        self.btn_start.setText(t("btn_stop") if self.tracking_active else t("btn_start"))
        self.btn_new.setText(t("btn_new"))
        self.btn_delete.setText(t("btn_delete"))
        self.tabs.setTabText(0, t("tab_camera"))
        self.tabs.setTabText(1, t("tab_axes"))
        self.tabs.setTabText(2, t("tab_output"))
        self.tabs.setTabText(3, t("tab_log"))
        self.tabs.setTabText(4, t("tab_about"))
        self.lbl_status.setText(t("status_running") if self.tracking_active else t("status_stopped"))
        self.lbl_ft_status.setText(t("status_running") if self.tracking_active else t("status_not_running"))
        # Tray actions
        if hasattr(self, "_tray_action_show"):
            self._tray_action_show.setText(t("tray_show"))
            self._tray_action_start.setText(t("btn_stop") if self.tracking_active else t("btn_start"))
            self._tray_action_exit.setText(t("tray_exit"))
        # Status tab
        self._pose_group.setTitle(t("head_pose"))
        self._lbl_yaw_title.setText(t("yaw"))
        self._lbl_pitch_title.setText(t("pitch"))
        self._lbl_roll_title.setText(t("roll"))
        self._lbl_x_title.setText(t("x_axis"))
        self._lbl_y_title.setText(t("y_axis"))
        self._lbl_z_title.setText(t("z_axis"))
        self._fix_pose_group_width()
        self._info_group.setTitle(t("info"))
        self._lbl_conf_title.setText(t("confidence"))
        self._lbl_fps_title.setText(t("fps"))
        self._lbl_profile_title.setText(t("profile_name"))
        self._lbl_status_title.setText(t("tab_status") + ":")
        # Axes tab
        self._smoothing_group.setTitle(t("smoothing"))
        self._smoothing_group.setToolTip(t("smoothing_tip") + "\n" + t("smoothing_deadzone_tip"))
        self.lbl_smoothing_warn.setText(t("smoothing_deadzone_warn"))
        # Camera tab
        self._lbl_source.setText(t("source"))
        self._lbl_camera.setText(t("camera"))
        self._lbl_url.setText(t("url"))
        self._lbl_width.setText(t("width"))
        self._lbl_height.setText(t("height"))
        self._lbl_fps_cam.setText(t("fps"))
        self._cam_adapt_group.setTitle(t("cam_adaptation"))
        self._lbl_cam_offset_x.setText(t("cam_offset_x"))
        self._lbl_cam_offset_y.setText(t("cam_offset_y"))
        self._lbl_cam_offset_z.setText(t("cam_offset_z"))
        self._lbl_cam_yaw.setText(t("cam_tilt_yaw"))
        self._lbl_cam_pitch.setText(t("cam_tilt_pitch"))
        self._lbl_cam_roll.setText(t("cam_tilt_roll"))
        self._lbl_cam_fov.setText(t("cam_fov"))
        self.btn_cam_center.setText(t("btn_set_center"))
        self.btn_cam_center_reset.setText(t("btn_reset_center"))
        self.btn_cam_setup.setText(t("cam_setup_btn"))
        self._ip_stats_group.setTitle(t("stream_stats"))
        self._lbl_stat_fps.setText(t("fps"))
        self._lbl_stat_ft.setText(t("frame_time"))
        self._lbl_stat_bw.setText(t("bandwidth"))
        self._lbl_stat_res.setText(t("resolution"))
        self._lbl_stat_frames.setText(t("frames"))
        # Axes tab
        for axis_name in ["yaw", "pitch", "roll", "x", "y", "z"]:
            labels = self._axis_form_labels[axis_name]
            labels["sensitivity"].setText(t("sensitivity"))
            labels["deadzone"].setText(t("deadzone"))
        # Output tab
        self._lbl_protocol.setText(t("protocol"))
        self._lbl_ft_status_title.setText(t("tab_status") + ":")
        self._lbl_host.setText(t("host"))
        self._lbl_port.setText(t("port"))
        self._proto_log_title.setText(t("protocol_log"))
        self._lbl_mouse_mode.setText(t("mouse_mode"))
        self._lbl_mouse_speed.setText(t("mouse_speed"))
        self.spin_mouse_speed.setToolTip(t("mouse_speed_tip"))
        self._lbl_mouse_stop.setText(t("mouse_stop_mode"))
        self._lbl_mouse_hotkey.setText(t("mouse_hotkey"))
        self._retranslate_combo(
            self.combo_mouse_stop,
            [(t("mouse_stop_hold"), "hold"), (t("mouse_stop_toggle"), "toggle")],
        )
        # About tab
        self._about_title.setText(t("about_title"))
        self._about_version.setText(t("about_version"))
        self._about_desc.setText(t("about_desc"))
        self._about_lang_label.setText(t("lang"))
        self._about_links.setText('<a href="https://github.com">' + t("about_github") + '</a>')

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
            for name, widgets in self._axis_widgets.items():
                if name in self.profile.axes:
                    ax = self.profile.axes[name]
                    widgets["enabled"].setChecked(ax.enabled)
                    widgets["sensitivity"].setValue(ax.sensitivity)
                    widgets["deadzone"].setValue(ax.deadzone)
                    widgets["inverted"].setChecked(ax.inverted)
            self.lbl_profile.setText(self.profile.name)
            self._update_smoothing_warning()
            log.info(f"Profile loaded: {self.profile.name}")
            if self.tracking_active:
                self.worker.update_profile(self.profile)
        except Exception as e:
            log.error(f"Failed to load profile: {e}", exc_info=True)
            QMessageBox.warning(self, t("status_error"), t("failed_load_profile").format(e))
        self._update_buttons_for_default()

    def _update_buttons_for_default(self):
        is_default = self.profile.name == "Default"
        self.btn_delete.setEnabled(not is_default)

    def _apply_profile(self):
        s = self.app_settings
        self.chk_mirror.setChecked(s.mirror)
        self.chk_enhance.setChecked(s.image_enhance)
        self.spin_width.setValue(s.camera_width)
        self.spin_height.setValue(s.camera_height)
        self.spin_fps.setValue(s.camera_fps)
        self.edit_url.setText(s.camera_url)
        self.spin_cam_offset_x.setValue(s.cam_offset_x)
        self.spin_cam_offset_y.setValue(s.cam_offset_y)
        self.spin_cam_offset_z.setValue(s.cam_offset_z)
        self.spin_cam_yaw.setValue(s.cam_rotation_yaw)
        self.spin_cam_pitch.setValue(s.cam_rotation_pitch)
        self.spin_cam_roll.setValue(s.cam_rotation_roll)
        self.spin_cam_fov.setValue(s.camera_fov)

        rot_idx = self.combo_rotation.findData(s.camera_rotation)
        if rot_idx != -1:
            self.combo_rotation.setCurrentIndex(rot_idx)

        if s.camera_source == "websocket":
            self.combo_cam_type.setCurrentIndex(2)
        elif s.camera_url:
            self.combo_cam_type.setCurrentIndex(1)
        else:
            self.combo_cam_type.setCurrentIndex(0)
        self._on_cam_type_changed(self.combo_cam_type.currentIndex())

        for i in range(self.combo_camera.count()):
            if self.combo_camera.itemData(i) == s.camera_index:
                self.combo_camera.setCurrentIndex(i); break

        p = self.profile
        for name, widgets in self._axis_widgets.items():
            if name in p.axes:
                ax = p.axes[name]
                widgets["enabled"].setChecked(ax.enabled)
                widgets["sensitivity"].setValue(ax.sensitivity)
                widgets["deadzone"].setValue(ax.deadzone)
                widgets["inverted"].setChecked(ax.inverted)
        self.lbl_profile.setText(p.name)

        idx = self.combo_protocol.findData(s.output_protocol)
        self.combo_protocol.setCurrentIndex(idx if idx != -1 else 0)
        self._on_protocol_changed(self.combo_protocol.currentIndex())
        mode_idx = self.combo_mouse_mode.findData(s.mouse_mode)
        self.combo_mouse_mode.setCurrentIndex(mode_idx if mode_idx != -1 else 0)
        self.spin_mouse_speed.setValue(s.mouse_speed)
        stop_idx = self.combo_mouse_stop.findData(s.mouse_stop_mode)
        self.combo_mouse_stop.setCurrentIndex(stop_idx if stop_idx != -1 else 0)
        hk_idx = self.combo_mouse_hotkey.findData(s.mouse_hotkey)
        self.combo_mouse_hotkey.setCurrentIndex(hk_idx if hk_idx != -1 else 0)
        self.slider_smoothing.setValue(int(s.pose_smoothing * 100))
        self.edit_udp_host.setText(s.udp_host)
        self.spin_udp_port.setValue(s.udp_port)
        self._update_smoothing_warning()

    def _on_cam_type_changed(self, index):
        is_ip = index == 1
        is_ws = index == 2
        self.combo_camera.setVisible(not is_ip and not is_ws)
        self._lbl_camera.setVisible(not is_ip and not is_ws)
        self.edit_url.setVisible(is_ip or is_ws)
        self._lbl_url.setVisible(is_ip or is_ws)
        self._ip_stats_group.setVisible(is_ip or is_ws)
        self.preview_label.setVisible(True)
        if is_ws:
            self.edit_url.setPlaceholderText("ws://192.168.1.100:8080/ws")
            self._lbl_url.setText(t("ws_url"))
        elif is_ip:
            self.edit_url.setPlaceholderText("http://192.168.1.100:4444/video  or  rtsp://192.168.1.100:554/stream")
            self._lbl_url.setText(t("url"))

    def _fix_pose_group_width(self):
        fm = QFontMetricsF(QFont("Consolas", 14))
        w_val = max(
            fm.horizontalAdvance("-180.00"),
            fm.horizontalAdvance("-9999.9"),
        )
        for lbl in (self.lbl_yaw, self.lbl_pitch, self.lbl_roll, self.lbl_x, self.lbl_y, self.lbl_z):
            lbl.setFixedWidth(int(math.ceil(w_val)))
        self._pose_group.setFixedWidth(int(math.ceil(self._pose_group.sizeHint().width())))

    def _on_smoothing_changed(self, value):
        self.lbl_smoothing_val.setText(f"{value}%")
        self._update_smoothing_warning()

    def _update_smoothing_warning(self):
        warn = self.slider_smoothing.value() > 60 and any(
            ax.enabled and ax.deadzone > 0.0 for ax in self.profile.axes.values()
        )
        self.lbl_smoothing_warn.setVisible(warn)

    def _on_live_setting_changed(self, *_):
        if not self.tracking_active:
            return
        self._read_settings_from_ui()
        self.worker.update_live_settings(self.app_settings)
        self._autosave_timer.start()

    def _autosave_settings(self):
        try:
            self._read_settings_from_ui()
            save_settings(self.app_settings)
        except Exception as e:
            log.warning(f"Autosave settings failed: {e}")

    def _autosave_profile(self):
        if not self._current_profile_path:
            return
        try:
            save_profile(self.profile, self._current_profile_path)
        except Exception as e:
            log.warning(f"Autosave profile failed: {e}")

    def _on_protocol_changed(self, index):
        proto = self.combo_protocol.currentData()
        self._udp_widget.setVisible(proto == "udp")
        self._mouse_widget.setVisible(proto == "mouse")

    def _read_profile_from_ui(self) -> Profile:
        p = Profile(name=self.profile.name)
        for name, widgets in self._axis_widgets.items():
            p.axes[name] = AxisConfig(
                enabled=widgets["enabled"].isChecked(),
                sensitivity=widgets["sensitivity"].value(),
                deadzone=widgets["deadzone"].value(),
                inverted=widgets["inverted"].isChecked(),
            )
        return p

    def _read_settings_from_ui(self):
        s = self.app_settings
        cam_type = self.combo_cam_type.currentIndex()
        s.camera_source = ["local", "ip", "websocket"][cam_type]
        s.camera_url = self.edit_url.text().strip() if cam_type in (1, 2) else ""
        s.camera_index = self.combo_camera.currentData() or 0
        s.camera_width = self.spin_width.value()
        s.camera_height = self.spin_height.value()
        s.camera_fps = self.spin_fps.value()
        s.camera_rotation = self.combo_rotation.currentData() or 0
        s.mirror = self.chk_mirror.isChecked()
        s.image_enhance = self.chk_enhance.isChecked()
        s.cam_offset_x = self.spin_cam_offset_x.value()
        s.cam_offset_y = self.spin_cam_offset_y.value()
        s.cam_offset_z = self.spin_cam_offset_z.value()
        s.cam_rotation_yaw = self.spin_cam_yaw.value()
        s.cam_rotation_pitch = self.spin_cam_pitch.value()
        s.cam_rotation_roll = self.spin_cam_roll.value()
        s.camera_fov = self.spin_cam_fov.value()
        s.output_protocol = self.combo_protocol.currentData() or "udp"
        s.mouse_mode = self.combo_mouse_mode.currentData() or "velocity"
        s.mouse_speed = self.spin_mouse_speed.value()
        s.mouse_stop_mode = self.combo_mouse_stop.currentData() or "hold"
        s.mouse_hotkey = self.combo_mouse_hotkey.currentData() or "f8"
        s.pose_smoothing = self.slider_smoothing.value() / 100.0
        s.udp_host = self.edit_udp_host.text().strip() or "127.0.0.1"
        s.udp_port = self.spin_udp_port.value()

    def _on_cam_adapt_changed(self, *_):
        self._read_settings_from_ui()
        self.worker.update_calibration(self.app_settings)
        self._autosave_timer.start()

    def _on_axis_changed(self, axis_name, *_):
        w = self._axis_widgets.get(axis_name)
        if w is None:
            return
        ax = self.profile.axes.get(axis_name)
        if ax is None:
            return
        ax.enabled = w["enabled"].isChecked()
        ax.sensitivity = w["sensitivity"].value()
        ax.deadzone = w["deadzone"].value()
        ax.inverted = w["inverted"].isChecked()
        self._update_smoothing_warning()
        if self.tracking_active:
            self.worker.update_profile(self.profile)
        self._profile_autosave_timer.start()

    def _on_axes_setup(self):
        from ui.axes_helper_dialog import AxesHelperDialog
        dlg = AxesHelperDialog(self.profile, self.worker, parent=self)

        def apply_axis(name, sens, dz):
            w = self._axis_widgets.get(name)
            if w is None:
                return
            w["sensitivity"].setValue(round(sens, 1))
            w["deadzone"].setValue(round(dz, 1))

        dlg.on_axis_applied = apply_axis
        dlg.exec()

    def _on_cam_center(self):
        if not self.tracking_active:
            log.info("Set center skipped: tracking not running")
            self.lbl_status.setText(t("cam_center_need_tracking"))
            return
        if self.worker.recenter_camera():
            if self.chk_save_center.isChecked():
                pose = self.worker.get_raw_pose()
                self.profile.center_pose = {
                    "yaw": pose.yaw, "pitch": pose.pitch, "roll": pose.roll,
                    "x": pose.x, "y": pose.y, "z": pose.z,
                }
                self._profile_autosave_timer.start()
                log.info(f"Center saved to profile: {self.profile.name}")
            self.lbl_status.setText(t("cam_center_ok"))
            log.info(t("cam_center_ok"))
        else:
            log.warning("Set center failed: face not tracked")
            self.lbl_status.setText(t("cam_center_need_tracking"))

    def _on_cam_center_reset(self):
        self.worker.reset_camera_center()
        if self.chk_save_center.isChecked() and self.profile.center_pose is not None:
            self.profile.center_pose = None
            self._profile_autosave_timer.start()
            log.info(f"Center cleared from profile: {self.profile.name}")
        self.lbl_status.setText(t("cam_center_reset_ok"))
        log.info("Camera center cleared")

    def _on_save_center_toggled(self, checked):
        if checked and not self.tracking_active:
            log.info("Save center to profile: will apply to next Start")
            return
        if not checked and self.profile.center_pose is not None:
            self.profile.center_pose = None
            self._profile_autosave_timer.start()
            log.info("Center removed from profile")

    def _on_cam_setup(self):
        from ui.cam_setup_dialog import CamSetupDialog
        s = self.app_settings
        dlg = CamSetupDialog(
            offset_x_cm=s.cam_offset_x, offset_y_cm=s.cam_offset_y, offset_z_cm=s.cam_offset_z,
            yaw=s.cam_rotation_yaw, pitch=s.cam_rotation_pitch, roll=s.cam_rotation_roll,
            parent=self,
        )

        def apply_vals(ox, oy, oz, yaw, pitch, roll):
            self.spin_cam_offset_x.setValue(round(ox, 1))
            self.spin_cam_offset_y.setValue(round(oy, 1))
            self.spin_cam_offset_z.setValue(round(oz, 1))
            self.spin_cam_yaw.setValue(round(yaw, 1))
            self.spin_cam_pitch.setValue(round(pitch, 1))
            self.spin_cam_roll.setValue(round(roll, 1))

        dlg.apply_callback = apply_vals
        dlg.exec()

    def _on_profile_new(self):
        self.btn_new.setEnabled(False)
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, t("new_profile"), t("profile_name_prompt"),
                                         text=f"{self.profile.name} {t('copy_suffix')}")
        if ok and name:
            new_profile = self._read_profile_from_ui()
            new_profile.name = name
            path = PROFILES_DIR / f"{name.lower().replace(' ', '_')}.json"
            try:
                save_profile(new_profile, path)
                self._populate_profiles()
                for i in range(self.combo_profile.count()):
                    if self.combo_profile.itemData(i) == str(path):
                        self.combo_profile.setCurrentIndex(i); break
                log.info(f"New profile created (duplicate): {name}")
            except Exception as e:
                log.error(f"Failed to create profile: {e}", exc_info=True)
                QMessageBox.warning(self, t("status_error"), t("failed_create_profile").format(e))
        self.btn_new.setEnabled(True)

    def _on_profile_delete(self):
        self.btn_delete.setEnabled(False)
        if not self._current_profile_path:
            self.btn_delete.setEnabled(True)
            return
        if self.profile.name == "Default":
            QMessageBox.information(self, t("cannot_delete"), t("cannot_delete_msg"))
            self.btn_delete.setEnabled(True)
            return
        reply = QMessageBox.question(
            self, t("delete_profile"),
            t("delete_confirm").format(self.profile.name),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._current_profile_path.unlink(missing_ok=True)
            log.info(f"Profile deleted: {self.profile.name}")
            self._populate_profiles()
            if self.combo_profile.count() > 0:
                self.combo_profile.setCurrentIndex(0)
            self.profile = load_profile(self.combo_profile.currentData())
        self._update_buttons_for_default()
        self.btn_delete.setEnabled(True)

    # ── Tracking ─────────────────────────────────────────────────
    @Slot()
    def _on_worker_connecting(self):
        self.lbl_status.setText(t("status_connecting"))
        self.lbl_ft_status.setText(t("status_connecting"))

    @Slot()
    def _on_worker_started(self):
        self.lbl_status.setText(t("status_running"))
        self.lbl_ft_status.setText(t("status_running"))

    @Slot(object)
    def _on_worker_frame(self, frame):
        try:
            self._last_landmarks = getattr(frame, "landmarks", None)
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
    def _on_protocol_log(self, msg):
        self.protocol_log.append(msg)
        if self.protocol_log.document().blockCount() > 300:
            cursor = self.protocol_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.movePosition(cursor.MoveOperation.Down, cursor.MoveMode.KeepAnchor, 100)
            cursor.removeSelectedText()

    @Slot(str)
    def _on_worker_error(self, msg):
        log.error(f"Worker error: {msg}")
        self._stop_tracking()
        self.lbl_status.setText(t("status_error"))
        QMessageBox.warning(self, t("status_error"), msg)

    @Slot()
    def _on_worker_stopped(self):
        self.tracking_active = False
        self.btn_start.setText(t("btn_start"))
        self.btn_start.setStyleSheet("QPushButton { background-color: #2ecc71; color: white; font-weight: bold; } QPushButton:hover { background-color: #27ae60; }")
        self.lbl_status.setText(t("status_stopped"))
        self.lbl_ft_status.setText(t("status_not_running"))
        self.lbl_yaw.setText("0.00")
        self.lbl_pitch.setText("0.00")
        self.lbl_roll.setText("0.00")
        self.lbl_x.setText("0.00")
        self.lbl_y.setText("0.00")
        self.lbl_z.setText("0.00")
        self.lbl_confidence.setText("0.00")
        self.lbl_fps.setText("0")
        self.preview_label.clear()
        self.preview_label.setText(t("camera_preview"))
        self.preview_label.setVisible(True)
        self._set_controls_enabled(True)
        try:
            self._read_settings_from_ui()
            save_settings(self.app_settings)
        except Exception as e:
            log.warning(f"Failed to save settings on stop: {e}")
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
        if getattr(self, '_btn_locked', False):
            return
        self._debounce(self.btn_start)
        if self.tracking_active: self._stop_tracking()
        else: self._start_tracking()

    def _start_tracking(self):
        self.profile = self._read_profile_from_ui()
        self._read_settings_from_ui()
        log.info(f"Starting tracking asynchronously: {self.profile.name}")
        self.tracking_active = True
        self.btn_start.setText(t("btn_stop"))
        self.btn_start.setStyleSheet("QPushButton { background-color: #e74c3c; color: white; font-weight: bold; } QPushButton:hover { background-color: #c0392b; }")
        self.lbl_status.setText(t("status_connecting"))
        self.lbl_ft_status.setText(t("status_connecting"))
        self._set_controls_enabled(False)
        self.worker.start_tracking(self.profile, self.app_settings)

    def _stop_tracking(self):
        log.info("Stopping tracking...")
        self.tracking_active = False
        self.worker.stop_tracking()
        self.btn_start.setText(t("btn_start"))
        self.btn_start.setStyleSheet("QPushButton { background-color: #2ecc71; color: white; font-weight: bold; } QPushButton:hover { background-color: #27ae60; }")
        self.lbl_status.setText(t("status_stopped"))
        self.lbl_ft_status.setText(t("status_not_running"))
        self.preview_label.clear()
        self.preview_label.setText(t("camera_preview"))
        self.preview_label.setVisible(True)
        self._set_controls_enabled(True)
        try:
            self._read_settings_from_ui()
            save_settings(self.app_settings)
            log.info("Settings saved on tracking stop")
        except Exception as e:
            log.warning(f"Failed to save settings on stop: {e}")
        log.info("Tracking stopped")

    def _set_controls_enabled(self, enabled: bool):
        self.btn_new.setEnabled(enabled)
        self.btn_delete.setEnabled(enabled)
        self.combo_cam_type.setEnabled(enabled)
        self.combo_camera.setEnabled(enabled)
        self.edit_url.setEnabled(enabled)
        self.spin_width.setEnabled(enabled)
        self.spin_height.setEnabled(enabled)
        self.spin_fps.setEnabled(enabled)
        self.combo_protocol.setEnabled(enabled)
        self.edit_udp_host.setEnabled(enabled)
        self.spin_udp_port.setEnabled(enabled)
        if enabled:
            self._update_buttons_for_default()

    @Slot()
    def closeEvent(self, event):
        if self.tracking_active:
            reply = QMessageBox.question(
                self, t("warning"),
                t("confirm_exit"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No:
                event.ignore()
                return
        try:
            self._stop_tracking()
            save_settings(self.app_settings)
        except Exception as e:
            log.error(f"Error during shutdown: {e}", exc_info=True)
        event.accept()
