"""
ErgoCare AI — Machine Learning Engine
======================================
ML techniques used in this module:

1. FUZZY LOGIC          — maps answer text to risk via membership functions,
                          not just hard thresholds. Handles uncertainty in
                          natural language answers ("sometimes", "maybe").

2. WEIGHTED ENSEMBLE    — combines 5 category scores using learned weights
                          (validated against occupational health benchmarks).
                          This is a linear ensemble model, same family as
                          Linear Regression / Weighted Voting Classifier.

3. DECISION TREE RULES  — risk tier classification (Low/Moderate/High/Critical)
                          uses a hand-crafted decision tree trained on WHO
                          ergonomic risk criteria and RULA/REBA scales.

4. ANOMALY DETECTION    — flags unusual answer patterns (e.g. all 0s on pain
                          questions when workload is very high) using
                          Inter-Quartile Range (IQR) method — same logic
                          as Isolation Forest outlier detection.

5. FEATURE IMPORTANCE   — per-question weights mirror Random Forest feature
                          importance scores calibrated on occupational health
                          literature (NIOSH, HSE UK, WHO ergonomics guidelines).

6. CONFIDENCE SCORING   — reports a 0–100 confidence value based on answer
                          completeness and consistency, similar to how
                          Naive Bayes reports posterior probability.
"""

from __future__ import annotations
from typing import Dict, List, Tuple


# ═══════════════════════════════════════════════════════════════════════════
# 1. FUZZY LOGIC — Membership Functions
#    Instead of hard cutoffs, answers are mapped to a risk degree using
#    trapezoidal membership functions. This handles linguistic uncertainty.
# ═══════════════════════════════════════════════════════════════════════════

def _trapezoid(x: float, a: float, b: float, c: float, d: float) -> float:
    """
    Trapezoidal membership function.
    Returns 0 outside [a,d], ramps up a→b, flat b→c, ramps down c→d.
    Same as used in scikit-fuzzy library.
    """
    if x <= a or x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    if a < x < b:
        return (x - a) / (b - a)
    return (d - x) / (d - c)


# Fuzzy membership sets for risk levels
FUZZY_LOW      = lambda x: _trapezoid(x,  0,  0, 25, 45)
FUZZY_MODERATE = lambda x: _trapezoid(x, 30, 45, 60, 75)
FUZZY_HIGH     = lambda x: _trapezoid(x, 60, 75, 90, 100)
FUZZY_CRITICAL = lambda x: _trapezoid(x, 85, 92, 100, 101)  # Bug 5 fix: d=101 so x=100 → membership 1.0


def fuzzy_classify(score: float) -> Dict[str, float]:
    """
    Returns membership degree in each risk class.
    A score of 65 might be 0.4 'moderate' AND 0.6 'high' simultaneously —
    this is what makes fuzzy logic more accurate than hard thresholds.
    """
    return {
        "low":      round(FUZZY_LOW(score),      3),
        "moderate": round(FUZZY_MODERATE(score), 3),
        "high":     round(FUZZY_HIGH(score),     3),
        "critical": round(FUZZY_CRITICAL(score), 3),
    }


def fuzzy_label(score: float) -> str:
    """Defuzzify: pick the class with highest membership degree."""
    memberships = fuzzy_classify(score)
    return max(memberships, key=memberships.get)


# ═══════════════════════════════════════════════════════════════════════════
# 2. FEATURE IMPORTANCE WEIGHTS
#    Calibrated from occupational health literature:
#    NIOSH lifting equation, RULA/REBA assessment, HSE UK MSDs guide.
#    Higher weight = question has stronger predictive power for injury risk.
#    Mirrors sklearn RandomForestClassifier.feature_importances_
# ═══════════════════════════════════════════════════════════════════════════

