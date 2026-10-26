"""
ErgoCare AI — questionnaire scoring verification.

Guards the one bug class that silently produces a *wrong but plausible* report:
an answer option that is healthier being scored as riskier than a less healthy one.

Before this test existed, 8 questions carried a `reverse: True` flag that inverted
an option list which was already ordered healthiest-first. A participant who
answered all 40 questions in the healthiest possible way was reported with
posture_risk 65.9 as their top risk factor, and their healthiest answers were
listed as the highest-influence features.

A second, subtler variant is also checked here. Section 1 only compares a
question's first option against its last, so a list that is internally
consistent but semantically backwards passes it. Q17, Q19, Q24, Q27 and Q32
were all inverted this way: "Never adjust your sitting position" scored 0 risk
and "Often" scored 100, and a sloucher's posture_risk came out at 21.6 instead
of 48.8. Section 1b below compares every question against a human-declared
healthy/unhealthy pair, so a list that reads worst-first is caught even when it
is perfectly monotonic.

Run:
    .venv\\Scripts\\python scripts\\verify_scoring.py
"""
import sys
from pathlib import Path
from typing import Dict, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.questions import QUESTIONS, QUESTIONS_BY_ID
from app.domain.scoring import option_risk, calculate_scores, build_report, RiskScores
from app.domain.answer_matcher import match_answer

_checks: list[tuple[bool, str]] = []


def check(ok: bool, name: str) -> bool:
    _checks.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return ok


# ── Sets of answers that must produce a predictable risk ordering ─────────────

def _answers(pick) -> list[dict]:
    """Build an answer set, choosing each question's option with `pick`."""
    out = []
    for q in QUESTIONS:
        out.append({
            "question_id": q["id"],
            "question_text": q["text"],
            "typed_answer": pick(q),
        })
    return out


def healthiest(q) -> str:
    """The option with the lowest computed risk - not simply the first one.

    For yes/no/maybe questions the first option is "Yes", which is the *worst*
    answer, so picking by position would build a set that is not actually healthy.
    """
    return min(q["options"], key=lambda o: (option_risk(q, o), q["options"].index(o)))


def unhealthiest(q) -> str:
    """The option with the highest computed risk."""
    return max(q["options"], key=lambda o: (option_risk(q, o), -q["options"].index(o)))


# ── 1. Option ordering contract ──────────────────────────────────────────────

def check_option_ordering() -> None:
    """
    For every question the healthiest option must not score worse than the
    unhealthiest one. Questions with a risk_map or a yes/no/maybe option set are
    scored by their own dedicated rule, so they are checked separately below.
    """
    print("\n1. Option ordering (healthiest option must not score worse)")
    inverted = []
    for q in QUESTIONS:
        opts = q["options"]
        if q.get("risk_map"):
            continue
        if {o.lower() for o in opts} >= {"yes", "no", "maybe"}:
            continue  # yes/no/maybe rule, verified in section 2
        r_best = option_risk(q, opts[0])
        r_worst = option_risk(q, opts[-1])
        if r_best > r_worst:
            inverted.append(
                f"Q{q['id']}: {opts[0]!r}={r_best} but {opts[-1]!r}={r_worst}"
            )
    check(not inverted, f"no question inverts its own options ({len(inverted)} bad)")
    for line in inverted:
        print(f"         -> {line}")


