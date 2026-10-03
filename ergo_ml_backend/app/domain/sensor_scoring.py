"""
Wearable scoring — turns the per-second readings recorded while the person
answered the questionnaire into an objective score, fuses it with the
questionnaire score into the ErgoCare Index, and explains where the two disagree.

Every rule is transparent and hand-set (no trained model), so each number in
the report can be explained:

  posture score   = 70% x share of time leaning > 20 deg + 30% x average lean (30 deg = 100)
  stress score    = share of time at HIGH stress + half the share at ELEVATED stress
                    (both relative to the person's own 60 s baseline)
  stillness score = longest period without moving (20 min = 100)
  objective score = 50% posture + 40% stress + 10% stillness   (re-weighted if a signal is missing)
  ErgoCare Index  = 60% questionnaire + 40% objective

Readings taken during the baseline are excluded — only the questionnaire period counts.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from app.domain import sensors as S

W_POSTURE, W_STRESS, W_STILL = 0.5, 0.4, 0.1
W_QUESTIONNAIRE, W_OBJECTIVE = 0.6, 0.4
MIN_READINGS = 30            # need at least ~30 s of questionnaire data
LEAN_FULL_DEG = 30           # average lean that counts as 100
STILL_FULL_S = 1200          # 20 min without moving counts as 100

BODY_STRESS_HIGH = 40        # stress score at/above this = body clearly stressed
BODY_STRESS_LOW = 20
REPORTED_LOW = 40            # questionnaire score below this = "low" self-report
REPORTED_HIGH = 60
SLOUCH_TIME_HIGH = 30        # % of time leaning > 20 deg that counts as poor posture

METHOD = ("Objective score = 50% posture (time leaning > 20 deg and average lean) + "
          "40% stress (time with skin response or heart rate above your own baseline) + "
          "10% stillness (longest time without moving). "
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


def _rula_style(angle: float) -> tuple[int, str]:
    """
    RULA-inspired trunk/upper-back flexion band from the typical lean angle.
    (RULA proper needs an observer; this uses the measured angle only.)
    """
    if angle <= 10:
        return 1, "Upright (0-10 deg)"
    if angle <= 20:
        return 2, "Mild lean (10-20 deg)"
    if angle <= 60:
        return 3, "Moderate flexion (20-60 deg)"
    return 4, "Severe flexion (> 60 deg)"


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

    # ── Posture ────────────────────────────────────────────────────────────────
    angles = [p["posture_angle"] for p in pts if p["mpu_ok"] and p["posture_angle"] is not None]
    posture = None
    if angles:
        pct_bad = _pct(sum(a > S.POSTURE_BAD_DEG for a in angles), len(angles))
        avg = statistics.mean(angles)
        rula, rula_label = _rula_style(statistics.median(angles))
        score = 0.7 * pct_bad + 0.3 * min(100.0, avg / LEAN_FULL_DEG * 100)
        posture = {
            "score":        round(score, 1),
            "pct_time_bad": pct_bad,
            "avg_angle":    round(avg, 1),
            "p90_angle":    round(sorted(angles)[int(0.9 * (len(angles) - 1))], 1),
            "max_angle":    round(max(angles), 1),
            "rula_style_score": rula,
            "rula_label":   rula_label,
            "alerts":       sum(1 for d in _runs(pts, lambda p: p["posture_bad"]) if d >= S.POSTURE_WARN_AFTER_S),
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

    # ── Stillness ──────────────────────────────────────────────────────────────
    still_runs = _runs(pts, lambda p: not p["moving"])
    longest = max(still_runs, default=0)
    stillness = {
        "score":           round(min(100.0, longest / STILL_FULL_S * 100), 1),
        "longest_still_s": round(longest),
        "pct_time_still":  _pct(sum(not p["moving"] for p in pts), len(pts)),
        "alerts":          sum(1 for d in still_runs if d >= S.STILL_WARN_AFTER_S),
    }

    out["coverage"] = {
        "pulse_pct":   _pct(sum(p["bpm"] is not None for p in pts), len(pts)),
        "gsr_pct":     _pct(sum(p["gsr"] is not None for p in pts), len(pts)),
        "posture_pct": _pct(len(angles), len(pts)),
    }
    out.update({"posture": posture, "stress": stress, "stillness": stillness})

    # ── Objective score (re-weighted over the signals that exist) ─────────────
    parts = [(W_POSTURE, posture), (W_STRESS, stress), (W_STILL, stillness)]
    parts = [(w, p["score"]) for w, p in parts if p is not None]
    total_w = sum(w for w, _ in parts)
    objective = round(sum(w * s for w, s in parts) / total_w, 1)
    out["objective_score"] = objective

    # ── ErgoCare Index ─────────────────────────────────────────────────────────
    q_overall = float(questionnaire.overall_risk)
    index = round(W_QUESTIONNAIRE * q_overall + W_OBJECTIVE * objective, 1)
    out["combined"] = {
        "index":         index,
        "level":         _level(index),
        "questionnaire": round(q_overall, 1),
        "objective":     objective,
        "weights":       {"questionnaire": W_QUESTIONNAIRE, "objective": W_OBJECTIVE},
    }

    out["insights"] = _insights(questionnaire, posture, stress)
    out["actions"] = _actions(out["insights"], posture, stress, stillness)
    return out


# ── Where answers and body signals agree / disagree ───────────────────────────
def _insights(q, posture: Optional[dict], stress: Optional[dict]) -> List[dict]:
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

    reported_posture = float(q.posture_risk)
    if posture and posture["pct_time_bad"] >= SLOUCH_TIME_HIGH:
        if reported_posture < REPORTED_LOW:
            items.append({"type": "posture_blind_spot", "severity": "warning", "title": "Posture blind spot",
                          "message": f"You rated your posture setup as low risk ({reported_posture:.0f}%), but you leaned "
                                     f"forward more than {S.POSTURE_BAD_DEG} deg for {posture['pct_time_bad']:.0f}% of the time."})
        else:
            items.append({"type": "confirmed_posture", "severity": "warning", "title": "Posture problem confirmed",
                          "message": f"Your answers and the sensor agree: you leaned forward more than "
                                     f"{S.POSTURE_BAD_DEG} deg for {posture['pct_time_bad']:.0f}% of the time."})
    return items


def _actions(insights: List[dict], posture, stress, stillness) -> List[str]:
    kinds = {i["type"] for i in insights}
    actions: List[str] = []
    if posture and posture["pct_time_bad"] >= SLOUCH_TIME_HIGH:
        actions.append(f"Wearable: you leaned forward {posture['pct_time_bad']:.0f}% of the time - raise your screen "
                       f"to eye level and check your posture every 20 minutes.")
    if kinds & {"hidden_stress", "confirmed_stress"}:
        actions.append("Wearable: your body showed stress responses - take a 2-minute slow-breathing break "
                       "(breathe in 4 s, out 6 s) between tasks.")
    if stillness["longest_still_s"] >= S.STILL_WARN_AFTER_S * 5:
        actions.append(f"Wearable: you sat still for {stillness['longest_still_s'] // 60} minutes at a stretch - "
                       f"stand up and move for 2 minutes every 30 minutes.")
    return actions
