import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication

import worker as worker_mod
from worker import TrackingWorker, TOGGLE_DEBOUNCE
from config import AppSettings

from pynput.keyboard import Key, KeyCode

app = QApplication([])


class FakeOutput:
    def __init__(self):
        self.active = False

    def is_active(self):
        return self.active

    def set_active(self, v):
        self.active = bool(v)


class FakeListener:
    instances = []

    def __init__(self, on_press=None, on_release=None):
        self.on_press = on_press
        self.on_release = on_release
        FakeListener.instances.append(self)

    def start(self):
        pass

    def stop(self):
        pass

    def join(self, timeout=None):
        pass


def make_worker(hotkey, mode):
    w = TrackingWorker()
    w._output = FakeOutput()
    logs = []
    w.output_log.connect(logs.append)
    s = AppSettings()
    s.mouse_hotkey = hotkey
    s.mouse_stop_mode = mode
    orig = worker_mod.KeyboardListener
    worker_mod.KeyboardListener = FakeListener
    try:
        w._start_mouse_hotkey(s)
        listener = FakeListener.instances[-1]
    finally:
        worker_mod.KeyboardListener = orig
    return w, listener, logs


def test_parse_single():
    mods, key = TrackingWorker._parse_hotkey("f8")
    assert mods == frozenset()
    assert key == Key.f8
    print("PASS: parse single key 'f8'")


def test_parse_combo():
    mods, key = TrackingWorker._parse_hotkey("ctrl+f8")
    assert mods == frozenset({"ctrl"})
    assert key == Key.f8
    print("PASS: parse combo 'ctrl+f8'")


def test_parse_multi_combo():
    mods, key = TrackingWorker._parse_hotkey("ctrl+shift+f10")
    assert mods == frozenset({"ctrl", "shift"})
    assert key == Key.f10
    print("PASS: parse multi-combo 'ctrl+shift+f10'")


def test_parse_case_and_spaces():
    mods, key = TrackingWorker._parse_hotkey("  Ctrl + F9 ")
    assert mods == frozenset({"ctrl"})
    assert key == Key.f9
    print("PASS: parse case-insensitive with spaces")


def test_parse_letter_keys():
    mods, key = TrackingWorker._parse_hotkey("x")
    assert mods == frozenset()
    assert key == KeyCode.from_char("x")
    mods, key = TrackingWorker._parse_hotkey("ctrl+x")
    assert mods == frozenset({"ctrl"})
    assert key == KeyCode.from_char("x")
    print("PASS: parse letter keys")


def test_parse_other_keys():
    assert TrackingWorker._parse_hotkey("space")[1] == Key.space
    assert TrackingWorker._parse_hotkey("insert")[1] == Key.insert
    assert TrackingWorker._parse_hotkey("delete")[1] == Key.delete
    mods, key = TrackingWorker._parse_hotkey("ctrl+space")
    assert mods == frozenset({"ctrl"}) and key == Key.space
    print("PASS: parse space/insert/delete")


def test_parse_invalid():
    assert TrackingWorker._parse_hotkey("") is None
    assert TrackingWorker._parse_hotkey(None) is None
    assert TrackingWorker._parse_hotkey("win+f8") is None
    assert TrackingWorker._parse_hotkey("ctrl+") is None
    assert TrackingWorker._parse_hotkey("ctrl++f8") is None
    assert TrackingWorker._parse_hotkey("ctrl+f99") is None
    print("PASS: invalid specs -> None")


def test_modifier_name_variants():
    w = TrackingWorker()
    assert w._modifier_name(Key.ctrl_l) == "ctrl"
    assert w._modifier_name(Key.ctrl_r) == "ctrl"
    assert w._modifier_name(Key.alt_l) == "alt"
    assert w._modifier_name(Key.alt_r) == "alt"
    assert w._modifier_name(Key.shift_l) == "shift"
    assert w._modifier_name(Key.shift_r) == "shift"
    assert w._modifier_name(Key.f8) is None
    assert w._modifier_name(KeyCode.from_char("a")) is None
    print("PASS: modifier name maps left/right/generic variants")


def test_combo_hold():
    w, lis, logs = make_worker("ctrl+f8", "hold")
    lis.on_press(Key.ctrl_l)
    lis.on_press(Key.f8)
    assert w._output.active
    lis.on_press(Key.f9)
    assert w._output.active, "other key must not affect state"
    lis.on_release(Key.f8)
    assert not w._output.active
    assert len(logs) == 2 and "on" in logs[0] and "off" in logs[1]
    print("PASS: combo hold on/off (left ctrl)")


def test_combo_requires_exact_modifiers():
    w, lis, _ = make_worker("ctrl+f8", "hold")
    lis.on_press(Key.alt_l)
    lis.on_press(Key.f8)
    assert not w._output.active, "wrong modifier must not trigger"
    lis.on_press(Key.shift_l)
    lis.on_press(Key.f8)
    assert not w._output.active, "extra modifier must not trigger"
    lis.on_release(Key.alt_l)
    lis.on_release(Key.shift_l)
    lis.on_press(Key.ctrl_r)
    lis.on_press(Key.f8)
    assert w._output.active, "right ctrl variant must trigger"
    print("PASS: exact modifier matching, right-ctrl variant works")


def test_combo_toggle():
    w, lis, logs = make_worker("ctrl+f8", "toggle")
    lis.on_press(Key.ctrl_l)
    lis.on_press(Key.f8)
    assert w._output.active
    lis.on_press(Key.f8)
    assert w._output.active, "second press within debounce must not flip"
    time.sleep(TOGGLE_DEBOUNCE + 0.05)
    lis.on_press(Key.f8)
    assert not w._output.active
    print("PASS: combo toggle with debounce")


def test_single_key_still_works():
    w, lis, logs = make_worker("f8", "hold")
    lis.on_press(Key.f8)
    assert w._output.active
    lis.on_release(Key.f8)
    assert not w._output.active
    print("PASS: single key regression")


def test_single_key_ignored_with_modifier():
    w, lis, _ = make_worker("f8", "hold")
    lis.on_press(Key.ctrl_l)
    lis.on_press(Key.f8)
    assert not w._output.active, "ctrl+f8 must not trigger plain f8 hotkey"
    print("PASS: plain hotkey ignores key pressed with modifier")


if __name__ == "__main__":
    test_parse_single()
    test_parse_combo()
    test_parse_multi_combo()
    test_parse_case_and_spaces()
    test_parse_letter_keys()
    test_parse_other_keys()
    test_parse_invalid()
    test_modifier_name_variants()
    test_combo_hold()
    test_combo_requires_exact_modifiers()
    test_combo_toggle()
    test_single_key_still_works()
    test_single_key_ignored_with_modifier()
    print("ALL HOTKEY TESTS PASSED")
