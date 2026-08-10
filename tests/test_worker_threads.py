import os
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from config import AppSettings, Profile
from camera import Camera
from tracker import HeadTracker
from mouse_output import MouseOutput
from worker import TrackingWorker

app = QApplication([])


def make_worker():
    w = TrackingWorker()
    w._camera = Camera()
    w._tracker = HeadTracker(smoothing=0.0)
    w._output = MouseOutput(mode="velocity", speed=25.0)
    return w


# --- 1. hotkey restart is deferred to the worker thread, not run from UI thread ---
w = make_worker()
s1 = AppSettings()
s1.mouse_hotkey = "f8"
s1.mouse_stop_mode = "hold"
w.update_live_settings(s1)
assert w._key_listener is None, "UI-thread call must NOT touch the listener"
assert w._hotkey_request is not None, "hotkey restart must be deferred"
w._process_hotkey_request()
assert w._key_listener is not None, "worker-thread apply must start listener"
assert w._hotkey_request is None
w._stop_mouse_hotkey()
print("1. hotkey restart deferred to worker thread OK")

# --- 2. repeated identical live calls do not queue extra requests ---
s2 = AppSettings()
s2.mouse_hotkey = "f9"
s2.mouse_stop_mode = "toggle"
w.update_live_settings(s2)          # changed -> request queued
assert w._hotkey_request is not None
w.update_live_settings(s2)          # same values -> no new request
w.update_live_settings(s2)
assert w._hotkey_request is not None
w._process_hotkey_request()
assert w._hotkey_request is None and w._key_listener is not None
w._stop_mouse_hotkey()
print("2. change detection (only one pending request) OK")

# --- 3. stress: UI-thread writer vs worker-thread applier ---
w = make_worker()
errors = []
stop = threading.Event()

def writer():
    try:
        i = 0
        while not stop.is_set():
            s = AppSettings()
            s.mouse_hotkey = "f8" if i % 2 == 0 else "f9"
            s.mouse_speed = float(10 + i % 50)
            w.update_live_settings(s)
            i += 1
    except Exception as e:
        errors.append(e)

def applier():
    try:
        while not stop.is_set():
            w._process_hotkey_request()
    except Exception as e:
        errors.append(e)

t1 = threading.Thread(target=writer)
t2 = threading.Thread(target=applier)
t1.start()
t2.start()
time.sleep(1.0)
stop.set()
t1.join(5)
t2.join(5)
assert not t1.is_alive() and not t2.is_alive(), "threads did not finish"
assert not errors, errors
w._cleanup()
assert w._key_listener is None and w._output is None and w._hotkey_request is None
print("3. stress (writer vs applier) OK")

# --- 4. cleanup race: UI-thread writer vs worker-thread cleanup ---
errors2 = []
def writer2():
    try:
        for _ in range(300):
            s = AppSettings()
            s.mouse_hotkey = "f8"
            w.update_live_settings(s)
    except Exception as e:
        errors2.append(e)

for _ in range(5):
    w = make_worker()
    t = threading.Thread(target=writer2)
    t.start()
    time.sleep(0.002)
    w._cleanup()
    t.join(5)
    assert not t.is_alive(), "writer did not finish"
    assert not errors2, errors2
    assert w._key_listener is None and w._output is None and w._hotkey_request is None
print("4. cleanup race (writer vs cleanup x5) OK")

print("ALL WORKER THREAD TESTS PASSED")
