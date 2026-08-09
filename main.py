import sys
import os
import logging
from datetime import datetime
from pathlib import Path

# High DPI support — must be set before QApplication
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ui.main_window import MainWindow
from config import load_profile, load_settings, PROFILES_DIR

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)


class UILogHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self._window = None

    def set_window(self, window):
        self._window = window

    def emit(self, record):
        if self._window is None:
            return
        try:
            self._window.append_log(self.format(record))
        except Exception:
            pass


def setup_logging(debug: bool = False):
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    root_logger = logging.getLogger()
    level = logging.DEBUG if debug else logging.WARNING
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
    ui_handler = setup_logging(debug=debug)
    log = logging.getLogger("main")

    log.info("=== HeadTracker starting ===")
    app = QApplication(sys.argv)
    app.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    log.info("QApplication created")

    try:
        settings = load_settings()
        log.info(f"Settings loaded: last_profile={settings.last_profile}")
    except Exception as e:
        log.warning(f"Failed to load settings, using defaults: {e}")
        from config import AppSettings
        settings = AppSettings()

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
        ui_handler.set_window(window)
        window.show()
        log.info("Main window shown — entering event loop")
    except Exception as e:
        log.critical(f"Failed to create main window: {e}", exc_info=True)
        sys.exit(1)

    exit_code = app.exec()
    log.info(f"=== HeadTracker exiting (code={exit_code}) ===")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
