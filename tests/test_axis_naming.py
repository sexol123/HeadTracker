import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import cv2
from tracker import MODEL_POINTS, HeadTracker

FOCAL = 640.0
CX, CY = 320.0, 240.0
K = np.array([[FOCAL, 0, CX], [0, FOCAL, CY], [0, 0, 1]], dtype=np.float64)
D = np.zeros((4, 1), dtype=np.float64)
DIST = 500.0

def project(rvec_deg):
    rvec = np.array(rvec_deg, dtype=np.float64) * math.pi / 180.0
    tvec = np.array([0.0, 0.0, DIST], dtype=np.float64)
    pts, _ = cv2.projectPoints(MODEL_POINTS, rvec, tvec, K, D)
    return pts.reshape(-1, 2)

def pose_from(pts):
    success, rvec, tvec = cv2.solvePnP(MODEL_POINTS, pts, K, D, flags=cv2.SOLVEPNP_ITERATIVE)
    assert success
    R, _ = cv2.Rodrigues(rvec)
    return HeadTracker._rotation_matrix_to_euler(R)

def show(label, deg):
    pts = project(deg)
    e = pose_from(pts)
    print(f"{label:42s} -> yaw={e['yaw']:+7.2f} pitch={e['pitch']:+7.2f} roll={e['roll']:+7.2f}")
    return e

print("=== Fixed naming: turn->yaw, nod->pitch, tilt->roll (sim convention) ===")
show("identity", [0, 0, 0])
e_yaw = show("turn RIGHT 30 (about vertical)", [0, -30, 0])
assert abs(e_yaw["yaw"] - 30) < 0.5 and abs(e_yaw["pitch"]) < 0.5 and abs(e_yaw["roll"]) < 0.5, e_yaw
e_pitch = show("look UP 25 (about horizontal)", [-25, 0, 0])
assert abs(e_pitch["pitch"] - 25) < 0.5 and abs(e_pitch["yaw"]) < 0.5 and abs(e_pitch["roll"]) < 0.5, e_pitch
e_roll = show("tilt head RIGHT 20 (in-plane)", [0, 0, -20])
assert abs(e_roll["roll"] - 20) < 0.5 and abs(e_roll["yaw"]) < 0.5 and abs(e_roll["pitch"]) < 0.5, e_roll
show("turn LEFT 15 (about vertical)", [0, 30, 0])
show("nod DOWN 30", [25, 0, 0])
show("tilt LEFT 25", [0, 0, 20])
print("AXIS NAMING OK")
