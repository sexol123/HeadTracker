import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtWidgets import QApplication

from camera import Camera, WebSocketCamera, CameraStats, STALL_TIMEOUT
from config import AppSettings
from worker import TrackingWorker, MAX_CAMERA_RESTARTS, RECONNECT_WINDOW

app = QApplication([])


class FakeCap:
    def isOpened(self):
        return True

    def read(self):
        return False, None

    def release(self):
        pass

    def set(self, *args):
        return True

    def get(self, *args):
        return 0


class GoodCap:
    def isOpened(self):
        return True

    def read(self):
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def release(self):
        pass

    def set(self, *args):
        return True

    def get(self, *args):
        return 0


class FakeCam:
    def __init__(self, stay_stalled=False):
        self.stats = CameraStats()
        self.stats.stalled = True
        self.stay_stalled = stay_stalled
        self.start_calls = []
        self.stop_calls = 0

    def get_frame(self):
        return None

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        if not self.stay_stalled:
            self.stats.stalled = False
        return True

    def stop(self):
        self.stop_calls += 1


def make_worker():
    w = TrackingWorker()
    w._running = True
    return w


def test_camera_stall_flag():
    cam = Camera()
    cam._cap = FakeCap()
    cam._last_frame_time = time.perf_counter() - STALL_TIMEOUT - 1.0
    assert cam.get_frame() is None
    assert cam.stats.stalled
    print("PASS: Camera marks stalled when no frames arrive")


def test_camera_healthy_frame_clears_flag():
    cam = Camera()
    cam._cap = GoodCap()
    cam._last_frame_time = time.perf_counter() - STALL_TIMEOUT - 1.0
    cam._stats.stalled = True
    frame = cam.get_frame()
    assert frame is not None
    assert not cam.stats.stalled
    print("PASS: Camera clears stalled flag on healthy frame")


def test_websocket_read_stall():
    wsc = WebSocketCamera()
    wsc._running = True
    wsc._frame = None
    wsc._last_frame_time = time.perf_counter() - STALL_TIMEOUT - 1.0
    assert wsc.read() is None
    assert wsc.stats.stalled
    print("PASS: WebSocketCamera marks stalled when no frames arrive")


def test_worker_restarts_stalled_camera():
    w = make_worker()
    cam = FakeCam()
    w._camera = cam
    s = AppSettings()
    s.camera_source = "local"
    s.camera_index = 3
    s.camera_width = 800
    s.camera_height = 600
    s.camera_fps = 25
    s.mirror = True
    s.camera_rotation = 90
    s.image_enhance = True
    w._settings = s

    w._maybe_restart_camera(s)

    assert cam.stop_calls == 1
    assert len(cam.start_calls) == 1
    kw = cam.start_calls[0]
    assert kw["index"] == 3
    assert kw["width"] == 800
    assert kw["height"] == 600
    assert kw["fps"] == 25
    assert kw["mirror"] is True
    assert kw["rotation"] == 90
    assert kw["enhance"] is True
    assert w._running
    print("PASS: Worker restarts stalled camera with saved parameters")


def test_worker_restart_websocket_kwargs():
    w = make_worker()
    cam = FakeCam()
    w._camera = cam
    s = AppSettings()
    s.camera_source = "websocket"
    s.camera_url = "ws://127.0.0.1:8765"
    w._settings = s

    w._maybe_restart_camera(s)

    assert len(cam.start_calls) == 1
    kw = cam.start_calls[0]
    assert kw["url"] == "ws://127.0.0.1:8765"
    assert "index" not in kw
    print("PASS: WebSocket restart passes url only")


def test_restart_throttle_and_limit():
    w = make_worker()
    cam = FakeCam(stay_stalled=True)
    w._camera = cam
    s = AppSettings()
    s.camera_source = "local"
    w._settings = s

    errors = []
    w.error_occurred.connect(errors.append)

    w._maybe_restart_camera(s)
    w._maybe_restart_camera(s)
    assert len(cam.start_calls) == 1, "second attempt within interval must be throttled"

    for _ in range(MAX_CAMERA_RESTARTS * 2):
        w._last_reconnect_attempt = 0.0
        w._maybe_restart_camera(s)

    assert len(cam.start_calls) == MAX_CAMERA_RESTARTS
    assert len(errors) == 1
    assert w._running is False
    print("PASS: Restarts limited to %d per %ds window, error emitted on give-up" % (
        MAX_CAMERA_RESTARTS, RECONNECT_WINDOW))


def test_healthy_frame_resets_restart_budget():
    w = make_worker()
    cam = FakeCam(stay_stalled=True)
    w._camera = cam
    s = AppSettings()
    s.camera_source = "local"
    w._settings = s

    w._maybe_restart_camera(s)
    assert len(cam.start_calls) == 1

    w._mark_camera_healthy()
    w._maybe_restart_camera(s)
    assert len(cam.start_calls) == 2
    print("PASS: Healthy frame resets the restart budget")


def test_healthy_camera_not_restarted():
    w = make_worker()
    cam = FakeCam()
    cam.stats.stalled = False
    w._camera = cam
    s = AppSettings()
    s.camera_source = "local"
    w._settings = s

    w._maybe_restart_camera(s)
    assert len(cam.start_calls) == 0
    assert cam.stop_calls == 0
    print("PASS: Healthy camera is never restarted")


if __name__ == "__main__":
    test_camera_stall_flag()
    test_camera_healthy_frame_clears_flag()
    test_websocket_read_stall()
    test_worker_restarts_stalled_camera()
    test_worker_restart_websocket_kwargs()
    test_restart_throttle_and_limit()
    test_healthy_frame_resets_restart_budget()
    test_healthy_camera_not_restarted()
    print("ALL CAMERA STALL TESTS PASSED")
