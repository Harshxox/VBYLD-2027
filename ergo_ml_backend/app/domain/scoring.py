"""
ErgoCare AI — Scoring Engine v4.0
Integrates the ML engine (ml_engine.py) into the scoring pipeline.

ML techniques active in this file:
  - Fuzzy logic risk mapping        (via ml_engine.fuzzy_classify)
  - Feature importance weights      (via ml_engine.get_weight)
  - Weighted ensemble scoring       (via ml_engine.ensemble_overall)
  - Decision tree classification    (via ml_engine.decision_tree_classify)
  - IQR anomaly detection           (via ml_engine.detect_anomalies)
  - Confidence scoring              (via ml_engine.confidence_score)
"""
from typing import List, Dict, Tuple
from app.domain.questions import QUESTIONS_BY_ID, CATEGORY_LABELS
from app.domain.ml_engine import get_weight, run_ml_pipeline
from app.domain.answer_matcher import match_answer
from app.models.schemas import RiskScores, ReportData


# ─────────────────────────────────────────────────────────────────────────────
# Answer → raw risk value (0–100)
# Uses fuzzy logic for "maybe/somewhat" — not a hard 50, but a membership-
# weighted value based on where "maybe" sits in the risk distribution.
# ─────────────────────────────────────────────────────────────────────────────

def option_risk(question: Dict, answer: str) -> int:
    """Map one answer string to a 0-100 risk integer using fuzzy-aware logic."""
    # Free-form (spoken / typed) answers: find the option they mean first,
    # otherwise they would all score a neutral 50. See answer_matcher.py.
    if answer.strip().lower() not in {o.lower() for o in question.get("options", [])}:
        matched = match_answer(question, answer).option
        if matched:
            answer = matched
    normalized = answer.strip().lower()
    risk_map: Dict[str, int] = question.get("risk_map", {})

    for option, risk in risk_map.items():
        if option.lower() == normalized:
            return risk

    # Fuzzy linguistic values — "maybe" is NOT hard 50;
    # it sits in the moderate membership zone (~45–60)
    if normalized == "yes":    return 100
    if normalized == "maybe":  return 58   # fuzzy moderate zone centroid
    if normalized == "somewhat": return 48
    if normalized == "no":     return 0

    # Numeric pain scale (0–5) — maps linearly to 0–100
    options: List[str] = question.get("options", [])
    is_numeric = all(opt.lstrip("-").isdigit() for opt in options)
    try:
        num = int(normalized)
        if is_numeric:
            max_val = max(int(o) for o in options)
            return round((num / max_val) * 100) if max_val else 0
    except ValueError:
        pass

    # Positional index fallback.
    # CONTRACT: options are listed healthiest-first (see app/domain/questions.py),
    # so index 0 -> risk 0 and the last option -> risk 100.
    # `reverse` is retained only for the rare worst-first question and must not be
    # used to "fix" a list that is already healthiest-first - that inverts it.
    idx = next((i for i, o in enumerate(options) if o.lower() == normalized), -1)
    if idx == -1:
        return 50
    denom = max(len(options) - 1, 1)
    raw = round((idx / denom) * 100)
    return (100 - raw) if question.get("reverse") else raw


# ─────────────────────────────────────────────────────────────────────────────
# Main scoring function
# ─────────────────────────────────────────────────────────────────────────────

