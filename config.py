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


@dataclass
class Profile:
    name: str = "Default"
    axes: dict[str, AxisConfig] = field(default_factory=dict)

    def __post_init__(self):
        if not self.axes:
            self.axes = self.default_axes()

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
            axes=axes,
        )


@dataclass
class AppSettings:
    last_profile: str = "Default"
    language: str = "en"
    first_run: bool = True
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    mirror: bool = True
    camera_url: str = ""
    camera_source: str = "local"
    camera_rotation: int = 0
    image_enhance: bool = False
    cam_offset_x: float = 0.0
    cam_offset_y: float = 0.0
    cam_offset_z: float = 0.0
    cam_rotation_yaw: float = 0.0
    cam_rotation_pitch: float = 0.0
    cam_rotation_roll: float = 0.0
    camera_fov: float = 0.0
    output_protocol: str = "freetrack"
    udp_host: str = "127.0.0.1"
    udp_port: int = 4242
    mouse_mode: str = "velocity"
    mouse_speed: float = 25.0
    mouse_stop_mode: str = "hold"
    mouse_hotkey: str = "f8"
    pose_smoothing: float = 0.5

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


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
        raise
    except OSError as e:
        log.error(f"OS error writing settings {SETTINGS_FILE}: {e}")
        raise
    except Exception as e:
        log.error(f"Failed to save settings: {e}")
