"""Tuning assistant: records raw vs mapped pose while the user moves their
head, then quantifies gain, inversion, deadzone, jitter, lag and drift per
axis, and proposes concrete profile changes — the same criteria OpenTrack /
Beam Eye Tracker setups are judged by. Sessions can be exported to JSON for
offline analysis."""
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTextEdit, QMessageBox,
)

from i18n import t
from qobject_diag import track_obj

log = logging.getLogger("tuning")

ANGLES = ("yaw", "pitch", "roll")
AXES = ("yaw", "pitch", "roll", "x", "y", "z")
JITTER_WINDOW = 7          # moving-average window for jitter estimation
MAX_LAG_MS = 400           # cross-correlation search window
LAG_THRESHOLD_MS = 90      # above this, smoothing feels laggy
JITTER_THRESHOLD_DEG = 1.2  # rms of high-freq residual -> "jittery"
JITTER_THRESHOLD_MM = 12.0
JITTER_QUIET_SPEED_DEG = 1.0  # max per-frame raw delta counted as "still"
JITTER_QUIET_SPEED_MM = 10.0  # (else intentional motion reads as jitter)
MIN_JITTER_SAMPLES = 8
DEADZONE_MOVING_FRAC = 0.15  # mapped ~0 while clearly moving -> deadzone too big
DRIFT_THRESHOLD_DEG = 5.0    # mean raw angle offset -> recenter / drift
MIN_CONFIDENCE = 0.5         # below this the pipeline holds a stale pose
SPIKE_ANGLE_DEG = 30.0       # impossible between-frame head jump at 60Hz
SPIKE_TRANS_MM = 60.0
GAIN_LOW = 0.7
GAIN_HIGH = 1.5
MIN_RAW_RANGE_DEG = 2.0       # below this a "range" analysis is meaningless
MIN_RAW_RANGE_MM = 20.0
MIN_SAMPLES = 30


class TuningRecorder:
    """Collects (raw, mapped, confidence, t) samples; pure data holder."""

    def __init__(self):
        self.samples: list[dict] = []
        self.recording = False
        self.started_at = 0.0

    def start(self):
        self.samples = []
        self.recording = True
        self.started_at = time.perf_counter()

    def stop(self):
        self.recording = False

    def add(self, raw_pose, mapped_pose):
        if not self.recording:
            return
        self.samples.append({
            "t": time.perf_counter() - self.started_at,
            "raw": {
                "yaw": raw_pose.yaw, "pitch": raw_pose.pitch, "roll": raw_pose.roll,
                "x": raw_pose.x, "y": raw_pose.y, "z": raw_pose.z,
            },
            "mapped": {
                "yaw": mapped_pose.yaw, "pitch": mapped_pose.pitch, "roll": mapped_pose.roll,
                "x": mapped_pose.x, "y": mapped_pose.y, "z": mapped_pose.z,
            },
            "confidence": mapped_pose.confidence,
        })

    @property
    def count(self) -> int:
        return len(self.samples)


def _arr(samples: list[dict], field: str, axis: str) -> np.ndarray:
    return np.array([s[field][axis] for s in samples], dtype=np.float64)


def _p2p(v: np.ndarray) -> float:
    if len(v) < 2:
        return 0.0
    lo, hi = np.percentile(v, [5, 95])
    return float(hi - lo)


def _rms(v: np.ndarray) -> float:
    return float(np.sqrt(np.mean(v ** 2))) if len(v) else 0.0