def calculate_scores(answers: List[Dict]) -> Tuple[RiskScores, Dict]:
    """
    1. Maps each answer to a risk value.
    2. Applies feature importance weights (ML — mirrors Random Forest weights).
    3. Runs the ML pipeline (ensemble + decision tree + fuzzy + anomaly).
    4. Returns (RiskScores, ml_dict).
    """
    # Enrich answers with risk values, weights, and category
    enriched: List[Dict] = []
    for answer in answers:
        q = QUESTIONS_BY_ID.get(answer["question_id"])
        if not q:
            continue
        value = answer.get("typed_answer") or answer.get("transcript") or ""
        if not value:
            continue
        risk   = option_risk(q, value)
        weight = get_weight(answer["question_id"])
        enriched.append({
            "question_id":   answer["question_id"],
            "question_text": q["text"],
            "category":      q["category"],
            "risk":          risk,
            "weight":        weight,
        })

    if not enriched:
        # Still return the (scores, ml) pair the signature promises - callers
        # unpack two values and would break on a bare RiskScores here.
        return RiskScores(
            posture_risk=0, eye_strain=0, workload_stress=0,
            musculoskeletal_risk=0, recovery_risk=0, overall_risk=0,
        ), {}

    # Run full ML pipeline
    ml = run_ml_pipeline(enriched, {})

    scores = ml["category_scores"]
    return RiskScores(
        posture_risk         = scores["posture_risk"],
        eye_strain           = scores["eye_strain"],
        workload_stress      = scores["workload_stress"],
        musculoskeletal_risk = scores["musculoskeletal_risk"],
        recovery_risk        = scores["recovery_risk"],
        overall_risk         = ml["overall_risk"],
    ), ml


# ─────────────────────────────────────────────────────────────────────────────
# Advice library (unchanged from v3)
# ─────────────────────────────────────────────────────────────────────────────

_ADVICE: Dict[str, Dict] = {
    "pain": {
        "critical": ["⚠ CRITICAL: Seek occupational health or physiotherapy referral this week.",
                     "Implement strict 30-minute seated limits with mandatory stand-and-stretch breaks.",
                     "Document pain locations and triggers daily; share log with a clinician."],
        "high": ["Schedule a physiotherapy or occupational health consultation as a priority.",
                 "Set a hard stop at 45-minute seated intervals and stand up to stretch.",
                 "Consider a lumbar support cushion and ergonomic wrist rest immediately."],
        "moderate": ["Add two 5-minute stretch blocks per day focused on neck, shoulders, and lower back.",
                     "Check that your chair height lets your feet rest flat on the floor."],
        "low": ["Your pain levels are low — keep your current movement habits."],
    },
    "posture": {
        "critical": ["Your workstation is causing measurable harm — a full ergonomic audit is needed.",
                     "Raise your screen to exact eye level using a monitor arm and external keyboard."],
        "high": ["Raise your screen to eye level; use a laptop stand with an external keyboard.",
                 "Review your chair settings: lumbar support at the small of your back.",
                 "Place keyboard so elbows stay at 90° without reaching."],
        "moderate": ["Consider a monitor riser or document holder to reduce neck flexion.",
                     "Set a posture reminder every 30 minutes using your phone or a browser extension."],
        "low": ["Your workstation setup scores well — keep adjusting proactively."],
    },
    "eyes": {
        "critical": ["High eye strain + headaches = clinically significant visual fatigue. See an optometrist.",
                     "Apply 20-20-20 every 20 minutes: look 20 feet away for 20 seconds."],
        "high": ["Apply the 20-20-20 rule: every 20 minutes, look 20 feet away for 20 seconds.",
                 "Reduce blue-light exposure an hour before sleep; enable night mode on all screens."],
        "moderate": ["Increase font size slightly to reduce strain during long reading sessions.",
                     "Blink consciously when reading on-screen — dry eyes amplify fatigue."],
        "low": ["Eye strain is within healthy range. Maintain your current screen-time boundaries."],
    },
    "workload": {
        "critical": ["Workload is at a critical level — this is unsustainable.",
                     "Block protected break windows in your calendar as non-negotiable events.",
                     "Escalate top two workload sources to your manager or client today."],
        "high": ["Block protected break windows in your calendar as non-negotiable.",
                 "Identify the top two workload sources and raise with your manager.",
                 "Use 25-5 or 50-10 rhythm — your data shows continuous overrun."],
        "moderate": ["Try time-boxing tasks so work sessions have a clear end point.",
                     "Eat away from your desk at least three times a week."],
        "low": ["Workload balance looks healthy. Keep boundary habits in place."],
    },
    "recovery": {
        "critical": ["Recovery is critically low — chronic fatigue accelerates all physical risks.",
                     "Establish a consistent sleep window and hold it on weekends too.",
                     "Track hydration — aim for at least 1.5 litres during work hours."],
        "high": ["Establish a consistent sleep window — irregular sleep is the top recovery disruptor.",
                 "Reduce work-related screen use in the hour before bed.",
                 "Track hydration: aim for 1.5–2 litres during work hours."],
        "moderate": ["10 minutes of non-work activity (walk, breathwork) after the workday aids recovery.",
                     "Limit commute-time screen use to allow passive recovery."],
        "low": ["Recovery capacity is good. Maintain sleep consistency even on weekends."],
    },
    "movement": {
        "critical": ["Sedentary pattern is severe — schedule three 10-minute movement blocks now."],
        "high": ["Schedule three 10-minute movement blocks through the day — set calendar alerts.",
                 "Standing for phone calls or walking for 1-on-1 meetings adds up significantly."],
        "moderate": ["Aim to break seated posture every 45–60 minutes with a brief walk or stretch."],
        "low": ["Good movement variety detected. Keep rotating between postures."],
    },
}

