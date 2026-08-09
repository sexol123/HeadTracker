import logging
import sys
import time
import threading
import cv2
import numpy as np
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

log = logging.getLogger("camera")


@dataclass
class CameraFrame:
    image: np.ndarray
    timestamp: float
    width: int
    height: int


@dataclass
class CameraStats:
    fps: float = 0.0
    frame_time_ms: float = 0.0
    bandwidth_mbps: float = 0.0
    total_frames: int = 0
    dropped_frames: int = 0
    resolution: str = ""


class Camera:
    def __init__(self):
        self._cap: cv2.VideoCapture | None = None
        self._index: int = -1
        self._mirror: bool = False
        self._url: str = ""
        self._stats = CameraStats()
        self._frame_times: list[float] = []
        self._last_frame_time: float = 0.0
        self._frame_count: int = 0
        self._drop_count: int = 0
        self._enhance: bool = False
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    @staticmethod
    def list_cameras(max_count: int = 10) -> list[dict]:
        cameras = []
        for i in range(max_count):
            try:
                # DirectShow only on Windows; Linux uses default backend (V4L2)
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW) if IS_WINDOWS else cv2.VideoCapture(i)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    fps = int(cap.get(cv2.CAP_PROP_FPS))
                    cameras.append({"index": i, "width": w, "height": h, "fps": fps})
                    cap.release()
            except Exception as e:
                log.warning(f"Error probing camera index={i}: {e}")
        return cameras

    def start(
        self,
        index: int = 0,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
        mirror: bool = False,
        url: str = "",
        enhance: bool = False,
    ) -> bool:
        self.stop()
        self._mirror = mirror
        self._url = url
        self._enhance = enhance
        self._frame_times = []
        self._last_frame_time = 0.0
        self._frame_count = 0
        self._drop_count = 0
        if enhance:
            log.info("Image enhancement (CLAHE) enabled")

        if url:
            log.info(f"Opening IP camera: {url}")
            if url.startswith("https://"):
                import os
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "ssl_verify;0"
                log.info("HTTPS detected — SSL verification disabled")
            self._cap = cv2.VideoCapture(url)
            if not self._cap.isOpened():
                log.error(f"Failed to open IP camera: {url}")
                return False
            w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._stats.resolution = f"{w}x{h}"
            log.info(f"IP camera opened OK ({w}x{h})")
            return True

        self._index = index
        log.info(f"Opening local camera index={index}, {width}x{height}@{fps}fps")
        # DirectShow only on Windows; Linux uses default backend (V4L2)
        self._cap = cv2.VideoCapture(index, cv2.CAP_DSHOW) if IS_WINDOWS else cv2.VideoCapture(index)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(index)
            if not self._cap.isOpened():
                log.error(f"Failed to open camera index={index}")
                return False
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv2.CAP_PROP_FPS, fps)
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._stats.resolution = f"{w}x{h}"
        log.info("Camera opened OK")
        return True

    def get_frame(self) -> CameraFrame | None:
        if self._cap is None or not self._cap.isOpened():
            return None

        try:
            t0 = time.perf_counter()
            ret, frame = self._cap.read()
            t1 = time.perf_counter()

            if not ret or frame is None:
                self._drop_count += 1
                return None
        except cv2.error as e:
            log.error(f"OpenCV error reading frame: {e}")
            self._drop_count += 1
            return None
        except Exception as e:
            log.error(f"Unexpected error reading frame: {e}", exc_info=True)
            self._drop_count += 1
            return None

        self._frame_count += 1
        read_ms = (t1 - t0) * 1000.0

        # Track frame times for FPS calculation (last 30 frames)
        self._frame_times.append(t1)
        if len(self._frame_times) > 30:
            self._frame_times.pop(0)

        # Calculate FPS
        if len(self._frame_times) >= 2:
            dt = self._frame_times[-1] - self._frame_times[0]
            if dt > 0:
                self._stats.fps = (len(self._frame_times) - 1) / dt

        self._stats.frame_time_ms = read_ms
        self._stats.total_frames = self._frame_count
        self._stats.dropped_frames = self._drop_count

        # Bandwidth estimate: frame size in bytes / read time
        h, w = frame.shape[:2]
        frame_bytes = w * h * 3  # BGR
        if read_ms > 0:
            self._stats.bandwidth_mbps = (frame_bytes * 8) / (read_ms / 1000.0) / 1_000_000

        if self._mirror:
            frame = cv2.flip(frame, 1)

        if self._enhance:
            log.debug("CLAHE enhancement applied")
            frame = self._apply_clahe(frame)

        return CameraFrame(
            image=frame,
            timestamp=time.perf_counter(),
            width=w,
            height=h,
        )

    def stop(self):
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception as e:
                log.warning(f"Error releasing camera: {e}")
            self._cap = None
        self._index = -1
        self._url = ""

    @property
    def is_running(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def index(self) -> int:
        return self._index

    @property
    def url(self) -> str:
        return self._url

    @property
    def stats(self) -> CameraStats:
        return self._stats

    def _apply_clahe(self, frame: np.ndarray) -> np.ndarray:
        """Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to enhance low-light images."""
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = self._clahe.apply(l)
        enhanced = cv2.merge([l, a, b])
        return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


class WebSocketCamera:
    def __init__(self):
        self._ws = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._url: str = ""
        self._stats = CameraStats()

    def start(self, url: str) -> bool:
        try:
            import websocket
        except ImportError:
            log.error("websocket-client library not installed. Run: pip install websocket-client")
            return False

        self._url = url
        self._running = True
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        log.info(f"WebSocket camera started: {url}")
        return True

    def _receive_loop(self):
        import websocket
        import base64
        import json

        def on_message(ws, message):
            try:
                if isinstance(message, bytes):
                    buf = np.frombuffer(message, dtype=np.uint8)
                    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                else:
                    data = json.loads(message)
                    if "image" in data:
                        img_bytes = base64.b64decode(data["image"])
                        buf = np.frombuffer(img_bytes, dtype=np.uint8)
                        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                    else:
                        return
                if frame is not None:
                    with self._lock:
                        self._frame = frame
                        self._stats.total_frames += 1
                        h, w = frame.shape[:2]
                        self._stats.resolution = f"{w}x{h}"
            except Exception as e:
                log.warning(f"WebSocket frame decode error: {e}")

        def on_error(ws, error):
            log.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            log.info(f"WebSocket closed: {close_status_code} {close_msg}")
            self._running = False

        def on_open(ws):
            log.info("WebSocket connected")

        try:
            ws = websocket.WebSocketApp(
                self._url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open,
            )
            self._ws = ws
            ws.run_forever(sslopt={"cert_reqs": 0})
        except Exception as e:
            log.error(f"WebSocket connection failed: {e}")
            self._running = False

    def read(self) -> CameraFrame | None:
        if not self._running or self._frame is None:
            return None
        with self._lock:
            frame = self._frame.copy()
        h, w = frame.shape[:2]
        return CameraFrame(image=frame, timestamp=time.perf_counter(), width=w, height=h)

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._frame = None
        self._url = ""
        log.info("WebSocket camera stopped")

    @property
    def is_running(self) -> bool:
        return self._running and self._frame is not None

    @property
    def stats(self) -> CameraStats:
        return self._stats
