import json
import logging
import math
import os
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path

log = logging.getLogger("config")

PROFILES_DIR = Path(__file__).parent / "profiles"
SETTINGS_FILE = Path(__file__).parent / "settings.json"

MIN_SENSITIVITY = 0.1
MAX_SENSITIVITY = 20.0
MIN_DEADZONE = 0.0
MAX_DEADZONE = 30.0
MIN_CAMERA_FOV = 0.0
MAX_CAMERA_FOV = 120.0
_HOST_LABEL_RE = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)$")


def _finite_float(value, default: float, minimum: float, maximum: float) -> float:
    """Return a finite JSON number in the inclusive allowed range."""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number) or not minimum <= number <= maximum:
        return default
    return number


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if minimum <= number <= maximum else default


def _json_bool(value, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _bounded_text(value, default: str, maximum: int = 255) -> str:
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value if value and len(value) <= maximum else default


def _valid_host(value: object) -> bool:
    if not isinstance(value, str) or not value or len(value) > 253:
        return False
    return all(_HOST_LABEL_RE.fullmatch(label) for label in value.split("."))


def _valid_camera_url(value: object) -> bool:
    """Accept a URL understood by Camera.start(), including host:port shorthand."""
    if not isinstance(value, str):
        return False
    value = value.strip()
    if not value:
        return True
    if len(value) > 2048 or any(char.isspace() for char in value):
        return False
    schemes = ("http://", "https://", "rtsp://", "udp://", "ws://", "wss://")
    if value.startswith(schemes):
        return bool(value.split("://", 1)[1].split("/", 1)[0])
    host = value.split("/", 1)[0].split(":", 1)[0]
    return _valid_host(host)


def _center_pose(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    limits = {"yaw": 180.0, "pitch": 90.0, "roll": 180.0, "x": 2000.0, "y": 2000.0, "z": 4000.0}
    result = {}
    for name, maximum in limits.items():
        number = _finite_float(value.get(name), math.nan, -maximum, maximum)
        if not math.isfinite(number):
            return None
        result[name] = number
    return result


@dataclass
class AxisConfig:
    """Per-axis mapping: sensitivity is a unitless multiplier; deadzone and
    curve input/output use degrees for rotation axes and millimetres for X/Y/Z."""
    enabled: bool = True
    sensitivity: float = 6.0
    deadzone: float = 2.0
    inverted: bool = False
    curve: list[float] | None = None

    @classmethod
    def from_dict(cls, data: object, defaults: "AxisConfig") -> "AxisConfig":
        """Normalize one axis config loaded from a profile JSON file."""
        if not isinstance(data, dict):
            return defaults

        curve = data.get("curve")
        if curve is not None:
            if not isinstance(curve, list) or len(curve) != 2:
                curve = None
            else:
                x2 = _finite_float(curve[0], 0.0, 0.001, 60.0)
                y2 = _finite_float(curve[1], -1.0, 0.0, 1200.0)
                curve = [x2, y2] if x2 > 0.0 and y2 >= 0.0 else None

        return cls(
            enabled=_json_bool(data.get("enabled"), defaults.enabled),
            sensitivity=_finite_float(
                data.get("sensitivity"), defaults.sensitivity, MIN_SENSITIVITY, MAX_SENSITIVITY
            ),
            deadzone=_finite_float(
                data.get("deadzone"), defaults.deadzone, MIN_DEADZONE, MAX_DEADZONE
            ),
            inverted=_json_bool(data.get("inverted"), defaults.inverted),
            curve=curve,
        )


@dataclass
class Profile:
    name: str = "Default"
    axes: dict[str, AxisConfig] = field(default_factory=dict)
    center_pose: dict | None = None

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
    def from_dict(cls, data: object) -> "Profile":
        if not isinstance(data, dict):
            log.warning("Invalid profile JSON root; using the default profile")
            return cls()

        defaults = cls.default_axes()
        source_axes = data.get("axes", {})
        if not isinstance(source_axes, dict):
            source_axes = {}
        axes = {
            name: AxisConfig.from_dict(source_axes.get(name), default)
            for name, default in defaults.items()
        }
        return cls(
            name=_bounded_text(data.get("name"), "Default", maximum=100),
            axes=axes,
            center_pose=_center_pose(data.get("center_pose")),
        )


@dataclass
class AppSettings:
    """Persisted app settings. Camera offset fields are centimetres in JSON/UI;
    CameraCalibration converts them to millimetres before applying PnP poses."""
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
    pose_smoothing: float = 0.6

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: object) -> "AppSettings":
        if not isinstance(data, dict):
            log.warning("Invalid settings JSON root; using defaults")
            return cls()

        defaults = cls()
        host = data.get("udp_host", defaults.udp_host)
        return cls(
            last_profile=_bounded_text(data.get("last_profile"), defaults.last_profile, maximum=100),
            language=data.get("language") if data.get("language") in {"en", "ru", "uk", "de"} else defaults.language,
            first_run=_json_bool(data.get("first_run"), defaults.first_run),
            camera_index=_bounded_int(data.get("camera_index"), defaults.camera_index, 0, 99),
            camera_width=_bounded_int(data.get("camera_width"), defaults.camera_width, 160, 7680),
            camera_height=_bounded_int(data.get("camera_height"), defaults.camera_height, 120, 4320),
            camera_fps=_bounded_int(data.get("camera_fps"), defaults.camera_fps, 1, 240),
            mirror=_json_bool(data.get("mirror"), defaults.mirror),
            camera_url=data.get("camera_url", "").strip() if _valid_camera_url(data.get("camera_url", "")) else "",
            camera_source=data.get("camera_source") if data.get("camera_source") in {"local", "ip", "websocket"} else defaults.camera_source,
            camera_rotation=data.get("camera_rotation") if data.get("camera_rotation") in {0, 90, 180, 270} else defaults.camera_rotation,
            image_enhance=_json_bool(data.get("image_enhance"), defaults.image_enhance),
            cam_offset_x=_finite_float(data.get("cam_offset_x"), defaults.cam_offset_x, -200.0, 200.0),
            cam_offset_y=_finite_float(data.get("cam_offset_y"), defaults.cam_offset_y, -200.0, 200.0),
            cam_offset_z=_finite_float(data.get("cam_offset_z"), defaults.cam_offset_z, -200.0, 200.0),
            cam_rotation_yaw=_finite_float(data.get("cam_rotation_yaw"), defaults.cam_rotation_yaw, -90.0, 90.0),
            cam_rotation_pitch=_finite_float(data.get("cam_rotation_pitch"), defaults.cam_rotation_pitch, -90.0, 90.0),
            cam_rotation_roll=_finite_float(data.get("cam_rotation_roll"), defaults.cam_rotation_roll, -90.0, 90.0),
            camera_fov=_finite_float(data.get("camera_fov"), defaults.camera_fov, MIN_CAMERA_FOV, MAX_CAMERA_FOV),
            output_protocol=data.get("output_protocol") if data.get("output_protocol") in {"freetrack", "udp", "mouse"} else defaults.output_protocol,
            udp_host=host.strip() if _valid_host(host.strip() if isinstance(host, str) else host) else defaults.udp_host,
            udp_port=_bounded_int(data.get("udp_port"), defaults.udp_port, 1, 65535),
            mouse_mode=data.get("mouse_mode") if data.get("mouse_mode") in {"velocity", "absolute"} else defaults.mouse_mode,
            mouse_speed=_finite_float(data.get("mouse_speed"), defaults.mouse_speed, 1.0, 200.0),
            mouse_stop_mode=data.get("mouse_stop_mode") if data.get("mouse_stop_mode") in {"hold", "toggle"} else defaults.mouse_stop_mode,
            mouse_hotkey=_bounded_text(data.get("mouse_hotkey"), defaults.mouse_hotkey, maximum=32),
            pose_smoothing=_finite_float(data.get("pose_smoothing"), defaults.pose_smoothing, 0.0, 1.0),
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


def _atomic_write_json(path: str | Path, data: dict):
    """Write JSON atomically: temp file + os.replace, so a crash mid-write
    never leaves a truncated file."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def save_profile(profile: Profile, path: str | Path):
    try:
        _atomic_write_json(Path(path), profile.to_dict())
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
        _atomic_write_json(SETTINGS_FILE, settings.to_dict())
        log.info(f"Settings saved: {SETTINGS_FILE}")
    except PermissionError:
        log.error(f"Permission denied writing settings: {SETTINGS_FILE}")
        raise
    except OSError as e:
        log.error(f"OS error writing settings {SETTINGS_FILE}: {e}")
        raise
    except Exception as e:
        log.error(f"Failed to save settings: {e}")
