import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import cv2
from cam_calib import CameraCalibration, euler_to_matrix, rotation_matrix_to_euler
from pose import Pose
from tracker import MODEL_POINTS

failures = []
def check(name, cond, detail=""):
    print(f"[{'OK ' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)

FOCAL, CX, CY = 640.0, 320.0, 240.0
K = np.array([[FOCAL, 0, CX], [0, FOCAL, CY], [0, 0, 1]], dtype=np.float64)
D = np.zeros((4, 1), dtype=np.float64)

def Rx(a):
    a = math.radians(a); c, s = math.cos(a), math.sin(a)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]], float)
def Ry(a):
    a = math.radians(a); c, s = math.cos(a), math.sin(a)
    return np.array([[c,0,s],[0,1,0],[-s,0,c]], float)

def simulate(R_world_cam, C, R_mon_head, t_mon):
    """Head pose in monitor frame -> raw pose PnP would produce for a camera
    with orientation R_world_cam (camera->world) at position C (world coords)."""
    pts_cam = []
    for p_model in MODEL_POINTS:
        p_world = R_mon_head @ p_model + t_mon
        pts_cam.append(R_world_cam.T @ (p_world - C))
    pts_cam = np.array(pts_cam, dtype=np.float64)
    img, _ = cv2.projectPoints(pts_cam, np.zeros(3), np.zeros(3), K, D)
    success, rvec, tvec = cv2.solvePnP(MODEL_POINTS, img.reshape(-1, 2), K, D, flags=cv2.SOLVEPNP_ITERATIVE)
    assert success
    R_obs, _ = cv2.Rodrigues(rvec)
    yaw, pitch, roll = rotation_matrix_to_euler(R_obs)
    t = tvec.flatten()
    return Pose(yaw=yaw, pitch=pitch, roll=roll, x=t[0], y=t[1], z=t[2], confidence=0.9)

# ---- Camera: 15 cm above, 50 cm from screen, pitched down 20 deg toward face
C = np.array([0.0, 150.0, 500.0])
CAM_PITCH = 20.0
R_world_cam = Rx(CAM_PITCH)  # camera forward tilts down: (0,-sin20,cos20)

cal = CameraCalibration(offset_y_cm=15.0, offset_z_cm=50.0, pitch=CAM_PITCH)

print("== straight head, tilted camera ==")
raw = simulate(R_world_cam, C, euler_to_matrix(0, 0, 0), np.array([0.0, 0.0, 650.0]))
print(f"    raw: yaw={raw.yaw:+.2f} pitch={raw.pitch:+.2f} roll={raw.roll:+.2f} t=({raw.x:+.0f},{raw.y:+.0f},{raw.z:+.0f})")
out = cal.apply(raw)
check("straight -> zero yaw", abs(out.yaw) < 1.0, f"got {out.yaw:+.2f}")
check("straight -> zero pitch", abs(out.pitch) < 1.0, f"got {out.pitch:+.2f}")
check("straight -> zero roll", abs(out.roll) < 1.0, f"got {out.roll:+.2f}")
check("straight -> zero x", abs(out.x) < 1.0, f"got {out.x:+.1f}")
check("straight -> zero y", abs(out.y) < 1.0, f"got {out.y:+.1f}")
check("straight -> z=650", abs(out.z - 650.0) < 1.0, f"got {out.z:+.1f}")

print("== turned head 20 deg right ==")
raw2 = simulate(R_world_cam, C, euler_to_matrix(20, 0, 0), np.array([0.0, 0.0, 650.0]))
out2 = cal.apply(raw2)
check("turn yaw", abs(out2.yaw - 20.0) < 1.0, f"got {out2.yaw:+.2f}")
check("turn pitch", abs(out2.pitch) < 1.0, f"got {out2.pitch:+.2f}")
check("turn roll", abs(out2.roll) < 1.0, f"got {out2.roll:+.2f}")

print("== look up 10, nod + tilt 15 ==")
raw3 = simulate(R_world_cam, C, euler_to_matrix(10, -8, 15), np.array([0.0, 0.0, 650.0]))
out3 = cal.apply(raw3)
check("combined yaw", abs(out3.yaw - 10.0) < 1.0, f"got {out3.yaw:+.2f}")
check("combined pitch", abs(out3.pitch - (-8.0)) < 1.0, f"got {out3.pitch:+.2f}")
check("combined roll", abs(out3.roll - 15.0) < 1.0, f"got {out3.roll:+.2f}")