def _axis_report(samples: list[dict], axis: str) -> dict:
    """Quantify one axis of a recording."""
    raw = _arr(samples, "raw", axis)
    mapped = _arr(samples, "mapped", axis)
    n = len(raw)
    report = {"axis": axis, "raw_range": _p2p(raw), "mapped_range": _p2p(mapped),
              "raw_mean": float(np.mean(raw)), "mapped_mean": float(np.mean(mapped)),
              "gain": None, "inverted": False, "corr": 0.0,
              "deadzone_frac": 0.0, "jitter_rms": 0.0, "lag_ms": 0.0}

    if n < 2:
        return report

    is_angle = axis in ANGLES
    range_thr = MIN_RAW_RANGE_DEG if is_angle else MIN_RAW_RANGE_MM

    # Correlation & inversion
    r, m = raw - raw.mean(), mapped - mapped.mean()
    denom = _rms(r) * _rms(m)
    if denom > 1e-9:
        report["corr"] = float(np.sum(r * m) / (n * denom))
    report["inverted"] = report["corr"] < -0.3

    # Gain over the usable range
    if report["raw_range"] >= range_thr and not report["inverted"] and abs(report["corr"]) > 0.5:
        report["gain"] = report["mapped_range"] / report["raw_range"]

    # Deadzone: mapped ~0 while raw is clearly moving
    moving = np.abs(raw) > (2.0 if is_angle else 15.0)
    if moving.sum() >= 10:
        report["deadzone_frac"] = float(np.mean(np.abs(mapped[moving]) < 0.3))

    # Jitter: rms of high-frequency residual of the mapped signal, evaluated
    # only over near-stationary segments (plus a margin). Intentional head
    # motion has a large smooth residual and would otherwise be misread as
    # tracking jitter, which then over-recommends smoothing.
    if n > JITTER_WINDOW + 2:
        kernel = np.ones(JITTER_WINDOW) / JITTER_WINDOW
        smooth = np.convolve(mapped, kernel, mode="same")
        residual = mapped - smooth
        speed_thr = JITTER_QUIET_SPEED_DEG if is_angle else JITTER_QUIET_SPEED_MM
        d = np.abs(np.diff(raw))
        fast = np.zeros(n)
        fast[1:] += (d >= speed_thr).astype(float)
        fast[:-1] += (d >= speed_thr).astype(float)
        margin = JITTER_WINDOW // 2
        neighbors = np.convolve(fast, np.ones(2 * margin + 1), mode="same")
        quiet = neighbors < 0.5
        if quiet.sum() >= MIN_JITTER_SAMPLES:
            report["jitter_rms"] = _rms(residual[quiet])

    # Lag via cross-correlation (mapped vs raw), capped search window
    lag = 0
    maxlag = max(1, int(MAX_LAG_MS / 1000.0 * n / max(1.0, float(samples[-1]["t"] - samples[0]["t"]))))
    maxlag = min(maxlag, n // 2)
    if n > maxlag * 2 + 2:
        r2, m2 = raw - raw.mean(), mapped - mapped.mean()
        m2 = m2 / (np.linalg.norm(m2) + 1e-12)
        best = -1.0
        for k in range(-maxlag, maxlag + 1):
            rk = r2[max(0, k): n + min(0, k)]
            mk = m2[max(0, -k): n + min(0, -k)]
            if len(rk) == len(mk) and len(rk) > 8:
                c = float(np.dot(rk, mk)) / (np.linalg.norm(rk) + 1e-12)
                if c > best:
                    best, lag = c, k
        dt = (samples[-1]["t"] - samples[0]["t"]) / max(1, n - 1)
        # Peak at a negative shift means the mapped signal lags the raw one
        report["lag_ms"] = max(0.0, -lag * dt * 1000.0)
    return report


def _jump(s, other) -> tuple[float, float]:
    return (max(abs(s["raw"][a] - other["raw"][a]) for a in ANGLES),
            max(abs(s["raw"][a] - other["raw"][a]) for a in ("x", "y", "z")))


def _clean_samples(samples: list[dict]) -> tuple[list[dict], int]:
    """Drop stale low-confidence frames and isolated spike frames, which
    would otherwise poison the range/jitter/drift metrics. A frame is a
    spike only if it jumps beyond physical limits from BOTH neighbours, so
    genuine fast head motion is never harmed."""
    clean: list[dict] = []
    prev_good = None
    dropped = 0
    for i, s in enumerate(samples):
        if s["confidence"] < MIN_CONFIDENCE:
            dropped += 1
            continue
        nxt = samples[i + 1] if i + 1 < len(samples) else None
        if prev_good is not None and nxt is not None:
            a_prev, t_prev = _jump(s, prev_good)
            a_next, t_next = _jump(nxt, s)
            if (a_prev > SPIKE_ANGLE_DEG or t_prev > SPIKE_TRANS_MM) and \
                    (a_next > SPIKE_ANGLE_DEG or t_next > SPIKE_TRANS_MM):
                dropped += 1
                continue
        prev_good = s
        clean.append(s)
    return clean, dropped


def analyze_tuning(samples: list[dict]) -> dict:
    """Full analysis: per-axis reports + human recommendations."""
    samples, dropped = _clean_samples(samples)
    if len(samples) < MIN_SAMPLES:
        return {"ok": False, "count": len(samples), "dropped": dropped,
                "reports": [], "recommendations": [], "changes": {}}
    reports = [_axis_report(samples, a) for a in AXES]
    recommendations: list[str] = []
    changes: dict = {}

    for r in reports:
        axis = r["axis"]
        if r["inverted"]:
            recommendations.append(t("tuning_invert_note").format(axis))
        if r["gain"] is not None:
            if r["gain"] < GAIN_LOW:
                factor = round(1.0 / r["gain"], 2)
                recommendations.append(t("tuning_gain_low").format(axis, f"{r['gain']:.2f}", factor))
                changes.setdefault("axes", {})[axis] = {"sensitivity": factor}
            elif r["gain"] > GAIN_HIGH:
                divisor = round(r["gain"], 2)
                recommendations.append(t("tuning_gain_high").format(axis, f"{r['gain']:.2f}", divisor))
                changes.setdefault("axes", {})[axis] = {"sensitivity": round(1.0 / r["gain"], 2)}
        if r["deadzone_frac"] > DEADZONE_MOVING_FRAC:
            recommendations.append(t("tuning_deadzone").format(axis, f"{r['deadzone_frac'] * 100:.0f}"))
        if r["lag_ms"] > LAG_THRESHOLD_MS:
            recommendations.append(t("tuning_lag").format(axis, f"{r['lag_ms']:.0f}"))
            changes.setdefault("pose_smoothing", "decrease")
        if r["jitter_rms"] > (JITTER_THRESHOLD_DEG if axis in ANGLES else JITTER_THRESHOLD_MM):
            recommendations.append(t("tuning_jitter").format(axis, f"{r['jitter_rms']:.2f}"))
            changes.setdefault("pose_smoothing", "increase")
        if axis in ANGLES and abs(r["raw_mean"]) > DRIFT_THRESHOLD_DEG:
            recommendations.append(t("tuning_drift").format(axis, f"{r['raw_mean']:+.1f} deg"))
            changes.setdefault("recenter", True)

    if not recommendations:
        recommendations.append(t("tuning_ok"))
    return {"ok": True, "count": len(samples), "dropped": dropped,
            "reports": reports, "recommendations": recommendations,
            "changes": changes}


CALIB_DIRS = ("left", "right", "up", "down")
CALIB_DIR_AXIS = {"left": "yaw", "right": "yaw", "up": "pitch", "down": "pitch"}


def analyze_calibration(segments: list[dict]) -> dict:
    """Directional calibration analysis.

    segments: list of {"dir": "left"|"right"|"up"|"down", "samples": [sample dicts]}
    recorded with the same sample shape as TuningRecorder produces.

    Returns the same shape as analyze_tuning(): ok / count / dropped / reports /
    recommendations / changes, so the wizard can reuse the standard apply path
    (_apply_tuning_changes) unchanged. yaw comes from the left/right segments,
    pitch from up/down. Deadzone/curve are never changed; roll and translation
    axes are reported only.
    """
    reports = []
    for seg in segments:
        direction = seg.get("dir", "left")
        axis = CALIB_DIR_AXIS.get(direction, "yaw")
        clean, dropped = _clean_samples(seg.get("samples") or [])
        report = _axis_report(clean, axis)
        report.update({"dir": direction, "count": len(clean), "dropped": dropped})
        reports.append(report)

    total = sum(r["count"] for r in reports)
    total_dropped = sum(r["dropped"] for r in reports)
    if total < MIN_SAMPLES or any(r["count"] < MIN_SAMPLES for r in reports):
        return {"ok": False, "count": total, "dropped": total_dropped,
                "reports": reports,
                "recommendations": [t("calib_insufficient")],
                "changes": {}}

    recommendations: list[str] = []
    changes: dict = {}

    def _report_axis(axis):
        rs = [r for r in reports if r["axis"] == axis]
        valid_gain = [r for r in rs if r["gain"] is not None]
        if valid_gain:
            weight = sum(r["raw_range"] for r in valid_gain) or 1.0
            gain = sum(r["gain"] * r["raw_range"] for r in valid_gain) / weight
            if gain < GAIN_LOW:
                factor = round(1.0 / gain, 2)
                recommendations.append(t("tuning_gain_low").format(axis, f"{gain:.2f}", factor))
                changes.setdefault("axes", {})[axis] = {"sensitivity": factor}
            elif gain > GAIN_HIGH:
                divisor = round(gain, 2)
                recommendations.append(t("tuning_gain_high").format(axis, f"{gain:.2f}", divisor))
                changes.setdefault("axes", {})[axis] = {"sensitivity": round(1.0 / gain, 2)}
        if all(r["inverted"] for r in rs):
            recommendations.append(t("tuning_invert_note").format(axis))
        if any(r["deadzone_frac"] > DEADZONE_MOVING_FRAC for r in rs):
            worst = max(r["deadzone_frac"] for r in rs)
            recommendations.append(t("tuning_deadzone").format(axis, f"{worst * 100:.0f}"))
        if any(r["lag_ms"] > LAG_THRESHOLD_MS for r in rs):
            worst = max(r["lag_ms"] for r in rs)
            recommendations.append(t("tuning_lag").format(axis, f"{worst:.0f}"))
            changes.setdefault("pose_smoothing", "decrease")
        if any(r["jitter_rms"] > (JITTER_THRESHOLD_DEG if axis in ANGLES else JITTER_THRESHOLD_MM) for r in rs):
            worst = max(r["jitter_rms"] for r in rs)
            recommendations.append(t("tuning_jitter").format(axis, f"{worst:.2f}"))
            changes.setdefault("pose_smoothing", "increase")
        if any(abs(r["raw_mean"]) > DRIFT_THRESHOLD_DEG for r in rs):
            worst = max(abs(r["raw_mean"]) for r in rs)
            recommendations.append(t("tuning_drift").format(axis, f"{worst:+.1f} deg"))
            changes.setdefault("recenter", True)

    for axis in ("yaw", "pitch"):
        _report_axis(axis)

    if not recommendations:
        recommendations.append(t("tuning_ok"))
    return {"ok": True, "count": total, "dropped": total_dropped,
            "reports": reports, "recommendations": recommendations,
            "changes": changes}


def export_tuning(samples: list[dict], profile_name: str, analysis: dict | None,
                  out_dir: Path | None = None) -> Path:
    """Write a session to logs/tuning_<timestamp>.json for offline analysis."""
    out_dir = out_dir or (Path(__file__).parent.parent / "logs")
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"tuning_{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    payload = {
        "exported": datetime.now().isoformat(),
        "profile": profile_name,
        "analysis": analysis,
        "samples": samples,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("Tuning session exported: %s", path)
    return path


class TuningDialog(QDialog):
    """Record -> analyze -> apply workflow."""

    def __init__(self, recorder: TuningRecorder, apply_changes, recenter, parent=None):
        super().__init__(parent)
        self._recorder = recorder
        self._apply_changes = apply_changes
        self._recenter = recenter
        self._analysis: dict | None = None
        self.setWindowTitle(t("tuning_title"))
        self.setMinimumSize(560, 420)

        layout = QVBoxLayout(self)
        hint = QLabel(t("tuning_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.lbl_status = QLabel(t("tuning_idle"))
        layout.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        self.btn_record = QPushButton(t("tuning_record_start"))
        self.btn_record.clicked.connect(self._on_record)
        btn_row.addWidget(self.btn_record)
        self.btn_analyze = QPushButton(t("tuning_analyze"))
        self.btn_analyze.clicked.connect(self._on_analyze)
        self.btn_analyze.setEnabled(False)
        btn_row.addWidget(self.btn_analyze)
        self.btn_apply = QPushButton(t("tuning_apply"))
        self.btn_apply.clicked.connect(self._on_apply)
        self.btn_apply.setEnabled(False)
        btn_row.addWidget(self.btn_apply)
        self.btn_export = QPushButton(t("tuning_export"))
        self.btn_export.clicked.connect(self._on_export)
        self.btn_export.setEnabled(False)
        btn_row.addWidget(self.btn_export)
        layout.addLayout(btn_row)

        self.report = QTextEdit()
        self.report.setReadOnly(True)
        self.report.setFocusPolicy(Qt.NoFocus)
        self.report.setFont(self.report.font())
        layout.addWidget(self.report)

        self._refresh_timer = None

        track_obj(self, "tuning_dialog")
        for w in (hint, self.lbl_status, self.btn_record, self.btn_analyze,
                  self.btn_apply, self.btn_export, self.report):
            track_obj(w, f"tuning_child:{type(w).__name__}")

    def _on_record(self):
        r = self._recorder
        if r.recording:
            r.stop()
            self.btn_record.setText(t("tuning_record_start"))
            self.lbl_status.setText(t("tuning_recorded").format(r.count))
            self.btn_analyze.setEnabled(r.count >= MIN_SAMPLES)
        else:
            r.start()
            self.btn_record.setText(t("tuning_record_stop"))
            self.lbl_status.setText(t("tuning_recording"))
            self.btn_analyze.setEnabled(False)
            self.btn_apply.setEnabled(False)
            self.btn_export.setEnabled(False)
            self.report.clear()

    def _on_analyze(self):
        self._analysis = analyze_tuning(self._recorder.samples)
        if not self._analysis["ok"]:
            self.lbl_status.setText(t("tuning_too_few").format(self._analysis["count"]))
            return
        lines = [t("tuning_count").format(self._analysis["count"])]
        if self._analysis.get("dropped"):
            lines.append(t("tuning_filtered").format(self._analysis["dropped"]))
        for r in self._analysis["reports"]:
            lines.append(
                f"{r['axis']}: raw {r['raw_range']:6.1f} -> sent {r['mapped_range']:6.1f}"
                f"  gain {('%.2f' % r['gain']) if r['gain'] is not None else '  -- '}"
                f"  corr {r['corr']:+.2f}  deadzone {r['deadzone_frac'] * 100:4.0f}%"
                f"  jitter {r['jitter_rms']:5.2f}  lag {r['lag_ms']:5.0f}ms"
            )
        lines.append("")
        lines.append("== " + t("tuning_recommendations") + " ==")
        lines.extend(self._analysis["recommendations"])
        self.report.setPlainText("\n".join(lines))
        self.btn_apply.setEnabled(bool(self._analysis["changes"]))
        self.btn_export.setEnabled(True)

    def _on_apply(self):
        if self._analysis and self._analysis["changes"]:
            self._apply_changes(self._analysis["changes"])
            self.lbl_status.setText(t("tuning_applied"))
            if self._analysis["changes"].get("recenter"):
                self._recenter()
            self.btn_apply.setEnabled(False)

    def _on_export(self):
        if not self._recorder.samples:
            return
        path = export_tuning(self._recorder.samples, "", self._analysis)
        self.lbl_status.setText(t("tuning_exported").format(path))
