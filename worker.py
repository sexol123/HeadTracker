import logging
import time
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from camera import Camera, CameraFrame
from tracker import HeadTracker, Pose
from freetrack import FreeTrackOutput
from udp_output import UdpOutput
from config import Profile
from i18n import t

log = logging.getLogger("worker")


class TrackingWorker(QThread):
    frame_ready = Signal(object)   # CameraFrame
    pose_ready = Signal(object)    # Pose (mapped, after center subtraction)
    confidence_ready = Signal(float)
    error_occurred = Signal(str)
    stopped = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._camera: Camera | None = None
        self._tracker: HeadTracker | None = None
        self._output = None
        self._profile: Profile | None = None
        self._mutex = QMutex()
        self._last_raw_pose = Pose()
        self._last_frame: CameraFrame | None = None

    def start_tracking(self, profile: Profile):
        with QMutexLocker(self._mutex):
            if self._running:
                return
            self._profile = profile

        try:
            self._camera = Camera()
            if not self._camera.start(
                index=profile.camera_index,
                width=profile.camera_width,
                height=profile.camera_height,
                fps=profile.camera_fps,
                mirror=profile.mirror,
                url=profile.camera_url,
                enhance=profile.image_enhance,
            ):
                self.error_occurred.emit(t("error_camera"))
                return

            self._tracker = HeadTracker(
                face_hold_time=1.0,
                confidence_threshold=0.3,
            )

            if profile.output_protocol == "freetrack":
                self._output = FreeTrackOutput()
            else:
                self._output = UdpOutput(host=profile.udp_host, port=profile.udp_port)

            if not self._output.start():
                self.error_occurred.emit(t("error_output").format(profile.output_protocol))
                self._cleanup()
                return

            self._running = True
            self.start()
            log.info(f"Worker started: {profile.name}")

        except Exception as e:
            log.error(f"Failed to start worker: {e}", exc_info=True)
            self.error_occurred.emit(str(e))
            self._cleanup()

    def update_profile(self, profile: Profile):
        with QMutexLocker(self._mutex):
            self._profile = profile

    def run(self):
        log.info("Worker thread running")
        while self._running:
            t0 = time.perf_counter()

            frame = self._camera.get_frame()
            if frame is None:
                time.sleep(0.005)
                continue

            self._last_frame = frame

            with QMutexLocker(self._mutex):
                profile = self._profile

            pose = self._tracker.process_frame(
                frame.image, frame.timestamp, frame.width, frame.height
            )
            self._last_raw_pose = pose

            corrected = pose

            mapped = self._apply_mapping(corrected, profile)

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

        log.info("Worker thread exiting")
        self.stopped.emit()

    def stop_tracking(self):
        self._running = False
        self.wait(3000)
        self._cleanup()
        log.info("Worker stopped")

    def update_profile(self, profile: Profile):
        with QMutexLocker(self._mutex):
            self._profile = profile

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
