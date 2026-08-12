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

# 5. Invalid external JSON is normalized before it reaches the worker/UI.
bad_profile = Profile.from_dict({
    "name": 42,
    "axes": {
        "yaw": {"sensitivity": 999, "deadzone": -5, "enabled": "yes", "curve": ["bad", float("inf")]},
        "pitch": {"sensitivity": 4.0, "deadzone": 3.0, "curve": [20, 60]},
    },
    "center_pose": {"yaw": 0, "pitch": 0, "roll": 0, "x": 0, "y": 0, "z": float("nan")},
})
assert bad_profile.name == "Default"
assert bad_profile.axes["yaw"].sensitivity == 6.0
assert bad_profile.axes["yaw"].deadzone == 2.0
assert bad_profile.axes["yaw"].curve is None
assert bad_profile.axes["pitch"].curve == [20.0, 60.0]
assert bad_profile.center_pose is None

bad_settings = AppSettings.from_dict({
    "camera_fov": 180,
    "udp_port": 70000,
    "udp_host": "bad host name",
    "camera_url": "https://",
    "camera_rotation": 45,
    "pose_smoothing": -1,
})
assert bad_settings.camera_fov == 0.0
assert bad_settings.udp_port == 4242
assert bad_settings.udp_host == "127.0.0.1"
assert bad_settings.camera_url == ""
assert bad_settings.camera_rotation == 0
assert bad_settings.pose_smoothing == 0.5
print("5. invalid JSON values normalized safely")

print("ALL CONFIG TESTS PASSED")
