import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from main import parse_cli
from ui.main_window import MainWindow
from config import Profile

app = QApplication([])


def test_parse_cli_empty():
    assert parse_cli([]) == (None, False)
    print("PASS: no args -> (None, False)")


def test_parse_cli_profile():
    assert parse_cli(["--profile", "beamng"]) == ("beamng", False)
    assert parse_cli(["--profile=beamng"]) == ("beamng", False)
    print("PASS: --profile parsed in both forms")


def test_parse_cli_autostart():
    assert parse_cli(["--autostart"]) == (None, True)
    assert parse_cli(["--profile", "beamng", "--autostart"]) == ("beamng", True)
    print("PASS: --autostart parsed, combinations work")


def test_parse_cli_ignores_other_args():
    assert parse_cli(["-debug", "--profile", "p", "extra"]) == ("p", False)
    assert parse_cli(["--profile", "--autostart"]) == (None, True)  # missing value
    print("PASS: unrelated args ignored, missing value tolerated")


def test_select_profile_by_name():
    win = MainWindow(Profile())
    names = [win.combo_profile.itemText(i) for i in range(win.combo_profile.count())]
    assert names, "profile combo should not be empty"
    target = names[0]
    assert win.select_profile_by_name(target) is True
    assert win.combo_profile.currentText() == target
    assert win.select_profile_by_name(target.upper()) is True
    assert win.select_profile_by_name("no_such_profile_xyz") is False
    print("PASS: select_profile_by_name works case-insensitively, unknown -> False")


def test_autostart_starts_tracking():
    win = MainWindow(Profile())
    calls = []
    win.worker.start_tracking = lambda p, s: calls.append((p, s))
    win.autostart(50)
    QTest.qWait(200)
    assert len(calls) == 1, f"expected 1 start call, got {len(calls)}"
    assert win.tracking_active
    # Second scheduled start while already active -> skipped
    win.autostart(50)
    QTest.qWait(200)
    assert len(calls) == 1, "already-tracking skip must not start again"
    # After stop, a new autostart starts tracking again
    win._stop_tracking()
    win.autostart(50)
    QTest.qWait(200)
    assert len(calls) == 2
    assert win.tracking_active
    win._stop_tracking()
    print("PASS: autostart starts tracking once, skipped when already active")


from config import Profile as _P  # noqa: E402, F811

if __name__ == "__main__":
    test_parse_cli_empty()
    test_parse_cli_profile()
    test_parse_cli_autostart()
    test_parse_cli_ignores_other_args()
    test_select_profile_by_name()
    test_autostart_starts_tracking()
    print("AUTOSTART TESTS PASSED")
