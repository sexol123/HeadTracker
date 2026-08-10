import logging
import time
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from camera import Camera, WebSocketCamera, CameraFrame
from tracker import HeadTracker, Pose
from freetrack import FreeTrackOutput
from udp_output import UdpOutput
from config import Profile, AppSettings
from i18n import t

log = logging.getLogger("worker")


class TrackingWorker(QThread):
    connecting = Signal()
    started_signal = Signal()
    frame_ready = Signal(object)
    pose_ready = Signal(object)
    confidence_ready = Signal(float)
    error_occurred = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._camera = None
        self._tracker: HeadTracker | None = None
        self._output = None
        self._profile: Profile | None = None
        self._settings: AppSettings | None = None
        self._mutex = QMutex()
        self._last_raw_pose = Pose()
        self._last_frame: CameraFrame | None = None

    def start_tracking(self, profile: Profile, settings: AppSettings):
        with QMutexLocker(self._mutex):
            if self._running or self.isRunning():
                return
            self._profile = profile
            self._settings = settings
            self._running = True

        self.start()
        log.info(f"Worker thread launched for profile: {profile.name}")

    def update_profile(self, profile: Profile):
        with QMutexLocker(self._mutex):
            self._profile = profile

    def run(self):
        log.info("Worker thread starting background initialization...")
        self.connecting.emit()

        with QMutexLocker(self._mutex):
            settings = self._settings
            profile = self._profile

        if not self._running:
            log.info("Worker stopped before camera init")
            self._cleanup()
            self.stopped.emit()
            return

        # 1. Initialize Camera in background thread
        try:
            if settings.camera_source == "websocket":
                self._camera = WebSocketCamera()
                success = self._camera.start(
                    url=settings.camera_url,
                    mirror=settings.mirror,
                    rotation=settings.camera_rotation,
                    enhance=settings.image_enhance,
                )
            else:
                self._camera = Camera()
                success = self._camera.start(
                    index=settings.camera_index,
                    width=settings.camera_width,
                    height=settings.camera_height,
                    fps=settings.camera_fps,
                    mirror=settings.mirror,
                    rotation=settings.camera_rotation,
                    url=settings.camera_url,
                    enhance=settings.image_enhance,
                )
        except Exception as e:
            log.error(f"Camera init exception: {e}", exc_info=True)
            success = False

        if not success or not self._running:
            if not self._running:
                log.info("Worker stopped during camera init")
            else:
                log.error("Failed to open camera stream")
                self.error_occurred.emit(t("error_camera"))
            self._cleanup()
            self.stopped.emit()
            return

        # 2. Initialize HeadTracker in background thread
        try:
            self._tracker = HeadTracker(
                face_hold_time=1.0,
                confidence_threshold=0.3,
            )
        except Exception as e:
            log.error(f"Tracker init exception: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
            self._cleanup()
            self.stopped.emit()
            return

        if not self._running:
            self._cleanup()
            self.stopped.emit()
            return

        # 3. Initialize Output in background thread
        try:
            if settings.output_protocol == "freetrack":
                self._output = FreeTrackOutput()
            else:
                self._output = UdpOutput(host=settings.udp_host, port=settings.udp_port)

            if not self._output.start():
                self.error_occurred.emit(t("error_output").format(settings.output_protocol))
                self._cleanup()
                self.stopped.emit()
                return
        except Exception as e:
            log.error(f"Output init exception: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
            self._cleanup()
            self.stopped.emit()
            return

        if not self._running:
            self._cleanup()
            self.stopped.emit()
            return

        self.started_signal.emit()
        log.info(f"Worker thread initialized — entering tracking loop for {profile.name}")

        frame_count = 0
        while self._running:
            t0 = time.perf_counter()

            frame = self._camera.get_frame()
            if frame is None:
                time.sleep(0.005)
                continue

            self._last_frame = frame

            with QMutexLocker(self._mutex):
                prof = self._profile

            pose = self._tracker.process_frame(
                frame.image, frame.timestamp, frame.width, frame.height
            )
            frame.landmarks = self._tracker.get_last_landmarks()
            self._last_raw_pose = pose

            mapped = self._apply_mapping(pose, prof)

            frame_count += 1
            if frame_count % 120 == 0:
                log.debug(
                    f"mapped conf={mapped.confidence:.2f} send={mapped.confidence >= 0.3} "
                    f"yaw={mapped.yaw:+.1f} pitch={mapped.pitch:+.1f} roll={mapped.roll:+.1f} "
                    f"x={mapped.x:+.1f} y={mapped.y:+.1f} z={mapped.z:+.1f}"
                )

            if self._output and mapped.confidence >= 0.3:
                self._output.send_pose(
                    yaw=mapped.yaw, pitch=mapped.pitch, roll=mapped.roll,
                    x=mapped.x, y=mapped.y, z=mapped.z,
                )

            self.confidence_ready.emit(mapped.confidence)
            self.pose_ready.emit(mapped)
            self.frame_ready.emit(frame)

            elapsed = time.perf_counter() - t0
            sleep_time = max(0, 0.016 - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

        log.info("Worker thread exiting tracking loop")
        self._cleanup()
        self.stopped.emit()

    def stop_tracking(self):
        log.info("Requesting worker stop...")
        self._running = False
        if self._camera:
            try:
                self._camera.stop()
            except Exception:
                pass
        if self.isRunning():
            if not self.wait(1000):
                log.warning("Worker thread did not terminate within 1s — forcing terminate")
                self.terminate()
                self.wait(500)
        self._cleanup()
        log.info("Worker stopped")

    def get_raw_pose(self) -> Pose:
        return self._last_raw_pose

    def get_last_frame(self) -> CameraFrame | None:
        return self._last_frame

    @staticmethod
    def _apply_mapping(pose: Pose, profile: Profile) -> Pose:
        axes = profile.axes

        def map_axis(value, name):
            cfg = axes.get(name)
            if cfg is None or not cfg.enabled:
                return 0.0
            v = value
            if cfg.inverted:
                v = -v
            if abs(v) < cfg.deadzone:
                v = 0.0
            v *= cfg.sensitivity
            return v

        return Pose(
            yaw=map_axis(pose.yaw, "yaw"),
            pitch=map_axis(pose.pitch, "pitch"),
            roll=map_axis(pose.roll, "roll"),
            x=map_axis(pose.x, "x"),
            y=map_axis(pose.y, "y"),
            z=map_axis(pose.z, "z"),
            confidence=pose.confidence,
            timestamp=pose.timestamp,
        )

    def _cleanup(self):
        if self._output:
            try:
                self._output.stop()
            except Exception as e:
                log.warning(f"Error stopping output: {e}")
            self._output = None
        if self._camera:
            try:
                self._camera.stop()
            except Exception as e:
                log.warning(f"Error stopping camera: {e}")
            self._camera = None
        if self._tracker:
            try:
                self._tracker.close()
            except Exception as e:
                log.warning(f"Error closing tracker: {e}")
            self._tracker = None
