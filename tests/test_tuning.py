import math
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtWidgets import QApplication

from ui.tuning_assistant import (
    analyze_tuning, TuningRecorder, export_tuning,
    GAIN_LOW, GAIN_HIGH, LAG_THRESHOLD_MS, JITTER_THRESHOLD_DEG,
)
from pose import Pose

app = QApplication([])


def make_samples(n=400, dt=0.016, phase=0.0, gain=1.0, invert=False, lag_samples=0,
                 jitter=0.0, drift=0.0, deadzone_frac=0.0):
    """Synthetic recording: yaw only gets exercised, other axes stay small."""
    samples = []
    for k in range(n):
        t = k * dt
        raw = 20.0 * math.sin(2 * math.pi * 0.4 * t + phase)
        if deadzone_frac > 0 and k % 10 < deadzone_frac * 10:
            sent = 0.0
        else:
            sent = raw * gain
        if invert:
            sent = -sent
        r = raw + drift
        samples.append({
            "t": t,
            "raw": {"yaw": r, "pitch": 0.0, "roll": 0.0, "x": 0.0, "y": 0.0, "z": 0.0},
            "mapped": {"yaw": sent + (jitter if jitter else 0.0),
                       "pitch": 0.0, "roll": 0.0, "x": 0.0, "y": 0.0, "z": 0.0},
            "confidence": 1.0,
        })
    return samples


def samples_with_lag(n=400, dt=0.016, gain=1.0, lag_samples=4, jitter=0.0):
    samples = []
    hist = []
    for k in range(n):
        t = k * dt
        raw = 20.0 * math.sin(2 * math.pi * 0.4 * t)
        hist.append(raw * gain)
        if len(hist) > lag_samples:
            sent = hist[-lag_samples - 1]
        else:
            sent = 0.0
        samples.append({
            "t": t,
            "raw": {"yaw": raw, "pitch": 0.0, "roll": 0.0, "x": 0.0, "y": 0.0, "z": 0.0},
            "mapped": {"yaw": sent + (jitter if jitter else 0.0),
                       "pitch": 0.0, "roll": 0.0, "x": 0.0, "y": 0.0, "z": 0.0},
            "confidence": 1.0,
        })
    return samples


def test_too_few_samples():
    a = analyze_tuning([])
    assert not a["ok"]
    a = analyze_tuning(make_samples(10))
    assert not a["ok"]


def test_healthy_gain():
    a = analyze_tuning(make_samples(gain=1.0))
    assert a["ok"]
    rep = next(r for r in a["reports"] if r["axis"] == "yaw")
    assert not rep["inverted"]
    assert 0.5 <= rep["gain"] <= 1.5


def test_low_gain_suggests_sensitivity():
    a = analyze_tuning(make_samples(gain=0.4))
    rep = next(r for r in a["reports"] if r["axis"] == "yaw")
    assert rep["gain"] < GAIN_LOW
    assert a["changes"]["axes"]["yaw"]["sensitivity"] > 1.0
    assert any("yaw" in s and "sensitivity" in s for s in a["recommendations"])


def test_inversion_detected():
    a = analyze_tuning(make_samples(gain=1.0, invert=True))
    rep = next(r for r in a["reports"] if r["axis"] == "yaw")
    assert rep["inverted"]
    assert a["changes"]["axes"]["yaw"].get("inverted")


def test_lag_detected():
    a = analyze_tuning(samples_with_lag(lag_samples=6))
    rep = next(r for r in a["reports"] if r["axis"] == "yaw")
    assert rep["lag_ms"] > LAG_THRESHOLD_MS
    assert a["changes"].get("pose_smoothing") == "decrease"


def test_jitter_detected():
    rng = np.random.default_rng(42)
    samples = make_samples(gain=1.0)
    for s in samples:
        s["mapped"]["yaw"] += rng.normal(0.0, 3.0)
    a = analyze_tuning(samples)
    rep = next(r for r in a["reports"] if r["axis"] == "yaw")
    assert rep["jitter_rms"] > JITTER_THRESHOLD_DEG
    assert a["changes"].get("pose_smoothing") == "increase"


def test_drift_detected():
    a = analyze_tuning(make_samples(gain=1.0, drift=8.0))
    rep = next(r for r in a["reports"] if r["axis"] == "yaw")
    assert abs(rep["raw_mean"]) > 5.0
    assert a["changes"].get("recenter")


def test_low_confidence_frames_removed():
    samples = make_samples(n=200)
    for s in samples[100:]:
        s["confidence"] = 0.1
    a = analyze_tuning(samples)
    assert a["count"] == 100
    assert a["dropped"] == 100


def test_spike_frame_removed():
    samples = make_samples(n=200)
    samples[100]["raw"]["yaw"] += 60.0
    samples[100]["mapped"]["yaw"] += 60.0
    a = analyze_tuning(samples)
    assert a["dropped"] == 1
    rep = next(r for r in a["reports"] if r["axis"] == "yaw")
    assert rep["raw_range"] < 50.0


def test_translation_drift_never_recenters():
    samples = make_samples(gain=1.0)
    for s in samples:
        s["raw"]["x"] = 100.0 + 5.0 * math.sin(2 * math.pi * 0.4 * s["t"])
        s["mapped"]["x"] = s["raw"]["x"]
    a = analyze_tuning(samples)
    assert "recenter" not in a["changes"]
    assert not any(r.startswith("x:") for r in a["recommendations"])


def test_recorder():
    rec = TuningRecorder()
    assert not rec.recording
    rec.start()
    assert rec.recording
    rec.add(Pose(yaw=1.0, confidence=1.0), Pose(yaw=0.5, confidence=1.0))
    rec.add(Pose(yaw=2.0, confidence=1.0), Pose(yaw=1.0, confidence=1.0))
    rec.stop()
    rec.add(Pose(yaw=3.0, confidence=1.0), Pose(yaw=1.5, confidence=1.0))
    assert rec.count == 2
    assert rec.samples[0]["raw"]["yaw"] == 1.0
    assert rec.samples[0]["mapped"]["yaw"] == 0.5


def test_export(tmp_path=None):
    import tempfile
    tmp = tmp_path or os.path.join(tempfile.gettempdir(), "ht_tuning_test")
    os.makedirs(tmp, exist_ok=True)
    samples = make_samples(50)
    a = analyze_tuning(samples)
    from pathlib import Path
    path = export_tuning(samples, "Test", a, Path(tmp))
    import json
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert data["profile"] == "Test"
    assert len(data["samples"]) == 50
    os.remove(path)


if __name__ == "__main__":
    test_too_few_samples()
    print("PASS: too-few-samples guard")
    test_healthy_gain()
    print("PASS: healthy gain -> no change")
    test_low_gain_suggests_sensitivity()
    print("PASS: low gain detected, sensitivity suggested")
    test_inversion_detected()
    print("PASS: inversion detected")
    test_lag_detected()
    print("PASS: lag detected, smoothing decrease suggested")
    test_jitter_detected()
    print("PASS: jitter detected, smoothing increase suggested")
    test_drift_detected()
    print("PASS: drift detected, recenter suggested")
    test_low_confidence_frames_removed()
    print("PASS: low-confidence frames dropped")
    test_spike_frame_removed()
    print("PASS: spike frame dropped")
    test_translation_drift_never_recenters()
    print("PASS: x/y/z offset never triggers recenter")
    test_recorder()
    print("PASS: recorder stores raw/mapped only while recording")
    test_export()
    print("PASS: export JSON round-trip")
    print("ALL TUNING TESTS PASSED")