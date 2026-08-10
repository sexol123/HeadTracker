import logging
import sys
import time
from PySide6.QtCore import QThread, Signal, QMutex, QMutexLocker

from camera import Camera, WebSocketCamera, CameraFrame
from tracker import HeadTracker
from pose import Pose
from cam_calib import CameraCalibration
from freetrack import FreeTrackOutput
from udp_output import UdpOutput
from mouse_output import MouseOutput
from config import Profile, AppSettings
from i18n import t

try:
    from pynput.keyboard import Listener as KeyboardListener, Key, KeyCode
except ImportError:
    KeyboardListener = Key = KeyCode = None

log = logging.getLogger("worker")

TOGGLE_DEBOUNCE = 0.3


class TrackingWorker(QThread):
    connecting = Signal()
    started_signal = Signal()
    frame_ready = Signal(object)
    pose_ready = Signal(object)
    confidence_ready = Signal(float)
    output_log = Signal(str)
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
        self._key_listener = None
        self._calibration: CameraCalibration | None = None
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
        if isinstance(self._output, MouseOutput):
            self._output.update_profile(profile)

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
            self._calibration = CameraCalibration(
                offset_x_cm=settings.cam_offset_x,
                offset_y_cm=settings.cam_offset_y,
                offset_z_cm=settings.cam_offset_z,
                yaw=settings.cam_rotation_yaw,
                pitch=settings.cam_rotation_pitch,
                roll=settings.cam_rotation_roll,
                fov=settings.camera_fov,
            )
            self._tracker = HeadTracker(
                face_hold_time=1.0,
                confidence_threshold=0.3,
                smoothing=settings.pose_smoothing,
                calibration=self._calibration,
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
            elif settings.output_protocol == "mouse":
                self._output = MouseOutput(mode=settings.mouse_mode, speed=settings.mouse_speed)
                self._output.update_profile(profile)
                self._start_mouse_hotkey(settings)
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
        proto_tag = "FT" if settings.output_protocol == "freetrack" else ("Mouse" if settings.output_protocol == "mouse" else "UDP")
        while self._running:
            t0 = time.perf_counter()

            frame = self._camera.get_frame()
            if frame is None:
                time.sleep(0.005)
                continue

            self._last_frame = frame

            with QMutexLocker(self._mutex):
                prof = self._profile

            try:
                pose = self._tracker.process_frame(
                    frame.image, frame.timestamp, frame.width, frame.height
                )
            except Exception as e:
                log.critical(f"Fatal error in tracking loop: {e}", exc_info=True)
                import crashlog
                crashlog.write_crash_dump("Fatal error in worker tracking loop", sys.exc_info())
                self._running = False
                break
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

            sent = False
            if self._output and mapped.confidence >= 0.3:
                try:
                    if isinstance(self._output, MouseOutput):
                        self._output.send_pose(
                            yaw=pose.yaw, pitch=pose.pitch, roll=pose.roll,
                            x=pose.x, y=pose.y, z=pose.z,
                        )
                    else:
                        self._output.send_pose(
                            yaw=mapped.yaw, pitch=mapped.pitch, roll=mapped.roll,
                            x=mapped.x, y=mapped.y, z=mapped.z,
                        )
                except Exception as e:
                    log.critical(f"Fatal error in output: {e}", exc_info=True)
                    import crashlog
                    crashlog.write_crash_dump("Fatal error in output", sys.exc_info())
                    self._running = False
                    break
                sent = True

            if frame_count % 60 == 0:
                if not sent:
                    line = f"{proto_tag} » no send: conf={mapped.confidence:.2f} (< 0.3)"
                elif isinstance(self._output, MouseOutput) and not self._output.is_active():
                    line = f"Mouse » paused ({self._settings.mouse_hotkey if self._settings else '?'})"
                elif isinstance(self._output, MouseOutput):
                    line = (
                        f"Mouse » yaw={pose.yaw:+.1f}° pitch={pose.pitch:+.1f}° "
                        f"conf={mapped.confidence:.2f}"
                    )
                else:
                    fid = getattr(self._output, "frame_id", None)
                    fid_txt = f" DataID={fid()}" if fid else ""
                    line = (
                        f"{proto_tag} » Yaw={mapped.yaw:+.1f}° Pitch={mapped.pitch:+.1f}° "
                        f"Roll={mapped.roll:+.1f}° X={mapped.x:+.1f} Y={mapped.y:+.1f} "
                        f"Z={mapped.z:+.1f} conf={mapped.confidence:.2f}{fid_txt}"
                    )
                self.output_log.emit(line)

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

    def update_calibration(self, settings: AppSettings):
        """Live-apply camera adaptation values (called from the UI thread)."""
        if self._calibration is None:
            return
        self._calibration.update(
            offset_x_cm=settings.cam_offset_x,
            offset_y_cm=settings.cam_offset_y,
            offset_z_cm=settings.cam_offset_z,
            yaw=settings.cam_rotation_yaw,
            pitch=settings.cam_rotation_pitch,
            roll=settings.cam_rotation_roll,
            fov=settings.camera_fov,
        )

    def recenter_camera(self) -> bool:
        """Capture the current pose as the neutral center. Returns True on success."""
        if self._calibration is None or self._tracker is None:
            return False
        pose = self.get_raw_pose()
        if pose.confidence < 0.3:
            log.warning("Recenter skipped: face not tracked (conf=%.2f)", pose.confidence)
            return False
        self._calibration.set_center(pose.yaw, pose.pitch, pose.roll, pose.x, pose.y, pose.z)
        log.info(
            "Camera center set: yaw=%+.1f pitch=%+.1f roll=%+.1f x=%+.0f y=%+.0f z=%+.0f",
            pose.yaw, pose.pitch, pose.roll, pose.x, pose.y, pose.z,
        )
        return True

    def reset_camera_center(self):
        if self._calibration is None:
            return
        self._calibration.clear_center()
        log.info("Camera center cleared")

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

    @staticmethod
    def _parse_hotkey(name: str):
        name = (name or "").strip().lower()
        if not name or KeyboardListener is None:
            return None
        attr = {
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5", "f6": "f6",
            "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
            "space": "space", "insert": "insert", "delete": "delete",
        }.get(name)
        if attr:
            return getattr(Key, attr, None)
        if len(name) == 1 and name.isprintable():
            return KeyCode.from_char(name)
        return None

    def _start_mouse_hotkey(self, settings: AppSettings):
        if KeyboardListener is None:
            log.warning("pynput keyboard unavailable - mouse hotkey disabled")
            return
        key = self._parse_hotkey(settings.mouse_hotkey)
        if key is None:
            log.warning(f"Unknown mouse hotkey: {settings.mouse_hotkey!r}")
            return
        mode = settings.mouse_stop_mode
        output = self._output
        emit = self.output_log
        key_name = settings.mouse_hotkey
        last_toggle = [0.0]

        def on_press(k):
            if k != key:
                return
            if mode == "toggle":
                now = time.perf_counter()
                if now - last_toggle[0] >= TOGGLE_DEBOUNCE:
                    last_toggle[0] = now
                    output.set_active(not output.is_active())
                    emit.emit(f"Mouse » {'on' if output.is_active() else 'off'} ({key_name})")
            elif not output.is_active():
                output.set_active(True)
                emit.emit(f"Mouse » on ({key_name})")

        def on_release(k):
            if k == key and mode != "toggle" and output.is_active():
                output.set_active(False)
                emit.emit(f"Mouse » off ({key_name})")

        try:
            self._key_listener = KeyboardListener(on_press=on_press, on_release=on_release)
            self._key_listener.start()
            log.info(f"Mouse hotkey active: {key_name} (mode={mode})")
        except Exception as e:
            log.error(f"Failed to start keyboard listener: {e}", exc_info=True)
            self._key_listener = None

    def _cleanup(self):
        if self._key_listener is not None:
            try:
                self._key_listener.stop()
                self._key_listener.join(timeout=1.0)
            except Exception as e:
                log.warning(f"Error stopping keyboard listener: {e}")
            self._key_listener = None
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