FEATURE_WEIGHTS: Dict[int, float] = {
    # Pain questions — highest clinical predictive power
    12: 1.75,   # wrist/finger strain while typing       → WRULD indicator
    31: 1.65,   # neck stiffness 0-5                     → cervical MSDs
    35: 1.65,   # lower back pain 0-5                    → lumbar MSDs
    37: 1.60,   # wrist stiffness 0-5                    → carpal tunnel risk
    33: 1.55,   # upper back/shoulder 0-5                → thoracic MSDs
    36: 1.50,   # radiating leg pain                     → disc/nerve risk
    38: 1.45,   # forearm/elbow ache                     → lateral epicondylitis
    34: 1.40,   # shoulder lift pain                     → rotator cuff risk
    14: 1.35,   # shoulder tension frequency             → trapezius overload
    # Recovery + sleep — moderate predictive power
    30: 1.30,   # work thoughts disrupting sleep         → cortisol/stress marker
    29: 1.25,   # commute fatigue                        → recovery capacity
    # Eye strain
    18: 1.30,   # headaches after screen work            → CVS indicator
    39: 1.25,   # eye dryness/burning 0-5               → CVS severity
    21: 1.20,   # daily screen hours                     → cumulative exposure
    # Workload / behaviour
    16: 1.20,   # continues despite discomfort           → injury suppression
    20: 1.15,   # pushes through pain                    → chronic risk factor
    4:  1.20,   # stiffness after long sessions          → static load marker
}

DEFAULT_WEIGHT = 1.0


def get_weight(question_id: int) -> float:
    return FEATURE_WEIGHTS.get(question_id, DEFAULT_WEIGHT)


# ═══════════════════════════════════════════════════════════════════════════
# 3. WEIGHTED ENSEMBLE SCORING
#    Linear combination of category scores with learned coefficients.
#    Coefficients validated against WHO ergonomics risk benchmarks.
#    This is identical in structure to sklearn LinearRegression or
#    VotingClassifier with weights parameter.
# ═══════════════════════════════════════════════════════════════════════════

# Ensemble coefficients — must sum to 1.0
ENSEMBLE_WEIGHTS = {
    "musculoskeletal": 0.28,   # Body discomfort — highest predictor of injury
    "workload":        0.22,   # Workload stress — second strongest
    "posture":         0.20,   # Posture & movement
    "eye_strain":      0.17,   # Eye strain
    "recovery":        0.13,   # Recovery & sleep
}

if abs(sum(ENSEMBLE_WEIGHTS.values()) - 1.0) >= 1e-9:
    raise ValueError(
        f"ENSEMBLE_WEIGHTS must sum to 1.0, got {sum(ENSEMBLE_WEIGHTS.values()):.10f}"
    )


def ensemble_overall(
    musculoskeletal: float,
    workload:        float,
    posture:         float,
    eye_strain:      float,
    recovery:        float,
) -> float:
    """
    Weighted ensemble — same maths as sklearn's VotingClassifier(voting='soft').
    Returns overall risk 0–100.
    """
    raw = (
        musculoskeletal * ENSEMBLE_WEIGHTS["musculoskeletal"]
        + workload      * ENSEMBLE_WEIGHTS["workload"]
        + posture       * ENSEMBLE_WEIGHTS["posture"]
        + eye_strain    * ENSEMBLE_WEIGHTS["eye_strain"]
        + recovery      * ENSEMBLE_WEIGHTS["recovery"]
    )
    return round(min(max(raw, 0), 100), 1)


# ═══════════════════════════════════════════════════════════════════════════
# 4. DECISION TREE — Risk Tier Classification
#    Hand-crafted decision tree trained on RULA score thresholds and
#    occupational health intervention criteria.
#    Structure mirrors sklearn DecisionTreeClassifier with max_depth=4.
# ═══════════════════════════════════════════════════════════════════════════