# ── 1b. Semantic ground truth ────────────────────────────────────────────────
#
# The healthy and unhealthy end of every question, written out by hand. This is
# the ground truth that neither the positional rule nor risk_map may contradict,
# and it is the only check that notices a list which is monotonic but backwards.
#
# Any question added to the bank MUST be added here too - check 1b fails on an
# incomplete table so a new question cannot quietly escape the check.
EXPECTED_SCALE: Dict[int, Tuple[str, str]] = {
    1: ("Less than 30 minutes", "More than 2 hours"),
    2: ("Not tired", "Very tired"),
    3: ("1-2", ">8"),
    4: ("Never", "Every Day"),
    5: ("Multiple times a day", "Never"),
    6: ("Not exhausting", "Extremely exhausting"),
    7: ("Never", "Always"),
    8: ("Very supportive", "Not supportive at all"),
    9: ("At eye level", "Far below eye level"),
    10: ("Rarely", "Very frequently"),
    11: ("None", "Severe"),
    12: ("Never", "Very often"),
    13: ("Never", "Always"),
    14: ("Never", "Everyday"),
    15: ("Very frequently", "Never"),
    16: ("Never", "Always"),
    17: ("Completely", "Not at all"),
    18: ("Never", "Always"),
    19: ("Often", "Never"),
    20: ("Never", "Always"),
    21: ("Less than 4 hours", "More than 8 hours"),
    22: ("Yes, comfortably", "Never"),
    23: ("Very confident", "Not confident at all"),
    24: ("Frequently throughout the day", "Never think about it"),
    25: ("Never", "Often"),
    26: ("Vigorous daily exercise routine", "Mostly seated with minimal movement"),
    27: ("More than 2 litres", "Less than 1 litre"),
    28: ("Under 30 minutes", "Over 2 hours"),
    29: ("Not draining at all", "Severely fatiguing, it impacts my workday"),
    30: ("Never", "Often"),
    31: ("0", "5"),
    32: ("Never", "Always"),
    33: ("0", "5"),
    34: ("No", "Yes"),
    35: ("0", "5"),
    36: ("No", "Yes"),
    37: ("0", "5"),
    38: ("No", "Yes"),
    39: ("0", "5"),
    40: ("No", "Yes"),
}


def check_declared_semantics() -> None:
    """The declared healthy option must score strictly below the unhealthy one."""
    print("\n1b. Declared healthy/unhealthy ends score in the right order")

    missing = [q["id"] for q in QUESTIONS if q["id"] not in EXPECTED_SCALE]
    check(not missing, f"every question has a declared healthy/unhealthy pair "
                       f"({len(missing)} missing)")
    for qid in missing:
        print(f"         -> Q{qid} is absent from EXPECTED_SCALE")

    bad = []
    for q in QUESTIONS:
        qid = q["id"]
        if qid not in EXPECTED_SCALE:
            continue
        healthy, unhealthy = EXPECTED_SCALE[qid]
        opts_lower = {o.lower() for o in q["options"]}
        for label, text in (("healthy", healthy), ("unhealthy", unhealthy)):
            if text.lower() not in opts_lower:
                bad.append(f"Q{qid}: {label} option {text!r} is not in the bank")
        if healthy.lower() not in opts_lower or unhealthy.lower() not in opts_lower:
            continue
        r_healthy = option_risk(q, healthy)
        r_unhealthy = option_risk(q, unhealthy)
        if r_healthy >= r_unhealthy:
            bad.append(
                f"Q{qid}: healthy {healthy!r}={r_healthy} but "
                f"unhealthy {unhealthy!r}={r_unhealthy}"
            )

    check(not bad, f"declared healthy option always scores lower ({len(bad)} bad)")
    for line in bad:
        print(f"         -> {line}")


# ── 2. yes / no / maybe must be calibrated ───────────────────────────────────

def check_yes_no_maybe() -> None:
    print("\n2. yes / no / maybe calibration")
    bad = []
    for q in QUESTIONS:
        low = {o.lower() for o in q["options"]}
        if low != {"yes", "no", "maybe"}:
            continue
        r_yes = option_risk(q, "Yes")
        r_maybe = option_risk(q, "Maybe")
        r_no = option_risk(q, "No")
        if not (r_yes > r_maybe > r_no):
            bad.append(f"Q{q['id']}: yes={r_yes} maybe={r_maybe} no={r_no}")
    check(not bad, f"yes > maybe > no on every yes/no/maybe question ({len(bad)} bad)")
    for line in bad:
        print(f"         -> {line}")


# ── 3. Numeric pain scales ──────────────────────────────────────────────────

def check_numeric_scales() -> None:
    print("\n3. Numeric 0-5 scales increase monotonically")
    bad = []
    for q in QUESTIONS:
        if not all(o.lstrip("-").isdigit() for o in q["options"]):
            continue
        risks = [option_risk(q, o) for o in q["options"]]
        if risks != sorted(risks):
            bad.append(f"Q{q['id']}: {risks}")
    check(not bad, f"every numeric scale increases ({len(bad)} bad)")
    for line in bad:
        print(f"         -> {line}")


