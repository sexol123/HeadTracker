import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tracker import HeadTracker, Pose

# EMA smoothing test without mediapipe: construct tracker-like object
class FakeTracker(HeadTracker):
    def __init__(self, smoothing):
        self._smoothing = float(smoothing)
        self._smooth_state = None

ft = FakeTracker(0.0)
p = ft._apply_smoothing(Pose(yaw=10.0, pitch=5.0, roll=1.0))
assert p.yaw == 10.0 and p.pitch == 5.0, "smoothing=0 passes through"
assert ft._smooth_state is None, "smoothing=0 keeps no state"

ft = FakeTracker(0.9)
p1 = ft._apply_smoothing(Pose(yaw=10.0, pitch=5.0, roll=1.0))
assert p1.yaw == 10.0, "first frame = raw"
p2 = ft._apply_smoothing(Pose(yaw=30.0, pitch=5.0, roll=1.0))
assert abs(p2.yaw - 12.0) < 1e-6, f"ema alpha=0.1: 10 + 20*0.1 = 12, got {p2.yaw}"
p3 = ft._apply_smoothing(Pose(yaw=30.0, pitch=5.0, roll=1.0))
assert abs(p3.yaw - 13.8) < 1e-6, f"converges toward 30: 12 + 18*0.1 = 13.8, got {p3.yaw}"
print("EMA math OK:", p1.yaw, "->", p2.yaw, "->", p3.yaw)

ft.set_smoothing(0.0)
assert ft._smooth_state is None, "set_smoothing(0) resets state"
p4 = ft._apply_smoothing(Pose(yaw=100.0, pitch=0.0, roll=0.0))
assert p4.yaw == 100.0, "after reset, raw passes"

ft = FakeTracker(0.7)
ft._apply_smoothing(Pose(yaw=0.0, pitch=0.0, roll=0.0))
p5 = ft._apply_smoothing(Pose(yaw=10.0, pitch=20.0, roll=30.0))
assert abs(p5.yaw - 3.0) < 1e-6 and abs(p5.pitch - 6.0) < 1e-6 and abs(p5.roll - 9.0) < 1e-6, p5
print("per-axis independent OK:", p5.yaw, p5.pitch, p5.roll)

# Confidence blending must compare the new pose to the *previous* output.
# A regression used to update _last_valid_pose before calling _build_pose,
# making the blend inputs identical and silently disabling the blend.
ft = FakeTracker(0.0)
ft._last_valid_pose = Pose(yaw=10.0, pitch=-10.0, x=100.0)
blended = ft._build_pose(
    0.25,
    timestamp=1.0,
    raw_pose=Pose(yaw=30.0, pitch=10.0, x=300.0),
)
assert abs(blended.yaw - 15.0) < 1e-6
assert abs(blended.pitch - (-5.0)) < 1e-6
assert abs(blended.x - 150.0) < 1e-6
print("confidence blend uses previous pose OK")
print("SMOOTHING TESTS PASSED")