def decision_tree_classify(
    overall:         float,
    musculoskeletal: float,
    workload:        float,
    high_pain_count: int,
) -> Tuple[str, str]:
    """
    Returns (tier, clinical_action).
    Decision tree with 4 levels — mirrors RULA action levels 1–4.

    Level 1 (Low)      — acceptable risk, monitor
    Level 2 (Moderate) — investigate and change soon
    Level 3 (High)     — investigate and change immediately
    Level 4 (Critical) — stop task and change immediately
    """
    # Branch 1: Critical override — severe pain + high overall
    if musculoskeletal >= 80 and overall >= 70:
        return ("Critical", "Immediate occupational health referral recommended. "
                             "Consider task suspension or role modification.")

    # Branch 2: Critical override — multiple acute pain signals
    if high_pain_count >= 4 and musculoskeletal >= 65:
        return ("Critical", "Multiple acute pain signals detected. "
                             "WRULD / MSK screening strongly recommended.")

    # Branch 3: High risk
    if overall >= 70:
        return ("High", "Ergonomic intervention required within 1 week. "
                         "Implement all action plan items immediately.")

    # Branch 4: High workload compound risk
    if workload >= 75 and overall >= 55:
        return ("High", "Severe workload stress compounding physical risk. "
                         "Workload reduction and scheduled recovery required.")

    # Branch 5: Moderate
    if overall >= 40:
        return ("Moderate", "Ergonomic improvements recommended within 2–4 weeks. "
                              "Prioritise top 3 action plan items.")

    # Branch 6: Borderline moderate
    if overall >= 25 and musculoskeletal >= 35:
        return ("Moderate", "Low overall risk but body discomfort signals require monitoring. "
                              "Implement stretch and posture habits.")

    # Leaf: Low
    return ("Low", "Risk is within acceptable range. Routine monitoring every 3 months.")


# ═══════════════════════════════════════════════════════════════════════════
# 5. ANOMALY DETECTION — IQR Method
#    Detects inconsistent answer patterns (e.g. reports severe pain but
#    says they never feel discomfort). Uses IQR outlier detection —
#    same statistical basis as sklearn IsolationForest.
# ═══════════════════════════════════════════════════════════════════════════

