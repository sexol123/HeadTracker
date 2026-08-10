import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import cv2
import tracker as tr

frame = cv2.imread(os.path.join(os.path.dirname(__file__), "data", "raw_frame.png"))
assert frame is not None, "raw_frame.png missing in tests/data/"
print("frame shape:", frame.shape)

tr.LANDMARK_INDICES = [1, 152, 263, 33, 291, 61]  # swapped eye & mouth pairs

t = tr.HeadTracker()
ts = time.perf_counter() - 1000
seen_confident = False
for rot, mir in [(0, 0), (270, 0), (270, 1), (0, 1), (90, 0)]:
    img = frame.copy()
    if rot == 90:
        img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    elif rot == 180:
        img = cv2.rotate(img, cv2.ROTATE_180)
    elif rot == 270:
        img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if mir:
        img = cv2.flip(img, 1)
    ts += 0.033
    p = t.process_frame(img, ts, img.shape[1], img.shape[0])
    print(f"swap rot={rot} mir={int(mir)}: yaw={p.yaw:+.1f} pitch={p.pitch:+.1f} roll={p.roll:+.1f} conf={p.confidence:.2f}")
    if p.confidence > 0.3:
        seen_confident = True
t.close()

assert seen_confident, "no confident detection in any rotation/mirror config"
print("POSE SWAP SMOKE OK")