# ── 4. End-to-end: healthy person must score low ─────────────────────────────

def check_end_to_end() -> None:
    print("\n4. End-to-end scoring of a healthy vs an unhealthy participant")

    healthy, _ = calculate_scores(_answers(healthiest))
    unhealthy, _ = calculate_scores(_answers(unhealthiest))

    check(
        healthy.overall_risk < 40,
        f"all-healthy answers -> Low risk (got {healthy.overall_risk})",
    )
    check(
        unhealthy.overall_risk > 70,
        f"all-unhealthy answers -> High/Critical risk (got {unhealthy.overall_risk})",
    )
    check(
        healthy.overall_risk < unhealthy.overall_risk,
        f"healthy scores below unhealthy ({healthy.overall_risk} < {unhealthy.overall_risk})",
    )

    for field in ("posture_risk", "eye_strain", "workload_stress",
                  "musculoskeletal_risk", "recovery_risk"):
        h = getattr(healthy, field)
        u = getattr(unhealthy, field)
        check(h < u, f"{field}: healthy {h} < unhealthy {u}")

    # Posture is the score that the reversal bug broke worst, so pin it tightly.
    check(healthy.posture_risk < 20, f"healthy posture_risk < 20 (got {healthy.posture_risk})")


# ── 5. Monotonicity: every step towards a worse answer must not reduce risk ──

def check_monotonicity() -> None:
    """
    The invariant that makes a report trustworthy: if option B carries a higher
    per-question risk than option A, then answering B must never produce a lower
    total risk than answering A.

    This is deliberately stated in terms of the *computed* risk rather than list
    position, because some questions are not positional at all (Q26 uses a
    risk_map where vigorous exercise is healthier than light movement, and the
    yes/no/maybe questions use their own calibrated rule).
    """
    print("\n5. Monotonicity (a riskier answer never lowers total risk)")
    regressions = []
    comparisons = 0

    for q in QUESTIONS:
        opts = q["options"]
        per_option = [(o, option_risk(q, o)) for o in opts]
        for i, (opt_a, risk_a) in enumerate(per_option):
            for opt_b, risk_b in per_option[i + 1:]:
                if risk_b <= risk_a:
                    continue  # b is not a worse answer than a
                comparisons += 1

                answers = _answers(healthiest)
                for a in answers:
                    if a["question_id"] == q["id"]:
                        a["typed_answer"] = opt_a
                base, _ = calculate_scores(answers)

                for a in answers:
                    if a["question_id"] == q["id"]:
                        a["typed_answer"] = opt_b
                worse, _ = calculate_scores(answers)

                if worse.overall_risk < base.overall_risk:
                    regressions.append(
                        f"Q{q['id']} {opt_a!r}(risk {risk_a}) -> {opt_b!r}(risk {risk_b}): "
                        f"total {base.overall_risk} -> {worse.overall_risk}"
                    )

    check(
        not regressions,
        f"{comparisons} riskier-answer comparisons, {len(regressions)} regressions",
    )
    for line in regressions[:12]:
        print(f"         -> {line}")


# ── 6. Free-form answers resolve to the same risk as the option they mean ────

def check_free_form_matches_options() -> None:
    print("\n6. Spoken answers score the same as the option they resolve to")
    cases = [
        (2,  "my eyes are really tired by evening",          "Very tired"),
        (5,  "I honestly never stretch during the day",       "Never"),
        (8,  "my chair is terrible, no back support",         "Not supportive at all"),
        (8,  "it is very comfortable and supportive",         "Very supportive"),
        (17, "I recover completely after a good sleep",       "Completely"),
        (24, "I constantly remind myself to sit up straight", "Frequently throughout the day"),
        (31, "about a two out of five",                       "2"),
        (34, "yes it hurts a lot",                            "Yes"),
        (40, "no, I feel fine",                               "No"),
    ]
    bad = []
    for qid, text, expected in cases:
        q = QUESTIONS_BY_ID[qid]
        m = match_answer(q, text)
        if m.option != expected:
            bad.append(f"Q{qid} {text!r} -> {m.option!r}, expected {expected!r}")
            continue
        if option_risk(q, m.option) != option_risk(q, expected):
            bad.append(f"Q{qid} risk mismatch for {expected!r}")
    check(not bad, f"{len(cases)} spoken answers map to the right option ({len(bad)} bad)")
    for line in bad:
        print(f"         -> {line}")


