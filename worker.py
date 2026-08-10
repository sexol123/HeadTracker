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
MAX_CAMERA_RESTARTS = 5      # allowed restarts per RECONNECT_WINDOW before giving up
RECONNECT_WINDOW = 60.0      # sliding window (seconds)
RECONNECT_INTERVAL = 3.0     # minimum time between restart attempts


def _apply_curve(v, sens, curve):
    """Piecewise response curve shared with ui.axes_helper_dialog.axis_curve:
    (0,0) -> (x2,y2) -> slope=sens. curve=None keeps linear mapping."""
    if not curve or len(curve) < 2 or float(curve[0]) <= 0:
        return v * sens
    x2 = float(curve[0])
    y2 = max(0.0, float(curve[1]))
    sign = 1.0 if v >= 0 else -1.0
    a = abs(v)
    if a <= x2:
        out = y2 / x2 * a
    else:
        out = y2 + sens * (a - x2)
    return sign * out


class TrackingWorker(QThread):
    connecting = Signal()
    started_signal = Signal()
    frame_ready = Signal(object)
    pose_ready = Signal(object)
    confidence_ready = Signal(float)
    output_log = Signal(str)
    error_occurred = Signal(str)
    stopped = Signal()
    faces_ready = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._camera = None
        self._tracker: HeadTracker | None = None
        self._output = None
        self._profile: Profile | None = None
        self._settings: AppSettings | None = None
        self._key_listener = None
        self._last_mouse_hotkey: str | None = None
        self._last_mouse_stop_mode: str | None = None
        self._hotkey_request: AppSettings | None = None
        self._last_reconnect_attempt = 0.0
        self._reconnect_times: list[float] = []
        self._calibration: CameraCalibration | None = None
        self._mutex = QMutex()
        self._last_raw_pose = Pose()
        self._last_mapped_pose = Pose()
        self._last_frame: CameraFrame | None = None
        self._face_index: int = 0

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
            output = self._output
        if isinstance(output, MouseOutput):
            output.update_profile(profile)

    def set_face_index(self, index: int):
        """Select which detected face to track (0-based)."""
        with QMutexLocker(self._mutex):
            self._face_index = max(0, int(index))
            tracker = self._tracker
        if tracker is not None:
            tracker.set_face_index(self._face_index)

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
                camera = WebSocketCamera()
                success = camera.start(
                    url=settings.camera_url,
                    mirror=settings.mirror,
                    rotation=settings.camera_rotation,
                    enhance=settings.image_enhance,
                )
            else:
                camera = Camera()
                success = camera.start(
                    index=settings.camera_index,
                    width=settings.camera_width,
                    height=settings.camera_height,
                    fps=settings.camera_fps,
                    mirror=settings.mirror,
                    rotation=settings.camera_rotation,
                    url=settings.camera_url,
                    enhance=settings.image_enhance,
                )
            with QMutexLocker(self._mutex):
                self._camera = camera if success else None
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
            calibration = CameraCalibration(
                offset_x_cm=settings.cam_offset_x,
                offset_y_cm=settings.cam_offset_y,
                offset_z_cm=settings.cam_offset_z,
                yaw=settings.cam_rotation_yaw,
                pitch=settings.cam_rotation_pitch,
                roll=settings.cam_rotation_roll,
                fov=settings.camera_fov,
            )
            tracker = HeadTracker(
                face_hold_time=1.0,
                confidence_threshold=0.3,
                smoothing=settings.pose_smoothing,
                calibration=calibration,
            )
            self._apply_profile_center(calibration, profile)
            with QMutexLocker(self._mutex):
                self._calibration = calibration
                self._tracker = tracker
                tracker.set_face_index(self._face_index)
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
                output = FreeTrackOutput()
            elif settings.output_protocol == "mouse":
                output = MouseOutput(mode=settings.mouse_mode, speed=settings.mouse_speed)
                output.update_profile(profile)
                with QMutexLocker(self._mutex):
                    self._last_mouse_hotkey = settings.mouse_hotkey
                    self._last_mouse_stop_mode = settings.mouse_stop_mode
            else:
                output = UdpOutput(host=settings.udp_host, port=settings.udp_port)
            with QMutexLocker(self._mutex):
                self._output = output

            if not output.start():
                self.error_occurred.emit(t("error_output").format(settings.output_protocol))
                self._cleanup()
                self.stopped.emit()
                return
            if isinstance(output, MouseOutput):
                self._start_mouse_hotkey(settings)
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

            self._process_hotkey_request()

            frame = self._camera.get_frame()
            if frame is None:
                with QMutexLocker(self._mutex):
                    settings_now = self._settings
                if settings_now is not None:
                    self._maybe_restart_camera(settings_now)
                time.sleep(0.005)
                continue

            self._mark_camera_healthy()
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
            self._last_mapped_pose = mapped

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
            self.faces_ready.emit((
                self._tracker.get_selected_face_index(),
                self._tracker.get_face_boxes(),
            ))
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
        with QMutexLocker(self._mutex):
            camera = self._camera
        if camera:
            try:
                camera.stop()
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

    def get_mapped_pose(self) -> Pose:
        return self._last_mapped_pose

    def update_calibration(self, settings: AppSettings):
        """Live-apply camera adaptation values (called from the UI thread).
        CameraCalibration is internally lock-protected, so no race with the
        worker loop reading it."""
        with QMutexLocker(self._mutex):
            calibration = self._calibration
        if calibration is None:
            return
        calibration.update(
            offset_x_cm=settings.cam_offset_x,
            offset_y_cm=settings.cam_offset_y,
            offset_z_cm=settings.cam_offset_z,
            yaw=settings.cam_rotation_yaw,
            pitch=settings.cam_rotation_pitch,
            roll=settings.cam_rotation_roll,
            fov=settings.camera_fov,
        )

    @staticmethod
    def _apply_profile_center(calibration, profile: Profile | None) -> bool:
        """Apply the center pose stored in the profile (if any) to the
        calibration. Returns True when a center was applied."""
        if profile is None:
            return False
        cp = profile.center_pose
        if not isinstance(cp, dict):
            return False
        calibration.set_center(
            float(cp.get("yaw", 0.0)),
            float(cp.get("pitch", 0.0)),
            float(cp.get("roll", 0.0)),
            float(cp.get("x", 0.0)),
            float(cp.get("y", 0.0)),
            float(cp.get("z", 0.0)),
        )
        return True

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
            v = _apply_curve(v, cfg.sensitivity, cfg.curve)
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
        """Parse a hotkey spec like 'f8', 'ctrl+f8' or 'ctrl+shift+f10'.
        Returns (frozenset of modifier names, key) or None if invalid."""
        name = (name or "").strip().lower()
        if not name or KeyboardListener is None:
            return None
        parts = [p.strip() for p in name.split("+")]
        if not parts or not parts[-1]:
            return None
        valid_mods = {"ctrl", "alt", "shift"}
        mods = frozenset()
        for p in parts[:-1]:
            if p not in valid_mods:
                return None
            mods = frozenset(set(mods) | {p})
        base = parts[-1]
        attr = {
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5", "f6": "f6",
            "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
            "space": "space", "insert": "insert", "delete": "delete",
        }.get(base)
        if attr:
            key = getattr(Key, attr, None)
        elif len(base) == 1 and base.isprintable():
            key = KeyCode.from_char(base)
        else:
            key = None
        if key is None:
            return None
        return (mods, key)

    @staticmethod
    def _modifier_name(key) -> str | None:
        """Map a pressed key to a modifier name ('ctrl'/'alt'/'shift'), handling
        left/right/generic variants on Windows."""
        if KeyboardListener is None:
            return None
        for name in ("ctrl", "alt", "shift"):
            for attr in (name, name + "_l", name + "_r"):
                v = getattr(Key, attr, None)
                if v is not None and key == v:
                    return name
        return None

    def _start_mouse_hotkey(self, settings: AppSettings):
        if KeyboardListener is None:
            log.warning("pynput keyboard unavailable - mouse hotkey disabled")
            return
        parsed = self._parse_hotkey(settings.mouse_hotkey)
        if parsed is None:
            log.warning(f"Unknown mouse hotkey: {settings.mouse_hotkey!r}")
            return
        required_mods, key = parsed
        mode = settings.mouse_stop_mode
        output = self._output
        emit = self.output_log
        key_name = settings.mouse_hotkey
        last_toggle = [0.0]
        pressed_mods: set[str] = set()

        def on_press(k):
            mod = self._modifier_name(k)
            if mod is not None:
                pressed_mods.add(mod)
                return
            if k != key or pressed_mods != set(required_mods):
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
            mod = self._modifier_name(k)
            if mod is not None:
                pressed_mods.discard(mod)
                return
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

    def _stop_mouse_hotkey(self):
        if self._key_listener is not None:
            try:
                self._key_listener.stop()
                self._key_listener.join(timeout=1.0)
            except Exception as e:
                log.warning(f"Error stopping keyboard listener: {e}")
            self._key_listener = None

    def update_live_settings(self, settings: AppSettings):
        """Live-apply image/smoothing/mouse options (called from the UI thread).

        All writes are guarded by the worker mutex. The mouse hotkey is NOT
        restarted here: stopping/starting the keyboard listener blocks (join up
        to 1s) and would race with the worker thread's cleanup. Instead a
        request is queued and applied by _process_hotkey_request() inside the
        worker loop."""
        with QMutexLocker(self._mutex):
            cam = self._camera
            if cam is not None:
                try:
                    cam.set_image_options(
                        mirror=settings.mirror,
                        rotation=settings.camera_rotation,
                        enhance=settings.image_enhance,
                    )
                except Exception as e:
                    log.warning(f"Failed to apply image options live: {e}")
            if self._tracker is not None:
                try:
                    self._tracker.set_smoothing(settings.pose_smoothing)
                except Exception as e:
                    log.warning(f"Failed to apply smoothing live: {e}")
            if isinstance(self._output, MouseOutput):
                try:
                    self._output.set_mode(settings.mouse_mode)
                    self._output.set_speed(settings.mouse_speed)
                except Exception as e:
                    log.warning(f"Failed to apply mouse options live: {e}")
                hotkey_changed = (
                    settings.mouse_hotkey != self._last_mouse_hotkey
                    or settings.mouse_stop_mode != self._last_mouse_stop_mode
                )
                self._last_mouse_hotkey = settings.mouse_hotkey
                self._last_mouse_stop_mode = settings.mouse_stop_mode
                if hotkey_changed:
                    self._hotkey_request = settings
        log.debug("Live settings applied")

    def _process_hotkey_request(self):
        """Apply a pending mouse hotkey restart. Must run in the worker thread."""
        with QMutexLocker(self._mutex):
            request = self._hotkey_request
            self._hotkey_request = None
        if request is None:
            return
        try:
            self._stop_mouse_hotkey()
            self._start_mouse_hotkey(request)
        except Exception as e:
            log.warning(f"Failed to re-apply mouse hotkey: {e}")

    @staticmethod
    def _camera_start_kwargs(settings: AppSettings) -> dict:
        common = dict(
            mirror=settings.mirror,
            rotation=settings.camera_rotation,
            enhance=settings.image_enhance,
        )
        if settings.camera_source == "websocket":
            return dict(url=settings.camera_url, **common)
        return dict(
            index=settings.camera_index,
            width=settings.camera_width,
            height=settings.camera_height,
            fps=settings.camera_fps,
            url=settings.camera_url,
            **common,
        )

    def _maybe_restart_camera(self, settings: AppSettings):
        """Detect a stalled camera (e.g. after sleep/hibernate) and restart the
        stream with the current settings. Must run in the worker thread."""
        if not self._running:
            return
        cam = self._camera
        if cam is None or not cam.stats.stalled:
            return

        now = time.perf_counter()
        if now - self._last_reconnect_attempt < RECONNECT_INTERVAL:
            return

        cutoff = now - RECONNECT_WINDOW
        self._reconnect_times = [t for t in self._reconnect_times if t > cutoff]
        if len(self._reconnect_times) >= MAX_CAMERA_RESTARTS:
            log.error("Camera keeps stalling — giving up after %d restarts", MAX_CAMERA_RESTARTS)
            self.error_occurred.emit(t("error_camera"))
            self._running = False
            return

        self._last_reconnect_attempt = now
        self._reconnect_times.append(now)
        log.warning("Camera stalled (no frames) — restarting stream...")
        self.output_log.emit("Camera stalled — reconnecting…")

        try:
            cam.stop()
        except Exception as e:
            log.warning(f"Error stopping camera before restart: {e}")

        kwargs = self._camera_start_kwargs(settings)
        try:
            success = cam.start(**kwargs)
        except Exception as e:
            log.error(f"Camera restart failed: {e}", exc_info=True)
            success = False

        if not success:
            log.error("Camera restart failed — stopping tracking")
            self.error_occurred.emit(t("error_camera"))
            self._running = False
            return

        log.info("Camera restarted successfully")
        self.output_log.emit("Camera reconnected")

    def _mark_camera_healthy(self):
        """Reset the restart budget when frames flow again."""
        self._reconnect_times.clear()
        self._last_reconnect_attempt = 0.0

    def _cleanup(self):
        with QMutexLocker(self._mutex):
            listener = self._key_listener
            output = self._output
            camera = self._camera
            tracker = self._tracker
            self._key_listener = None
            self._output = None
            self._camera = None
            self._tracker = None
            self._hotkey_request = None
        if listener is not None:
            try:
                listener.stop()
                listener.join(timeout=1.0)
            except Exception as e:
                log.warning(f"Error stopping keyboard listener: {e}")
        if output:
            try:
                output.stop()
            except Exception as e:
                log.warning(f"Error stopping output: {e}")
        if camera:
            try:
                camera.stop()
            except Exception as e:
                log.warning(f"Error stopping camera: {e}")
        if tracker:
            try:
                tracker.close()
            except Exception as e:
                log.warning(f"Error closing tracker: {e}")
            self._tracker = None
