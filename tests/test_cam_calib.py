import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
from cam_calib import CameraCalibration, euler_to_matrix, rotation_matrix_to_euler
from pose import Pose

failures = []
def check(name, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)

def near(a, b, tol):
    return abs(a - b) <= tol

# 1. Euler <-> matrix roundtrip
print("== 1. euler_to_matrix / rotation_matrix_to_euler roundtrip ==")
for y, p, r in [(15, 10, -5), (-30, 20, 5), (5, -12, 25), (40, 30, -40), (0, 0, 0),
                (10, 0, 0), (0, 10, 0), (0, 0, 10), (45, -45, 45), (-20, 15, 5), (0, 0, -10)]:
    m = euler_to_matrix(y, p, r)
    y2, p2, r2 = rotation_matrix_to_euler(m)
    check(f"roundtrip ({y},{p},{r})", near(y2, y, 1e-6) and near(p2, p, 1e-6) and near(r2, r, 1e-6),
          f"got ({y2:.6f},{p2:.6f},{r2:.6f})")

# 2. Identity mode
print("== 2. identity (all zeros) ==")
cal = CameraCalibration()
p0 = Pose(yaw=12.5, pitch=-6.0, roll=3.0, x=10.0, y=-20.0, z=350.0, confidence=0.9)
res = cal.apply(p0)
check("identity apply", near(res.yaw, p0.yaw, 1e-9) and near(res.pitch, p0.pitch, 1e-9) and near(res.roll, p0.roll, 1e-9)
      and near(res.x, p0.x, 1e-6) and near(res.y, p0.y, 1e-6) and near(res.z, p0.z, 1e-6))

# 3. FOV focal length
print("== 3. FOV ==")
cal3 = CameraCalibration(fov=60.0)
f = cal3.focal_length(640)
check("fov 60 focal", near(f, 640 / 2 / np.tan(np.radians(30)), 1e-9), f"got {f:.4f}")
cal4 = CameraCalibration(fov=0.0)
check("fov 0 -> legacy", near(cal4.focal_length(640), 640.0, 1e-9), f"got {cal4.focal_length(640)}")

# 4. live update changes behavior
print("== 4. live update ==")
cal5 = CameraCalibration()
raw = Pose(yaw=0.0, pitch=20.0, roll=0.0, x=0.0, y=0.0, z=0.0, confidence=0.9)
check("no compensation at default", near(cal5.apply(raw).pitch, 20.0, 1e-9))
cal5.update(0.0, 0.0, 0.0, 0.0, 20.0, 0.0, 0.0)
out_u = cal5.apply(raw)
check("after live update compensated", near(out_u.pitch, 0.0, 1e-6), f"got {out_u.pitch:+.4f}")

# 5. set/clear center on raw values
print("== 5. center set/clear ==")
cal6 = CameraCalibration()
cal6.set_center(5.0, -3.0, 2.0, 10.0, 20.0, 30.0)
out_n = cal6.apply(Pose(yaw=5.0, pitch=-3.0, roll=2.0, x=10.0, y=20.0, z=30.0))
check("center neutral -> zero", all(near(getattr(out_n, k), 0.0, 1e-6) for k in ("yaw", "pitch", "roll", "x", "y", "z")))
out_s = cal6.apply(Pose(yaw=15.0, pitch=-3.0, roll=2.0, x=60.0, y=20.0, z=80.0))
check("center yaw rel", near(out_s.yaw, 10.0, 0.1), f"got {out_s.yaw:+.4f}")
check("center x rel", near(out_s.x, 50.0, 1e-6), f"got {out_s.x:+.4f}")
check("center z rel", near(out_s.z, 50.0, 1e-6), f"got {out_s.z:+.4f}")
cal6.clear_center()
out_c = cal6.apply(Pose(yaw=15.0, pitch=-3.0, roll=2.0, x=60.0, y=20.0, z=80.0))
check("cleared -> absolute", near(out_c.yaw, 15.0, 1e-6) and near(out_c.x, 60.0, 1e-6), f"got {out_c.yaw:+.4f}")

print()
if failures:
    print(f"FAILED: {len(failures)} tests")
    sys.exit(1)
print("ALL TESTS PASSED")