_POSITIVES: Dict[str, Dict] = {
    "pain":     {"low": "Low body discomfort — pain management habits are working.",
                 "moderate": "No severe pain signals; catching this at moderate stage is valuable."},
    "posture":  {"low": "Workstation setup appears ergonomically sound.",
                 "moderate": "Posture awareness detected — building on that is straightforward."},
    "eyes":     {"low": "Healthy eye strain levels — screen habits are balanced."},
    "workload": {"low": "Work–life boundary management is healthy.",
                 "moderate": "Workload is manageable with small adjustments."},
    "recovery": {"low": "Strong recovery markers — sleep and hydration habits are solid."},
    "movement": {"low": "Active movement habits detected — keep it up.",           # Bug 7 fix: was missing
                 "moderate": "Some movement breaks taken — increasing frequency will help."},
}


def _tier(score: float) -> str:
    if score >= 85: return "critical"
    if score >= 65: return "high"
    if score >= 38: return "moderate"
    return "low"


# ─────────────────────────────────────────────────────────────────────────────
# Report builder
# ─────────────────────────────────────────────────────────────────────────────

def build_report(scores: RiskScores, ml: Dict, answers: List[Dict]) -> ReportData:
    """
    Builds the full report including ML outputs:
    - Decision tree tier and clinical action
    - Fuzzy membership breakdown
    - Confidence score
    - Anomaly flags
    - Feature importance (top 5 questions that drove the score)
    """
    from app.domain.ml_engine import (
        fuzzy_classify, detect_anomalies, confidence_score, get_weight
    )
    
    # Re-enrich answers for pain signal extraction
    enriched: List[Dict] = []
    for answer in answers:
        q = QUESTIONS_BY_ID.get(answer["question_id"])
        if not q:
            continue
        value = answer.get("typed_answer") or answer.get("transcript") or ""
        if not value:
            continue
        enriched.append({
            "question_text": q["text"],
            "category":      q["category"],
            "risk":          option_risk(q, value),
        })

    tier           = ml.get("tier", "Low")
    clinical_action = ml.get("clinical_action", "Not enough answers to build a report.")
    fuzzy          = ml.get("fuzzy_memberships", {})
    confidence     = ml.get("confidence", 0.0)
    anomalies      = ml.get("anomalies", [])
    top5           = ml.get("feature_importance_top5", [])
    overall_level  = "High" if scores.overall_risk >= 70 else "Moderate" if scores.overall_risk >= 40 else "Low"

    # Top risk factors
    factors = sorted([
        ("Body discomfort",   scores.musculoskeletal_risk),
        ("Workload pressure", scores.workload_stress),
        ("Posture & movement",scores.posture_risk),
        ("Eye strain",        scores.eye_strain),
        ("Recovery & sleep",  scores.recovery_risk),
    ], key=lambda x: x[1], reverse=True)
    top_factors = [f"{n}: {v:.0f}%" for n, v in factors[:3]]

    # Category breakdown — enriched with ML outputs
    category_breakdown: Dict = {
        "Body discomfort":    scores.musculoskeletal_risk,
        "Posture & movement": scores.posture_risk,
        "Eye strain":         scores.eye_strain,
        "Workload stress":    scores.workload_stress,
        "Recovery & sleep":   scores.recovery_risk,
        "Overall risk":       scores.overall_risk,
        # ML outputs stored here for frontend + PDF to consume
        "__ml": {
            "tier":              tier,
            "clinical_action":   clinical_action,
            "fuzzy":             fuzzy,
            "confidence":        confidence,
            "anomalies":         anomalies,
            "top5_features":     top5,
        }
    }

    # Pain signals (high-weight pain questions that fired)
    pain_signals = [
        q["question_text"] for q in enriched
        if q["category"] == "pain" and q["risk"] >= 70
    ]

    # Build detailed findings
    detailed_findings: List[str] = []
    score_map = {
        "pain":     scores.musculoskeletal_risk,
        "posture":  scores.posture_risk,
        "eyes":     scores.eye_strain,
        "workload": scores.workload_stress,
        "recovery": scores.recovery_risk,
        "movement": scores.posture_risk,
    }

    # ML-derived findings first
    detailed_findings.append(
        f"ML Confidence Score: {confidence:.0f}% — based on answer completeness and consistency."
    )
    detailed_findings.append(
        f"Fuzzy Risk Profile: Low={fuzzy['low']:.2f}, Moderate={fuzzy['moderate']:.2f}, "
        f"High={fuzzy['high']:.2f}, Critical={fuzzy['critical']:.2f}"
    )
    if top5:
        top_q = top5[0]
        detailed_findings.append(
            f"Highest-influence question: Q{top_q['question_id']} — "
            f"'{top_q['question_text'][:60]}…' (risk {top_q['risk']}%, weight {top_q['weight']}×)"
        )
    if anomalies:
        for anom in anomalies:
            detailed_findings.append(f"⚠ Anomaly detected: {anom}")
    if pain_signals:
        detailed_findings.append(f"Priority pain signals: {'; '.join(pain_signals[:2])}")

    # Category-level findings
    for cat in ["pain", "posture", "eyes", "workload", "recovery", "movement"]:
        lv = _tier(score_map.get(cat, 0))
        detailed_findings.extend(_ADVICE.get(cat, {}).get(lv, []))

    # Positive habits
    positive_habits: List[str] = []
    for cat in ["pain", "posture", "eyes", "workload", "recovery", "movement"]:
        lv = _tier(score_map.get(cat, 0))
        pos = _POSITIVES.get(cat, {}).get(lv if lv in ("low", "moderate") else None)
        if pos:
            positive_habits.append(pos)

    # Action plan
    action_plan: List[str] = [
        clinical_action,  # ML decision tree action — most important
        "Use a 25-5 or 50-10 work rhythm and log breaks as part of your daily routine.",
        "Raise your screen to eye level and use an external keyboard/mouse for long sessions.",
        "Add two daily micro-stretch blocks: neck, shoulders, lower back, and wrists.",
        "Apply 20-20-20 eye rule every 20 minutes during screen work.",
    ]
    if pain_signals:
        action_plan.insert(1, f"Address priority pain: {'; '.join(pain_signals[:2])}.")
    if scores.recovery_risk >= 55:
        action_plan.append("Establish a consistent sleep window — protect it on weekends.")
    if scores.musculoskeletal_risk >= 55:
        action_plan.append("Consider occupational health consultation if pain persists beyond 2 weeks.")

    return ReportData(
        level=overall_level,
        top_factors=top_factors,
        action_plan=action_plan,
        category_breakdown=category_breakdown,
        detailed_findings=detailed_findings,
        positive_habits=positive_habits,
    )
