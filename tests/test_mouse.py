import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import mouse_output as mo
from config import Profile, AxisConfig

moves = []
positions = []

class FakeController:
    def move(self, dx, dy):
        moves.append((dx, dy))
    @property
    def position(self):
        return positions[-1] if positions else (0, 0)
    @position.setter
    def position(self, pos):
        positions.append(pos)

mo.MouseController = FakeController  # force fake, pynput not touched

prof = Profile(name="Test")
prof.axes["yaw"] = AxisConfig(enabled=True, sensitivity=6.0, deadzone=2.0, inverted=False)
prof.axes["pitch"] = AxisConfig(enabled=True, sensitivity=6.0, deadzone=2.0, inverted=False)

# --- velocity mode ---
o = mo.MouseOutput(mode="velocity", speed=25.0)
o.update_profile(prof)
print("start:", o.start())
moves.clear()
o._last_time = None
o.send_pose(10.0, 5.0, 0.0, 0.0, 0.0, 0.0)   # dt defaults to 0.016 on first call
time.sleep(0.02)
o.send_pose(10.0, 5.0, 0.0, 0.0, 0.0, 0.0)   # second call uses real dt
time.sleep(0.02)
o.send_pose(2.0, 5.0, 0.0, 0.0, 0.0, 0.0)    # yaw within deadzone -> 0 dx
total_dx = sum(m[0] for m in moves)
total_dy = sum(m[1] for m in moves)
print("velocity moves:", moves)
assert total_dx > 0, "expected positive dx for right turn"
assert total_dy < 0, "expected negative dy for looking up"
print("velocity OK, total dx=%d dy=%d" % (total_dx, total_dy))
o.stop()

# --- absolute mode ---
o = mo.MouseOutput(mode="absolute", speed=20.0)
o.update_profile(prof)
o._screen = (1920, 1080)
print("start:", o.start())
o.send_pose(30.0, -10.0, 0.0, 0.0, 0.0, 0.0)
print("absolute positions:", positions)
assert positions[-1] == (960 + 30 * 20, 540 + 10 * 20), positions[-1]
assert 0 <= positions[-1][0] < 1920 and 0 <= positions[-1][1] < 1080
for _ in range(50):
    o._last_time = None
    o.send_pose(200.0, 0.0, 0.0, 0.0, 0.0, 0.0)
print("clamped:", positions[-1])
assert positions[-1][0] == 1919
o.stop()

# --- disabled axis -> no movement ---
prof.axes["yaw"].enabled = False
moves.clear()
o = mo.MouseOutput(mode="velocity", speed=25.0)
o.update_profile(prof)
o.start()
o.send_pose(10.0, 5.0, 0.0, 0.0, 0.0, 0.0)
o._last_time = None
o.send_pose(10.0, 5.0, 0.0, 0.0, 0.0, 0.0)
print("disabled-axis moves:", moves)
assert all(m[0] == 0 for m in moves), "yaw disabled -> no horizontal movement"
print("disabled axis OK")
o.stop()

# --- hotkey pause: send_pose is a no-op while inactive ---
moves.clear()
o = mo.MouseOutput(mode="velocity", speed=25.0)
o.update_profile(prof)
o.start()
o.set_active(False)
o.send_pose(10.0, 5.0, 0.0, 0.0, 0.0, 0.0)
o.send_pose(10.0, 5.0, 0.0, 0.0, 0.0, 0.0)
print("paused moves:", moves)
assert moves == [], "inactive -> no mouse movement"
o.set_active(True)
o.send_pose(10.0, 5.0, 0.0, 0.0, 0.0, 0.0)
print("after activate moves:", moves)
assert len(moves) >= 1, "reactivated -> movement resumes"
o.stop()

# --- smoothing: pose jump is gradual ---
prof.axes["yaw"].enabled = True
prof.axes["pitch"].enabled = True
moves.clear()
o = mo.MouseOutput(mode="velocity", speed=25.0)
o.update_profile(prof)
o.start()
for _ in range(10):
    o._last_time = None
    o.send_pose(10.0, 0.0, 0.0, 0.0, 0.0, 0.0)
moves.clear()
o._last_time = None
o.send_pose(30.0, 0.0, 0.0, 0.0, 0.0, 0.0)   # jump: first frame small
for _ in range(5):
    o._last_time = None
    o.send_pose(30.0, 0.0, 0.0, 0.0, 0.0, 0.0)
print("smooth jump moves:", moves)
assert moves[0][0] < moves[4][0], "first frame after jump is smaller than later ones"
assert moves[0][0] > 0, "movement starts immediately"
o.stop()

print("ALL MOUSE TESTS PASSED")
