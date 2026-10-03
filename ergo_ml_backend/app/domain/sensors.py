"""
Wearable sensor logic — thresholds, personal baseline, live state and warnings.

Every threshold lives here so the live warnings (app) and the final report
use exactly the same rules. All stress measures are relative to the person's
own 60-second baseline, because raw GSR values from a low-cost sensor mean
nothing on their own.

Sensor facts verified on the prototype (see firmware/):
  - GSR raw rises with arousal/stress (skin conductance response).
  - tilt = degrees away from the posture captured at calibration.
"""
from __future__ import annotations

import statistics
import threading
import time
from datetime import timedelta
from typing import Dict, List, Optional

# ── Thresholds ────────────────────────────────────────────────────────────────
CONNECTED_WITHIN_S   = 5      # no reading for longer = wearable disconnected
POSTURE_BAD_DEG      = 20     # leaning more than this from upright = poor posture
POSTURE_WARN_AFTER_S = 10
STRESS_GSR_ELEVATED  = 15     # % rise over baseline
STRESS_GSR_HIGH      = 30
STRESS_BPM_ELEVATED  = 10     # BPM rise over baseline
STRESS_BPM_HIGH      = 20
STRESS_WARN_AFTER_S  = 15
STILL_WARN_AFTER_S   = 120
MAX_READING_GAP_S    = 5      # a longer gap breaks a streak
BASELINE_SECONDS     = 60
BASELINE_SKIP_S      = 2      # ignore readings while posture calibration settles
BASELINE_MIN_READINGS = 10
MIN_VALID_GSR        = 50     # below this the electrodes are not being touched

STRESS_LEVELS = ["calm", "elevated", "high"]


# ── Live device registry (in memory) ──────────────────────────────────────────
class DeviceRegistry:
    """Latest reading per device, and one-shot 'calibrate posture' requests."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Dict[str, tuple] = {}     # device_id -> (reading, monotonic time)
        self._calibrate: set = set()

    def update(self, device_id: str, reading: dict) -> None:
        with self._lock:
            self._latest[device_id] = (reading, time.monotonic())

    def latest(self, device_id: str) -> tuple[Optional[dict], Optional[float]]:
        with self._lock:
            item = self._latest.get(device_id)
        if not item:
            return None, None
        return item[0], round(time.monotonic() - item[1], 1)

    def devices(self) -> List[tuple[str, float]]:
        now = time.monotonic()
        with self._lock:
            return [(d, round(now - t, 1)) for d, (_, t) in self._latest.items()]

    def request_calibrate(self, device_id: str) -> None:
        with self._lock:
            self._calibrate.add(device_id)

    def pop_calibrate(self, device_id: str) -> bool:
        with self._lock:
            if device_id in self._calibrate:
                self._calibrate.discard(device_id)
                return True
            return False


registry = DeviceRegistry()


# ── Baseline ──────────────────────────────────────────────────────────────────
def compute_baseline(readings: List[dict]) -> dict:
    """
    Personal 'normal' from the relaxed baseline period.
    readings: dicts in time order, already limited to the baseline window.
    """
    pulse = [r["bpm_avg"] for r in readings if r["finger"] and r["bpm_avg"] and r["bpm_avg"] > 0]
    gsr   = [r["gsr_raw"] for r in readings if r["gsr_contact"] and r["gsr_raw"] >= MIN_VALID_GSR]
    tilt  = [r["tilt"] for r in readings if r["tilt"] is not None]

    issues: List[str] = []
    if len(pulse) < BASELINE_MIN_READINGS:
        issues.append("Heart rate not captured well - rest a fingertip gently on the pulse sensor.")
    if len(gsr) < BASELINE_MIN_READINGS:
        issues.append("Stress (GSR) not captured well - keep both fingers on the GSR electrodes.")

    return {
        "bpm":            round(statistics.median(pulse), 1) if pulse else None,
        "gsr":            round(statistics.median(gsr), 1) if gsr else None,
        "tilt":           round(statistics.median(tilt), 1) if tilt else 0.0,
        "readings":       len(readings),
        "pulse_readings": len(pulse),
        "gsr_readings":   len(gsr),
        "ok":             not issues,
        "issues":         issues,
    }


# ── Per-reading interpretation ────────────────────────────────────────────────
def _level(value: Optional[float], elevated: float, high: float) -> Optional[int]:
    if value is None:
        return None
    return 2 if value >= high else 1 if value >= elevated else 0


def derive(r: dict, baseline: Optional[dict]) -> dict:
    """Values relative to the person's baseline, plus posture/stress/still flags."""
    base_bpm = (baseline or {}).get("bpm")
    base_gsr = (baseline or {}).get("gsr")
    base_tilt = (baseline or {}).get("tilt") or 0.0

    bpm = r["bpm_avg"] if r["finger"] and r["bpm_avg"] and r["bpm_avg"] > 0 else None
    gsr = r["gsr_raw"] if r["gsr_contact"] and r["gsr_raw"] >= MIN_VALID_GSR else None

    bpm_change = round(bpm - base_bpm, 1) if bpm is not None and base_bpm else None
    gsr_change_pct = round((gsr - base_gsr) / base_gsr * 100, 1) if gsr is not None and base_gsr else None

    levels = [lv for lv in (_level(gsr_change_pct, STRESS_GSR_ELEVATED, STRESS_GSR_HIGH),
                            _level(bpm_change, STRESS_BPM_ELEVATED, STRESS_BPM_HIGH)) if lv is not None]
    stress = STRESS_LEVELS[max(levels)] if levels else None   # None = unknown (no baseline / no contact)

    posture_angle = round(max(0.0, (r["tilt"] or 0.0) - base_tilt), 1) if r.get("mpu_ok", True) else None
    return {
        "bpm":            bpm,
        "bpm_change":     bpm_change,
        "gsr":            gsr,
        "gsr_change_pct": gsr_change_pct,
        "stress_level":   stress,
        "posture_angle":  posture_angle,
        "posture_bad":    posture_angle is not None and posture_angle > POSTURE_BAD_DEG,
        "moving":         bool(r["moving"]),
    }