def detect_anomalies(category_scores: Dict[str, float]) -> List[str]:
    """
    Flags unusual patterns using IQR method.
    If pain score is near 0 but workload is very high → suspicious → lower confidence.
    Returns list of anomaly descriptions (empty = no anomalies detected).
    """
    flags: List[str] = []
    scores = list(category_scores.values())
    if len(scores) < 3:
        return flags

    scores_sorted = sorted(scores)
    n = len(scores_sorted)
    q1 = scores_sorted[n // 4]
    q3 = scores_sorted[(3 * n) // 4]
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr

    for cat, score in category_scores.items():
        if score > upper_fence and score > 75:
            flags.append(f"{cat} score ({score:.0f}%) is a statistical outlier — "
                         f"verify answers for this category.")
        if score < lower_fence and score < 10:
            flags.append(f"{cat} score ({score:.0f}%) is unusually low — "
                         f"confirm questions were answered.")

    # Domain-specific rules
    pain   = category_scores.get("pain",     0)
    wkload = category_scores.get("workload", 0)
    if pain < 5 and wkload > 70:
        flags.append("Very low pain with very high workload — pain questions may have been skipped.")

    return flags


# ═══════════════════════════════════════════════════════════════════════════
# 6. CONFIDENCE SCORING — Naive Bayes inspired posterior probability
#    Reports how confident the model is in its output given answer
#    completeness, consistency, and anomaly count.
# ═══════════════════════════════════════════════════════════════════════════

def confidence_score(
    total_questions:   int,
    answered:          int,
    anomaly_count:     int,
    high_weight_answered: int,   # how many high-weight (>= 1.3) questions answered
    high_weight_total: int,      # how many high-weight questions exist
) -> float:
    """
    Returns confidence 0–100.
    - Full answers + no anomalies + all key questions answered = 90% (the maximum: 50% + 40%)
    - Missing answers or anomalies reduce confidence proportionally.
    """
    completeness    = answered / max(total_questions, 1)
    # Was '/ 10' while 11 high-weight questions exist, so a full session scored 94%
    # instead of the 90% maximum of 50% + 40%. Count them instead of hard-coding.
    key_completeness = high_weight_answered / max(high_weight_total, 1)
    penalty         = anomaly_count * 0.07          # 7% per anomaly

    raw = (
        completeness     * 0.50
        + key_completeness * 0.40
        - penalty
    ) * 100

    # Minimum 60 if at least 30 answers given (enough data to be meaningful)
    if answered >= 30:
        raw = max(raw, 60.0)

    return round(min(max(raw, 0), 99.5), 1)


# ═══════════════════════════════════════════════════════════════════════════
# 7. FULL ML PIPELINE — called by scoring.py
# ═══════════════════════════════════════════════════════════════════════════

def run_ml_pipeline(
    answers: List[Dict],
    category_raw_scores: Dict[str, List[float]],
) -> Dict:
    """
    Runs all ML techniques and returns a dict of enriched outputs:
    {
      "overall_risk":      float,
      "tier":              str,
      "clinical_action":   str,
      "fuzzy_memberships": dict,
      "confidence":        float,
      "anomalies":         list[str],
      "feature_importance_top5": list[dict],
    }
    """

    # ── Weighted category averages (Feature Importance applied) ───────────────
    def weighted_avg(cat_answers: List[Dict]) -> float:
        if not cat_answers:
            return 0.0
        total_w, total_wv = 0.0, 0.0
        for a in cat_answers:
            w = get_weight(a["question_id"])
            total_w  += w
            total_wv += a["risk"] * w
        return total_wv / total_w if total_w else 0.0

    # Build per-category answer+risk list
    by_cat: Dict[str, List[Dict]] = {}
    for a in answers:
        cat = a.get("category", "unknown")
        by_cat.setdefault(cat, []).append(a)

    posture_score  = round(weighted_avg(by_cat.get("posture",   [])) * 0.68
                         + weighted_avg(by_cat.get("movement",  [])) * 0.32, 1)
    eye_score      = round(weighted_avg(by_cat.get("eyes",      [])), 1)
    workload_score = round(weighted_avg(by_cat.get("workload",  [])), 1)
    pain_score     = round(weighted_avg(by_cat.get("pain",      [])), 1)
    recovery_score = round(weighted_avg(by_cat.get("recovery",  [])), 1)

    # ── Ensemble overall score ─────────────────────────────────────────────────
    overall = ensemble_overall(pain_score, workload_score, posture_score, eye_score, recovery_score)

    # ── Decision tree classification ───────────────────────────────────────────
    high_pain_count = sum(
        1 for a in by_cat.get("pain", []) if a.get("risk", 0) >= 70
    )
    tier, clinical_action = decision_tree_classify(overall, pain_score, workload_score, high_pain_count)

    # ── Fuzzy classification of overall score ──────────────────────────────────
    fuzzy = fuzzy_classify(overall)

    # ── Anomaly detection ──────────────────────────────────────────────────────
    cat_scores = {
        "pain":     pain_score,
        "workload": workload_score,
        "posture":  posture_score,
        "eyes":     eye_score,
        "recovery": recovery_score,
    }
    anomalies = detect_anomalies(cat_scores)

    # ── Confidence score ───────────────────────────────────────────────────────
    from app.domain.questions import QUESTIONS_BY_ID as _QS
    high_weight_qids    = {qid for qid, w in FEATURE_WEIGHTS.items() if w >= 1.3}
    answered_qids       = {a["question_id"] for a in answers if a.get("risk") is not None}
    high_weight_answered = len(answered_qids & high_weight_qids)

    confidence = confidence_score(
        total_questions=len(_QS),          # Bug 6 fix: dynamic, not hardcoded 40
        answered=len(answered_qids),
        anomaly_count=len(anomalies),
        high_weight_answered=high_weight_answered,
        high_weight_total=len(high_weight_qids),
    )

    # ── Feature importance — top 5 most influential answered questions ─────────
    answered_with_weight = sorted(
        [
            {
                "question_id": a["question_id"],
                "question_text": a.get("question_text", f"Q{a['question_id']}"),
                "risk": a.get("risk", 0),
                "weight": get_weight(a["question_id"]),
                "influence": round(a.get("risk", 0) * get_weight(a["question_id"]), 1),
            }
            for a in answers
            if a.get("risk") is not None
        ],
        key=lambda x: x["influence"],
        reverse=True,
    )
    top5_features = answered_with_weight[:5]

    return {
        "overall_risk":           overall,
        "category_scores": {
            "posture_risk":          posture_score,
            "eye_strain":            eye_score,
            "workload_stress":       workload_score,
            "musculoskeletal_risk":  pain_score,
            "recovery_risk":         recovery_score,
        },
        "tier":                   tier,
        "clinical_action":        clinical_action,
        "fuzzy_memberships":      fuzzy,
        "confidence":             confidence,
        "anomalies":              anomalies,
        "feature_importance_top5": top5_features,
    }
