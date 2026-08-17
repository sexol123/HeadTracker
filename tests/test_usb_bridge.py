import os
import sys
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from usb_bridge import USB_URL, USB_PORT, find_adb, adb_forward
from config import AppSettings


def make_fake_adb(name, with_device=True, forward_fails=False):
    """Creates a tiny adb.bat stub and returns its path."""
    d = tempfile.mkdtemp()
    tab = "\t"
    lines = ["@echo off"]
    lines.append('if "%~1"=="devices" (')
    lines.append("  echo List of devices attached")
    if with_device:
        lines.append(f"  echo emulator-5554{tab}device")
    lines.append(") else (")
    lines.append("  exit /b 1" if forward_fails else "  echo tcp:%PORT%")
    lines.append(")")
    path = os.path.join(d, "adb.bat")
    with open(path, "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def test_find_adb_no_throw():
    adb = find_adb()
    assert adb is None or (isinstance(adb, str) and adb.lower().endswith("adb.exe" if sys.platform == "win32" else "adb"))
    print("PASS: find_adb returns a path or None without errors")


def test_forward_success():
    if sys.platform != "win32":
        return
    assert adb_forward(make_fake_adb("good")) == (True, "ok")
    print("PASS: adb forward succeeds with a connected device")


def test_forward_no_device():
    if sys.platform != "win32":
        return
    assert adb_forward(make_fake_adb("empty", with_device=False)) == (False, "no_device")
    print("PASS: no device -> no_device")


def test_forward_failed():
    if sys.platform != "win32":
        return
    assert adb_forward(make_fake_adb("fail", forward_fails=True)) == (False, "forward_failed")
    print("PASS: adb forward non-zero -> forward_failed")


def test_forward_missing_adb():
    assert adb_forward("Z:/definitely/not/here/adb") == (False, "no_adb")
    print("PASS: missing adb executable -> no_adb")


def test_worker_usb_kwargs():
    from PySide6.QtWidgets import QApplication
    from worker import TrackingWorker

    app = QApplication([])
    w = TrackingWorker()
    w._running = True
    s = AppSettings()
    s.camera_source = "usb"
    s.camera_url = ""
    kw = w._camera_start_kwargs(s)
    assert kw["url"] == USB_URL
    assert "index" not in kw
    assert kw["mirror"] is True
    print(f"PASS: usb source -> WebSocket kwargs with url {USB_URL}")


def test_config_accepts_usb_source():
    import config

    s = AppSettings()
    s.camera_source = "usb"
    data = s.to_dict()
    reloaded = AppSettings.from_dict(data)
    assert reloaded.camera_source == "usb"
    print("PASS: AppSettings round-trips camera_source 'usb'")


def main():
    test_find_adb_no_throw()
    test_forward_success()
    test_forward_no_device()
    test_forward_failed()
    test_forward_missing_adb()
    test_worker_usb_kwargs()
    test_config_accepts_usb_source()
    print("ALL USB BRIDGE TESTS PASSED")


if __name__ == "__main__":
    main()
    sys.exit(0)