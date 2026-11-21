"""
Wearable scoring — turns the per-second readings recorded while the person
answered the questionnaire into an objective score, fuses it with the
questionnaire score into the ErgoCare Index, and explains where the two disagree.

Every rule is transparent and hand-set (no trained model), so each number in
the report can be explained:

  stress score    = share of time at HIGH stress + half the share at ELEVATED stress
                    (both relative to the person's own 60 s baseline)
  objective score = stress score (only when pulse or skin-response data is available)
  ErgoCare Index  = 60% questionnaire + 40% objective

Wrist orientation and movement are reported as observations only. A wrist-worn
sensor cannot establish torso posture or whole-body stillness.
Readings taken during the baseline are excluded — only the questionnaire period counts.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from app.domain import sensors as S

W_QUESTIONNAIRE, W_OBJECTIVE = 0.6, 0.4
MIN_READINGS = 30            # need at least ~30 s of questionnaire data

BODY_STRESS_HIGH = 40        # stress score at/above this = body clearly stressed
BODY_STRESS_LOW = 20
REPORTED_LOW = 40            # questionnaire score below this = "low" self-report
REPORTED_HIGH = 60

METHOD = ("Body-signal score uses only heart-rate and skin-response changes relative to "
          "your own 60 s baseline: time at HIGH stress plus half the time at ELEVATED stress. "
          "Wrist orientation change and band-arm movement are descriptive observations only; "
          "they do not measure torso posture or whole-body activity. "
          "ErgoCare Index = 60% questionnaire + 40% objective. "
          "Rule-based screening, not a medical diagnosis.")


def _pct(n: int, d: int) -> Optional[float]:
    return round(100 * n / d, 1) if d else None


def _level(score: float) -> str:
    return "High" if score >= 70 else "Moderate" if score >= 40 else "Low"


def _runs(points: List[dict], test: Callable[[dict], bool]) -> List[float]:
    """Durations (s) of every continuous run where test() holds. Gaps break runs."""
    runs, start, prev = [], None, None
    for p in points:
        t = p["received_at"]
        gap = prev is not None and (t - prev).total_seconds() > S.MAX_READING_GAP_S
        if start is not None and (gap or not test(p)):
            runs.append((prev - start).total_seconds() + 1)
            start = None
        if start is None and test(p):
            start = t
        prev = t
    if start is not None:
        runs.append((prev - start).total_seconds() + 1)
    return runs


def score_session(readings: List[dict], baseline: Optional[dict],
                  baseline_started_at: Optional[datetime], questionnaire) -> dict:
    """
    readings: time-ordered dicts (SensorReading.as_dict()).
    questionnaire: RiskScores from the answers.
    Returns the 'wearable' section of the report.
    """
    out: Dict = {"used": True, "available": False, "reason": None, "method": METHOD}

    if not baseline or not baseline_started_at:
        out["reason"] = "No baseline was recorded, so body signals could not be scored."
        return out

    q_start = baseline_started_at + timedelta(seconds=S.BASELINE_SECONDS)
    pts = []
    for r in readings:
        if r["received_at"] >= q_start:
            d = S.derive(r, baseline)
            d["received_at"] = r["received_at"]
            d["mpu_ok"] = r.get("mpu_ok", True)
            pts.append(d)
    if len(pts) < MIN_READINGS:
        out["reason"] = f"Only {len(pts)} s of wearable data during the questions - at least {MIN_READINGS} s needed."
        return out

    duration = (pts[-1]["received_at"] - pts[0]["received_at"]).total_seconds() + 1
    out.update({"available": True, "duration_s": round(duration), "readings": len(pts), "baseline": baseline})

    # Wrist data describes only the band-wearing arm; it is not a posture or
    # sedentary-activity assessment and therefore does not contribute to scores.
    wrist_angles = [
        p["wrist_orientation_change"] for p in pts
        if p["mpu_ok"] and p["wrist_orientation_change"] is not None
    ]
    wrist_motion = {
        "readings": len(wrist_angles),
        "moving_pct": _pct(sum(p["moving"] for p in pts if p["mpu_ok"]), sum(p["mpu_ok"] for p in pts)),
        "avg_orientation_change_deg": round(statistics.mean(wrist_angles), 1) if wrist_angles else None,
        "max_orientation_change_deg": round(max(wrist_angles), 1) if wrist_angles else None,
    }

    # ── Stress (only readings where baseline-relative stress is known) ─────────
    known = [p for p in pts if p["stress_level"] is not None]
    stress = None
    if known:
        high = sum(p["stress_level"] == "high" for p in known)
        elevated = sum(p["stress_level"] == "elevated" for p in known)
        gsr = [p["gsr_change_pct"] for p in known if p["gsr_change_pct"] is not None]
        bpm = [p["bpm"] for p in known if p["bpm"] is not None]
        bpm_ch = [p["bpm_change"] for p in known if p["bpm_change"] is not None]
        stress = {
            "score":             round(min(100.0, _pct(high, len(known)) + 0.5 * _pct(elevated, len(known))), 1),
            "pct_time_high":     _pct(high, len(known)),
            "pct_time_elevated": _pct(elevated, len(known)),
            "avg_gsr_rise_pct":  round(statistics.mean(gsr), 1) if gsr else None,
            "peak_gsr_rise_pct": round(max(gsr), 1) if gsr else None,
            "avg_bpm":           round(statistics.mean(bpm), 1) if bpm else None,
            "avg_bpm_change":    round(statistics.mean(bpm_ch), 1) if bpm_ch else None,
            "peak_bpm_change":   round(max(bpm_ch), 1) if bpm_ch else None,
            "alerts":            sum(1 for d in _runs(pts, lambda p: p["stress_level"] == "high") if d >= S.STRESS_WARN_AFTER_S),
        }

    out["coverage"] = {
        "pulse_pct":   _pct(sum(p["bpm"] is not None for p in pts), len(pts)),
        "gsr_pct":     _pct(sum(p["gsr"] is not None for p in pts), len(pts)),
        "wrist_motion_pct": _pct(len(wrist_angles), len(pts)),
    }
    out.update({"wrist_motion": wrist_motion, "stress": stress})

    # Wrist motion is intentionally not used as a risk score. Without usable
    # pulse or skin-response data there is no body-signal score to combine.
    objective = stress["score"] if stress else None
    out["objective_score"] = objective

    # ── ErgoCare Index ─────────────────────────────────────────────────────────
    if objective is not None:
        q_overall = float(questionnaire.overall_risk)
        index = round(W_QUESTIONNAIRE * q_overall + W_OBJECTIVE * objective, 1)
        out["combined"] = {
            "index":         index,
            "level":         _level(index),
            "questionnaire": round(q_overall, 1),
            "objective":     objective,
            "weights":       {"questionnaire": W_QUESTIONNAIRE, "objective": W_OBJECTIVE},
        }
    else:
        out["combined"] = None
        out["reason"] = (
            "No usable pulse or skin-response data was captured. "
            "Wrist motion is shown as an observation, but no body-signal score was calculated."
        )

    out["insights"] = _insights(questionnaire, stress)
    out["actions"] = _actions(out["insights"], stress)
    return out


# ── Where answers and body signals agree / disagree ───────────────────────────
def _insights(q, stress: Optional[dict]) -> List[dict]:
    items: List[dict] = []
    reported_stress = float(q.workload_stress)
    if stress:
        body = stress["score"]
        time_stressed = round(stress["pct_time_high"] + stress["pct_time_elevated"])
        if body >= BODY_STRESS_HIGH and reported_stress < REPORTED_LOW:
            items.append({"type": "hidden_stress", "severity": "warning", "title": "Hidden stress",
                          "message": f"You reported low workload stress ({reported_stress:.0f}%), but your body showed "
                                     f"stress responses for {time_stressed}% of the session."})
        elif body >= BODY_STRESS_HIGH:
            items.append({"type": "confirmed_stress", "severity": "warning", "title": "Stress confirmed",
                          "message": f"Your answers ({reported_stress:.0f}% workload stress) and your body signals "
                                     f"({time_stressed}% of the session stressed) agree."})
        elif body < BODY_STRESS_LOW and reported_stress >= REPORTED_HIGH:
            items.append({"type": "calm_body", "severity": "info", "title": "Calm during the test",
                          "message": f"You reported high workload stress ({reported_stress:.0f}%), but your body stayed "
                                     f"calm here - your stress may be tied to specific work situations."})

    return items


def _actions(insights: List[dict], stress: Optional[dict]) -> List[str]:
    kinds = {i["type"] for i in insights}
    actions: List[str] = []
    if kinds & {"hidden_stress", "confirmed_stress"}:
        actions.append("Wearable: your body showed stress responses - take a 2-minute slow-breathing break "
                       "(breathe in 4 s, out 6 s) between tasks.")
    return actions
