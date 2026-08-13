import math
from dataclasses import dataclass
import logging

import cv2
import numpy as np

from pose import Pose
from cam_calib import euler_to_matrix, rotation_matrix_to_euler

log = logging.getLogger("filter")


class AdaptivePoseFilter:
    """Accela-style adaptive pose filter operating on frame deltas.

    - Rotation is filtered in tangent space (rotation-vector deltas), so the
      Euler extraction at the output cannot blow up near +-90 degrees pitch
      (the gimbal jitter of plain Euler-space EMA filtering).
    - Per-frame delta deadzone, subtractive like opentrack Accela.
    - Velocity-adaptive gain from a piecewise-linear spline using the opentrack
      Accela tables: tiny deltas barely move the output, large deltas follow
      quickly. Response is rate-correct (scales with dt).
    - Output pitch is clamped to +-PITCH_LIMIT (opentrack anti-bump clamp).
    """

    ROT_GAINS = [
        (0.0, 0.0), (0.5, 0.4), (1.0, 1.5), (1.5, 8.0), (2.5, 35.0),
        (5.0, 100.0), (8.0, 200.0), (9.0, 300.0),
    ]
    POS_GAINS = [
        (0.0, 0.0), (0.33, 0.375), (0.66, 0.75), (1.33, 2.25), (2.0, 7.5),
        (3.0, 24.0), (5.0, 60.0), (7.0, 110.0), (8.0, 150.0), (9.0, 200.0),
    ]
    ROT_DEADZONE = 0.03  # degrees
    POS_DEADZONE = 0.1  # mm
    PITCH_LIMIT = 89.86  # degrees
    MIN_DT = 1.0 / 500.0
    MAX_DT = 0.25

    def __init__(self, smoothing: float = 0.6):
        smoothing = max(0.0, min(1.0, smoothing))
        self.rot_thres = 0.05 + smoothing * (2.5 - 0.05)
        self.pos_thres = 0.05 + smoothing * (1.5 - 0.05)
        self._R_prev: np.ndarray | None = None
        self._t_prev: tuple[float, float, float] | None = None
        self._last_ts: float | None = None

    def reset(self):
        self._R_prev = None
        self._t_prev = None
        self._last_ts = None

    def __call__(self, pose: Pose) -> Pose:
        if self._R_prev is None or self._t_prev is None:
            self._R_prev = euler_to_matrix(pose.yaw, pose.pitch, pose.roll)
            self._t_prev = (pose.x, pose.y, pose.z)
            self._last_ts = pose.timestamp
            return pose

        ts = pose.timestamp or 0.0
        dt = ts - self._last_ts if self._last_ts is not None and ts > self._last_ts else 1.0 / 60.0
        dt = min(max(dt, self.MIN_DT), self.MAX_DT)

        # Rotation delta in the local (head) frame, in degrees
        R_cur = euler_to_matrix(pose.yaw, pose.pitch, pose.roll)
        rvec, _ = cv2.Rodrigues(self._R_prev.T @ R_cur)
        d = rvec.flatten() * (180.0 / math.pi)
        d_out = self._apply_delta(d, self.ROT_DEADZONE, self.rot_thres, self.ROT_GAINS, dt)
        R_out = self._R_prev @ cv2.Rodrigues(d_out * (math.pi / 180.0))[0]
        yaw, pitch, roll = rotation_matrix_to_euler(R_out)
        pitch = max(-self.PITCH_LIMIT, min(self.PITCH_LIMIT, pitch))

        # Translation delta, in millimetres
        t_in = np.array([pose.x, pose.y, pose.z], dtype=np.float64)
        t_delta = t_in - np.array(self._t_prev, dtype=np.float64)
        t_delta = self._apply_delta(t_delta, self.POS_DEADZONE, self.pos_thres, self.POS_GAINS, dt)
        t_out = np.array(self._t_prev, dtype=np.float64) + t_delta

        self._R_prev = R_out
        self._t_prev = (float(t_out[0]), float(t_out[1]), float(t_out[2]))
        self._last_ts = ts

        return Pose(
            yaw=yaw, pitch=pitch, roll=roll,
            x=float(t_out[0]), y=float(t_out[1]), z=float(t_out[2]),
            confidence=pose.confidence, timestamp=pose.timestamp,
        )

    def _apply_delta(self, v: np.ndarray, deadzone: float, thres: float, gains, dt: float) -> np.ndarray:
        """Accela delta step: subtractive deadzone, then spline gain as a
        per-second rate; output magnitude per frame is gain*dt, never exceeding
        the input delta."""
        norm = float(np.linalg.norm(v))
        if norm <= deadzone:
            return np.zeros_like(v)
        m = norm - deadzone
        v = v * (m / norm)
        x = m / thres
        gain = self._spline(x, gains)
        return v * (gain * dt / m)

    @staticmethod
    def _spline(x: float, pts) -> float:
        """Piecewise-linear gain curve, 0 at x=0, holds the last value beyond."""
        if x <= 0.0:
            return 0.0
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x <= x1:
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return pts[-1][1]


