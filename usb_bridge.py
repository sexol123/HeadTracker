import logging
import os
import shutil
import subprocess
import sys

log = logging.getLogger("usb_bridge")

USB_PORT = 8080
USB_URL = f"ws://127.0.0.1:{USB_PORT}/ws"

IS_WINDOWS = sys.platform == "win32"

_ADB_CANDIDATES = {
    "ANDROID_HOME": ["platform-tools", "adb"],
    "ANDROID_SDK_ROOT": ["platform-tools", "adb"],
}


def find_adb() -> str | None:
    """Locate the adb executable: PATH first, then common SDK locations."""
    exe = shutil.which("adb")
    if exe:
        return exe
    suffix = ".exe" if IS_WINDOWS else ""
    bases = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            bases.append(os.path.join(local, "Android", "Sdk"))
    else:
        bases.append(os.path.expanduser("~/Android/Sdk"))
    for env_name in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(env_name):
            bases.append(os.environ[env_name])
    for base in bases:
        cand = os.path.join(base, "platform-tools", "adb" + suffix)
        if os.path.isfile(cand):
            return cand
    return None


def adb_forward(adb: str, port: int = USB_PORT) -> tuple[bool, str]:
    """Run `adb forward tcp:PORT tcp:PORT`. Returns (ok, message code)."""
    kwargs = {"creationflags": 0x08000000} if IS_WINDOWS else {}  # CREATE_NO_WINDOW
    try:
        r = subprocess.run(
            [adb, "devices"], capture_output=True, text=True, timeout=10, **kwargs
        )
        devices = [
            line.split("\t")[0]
            for line in r.stdout.splitlines()[1:]
            if line.strip() and "\tdevice" in line
        ]
        if not devices:
            return False, "no_device"
        r2 = subprocess.run(
            [adb, "forward", f"tcp:{port}", f"tcp:{port}"],
            capture_output=True,
            text=True,
            timeout=10,
            **kwargs,
        )
        if r2.returncode != 0:
            log.warning(f"adb forward failed: {r2.stdout.strip()} {r2.stderr.strip()}")
            return False, "forward_failed"
        return True, "ok"
    except FileNotFoundError:
        return False, "no_adb"
    except subprocess.TimeoutExpired:
        return False, "error"
    except Exception:
        log.warning("adb forward failed", exc_info=True)
        return False, "error"


def setup_usb_bridge(port: int = USB_PORT) -> tuple[bool, str]:
    """Find adb and forward the phone's WebSocket port to this PC."""
    adb = find_adb()
    if adb is None:
        return False, "no_adb"
    return adb_forward(adb, port)
