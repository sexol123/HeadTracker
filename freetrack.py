import logging
import ctypes
import ctypes.wintypes
import math
import os
import winreg

log = logging.getLogger("freetrack")

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1)
FILE_MAP_ALL_ACCESS = 0x001F
PAGE_READWRITE = 0x04

FREETRACK_HEAP = "FT_SharedMem"
FREETRACK_MUTEX = "FT_Mutext"  # Original typo preserved for compatibility


class FTData(ctypes.Structure):
    _fields_ = [
        ("DataID", ctypes.c_uint32),
        ("CamWidth", ctypes.c_int32),
        ("CamHeight", ctypes.c_int32),
        ("Yaw", ctypes.c_float),
        ("Pitch", ctypes.c_float),
        ("Roll", ctypes.c_float),
        ("X", ctypes.c_float),
        ("Y", ctypes.c_float),
        ("Z", ctypes.c_float),
        ("RawYaw", ctypes.c_float),
        ("RawPitch", ctypes.c_float),
        ("RawRoll", ctypes.c_float),
        ("RawX", ctypes.c_float),
        ("RawY", ctypes.c_float),
        ("RawZ", ctypes.c_float),
        ("X1", ctypes.c_float),
        ("Y1", ctypes.c_float),
        ("X2", ctypes.c_float),
        ("Y2", ctypes.c_float),
        ("X3", ctypes.c_float),
        ("Y3", ctypes.c_float),
        ("X4", ctypes.c_float),
        ("Y4", ctypes.c_float),
    ]


