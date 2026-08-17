"""Qt object lifetime diagnostics.

Tracks QObject wrappers registered via track_obj():

- ``QObject.destroyed`` fires -> normal Qt-side deletion, logged at DEBUG;
- the PySide wrapper is collected by the GC WITHOUT a destroyed event ->
  logged at WARNING: either Shiboken silently deleted the native object
  (use-after-free candidate: the native sender died while app/PySide still
  held a pointer, the exact family behind the Qt6Core+0xAF238 crashes), or
  the wrapper died while a parented native object survives.

The banner() call records python / PySide6 / shiboken versions and dev-mode
flags so every crash log is self-describing.

Enabled by default; set HT_DIAGNOSTICS=0 to disable.
"""
import logging
import os
import sys
import weakref

from PySide6.QtCore import QObject

log = logging.getLogger("diag")

_ENABLED = os.environ.get("HT_DIAGNOSTICS", "1") != "0"
_TRACKED_IDS: set[int] = set()


def track_obj(obj, tag: str = ""):
    """Watch obj (QObject) for wrapper collection vs. Qt destroyed event.

    Returns obj unchanged so it can be used as an expression wrapper:
    ``self.x = track_obj(QWidget(), "x")``.
    """
    if not _ENABLED or obj is None or not isinstance(obj, QObject):
        return obj
    try:
        if id(obj) in _TRACKED_IDS:
            return obj
        _TRACKED_IDS.add(id(obj))
        cls = type(obj).__name__
        try:
            name = obj.objectName() or ""
        except Exception:
            name = ""
        state = {"destroyed": False}

        def _on_destroyed(*_a, _cls=cls, _tag=tag, _name=name):
            state["destroyed"] = True
            log.debug("Qt destroyed: %s [%s] name=%r", _cls, _tag, _name)

        def _on_collect(_ref, _cls=cls, _tag=tag, _name=name):
            if state["destroyed"]:
                log.debug("wrapper collected after Qt destroyed: %s [%s] name=%r", _cls, _tag, _name)
            else:
                log.warning(
                    "WRAPPER COLLECTED WITHOUT Qt destroyed (use-after-free candidate): "
                    "%s [%s] name=%r", _cls, _tag, _name
                )

        try:
            obj.destroyed.connect(_on_destroyed)
        except RuntimeError:
            pass
        weakref.ref(obj, _on_collect)
    except Exception as e:
        log.debug("track_obj(%r) failed: %s", obj, e)
    return obj


def init():
    """Enable diagnostics for the rest of the session; logs the banner."""
    if not _ENABLED:
        log.info("diag disabled (HT_DIAGNOSTICS=0)")
        return False
    try:
        import PySide6
        pyside_ver = getattr(PySide6, "__version__", "?")
    except Exception:
        pyside_ver = "?"
    try:
        import shiboken6 as shiboken
        shiboken_ver = getattr(shiboken, "__version__", "?")
    except Exception:
        shiboken_ver = "?"
    log.info("diag: python=%s (%s) PySide6=%s shiboken6=%s",
             sys.version.split()[0], sys.executable, pyside_ver, shiboken_ver)
    log.info("diag: PYTHONDEV=%r PYTHONMALLOC=%r HT_DIAGNOSTICS=%r",
             os.environ.get("PYTHONDEV"), os.environ.get("PYTHONMALLOC"),
             os.environ.get("HT_DIAGNOSTICS"))
    log.info("diag: qt env: QT_ENABLE_HIGHDPI_SCALING=%r QT_SCALE_FACTOR_ROUNDING_POLICY=%r",
             os.environ.get("QT_ENABLE_HIGHDPI_SCALING"),
             os.environ.get("QT_SCALE_FACTOR_ROUNDING_POLICY"))
    return True