import sys
import os
import logging
from collections import deque
from datetime import datetime
from pathlib import Path

# High DPI support — must be set before QApplication
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

# Windows explicit AppUserModelID so taskbar uses custom app icon
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HeadTracker.RaceSim.1.0")
    except Exception:
        pass

from PySide6.QtCore import Qt, QObject, Signal
from PySide6.QtWidgets import QApplication, QSplashScreen
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon

from ui.main_window import MainWindow
from config import load_profile, load_settings, PROFILES_DIR
from i18n import set_language, t

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)
ICON_PATH = Path(__file__).parent / "HeadTrackerIcon.png"


class LogBridge(QObject):
    """Marshals log records from any thread to the GUI thread via a queued signal."""

    message = Signal(str)


class UILogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self._emitter = None
        self._buffer: deque[str] = deque(maxlen=200)

    def set_emitter(self, emitter):
        self._emitter = emitter

    def flush_buffer(self):
        while self._buffer:
            if self._emitter is None:
                break
            try:
                self._emitter(self._buffer.popleft())
            except Exception:
                pass

    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            return
        if self._emitter is None:
            self._buffer.append(msg)
            return
        try:
            self._emitter(msg)
        except Exception:
            pass


def setup_logging(debug: bool = False):
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    root_logger = logging.getLogger()
    # INFO in normal mode so the Log tab shows regular activity, DEBUG with -debug
    level = logging.DEBUG if debug else logging.INFO
    root_logger.setLevel(level)

    if debug:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_file = LOGS_DIR / f"headtracker_{timestamp}.log"

        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root_logger.addHandler(file_handler)

        console = logging.StreamHandler()
        console.setLevel(logging.DEBUG)
        console.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
        root_logger.addHandler(console)

    ui_handler = UILogHandler()
    ui_handler.setLevel(logging.INFO)
    ui_handler.setFormatter(fmt)
    root_logger.addHandler(ui_handler)

    if debug:
        log = logging.getLogger("main")
        log.info(f"Log file: {log_file}")
        log.info(f"Python {sys.version}")
        log.info(f"Platform: {sys.platform}")
        log.info(f"CWD: {os.getcwd()}")

    return ui_handler


def main():
    debug = "-debug" in sys.argv or "-logging" in sys.argv
    import crashlog
    crashlog.install_crash_handlers(enable_faulthandler=True)
    ui_handler = setup_logging(debug=debug)
    log_bridge = LogBridge()
    log = logging.getLogger("main")

    log.info("=== HeadTracker starting ===")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    log.info("QApplication created")

    if ICON_PATH.exists():
        app_icon = QIcon(str(ICON_PATH))
        app.setWindowIcon(app_icon)
        log.info(f"App icon loaded from {ICON_PATH.name}")

    # Splash screen
    def _draw_splash(dots):
        pix = QPixmap(420, 280)
        pix.fill(QColor("#1a1a2e"))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        if ICON_PATH.exists():
            icon_pix = QPixmap(str(ICON_PATH)).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((420 - icon_pix.width()) // 2, 20, icon_pix)
            title_y = 120
            status_y = 175
        else:
            title_y = 60
            status_y = 130

        p.setPen(QColor("#00d4ff"))
        p.setFont(QFont("Segoe UI", 22, QFont.Bold))
        p.drawText(pix.rect().adjusted(0, title_y, 0, -60), Qt.AlignCenter, "HeadTracker")
        p.setPen(QColor("#888888"))
        p.setFont(QFont("Segoe UI", 11))
        p.drawText(pix.rect().adjusted(0, status_y, 0, 0), Qt.AlignHCenter | Qt.AlignTop, t("splash_loading") + dots)
        p.end()
        return pix

    splash = QSplashScreen(_draw_splash("."))
    splash.show()
    app.processEvents()

    _dot_count = 0
    def _update_splash():
        nonlocal _dot_count
        _dot_count = (_dot_count + 1) % 6
        splash.setPixmap(_draw_splash("." * (_dot_count or 1)))

    from PySide6.QtCore import QTimer
    _splash_timer = QTimer()
    _splash_timer.timeout.connect(_update_splash)
    _splash_timer.start(400)

    try:
        settings = load_settings()
        log.info(f"Settings loaded: last_profile={settings.last_profile}")
    except Exception as e:
        log.warning(f"Failed to load settings, using defaults: {e}")
        from config import AppSettings
        settings = AppSettings()

    # Apply language setting
    set_language(settings.language)

    # Load last used profile
    try:
        profile_path = PROFILES_DIR / f"{settings.last_profile.lower().replace(' ', '_')}.json"
        if profile_path.exists():
            profile = load_profile(profile_path)
        else:
            default_path = PROFILES_DIR / "default.json"
            profile = load_profile(default_path) if default_path.exists() else None
            if profile is None:
                from config import Profile
                profile = Profile()
    except Exception as e:
        log.warning(f"Failed to load profile '{settings.last_profile}', using Default: {e}")
        from config import Profile
        profile = Profile()

    log.info(f"Profile loaded: {profile.name}")

    try:
        window = MainWindow(profile)
        log_bridge.message.connect(window.append_log)
        ui_handler.set_emitter(log_bridge.message.emit)
        ui_handler.flush_buffer()
        window.show()
        _splash_timer.stop()
        splash.finish(window)
        log.info("Main window shown — entering event loop")
    except Exception as e:
        log.critical(f"Failed to create main window: {e}", exc_info=True)
        sys.exit(1)

    exit_code = app.exec()
    log.info(f"=== HeadTracker exiting (code={exit_code}) ===")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
