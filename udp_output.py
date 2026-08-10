import logging
import socket
import struct

log = logging.getLogger("udp_output")

# Standard OpenTrack UDP protocol: 6 doubles = 48 bytes (x, y, z in mm, yaw, pitch, roll in degrees)
PACKET_FORMAT_OPENTRACK = "<6d"
# Legacy float protocol: 6 floats = 24 bytes (yaw, pitch, roll, x, y, z)
PACKET_FORMAT_LEGACY = "!6f"


class UdpOutput:
    def __init__(self, host: str = "127.0.0.1", port: int = 4242):
        self._host = host
        self._port = port
        self._sock: socket.socket | None = None
        self._running = False

    def start(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._running = True
            log.info(f"UDP output started: {self._host}:{self._port}")
            return True
        except Exception as e:
            log.error(f"Failed to create UDP socket: {e}")
            return False

    def send_pose(
        self,
        yaw: float,
        pitch: float,
        roll: float,
        x: float,
        y: float,
        z: float,
    ):
        if not self._running or self._sock is None:
            return

        try:
            # OpenTrack UDP protocol expects: double x, y, z, yaw, pitch, roll (48 bytes)
            data_opentrack = struct.pack(
                PACKET_FORMAT_OPENTRACK,
                float(x), float(y), float(z),
                float(yaw), float(pitch), float(roll)
            )
            self._sock.sendto(data_opentrack, (self._host, self._port))
        except Exception as e:
            log.error(f"UDP send error: {e}")

    def stop(self):
        log.info("Stopping UDP output...")
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        log.info("UDP output stopped")