print("== head shifted 5 cm right, 7 cm forward ==")
raw4 = simulate(R_world_cam, C, euler_to_matrix(0, 0, 0), np.array([50.0, 0.0, 720.0]))
out4 = cal.apply(raw4)
check("shift x", abs(out4.x - 50.0) < 1.0, f"got {out4.x:+.1f}")
check("shift y", abs(out4.y - 0.0) < 1.0, f"got {out4.y:+.1f}")
check("shift z", abs(out4.z - 720.0) < 1.0, f"got {out4.z:+.1f}")

print("== center capture (physical path) ==")
cal_center = CameraCalibration(offset_y_cm=15.0, offset_z_cm=50.0, pitch=CAM_PITCH)
neutral_raw = simulate(R_world_cam, C, euler_to_matrix(3.0, 2.0, -1.0), np.array([-20.0, 10.0, 680.0]))
neutral_adapted = cal_center.apply(neutral_raw)  # worker.recenter_camera uses the adapted pose
cal_center.set_center(neutral_adapted.yaw, neutral_adapted.pitch, neutral_adapted.roll,
                      neutral_adapted.x, neutral_adapted.y, neutral_adapted.z)
out_n = cal_center.apply(neutral_raw)
check("center: neutral -> zero", max(abs(out_n.yaw), abs(out_n.pitch), abs(out_n.roll), abs(out_n.x), abs(out_n.y), abs(out_n.z)) < 0.1,
      f"got y={out_n.yaw:+.2f} p={out_n.pitch:+.2f} r={out_n.roll:+.2f} t=({out_n.x:+.1f},{out_n.y:+.1f},{out_n.z:+.1f})")
moved_raw = simulate(R_world_cam, C, euler_to_matrix(23.0, 2.0, -1.0), np.array([80.0, 10.0, 760.0]))
out_m = cal_center.apply(moved_raw)
check("center: yaw rel 20", abs(out_m.yaw - 20.0) < 0.5, f"got {out_m.yaw:+.2f}")
check("center: x rel 100", abs(out_m.x - 100.0) < 1.0, f"got {out_m.x:+.1f}")
check("center: z rel 80", abs(out_m.z - 80.0) < 1.0, f"got {out_m.z:+.1f}")

print("== dialog scenario: camera aims at face from (-30,15,50)cm ==")
yaw_dlg = math.degrees(math.asin(300.0 / 350.0))      # 59.0 (3D mount yaw)
pitch_dlg = math.degrees(math.atan2(150.0, 100.0))    # 56.31 (2D side projection)
R_dlg = Rx(pitch_dlg) @ Ry(yaw_dlg)                   # calibration convention: Rx(pitch)@Ry(yaw)
C_dlg = np.array([-300.0, 150.0, 500.0])
cal_dlg = CameraCalibration(offset_x_cm=-30.0, offset_y_cm=15.0, offset_z_cm=50.0,
                            yaw=yaw_dlg, pitch=pitch_dlg)
raw_dlg = simulate(R_dlg, C_dlg, euler_to_matrix(0, 0, 0), np.array([0.0, 0.0, 600.0]))
out_dlg = cal_dlg.apply(raw_dlg)
check("dlg straight -> zero yaw", abs(out_dlg.yaw) < 1.0, f"got {out_dlg.yaw:+.2f}")
check("dlg straight -> zero pitch", abs(out_dlg.pitch) < 1.0, f"got {out_dlg.pitch:+.2f}")
check("dlg straight -> zero roll", abs(out_dlg.roll) < 1.0, f"got {out_dlg.roll:+.2f}")
check("dlg straight -> zero x", abs(out_dlg.x) < 1.0, f"got {out_dlg.x:+.1f}")
check("dlg straight -> zero y", abs(out_dlg.y) < 1.0, f"got {out_dlg.y:+.1f}")
check("dlg straight -> z=600", abs(out_dlg.z - 600.0) < 1.0, f"got {out_dlg.z:+.1f}")

print("== dialog scenario: head turned 20 deg ==")
raw_dlg2 = simulate(R_dlg, C_dlg, euler_to_matrix(20, -5, 10), np.array([0.0, 0.0, 600.0]))
out_dlg2 = cal_dlg.apply(raw_dlg2)
check("dlg turn yaw 20", abs(out_dlg2.yaw - 20.0) < 1.0, f"got {out_dlg2.yaw:+.2f}")
check("dlg turn pitch -5", abs(out_dlg2.pitch - (-5.0)) < 1.0, f"got {out_dlg2.pitch:+.2f}")
check("dlg turn roll 10", abs(out_dlg2.roll - 10.0) < 1.0, f"got {out_dlg2.roll:+.2f}")

print()
if failures:
    print(f"FAILED: {len(failures)}"); sys.exit(1)
print("ALL SYNTHETIC PNP TESTS PASSED")
