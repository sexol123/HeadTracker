import logging
import ssl
import sys
import time
import threading
import cv2
import numpy as np
from dataclasses import dataclass

IS_WINDOWS = sys.platform == "win32"

log = logging.getLogger("camera")

STALL_TIMEOUT = 5.0  # seconds without a frame -> camera considered stalled


def apply_clahe(frame: np.ndarray, clahe: cv2.CLAHE) -> np.ndarray:
    """Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) to enhance low-light images."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = clahe.apply(l)
    enhanced = cv2.merge([l, a, b])
    return cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)


@dataclass
class CameraFrame:
    image: np.ndarray
    timestamp: float
    width: int
    height: int
    landmarks: list | None = None


@dataclass
class CameraStats:
    fps: float = 0.0
    frame_time_ms: float = 0.0
    bandwidth_mbps: float = 0.0
    total_frames: int = 0
    dropped_frames: int = 0
    resolution: str = ""
    stalled: bool = False


class Camera:
    def __init__(self):
        self._cap: cv2.VideoCapture | None = None
        self._index: int = -1
        self._mirror: bool = False
        self._rotation: int = 0
        self._url: str = ""
        self._stats = CameraStats()
        self._frame_times: list[float] = []
        self._last_frame_time: float = 0.0
        self._frame_count: int = 0
        self._drop_count: int = 0
        self._enhance: bool = False
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def get_stats(self) -> CameraStats:
        return self._stats

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
        rotation: int = 0,
        url: str = "",
        enhance: bool = False,
    ) -> bool:
        self.stop()
        self._mirror = mirror
        self._rotation = rotation
        self._url = url
        self._enhance = enhance
        self._frame_times = []
        self._last_frame_time = 0.0
        self._frame_count = 0
        self._drop_count = 0
        self._stats = CameraStats()
        if enhance:
            log.info("Image enhancement (CLAHE) enabled")

        if url:
            url = url.strip()
            # Normalize scheme if missing
            if not any(url.startswith(scheme) for scheme in ("http://", "https://", "rtsp://", "udp://", "wss://", "ws://")):
                if ":554" in url:
                    url = "rtsp://" + url
                else:
                    url = "http://" + url
                log.info(f"Auto-normalized IP camera URL to: {url}")

            # Auto-append stream path if user provided only IP:port (e.g. https://192.168.178.73:4444)
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.path or parsed.path == "/":
                url = url.rstrip("/") + "/video"
                log.info(f"Auto-appended '/video' stream endpoint: {url}")

            log.info(f"Opening IP camera stream: {url}")
            import os
            ffmpeg_opts = []
            if url.startswith("rtsp://"):
                ffmpeg_opts.extend(["rtsp_transport;tcp", "stimeout;3000000"])
            else:
                ffmpeg_opts.extend(["timeout;3000000"])

            if url.startswith("https://"):
                ffmpeg_opts.append("ssl_verify;0")

            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "|".join(ffmpeg_opts)
            log.info(f"FFmpeg options set: {os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS']}")

            self._cap = cv2.VideoCapture(url)
            if not self._cap.isOpened() and url.endswith("/video"):
                alt_url = url[:-6] + "/mjpeg"
                log.info(f"Retrying stream with alternative endpoint: {alt_url}")
                self._cap = cv2.VideoCapture(alt_url)

            if not self._cap or not self._cap.isOpened():
                log.error(f"Failed to open IP camera: {url}. Check IP address, port, and camera app.")
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

    def set_image_options(self, mirror: bool | None = None, rotation: int | None = None, enhance: bool | None = None):
        if mirror is not None:
            self._mirror = bool(mirror)
        if rotation is not None:
            self._rotation = int(rotation)
        if enhance is not None:
            self._enhance = bool(enhance)

    def get_frame(self) -> CameraFrame | None:
        if self._cap is None or not self._cap.isOpened():
            return None

        now = time.perf_counter()
        if self._last_frame_time > 0 and now - self._last_frame_time > STALL_TIMEOUT:
            self._stats.stalled = True

        try:
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
        self._last_frame_time = time.perf_counter()
        self._stats.stalled = False

        # Track frame times for FPS calculation (last 30 frames)
        previous_frame_time = self._frame_times[-1] if self._frame_times else None
        self._frame_times.append(t1)
        if len(self._frame_times) > 30:
            self._frame_times.pop(0)

        # Calculate FPS
        if len(self._frame_times) >= 2:
            dt = self._frame_times[-1] - self._frame_times[0]
            if dt > 0:
                self._stats.fps = (len(self._frame_times) - 1) / dt

        if previous_frame_time is not None:
            self._stats.frame_time_ms = (t1 - previous_frame_time) * 1000.0
        self._stats.total_frames = self._frame_count
        self._stats.dropped_frames = self._drop_count

        # Uncompressed BGR data rate derived from delivered FPS. It is not the
        # compressed on-the-wire bitrate of an IP stream.
        h, w = frame.shape[:2]
        frame_bytes = w * h * 3  # BGR
        self._stats.bandwidth_mbps = frame_bytes * 8 * self._stats.fps / 1_000_000

        if self._rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self._rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self._rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if self._mirror:
            frame = cv2.flip(frame, 1)

        if self._enhance:
            log.debug("CLAHE enhancement applied")
            frame = self._apply_clahe(frame)

        h, w = frame.shape[:2]
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
        return apply_clahe(frame, self._clahe)


class WebSocketCamera:
    def __init__(self):
        self._ws = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._url: str = ""
        self._mirror: bool = False
        self._rotation: int = 0
        self._enhance: bool = False
        self._stats = CameraStats()
        self._frame_times: list[float] = []
        self._frame_sizes: list[int] = []
        self._drop_count: int = 0
        self._last_frame_time: float = 0.0
        self._last_delivered_frame_time: float = 0.0
        self._clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))

    def get_stats(self) -> CameraStats:
        return self._stats

    def start(self, url: str, mirror: bool = False, rotation: int = 0, enhance: bool = False) -> bool:
        try:
            import websocket
        except ImportError:
            log.error("websocket-client library not installed. Run: pip install websocket-client")
            return False

        if not url:
            log.error("WebSocket URL is empty")
            return False

        url = url.strip()
        if not (url.startswith("ws://") or url.startswith("wss://")):
            url = "ws://" + url
            log.info(f"Auto-normalized WebSocket URL to: {url}")

        self._url = url
        self._mirror = mirror
        self._rotation = rotation
        self._enhance = enhance
        self._running = True
        self._frame_times = []
        self._frame_sizes = []
        self._drop_count = 0
        self._last_frame_time = 0.0
        self._last_delivered_frame_time = 0.0
        self._stats = CameraStats()

        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()
        log.info(f"WebSocket camera thread started: {url}")
        return True

    def set_image_options(self, mirror: bool | None = None, rotation: int | None = None, enhance: bool | None = None):
        if mirror is not None:
            self._mirror = bool(mirror)
        if rotation is not None:
            self._rotation = int(rotation)
        if enhance is not None:
            self._enhance = bool(enhance)

    def _receive_loop(self):
        import websocket
        import base64
        import json

        def on_message(ws, message):
            try:
                frame = None
                encoded_size = 0
                if isinstance(message, bytes):
                    encoded_size = len(message)
                    buf = np.frombuffer(message, dtype=np.uint8)
                    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                elif isinstance(message, str):
                    msg_str = message.strip()
                    if msg_str.startswith("{") and msg_str.endswith("}"):
                        data = json.loads(msg_str)
                        for key in ("image", "data", "frame", "jpeg", "b64", "img", "payload"):
                            if key in data and data[key]:
                                img_bytes = base64.b64decode(data[key])
                                encoded_size = len(img_bytes)
                                buf = np.frombuffer(img_bytes, dtype=np.uint8)
                                frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                                break
                    else:
                        img_bytes = base64.b64decode(msg_str)
                        encoded_size = len(img_bytes)
                        buf = np.frombuffer(img_bytes, dtype=np.uint8)
                        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)

                if frame is not None:
                    t_now = time.perf_counter()
                    with self._lock:
                        self._frame = frame
                        self._stats.total_frames += 1
                        self._stats.stalled = False
                        self._last_frame_time = t_now
                        h, w = frame.shape[:2]
                        self._stats.resolution = f"{w}x{h}"

                        self._frame_times.append(t_now)
                        self._frame_sizes.append(encoded_size)
                        if len(self._frame_times) > 30:
                            self._frame_times.pop(0)
                            self._frame_sizes.pop(0)

                        if len(self._frame_times) >= 2:
                            dt = self._frame_times[-1] - self._frame_times[0]
                            if dt > 0:
                                self._stats.fps = (len(self._frame_times) - 1) / dt
                                self._stats.frame_time_ms = (self._frame_times[-1] - self._frame_times[-2]) * 1000.0
                                self._stats.bandwidth_mbps = sum(self._frame_sizes) * 8 / dt / 1_000_000
            except Exception as e:
                log.warning(f"WebSocket frame decode error: {e}")

        def on_error(ws, error):
            log.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            log.info(f"WebSocket closed: {close_status_code} {close_msg}")
            self._running = False

        def on_open(ws):
            log.info(f"WebSocket connected successfully to {self._url}")

        try:
            ws = websocket.WebSocketApp(
                self._url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open,
            )
            self._ws = ws
            # ws:// is plaintext and has no TLS layer. For wss://, deliberately
            # accept self-signed camera certificates as requested by the user.
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE, "check_hostname": False})
        except Exception as e:
            log.error(f"WebSocket connection failed: {e}")
            self._running = False

    def get_frame(self) -> CameraFrame | None:
        return self.read()

    def read(self) -> CameraFrame | None:
        now = time.perf_counter()
        if self._last_frame_time > 0 and now - self._last_frame_time > STALL_TIMEOUT:
            self._stats.stalled = True
        if not self._running or self._frame is None:
            return None
        with self._lock:
            frame = self._frame.copy()
            frame_time = self._last_frame_time
        if frame_time <= self._last_delivered_frame_time:
            return None
        self._last_delivered_frame_time = frame_time
        self._stats.stalled = False
        if self._rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self._rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self._rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if self._mirror:
            frame = cv2.flip(frame, 1)
        if self._enhance:
            frame = self._apply_clahe(frame)
        h, w = frame.shape[:2]
        return CameraFrame(image=frame, timestamp=frame_time, width=w, height=h)

    def _apply_clahe(self, frame: np.ndarray) -> np.ndarray:
        return apply_clahe(frame, self._clahe)

    def stop(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._thread:
            self._thread.join(timeout=1.0)
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
