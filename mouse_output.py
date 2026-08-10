import logging
import math
import sys
import time

log = logging.getLogger("mouse_output")

try:
    from pynput.mouse import Controller as MouseController
except ImportError:
    MouseController = None

MAX_FRAME_DELTA = 64.0
FALLBACK_SCREEN = (1920, 1080)
MIN_DEADZONE = 1.5
SMOOTH_TAU = 0.05


class MouseOutput:
    """Moves the system mouse based on head pose.

    velocity: yaw/pitch turn into relative mouse deltas (mouse-look),
              the view pans while the head is turned and stops when centered.
    absolute: the cursor is positioned on screen proportionally to yaw/pitch.
    """

    def __init__(self, mode: str = "velocity", speed: float = 25.0):
        self._controller = None
        self._running = False
        self._mode = mode
        self._speed = float(speed)
        self._profile = None
        self._active = True
        self._last_time: float = 0.0
        self._frac_x = 0.0
        self._frac_y = 0.0
        self._smooth_yaw: float | None = None
        self._smooth_pitch: float | None = None
        self._screen = None

    def start(self) -> bool:
        if MouseController is None:
            log.error("pynput is not installed. Run: pip install pynput")
            return False
        try:
            self._controller = MouseController()
            self._running = True
            log.info(f"Mouse output started (mode={self._mode}, speed={self._speed})")
            return True
        except Exception as e:
            log.error(f"Failed to start mouse controller: {e}")
            return False

    def update_profile(self, profile):
        self._profile = profile

    def set_mode(self, mode: str):
        self._mode = mode

    def set_speed(self, speed: float):
        self._speed = float(speed)

    def set_active(self, active: bool):
        active = bool(active)
        if active == self._active:
            return
        self._active = active
        if active:
            self._last_time = 0.0
            self._frac_x = 0.0
            self._frac_y = 0.0
            self._smooth_yaw = None
            self._smooth_pitch = None
        log.info("Mouse output %s", "activated" if active else "paused")

    def is_active(self) -> bool:
        return self._active

    def send_pose(self, yaw, pitch, roll, x, y, z):
        if not self._running or self._controller is None or not self._active:
            return

        now = time.perf_counter()
        dt = (now - self._last_time) if self._last_time else 0.016
        self._last_time = now
        dt = max(dt, 1e-4)
        if dt > 0.5:
            dt = 0.016

        yaw_d = self._smooth(yaw, "yaw", dt)
        pitch_d = self._smooth(pitch, "pitch", dt)
        yaw_d = self._apply_axis(yaw_d, "yaw")
        pitch_d = self._apply_axis(pitch_d, "pitch")

        if self._mode == "velocity":
            vx = yaw_d * self._speed * dt
            vy = -pitch_d * self._speed * dt
            vx = max(-MAX_FRAME_DELTA, min(MAX_FRAME_DELTA, vx))
            vy = max(-MAX_FRAME_DELTA, min(MAX_FRAME_DELTA, vy))
            self._frac_x += vx
            self._frac_y += vy
            dx = int(self._frac_x)
            dy = int(self._frac_y)
            self._frac_x -= dx
            self._frac_y -= dy
            if dx or dy:
                try:
                    self._controller.move(dx, dy)
                except Exception as e:
                    log.debug(f"Mouse move error: {e}")
        else:
            w, h = self._screen_size()
            cx, cy = w / 2.0, h / 2.0
            tx = cx + yaw_d * self._speed
            ty = cy - pitch_d * self._speed
            tx = max(0.0, min(w - 1, tx))
            ty = max(0.0, min(h - 1, ty))
            try:
                self._controller.position = (int(tx), int(ty))
            except Exception as e:
                log.debug(f"Mouse position error: {e}")

    def _smooth(self, value: float, name: str, dt: float) -> float:
        prev = self._smooth_yaw if name == "yaw" else self._smooth_pitch
        if prev is None:
            smoothed = value
        else:
            alpha = 1.0 - math.exp(-dt / SMOOTH_TAU)
            smoothed = prev + (value - prev) * alpha
        if name == "yaw":
            self._smooth_yaw = smoothed
        else:
            self._smooth_pitch = smoothed
        return smoothed

    def _apply_axis(self, value: float, name: str) -> float:
        if self._profile is None:
            return value
        cfg = self._profile.axes.get(name)
        if cfg is None or not cfg.enabled:
            return 0.0
        v = value
        if cfg.inverted:
            v = -v
        if abs(v) < max(cfg.deadzone, MIN_DEADZONE):
            return 0.0
        return v

    def _screen_size(self):
        if self._screen is not None:
            return self._screen
        w, h = FALLBACK_SCREEN
        try:
            if sys.platform == "win32":
                import ctypes
                user32 = ctypes.windll.user32
                w, h = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        except Exception:
            pass
        self._screen = (int(w), int(h))
        return self._screen

    def stop(self):
        log.info("Stopping mouse output...")
        self._running = False
        self._controller = None
        self._last_time = 0.0
        self._frac_x = 0.0
        self._frac_y = 0.0
        log.info("Mouse output stopped")