# ── Streaks: how long each condition has held continuously ────────────────────
def streaks(readings_newest_first: List[dict], baseline: Optional[dict]) -> dict:
    """
    Seconds that posture has been bad / stress high / the person still, counting
    back from the newest reading. A gap longer than MAX_READING_GAP_S ends a streak.
    readings: dicts with 'received_at' (datetime), newest first.
    """
    tests = {
        "posture_bad_s": lambda d: d["posture_bad"],
        "stress_high_s": lambda d: d["stress_level"] == "high",
        "still_s":       lambda d: not d["moving"],
    }
    out = {}
    for name, test in tests.items():
        start = end = None
        prev_time = None
        for r in readings_newest_first:
            t = r["received_at"]
            if prev_time is not None and (prev_time - t).total_seconds() > MAX_READING_GAP_S:
                break
            if not test(derive(r, baseline)):
                break
            end = end or t
            start = t
            prev_time = t
        out[name] = round((end - start).total_seconds() + 1) if start is not None else 0
    return out


# ── Warnings shown on screen (replaces a hardware buzzer) ─────────────────────
def warnings(reading: Optional[dict], age_s: Optional[float], derived: Optional[dict],
             streak: Optional[dict], baseline: Optional[dict]) -> List[dict]:
    """
    Active warnings, most important first. Each: {type, severity, message}.
    severity: 'danger' | 'warning' | 'info'
    """
    if reading is None or age_s is None or age_s > CONNECTED_WITHIN_S:
        return [{"type": "disconnected", "severity": "info",
                 "message": "Wearable disconnected - check the USB cable / device power."}]

    out: List[dict] = []
    if streak and derived:
        if streak["posture_bad_s"] >= POSTURE_WARN_AFTER_S:
            out.append({"type": "posture", "severity": "danger",
                        "message": f"Sit up straight - you are leaning {derived['posture_angle']:.0f} deg "
                                   f"forward for {streak['posture_bad_s']} s."})
        if streak["stress_high_s"] >= STRESS_WARN_AFTER_S:
            out.append({"type": "stress", "severity": "warning",
                        "message": "Stress rising - take 3 slow, deep breaths."})
        if streak["still_s"] >= STILL_WARN_AFTER_S:
            mins = streak["still_s"] // 60
            out.append({"type": "still", "severity": "warning",
                        "message": f"You have been still for {mins} min - roll your shoulders and stretch."})

    if not reading.get("pulse_ok", True):
        out.append({"type": "sensor", "severity": "info", "message": "Pulse sensor error - reconnecting..."})
    elif not reading["finger"]:
        out.append({"type": "sensor", "severity": "info", "message": "Place a fingertip gently on the pulse sensor."})
    if not reading["gsr_contact"]:
        out.append({"type": "sensor", "severity": "info", "message": "Touch both GSR electrodes."})
    if not reading.get("mpu_ok", True):
        out.append({"type": "sensor", "severity": "info", "message": "Motion sensor error - check wiring."})
    if baseline is None:
        out.append({"type": "baseline", "severity": "info",
                    "message": "Baseline not recorded yet - stress levels need a 60 s baseline."})
    return out


# ── Time series for report graphs (web page and PDF) ──────────────────────────
def history_points(readings: List[dict], baseline: Optional[dict],
                   baseline_started_at=None, max_points: int = 600) -> dict:
    """
    readings: time-ordered dicts. Thinned evenly to max_points.
    t is seconds since the first reading; baseline_end_t marks where the
    relaxed baseline ended and the questions began (for shading on graphs).
    """
    total = len(readings)
    if total > max_points:
        step = total / max_points
        readings = [readings[int(i * step)] for i in range(max_points)]
    t0 = readings[0]["received_at"] if readings else None

    points = []
    for r in readings:
        d = derive(r, baseline)
        points.append({
            "t":              round((r["received_at"] - t0).total_seconds(), 1),
            "bpm":            d["bpm"],
            "bpm_change":     d["bpm_change"],
            "gsr":            d["gsr"],
            "gsr_change_pct": d["gsr_change_pct"],
            "stress_level":   d["stress_level"],
            "posture_angle":  d["posture_angle"],
            "posture_bad":    d["posture_bad"],
            "moving":         d["moving"],
        })

    baseline_end_t = None
    if t0 is not None and baseline_started_at is not None:
        end = baseline_started_at + timedelta(seconds=BASELINE_SECONDS)
        baseline_end_t = round((end - t0).total_seconds(), 1)
    return {"total_readings": total, "baseline_end_t": baseline_end_t, "points": points}
