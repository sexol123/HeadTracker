import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import AppSettings, Profile, AxisConfig, save_profile, load_profile, _atomic_write_json

tmp = tempfile.mkdtemp()

# 1. save/load profile roundtrip via temp path (real profiles/ untouched)
p = Profile(name="Test")
p.axes["yaw"] = AxisConfig(sensitivity=7.0, deadzone=1.0, inverted=True)
p.axes["z"].enabled = False
path = os.path.join(tmp, "p.json")
save_profile(p, path)
p2 = load_profile(path)
assert p2.name == "Test", p2.name
assert p2.axes["yaw"].sensitivity == 7.0 and p2.axes["yaw"].inverted is True
assert p2.axes["z"].enabled is False
print("1. profile save/load roundtrip OK")

# 2. atomic write leaves no .tmp leftovers
assert not os.path.exists(path + ".tmp"), "tmp file left behind"
print("2. atomic write, no leftover .tmp OK")

# 3. _atomic_write_json overwrites existing content atomically
_a = os.path.join(tmp, "a.json")
_atomic_write_json(_a, {"n": 1})
_atomic_write_json(_a, {"n": 2})
assert os.path.exists(_a) and not os.path.exists(_a + ".tmp")
assert load_profile(_a).name == "Default", "missing axes defaults to Default profile"
print("3. _atomic_write_json overwrite OK")

# 4. AppSettings roundtrip via to_dict/from_dict
s = AppSettings()
s.mouse_speed = 99.0
s.cam_offset_x = -12.5
s2 = AppSettings.from_dict(s.to_dict())
assert s2.mouse_speed == 99.0 and s2.cam_offset_x == -12.5
assert isinstance(s2.first_run, bool)
print("4. AppSettings roundtrip OK")

print("ALL CONFIG TESTS PASSED")
