import math
from dataclasses import dataclass
import logging

log = logging.getLogger("filter")


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
