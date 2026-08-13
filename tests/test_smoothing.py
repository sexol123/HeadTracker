import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from filter import AdaptivePoseFilter
from tracker import HeadTracker, Pose

# AdaptivePoseFilter tests without mediapipe: construct tracker-like object.
# The filter derives dt from pose.timestamp; frames below use 1/60 exactly.
class FakeTracker(HeadTracker):
    def __init__(self, smoothing):
        self._smoothing = float(smoothing)
        self._pose_filter = None if self._smoothing <= 0.0 else AdaptivePoseFilter(self._smoothing)

DT = 1.0 / 60.0

# smoothing=0 passes through and keeps no filter
ft = FakeTracker(0.0)
p = ft._apply_smoothing(Pose(yaw=10.0, pitch=5.0, roll=1.0))
assert p.yaw == 10.0 and p.pitch == 5.0, "smoothing=0 passes through"
assert ft._pose_filter is None, "smoothing=0 keeps no filter"

# set_smoothing rebuilds / disables the filter
ft = FakeTracker(0.6)
ft.set_smoothing(0.0)
assert ft._pose_filter is None, "set_smoothing(0) disables filter"
ft.set_smoothing(0.4)
assert ft._pose_filter is not None, "set_smoothing(>0) enables filter"
p = ft._apply_smoothing(Pose(yaw=5.0, timestamp=0.0))
assert p.yaw == 5.0, "fresh filter: first frame = raw"
print("passthrough / set_smoothing OK")

# Step response: a 30 deg yaw step is followed at gain*dt per frame.
# smoothing=0.9 -> rot_thres=2.255; deltas of ~30 deg hit the gain hold (300)
# -> exactly 300*dt = 5.0 deg per frame while the delta stays large.
ft = FakeTracker(0.9)
p0 = ft._apply_smoothing(Pose(yaw=0.0, timestamp=0.0))
assert p0.yaw == 0.0, "first frame = raw"
p1 = ft._apply_smoothing(Pose(yaw=30.0, timestamp=DT))
assert abs(p1.yaw - 5.0) < 1e-9, f"gain hold: 300*dt=5.0, got {p1.yaw}"
p2 = ft._apply_smoothing(Pose(yaw=30.0, timestamp=2 * DT))
assert abs(p2.yaw - 10.0) < 1e-9, f"still in gain hold, got {p2.yaw}"
for i in range(3, 60):
    last = ft._apply_smoothing(Pose(yaw=30.0, timestamp=DT * i))
assert abs(30.0 - last.yaw) < 2.0, f"converges near target, got {last.yaw}"
print("step response OK: 5.0 -> 10.0 -> ... -> %.2f" % last.yaw)

# Jitter suppression: alternating +-1 deg around a settled pose must not
# move the output more than a few hundredths of a degree.
ft = FakeTracker(0.9)
ft._apply_smoothing(Pose(yaw=30.0, timestamp=0.0))
worst = 0.0
for i in range(1, 41):
    y = 30.0 + (1.0 if i % 2 else -1.0)
    p = ft._apply_smoothing(Pose(yaw=y, timestamp=DT * i))
    worst = max(worst, abs(p.yaw - 30.0))
assert worst < 0.05, f"jitter must stay tiny, got {worst}"
print("jitter suppression OK: worst %.5f deg" % worst)

# Delta deadzone: sub-deadzone deltas freeze the output exactly.
ft = FakeTracker(0.5)
p0 = ft._apply_smoothing(Pose(yaw=12.0, timestamp=0.0))
p1 = ft._apply_smoothing(Pose(yaw=12.02, timestamp=DT))
assert p1.yaw == 12.0, "0.02 deg < rot deadzone 0.03 -> frozen"
p2 = ft._apply_smoothing(Pose(yaw=13.0, timestamp=2 * DT))
assert p2.yaw > 12.0, "above deadzone -> moves"
print("delta deadzone OK")

# Translation: 100 mm step, smoothing=0.6 -> pos_thres=0.92, gain hold 200
# -> exactly 200*dt = 3.333 mm on the first frame.
ft = FakeTracker(0.6)
ft._apply_smoothing(Pose(x=0.0, y=0.0, z=0.0, timestamp=0.0))
p = ft._apply_smoothing(Pose(x=100.0, timestamp=DT))
assert abs(p.x - 3.333) < 1e-3, f"translation gain hold, got {p.x}"
print("translation step OK: %.3f mm" % p.x)

# Gimbal regression: looking up to 89.5 deg pitch must stay stable — no NaN,
# pitch bounded and monotone toward the target, yaw/roll finite. The old
# Euler-space EMA blew up near +-90.
ft = FakeTracker(0.9)
ft._apply_smoothing(Pose(yaw=0.0, pitch=0.0, timestamp=0.0))
ts = 0.0
prev = 0.0
for target in [30.0, 60.0, 85.0, 89.5]:
    for _ in range(30):
        ts += DT
        p = ft._apply_smoothing(Pose(yaw=0.0, pitch=target, timestamp=ts))
        assert p.yaw == 0.0 and p.roll == 0.0, "no coupling while pitch ramps"
        assert abs(p.pitch) < 90.0, f"pitch bounded, got {p.pitch}"
        assert p.pitch >= prev - 1e-9, f"monotone, got {p.pitch} after {prev}"
        prev = p.pitch
for _ in range(120):
    ts += DT
    p = ft._apply_smoothing(Pose(yaw=0.0, pitch=89.5, timestamp=ts))
    assert abs(p.pitch) < 90.0, "pitch stays bounded"
assert p.pitch > 87.0, f"approach 89.5 (Accela crawl near target), got {p.pitch}"
print("gimbal stability OK: final pitch %.2f" % p.pitch)

# Yaw step at high pitch must not explode (the old Euler-space filter jumped
# wildly when the gimbal degenerated near +-90).
p_before = p
ts += DT
p = ft._apply_smoothing(Pose(yaw=10.0, pitch=89.5, timestamp=ts))
for name, v in (("yaw", p.yaw), ("pitch", p.pitch), ("roll", p.roll)):
    assert abs(v) < 100.0, f"high-pitch yaw step bounded, {name}={v}"
dyaw = abs(p.yaw - p_before.yaw)
assert dyaw < 15.0, f"per-frame euler jump bounded, d_yaw={dyaw}"
print("high-pitch yaw step OK: d_yaw=%.2f" % dyaw)

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
