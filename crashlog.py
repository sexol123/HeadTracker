import atexit
import logging
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

log = logging.getLogger("crashlog")

LOGS_DIR = Path(__file__).parent / "logs"
_faulthandler_file = None
_orig_thread_excepthook = None


def crash_log_path() -> Path:
    LOGS_DIR.mkdir(exist_ok=True)
    return LOGS_DIR / f"crash_{datetime.now():%Y-%m-%d_%H-%M-%S}.log"


def write_crash_dump(title: str = "Crash", exc_info=None, extra: str = "") -> Path | None:
    try:
        path = crash_log_path()
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"=== HeadTracker {title} - {datetime.now().isoformat()} ===\n")
            f.write(f"Python: {sys.version}\n")
            f.write(f"Platform: {sys.platform}\n")
            f.write(f"CWD: {os.getcwd()}\n")
            if extra:
                f.write(extra + "\n")
            if exc_info:
                traceback.print_exception(*exc_info, file=f)
        log.error("Crash dump written: %s", path)
        return path
    except Exception:
        log.error("Failed to write crash dump", exc_info=True)
        return None


def _excepthook(exc_type, exc, tb):
    write_crash_dump("Unhandled exception", (exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def _thread_excepthook(args):
    write_crash_dump(
        f"Unhandled exception in thread {args.thread.name}",
        (args.exc_type, args.exc_value, args.exc_traceback),
    )
    if _orig_thread_excepthook is not None:
        _orig_thread_excepthook(args)


def install_crash_handlers(enable_faulthandler: bool = True):
    """Install hooks that dump crashes (unhandled exceptions, native faults)
    to logs/crash_*.log files."""
    global _faulthandler_file, _orig_thread_excepthook
    sys.excepthook = _excepthook
    if sys.version_info >= (3, 8):
        _orig_thread_excepthook = threading.excepthook
        threading.excepthook = _thread_excepthook
    if enable_faulthandler:
        try:
            import faulthandler
            LOGS_DIR.mkdir(exist_ok=True)
            _faulthandler_file = open(
                LOGS_DIR / f"crash_native_{datetime.now():%Y-%m-%d_%H-%M-%S}.log",
                "w", encoding="utf-8", errors="replace",
            )
            faulthandler.enable(file=_faulthandler_file, all_threads=True)
            log.info("faulthandler enabled (native crashes -> crash_native_*.log)")
        except Exception as e:
            log.warning("Failed to enable faulthandler: %s", e)
    atexit.register(cleanup_crash_handlers)


def cleanup_crash_handlers():
    """Remove the empty faulthandler file left by a clean exit."""
    global _faulthandler_file
    if _faulthandler_file is not None:
        try:
            _faulthandler_file.flush()
            path = _faulthandler_file.name
            _faulthandler_file.close()
            _faulthandler_file = None
            if Path(path).stat().st_size == 0:
                Path(path).unlink(missing_ok=True)
        except Exception:
            pass