@dataclass
class FilterParams:
    min_cutoff: float = 1.0
    beta: float = 0.007
    d_cutoff: float = 1.0


class PassthroughFilter:
    def __call__(self, value: float, timestamp: float) -> float:
        return value

    def reset(self):
        pass


class OneEuroFilter:
    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.007, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._x_prev: float | None = None
        self._dx_prev: float = 0.0
        self._t_prev: float | None = None

    def __call__(self, value: float, timestamp: float) -> float:
        if self._t_prev is None or self._x_prev is None:
            self._x_prev = value
            self._t_prev = timestamp
            return value

        te = timestamp - self._t_prev
        if te <= 0:
            return self._x_prev

        # Derivative
        dx = (value - self._x_prev) / te
        alpha_d = self._smoothing_factor(te, self.d_cutoff)
        dx_hat = alpha_d * dx + (1.0 - alpha_d) * self._dx_prev

        # Adaptive cutoff
        cutoff = self.min_cutoff + self.beta * abs(dx_hat)
        alpha = self._smoothing_factor(te, cutoff)

        # Filter
        x_hat = alpha * value + (1.0 - alpha) * self._x_prev

        self._x_prev = x_hat
        self._dx_prev = dx_hat
        self._t_prev = timestamp

        return x_hat

    @staticmethod
    def _smoothing_factor(te: float, cutoff: float) -> float:
        if cutoff <= 0:
            return 1.0
        te = max(te, 1e-6)
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / te)

    def reset(self):
        self._x_prev = None
        self._dx_prev = 0.0
        self._t_prev = None


class ExponentialFilter:
    def __init__(self, alpha: float = 0.5):
        self.alpha = alpha
        self._prev: float | None = None

    def __call__(self, value: float, timestamp: float) -> float:
        if self._prev is None:
            self._prev = value
            return value
        result = self.alpha * value + (1.0 - self.alpha) * self._prev
        self._prev = result
        return result

    def reset(self):
        self._prev = None


def create_filter(filter_type: str, **kwargs):
    try:
        if filter_type == "one_euro":
            return OneEuroFilter(
                min_cutoff=kwargs.get("min_cutoff", 1.0),
                beta=kwargs.get("beta", 0.007),
            )
        elif filter_type == "exponential":
            return ExponentialFilter(alpha=kwargs.get("alpha", 0.5))
        elif filter_type == "adaptive":
            return AdaptiveExponentialFilter(
                rise_alpha=kwargs.get("rise_alpha", 0.7),
                fall_alpha=kwargs.get("fall_alpha", 0.1),
            )
        else:
            log.debug(f"Unknown filter type '{filter_type}', using PassthroughFilter")
            return PassthroughFilter()
    except Exception as e:
        log.warning(f"Failed to create filter '{filter_type}': {e}, using PassthroughFilter")
        return PassthroughFilter()


class AdaptiveExponentialFilter:
    """Exponential filter with different speeds for rising and falling signals.
    Fast recovery (rise_alpha) when signal returns, slow decay (fall_alpha) when lost.
    """

    def __init__(self, rise_alpha: float = 0.7, fall_alpha: float = 0.1):
        self.rise_alpha = rise_alpha
        self.fall_alpha = fall_alpha
        self._prev: float | None = None

    def __call__(self, value: float, timestamp: float = 0.0) -> float:
        if self._prev is None:
            self._prev = value
            return value
        if value > self._prev:
            alpha = self.rise_alpha
        else:
            alpha = self.fall_alpha
        result = alpha * value + (1.0 - alpha) * self._prev
        self._prev = result
        return result

    def reset(self):
        self._prev = None