class FTHeap(ctypes.Structure):
    _fields_ = [
        ("data", FTData),
        ("GameID", ctypes.c_int32),
        ("table", ctypes.c_uint8 * 8),
        ("GameID2", ctypes.c_int32),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Set proper types for 64-bit compatibility
kernel32.CreateFileMappingA.argtypes = [
    ctypes.c_void_p,  # HANDLE hFile
    ctypes.c_void_p,  # LPSECURITY_ATTRIBUTES
    ctypes.c_uint32,  # DWORD flProtect
    ctypes.c_uint32,  # DWORD dwMaximumSizeHigh
    ctypes.c_uint32,  # DWORD dwMaximumSizeLow
    ctypes.c_char_p,  # LPCSTR lpName
]
kernel32.CreateFileMappingA.restype = ctypes.c_void_p

kernel32.MapViewOfFile.argtypes = [
    ctypes.c_void_p,  # HANDLE hFileMappingObject
    ctypes.c_uint32,  # DWORD dwDesiredAccess
    ctypes.c_uint32,  # DWORD dwFileOffsetHigh
    ctypes.c_uint32,  # DWORD dwFileOffsetLow
    ctypes.c_size_t,  # SIZE_T dwNumberOfBytesToMap
]
kernel32.MapViewOfFile.restype = ctypes.c_void_p

kernel32.CreateMutexA.argtypes = [
    ctypes.c_void_p,  # LPSECURITY_ATTRIBUTES
    ctypes.c_bool,    # BOOL bInitialOwner
    ctypes.c_char_p,  # LPCSTR lpName
]
kernel32.CreateMutexA.restype = ctypes.c_void_p

kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
kernel32.WaitForSingleObject.restype = ctypes.c_uint32

kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
kernel32.ReleaseMutex.restype = ctypes.c_bool

kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.UnmapViewOfFile.restype = ctypes.c_bool

kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_bool


def _get_last_error() -> int:
    return ctypes.get_last_error()


def _format_error(code: int) -> str:
    if code == 0:
        return "ERROR_SUCCESS"
    buf = ctypes.create_unicode_buffer(256)
    kernel32.FormatMessageW(
        0x00000100, None, code, 0, buf, 256, None
    )
    return f"Error {code}: {buf.value.strip()}"


class FreeTrackOutput:
    def __init__(self):
        self._handle = None
        self._view = None
        self._mutex = None
        self._data_id: int = 0
        self._heap: FTHeap | None = None
        self._running = False

    def start(self) -> bool:
        log.info("Starting FreeTrack output...")
        log.info(f"FTHeap size: {ctypes.sizeof(FTHeap)} bytes")
        log.info(f"FTData size: {ctypes.sizeof(FTData)} bytes")

        try:
            # Create shared memory
            log.info(f"Creating shared memory: '{FREETRACK_HEAP}'")
            self._handle = kernel32.CreateFileMappingA(
                INVALID_HANDLE_VALUE,
                None,
                PAGE_READWRITE,
                0,
                ctypes.sizeof(FTHeap),
                FREETRACK_HEAP.encode("ascii"),
            )
            err = _get_last_error()
            if not self._handle:
                log.error(f"CreateFileMappingA failed: {_format_error(err)}")
                return False
            log.info(f"CreateFileMappingA OK, handle=0x{self._handle:X}")

            # Map view
            log.info("Mapping view of file...")
            self._view = kernel32.MapViewOfFile(
                self._handle,
                FILE_MAP_ALL_ACCESS,
                0,
                0,
                ctypes.sizeof(FTHeap),
            )
            err = _get_last_error()
            if not self._view:
                log.error(f"MapViewOfFile failed: {_format_error(err)}")
                self._cleanup()
                return False
            log.info(f"MapViewOfFile OK, view=0x{self._view:X}")

            # Map FTHeap structure to the view
            self._heap = FTHeap.from_address(self._view)
            # Zero out the structure
            ctypes.memset(self._view, 0, ctypes.sizeof(FTHeap))
            log.info("FTHeap mapped to shared memory")

            # Create mutex
            log.info(f"Creating mutex: '{FREETRACK_MUTEX}'")
            self._mutex = kernel32.CreateMutexA(
                None,
                False,
                FREETRACK_MUTEX.encode("ascii"),
            )
            err = _get_last_error()
            if not self._mutex:
                log.warning(f"CreateMutexA failed: {_format_error(err)} (non-fatal)")
            else:
                log.info(f"Mutex created OK, handle=0x{self._mutex:X}")

            # Register in Windows registry
            self._register_registry()

            self._running = True
            log.info("FreeTrack output started successfully")
            return True

        except Exception as e:
            log.error(f"Exception during FreeTrack start: {e}", exc_info=True)
            self._cleanup()
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
        if not self._running or self._heap is None:
            return

        self._data_id += 1
        d2r = math.pi / 180.0

        # Acquire mutex
        if self._mutex:
            wait_result = kernel32.WaitForSingleObject(self._mutex, 100)
            if wait_result != 0 and wait_result != 1:  # WAIT_OBJECT_0 or WAIT_ABANDONED
                log.warning(f"WaitForSingleObject returned {wait_result}")

        try:
            self._heap.data.DataID = self._data_id
            self._heap.data.CamWidth = 100
            self._heap.data.CamHeight = 250

            # Rotation: degrees to radians (with sign flips for FreeTrack convention)
            self._heap.data.Yaw = -yaw * d2r
            self._heap.data.Pitch = -pitch * d2r
            self._heap.data.Roll = roll * d2r

            # Translation in mm
            self._heap.data.X = x
            self._heap.data.Y = y
            self._heap.data.Z = z

            # Raw values
            self._heap.data.RawYaw = self._heap.data.Yaw
            self._heap.data.RawPitch = self._heap.data.Pitch
            self._heap.data.RawRoll = self._heap.data.Roll
            self._heap.data.RawX = self._heap.data.X
            self._heap.data.RawY = self._heap.data.Y
            self._heap.data.RawZ = self._heap.data.Z

            if self._data_id % 100 == 1:
                log.debug(
                    f"FT frame#{self._data_id}: "
                    f"Yaw={math.degrees(self._heap.data.Yaw):+.1f} "
                    f"Pitch={math.degrees(self._heap.data.Pitch):+.1f} "
                    f"Roll={math.degrees(self._heap.data.Roll):+.1f} "
                    f"X={self._heap.data.X:.1f} Y={self._heap.data.Y:.1f} Z={self._heap.data.Z:.1f}"
                )
        finally:
            if self._mutex:
                kernel32.ReleaseMutex(self._mutex)

    def stop(self):
        log.info("Stopping FreeTrack output...")
        self._running = False
        self._cleanup()
        log.info("FreeTrack output stopped")

    def _cleanup(self):
        if self._view:
            kernel32.UnmapViewOfFile(self._view)
            log.debug("Unmapped view")
            self._view = None
        if self._handle:
            kernel32.CloseHandle(self._handle)
            log.debug("Closed file mapping handle")
            self._handle = None
        if self._mutex:
            kernel32.CloseHandle(self._mutex)
            log.debug("Closed mutex")
            self._mutex = None
        self._heap = None

    @staticmethod
    def _register_registry():
        dll_dir = os.path.dirname(os.path.abspath(__file__))

        # FreeTrack registry
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                r"Software\Freetrack\FreetrackClient",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "Path", 0, winreg.REG_SZ, dll_dir + "\\")
            winreg.CloseKey(key)
            log.info(f"Registry: FreeTrack path set to {dll_dir}\\")
        except OSError as e:
            log.warning(f"Registry: Failed to set FreeTrack path: {e}")

        # NPClient registry (TrackIR compatibility)
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                r"Software\NaturalPoint\NATURALPOINT\NPClient Location",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.SetValueEx(key, "Path", 0, winreg.REG_SZ, dll_dir + "\\")
            winreg.CloseKey(key)
            log.info(f"Registry: NPClient path set to {dll_dir}\\")
        except OSError as e:
            log.warning(f"Registry: Failed to set NPClient path: {e}")
