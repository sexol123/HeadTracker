import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger("config")

PROFILES_DIR = Path(__file__).parent / "profiles"
SETTINGS_FILE = Path(__file__).parent / "settings.json"


@dataclass
class AxisConfig:
    enabled: bool = True
    sensitivity: float = 6.0
    deadzone: float = 2.0
    inverted: bool = False

    def __post_init__(self):
        self.sensitivity = max(0.1, min(20.0, self.sensitivity))
        self.deadzone = max(0.0, min(30.0, self.deadzone))


@dataclass
class Profile:
    name: str = "Default"
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    mirror: bool = True
    camera_url: str = ""
    camera_source: str = "local"
    image_enhance: bool = False
    axes: dict[str, AxisConfig] = field(default_factory=dict)
    output_protocol: str = "freetrack"
    udp_host: str = "127.0.0.1"
    udp_port: int = 4242
    hotkeys: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if not self.axes:
            self.axes = self.default_axes()
        if not self.hotkeys:
            self.hotkeys = {"center": "F12", "reset": "F11"}

    @staticmethod
    def default_axes() -> dict[str, AxisConfig]:
        return {
            "yaw": AxisConfig(sensitivity=6.0, deadzone=2.0),
            "pitch": AxisConfig(sensitivity=6.0, deadzone=2.0),
            "roll": AxisConfig(sensitivity=6.0, deadzone=2.0),
            "x": AxisConfig(sensitivity=1.0, deadzone=1.0),
            "y": AxisConfig(sensitivity=1.0, deadzone=1.0),
            "z": AxisConfig(sensitivity=1.0, deadzone=1.0),
        }

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        axes = {}
        for name, axis_data in data.get("axes", {}).items():
            axes[name] = AxisConfig(**axis_data)
        return cls(
            name=data.get("name", "Default"),
            camera_index=data.get("camera_index", 0),
            camera_width=data.get("camera_width", 640),
            camera_height=data.get("camera_height", 480),
            camera_fps=data.get("camera_fps", 30),
            mirror=data.get("mirror", True),
            camera_url=data.get("camera_url", ""),
            camera_source=data.get("camera_source", "local"),
            image_enhance=data.get("image_enhance", False),
            axes=axes,
            output_protocol=data.get("output_protocol", "freetrack"),
            udp_host=data.get("udp_host", "127.0.0.1"),
            udp_port=data.get("udp_port", 4242),
            hotkeys=data.get("hotkeys", {"center": "F12", "reset": "F11"}),
        )


@dataclass
class AppSettings:
    last_profile: str = "Default"
    auto_start: bool = False
    show_overlay: bool = True
    language: str = "en"
    first_run: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        return cls(
            last_profile=data.get("last_profile", "Default"),
            auto_start=data.get("auto_start", False),
            show_overlay=data.get("show_overlay", True),
            language=data.get("language", "en"),
            first_run=data.get("first_run", True),
        )


def load_profile(path: str | Path) -> Profile:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Profile.from_dict(data)
    except FileNotFoundError:
        log.error(f"Profile not found: {path}")
        raise
    except json.JSONDecodeError as e:
        log.error(f"Invalid JSON in profile {path}: {e}")
        raise
    except Exception as e:
        log.error(f"Failed to load profile {path}: {e}", exc_info=True)
        raise


def save_profile(profile: Profile, path: str | Path):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
        log.info(f"Profile saved: {path}")
    except PermissionError:
        log.error(f"Permission denied writing profile: {path}")
        raise
    except OSError as e:
        log.error(f"OS error writing profile {path}: {e}")
        raise
    except Exception as e:
        log.error(f"Failed to save profile {path}: {e}", exc_info=True)
        raise


def ensure_default_profile():
    """Guarantee the default.json profile always exists."""
    PROFILES_DIR.mkdir(exist_ok=True)
    default_path = PROFILES_DIR / "default.json"
    if not default_path.exists():
        save_profile(Profile(name="Default"), default_path)
        log.info("Created default profile")


def list_profiles() -> list[Path]:
    ensure_default_profile()
    all_profiles = sorted(PROFILES_DIR.glob("*.json"))
    # Always put default first
    default = PROFILES_DIR / "default.json"
    others = [p for p in all_profiles if p != default]
    return [default] + others


def load_settings() -> AppSettings:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AppSettings.from_dict(data)
        except json.JSONDecodeError as e:
            log.warning(f"Invalid settings file, using defaults: {e}")
            return AppSettings()
        except Exception as e:
            log.warning(f"Failed to load settings, using defaults: {e}")
            return AppSettings()
    return AppSettings()


def save_settings(settings: AppSettings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings.to_dict(), f, indent=2, ensure_ascii=False)
        log.info(f"Settings saved: {SETTINGS_FILE}")
    except PermissionError:
        log.error(f"Permission denied writing settings: {SETTINGS_FILE}")
    except OSError as e:
        log.error(f"OS error writing settings: {e}")
    except Exception as e:
        log.error(f"Failed to save settings: {e}", exc_info=True)