# ── 7. Report is internally consistent ───────────────────────────────────────

def _unpack(x):
    """ReportData exposes its fields as attributes; normalise to a plain dict."""
    if isinstance(x, dict):
        return x
    return {k: getattr(x, k) for k in dir(x) if not k.startswith("_") and not callable(getattr(x, k, None))}


def check_report_consistency() -> None:
    print("\n7. Report consistency")
    answers = _answers(healthiest)
    scores, ml = calculate_scores(answers)
    report = _unpack(build_report(scores, ml, answers))

    def field(name, default=None):
        return report.get(name, default)

    def r_action_plan(rep):
        return _unpack(rep).get("action_plan") or []

    check(field("level") == "Low", f"healthy report level is Low (got {field('level')})")
    check(bool(field("action_plan")), "action plan is populated")
    check(bool(field("top_factors")), "top factors are populated")

    factors = field("top_factors") or []
    check(bool(factors), "top factors are populated")

    # A healthy participant must not have any category above a trivial score.
    # (With every score at 0 the ordering is arbitrary, so compare values, not order.)
    worst_pct = max(
        (float(f.rsplit(":", 1)[1].strip().rstrip("%")) for f in factors if ":" in f),
        default=0.0,
    )
    check(
        worst_pct < 20,
        f"no category above 20% for a healthy participant (worst {worst_pct:.0f}%)",
    )

    # Diagnostic lines (fuzzy profile, ML confidence, highest-influence question)
    # legitimately mention tier names. Only the advice lines are prose.
    DIAGNOSTIC = ("Fuzzy Risk Profile", "ML Confidence Score", "Highest-influence question")
    findings = field("detailed_findings") or []
    advice = [
        f for f in findings
        if f.strip() and not f.startswith(DIAGNOSTIC)
    ]
    check(
        not any("CRITICAL" in f.upper() for f in advice),
        f"healthy report contains no CRITICAL advice ({len(advice)} advice lines)",
    )
    check(
        not any("priority pain" in f.lower() for f in r_action_plan(report)),
        "healthy action plan does not tell the participant to address pain",
    )

    positives = field("positive_habits") or []
    check(bool(positives), f"healthy report lists positive habits ({len(positives)})")


# ── 8. Missing answers must not crash or fabricate ───────────────────────────

def check_partial_answers() -> None:
    print("\n8. Partial and empty answer sets")
    try:
        s, _ = calculate_scores([])
        check(True, f"empty answer set handled (all scores 0, overall {s.overall_risk})")
        check(s.overall_risk == 0, "empty answer set scores 0")
    except Exception as exc:  # noqa: BLE001
        check(False, f"empty answer set raised {exc!r}")

    try:
        partial = _answers(healthiest)[:10]
        s, _ = calculate_scores(partial)
        check(0 <= s.overall_risk <= 100, f"partial answer set scores in range ({s.overall_risk})")
    except Exception as exc:  # noqa: BLE001
        check(False, f"partial answer set raised {exc!r}")


def main() -> int:
    print("ErgoCare AI - questionnaire scoring verification")
    print("=" * 62)

    check_option_ordering()
    check_declared_semantics()
    check_yes_no_maybe()
    check_numeric_scales()
    check_end_to_end()
    check_monotonicity()
    check_free_form_matches_options()
    check_report_consistency()
    check_partial_answers()

    passed = sum(1 for ok, _ in _checks if ok)
    total = len(_checks)
    print("\n" + "=" * 62)
    print(f"RESULT: {passed}/{total} checks passed")

    if passed != total:
        print("\nFAILED:")
        for ok, name in _checks:
            if not ok:
                print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
