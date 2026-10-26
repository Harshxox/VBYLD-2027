"""
500 simulated participants through the real scoring engine - answers + wearable.

    cd ergo_ml_backend
    .venv\\Scripts\\python scripts\\eval_500_participants.py      (~1 minute, no server needed)

Every participant (seed 2026) gets:
  - 40 answers from a hidden "true" risk level, with separate levels for posture
    and workload so answers and body can disagree, plus random answer noise;
  - a 60-s calm baseline, then 4-8 minutes of wearable readings (the demo
    simulator's body model) with a KNOWN share of time spent slouching and stressed;
  - 5% have poor sensor contact (finger off, electrodes loose) for the whole session.
They go through the same functions the server uses at /complete:
calculate_scores() -> compute_baseline() -> score_session().

Checks
  1. robustness: no crash, every score within 0-100
  2. ErgoCare Index = 60% questionnaire + 40% body signals (and its band)
  3. insight rules applied exactly as documented
  4. detection vs. what was simulated: slouching >= 30% of the time, stressed >= 40%
  5. poor contact never produces a stress result
  6. questionnaire score rises with the participant's true risk level

The participants are SIMULATED. This tests that the engine behaves correctly and
consistently - it is not clinical validation. Writes sample_data/participants_500.csv.
"""
import csv
import random
import statistics
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "firmware"))

from app.domain import sensors as S                                   # noqa: E402
from app.domain.questions import QUESTIONS                             # noqa: E402
from app.domain.scoring import calculate_scores, option_risk          # noqa: E402
from app.domain.sensor_scoring import score_session                   # noqa: E402
import demo_simulator                                                 # noqa: E402

N, SEED = 500, 2026
SLOUCH_TRUE, STRESS_TRUE = 0.30, 0.40          # the engine's own thresholds (30% / score 40)
MARGIN = 0.05                                  # "clear" cases are at least this far from a threshold
FIELDS = ("seq", "bpm", "bpm_avg", "finger", "ir", "gsr_raw", "gsr_mv", "gsr_contact",
          "tilt", "gyro", "acc_std", "moving", "pulse_ok", "mpu_ok")
BY_RISK = {q["id"]: sorted(q["options"], key=lambda o: option_risk(q, o)) for q in QUESTIONS}


def answers_for(rng, levels) -> list:
    out = []
    for q in QUESTIONS:
        lat = levels.get(q["category"], levels["general"])
        opts = BY_RISK[q["id"]]
        i = round(lat * (len(opts) - 1) + rng.gauss(0, 0.5))
        out.append({"question_id": q["id"], "typed_answer": opts[min(max(i, 0), len(opts) - 1)]})
    return out


def blocks(rng, seconds, frac) -> list:
    """Per-second True/False with roughly `frac` of the time True, in 1-3 blocks."""
    state = [False] * seconds
    total, k = round(frac * seconds), rng.randint(1, 3)
    for part in [total // k] * (k - 1) + [total - (total // k) * (k - 1)]:
        if part:
            start = rng.randint(0, seconds - part)
            for s in range(start, start + part):
                state[s] = True
    return state


def wearable(rng, live_s, slouch, stressed, poor_contact):
    clock = {"t": 0.0}
    demo_simulator.time = types.SimpleNamespace(monotonic=lambda: clock["t"])
    demo_simulator.random = rng                  # the simulator's noise follows our seed
    body = demo_simulator.Body()
    body.start = 0.0
    body.bpm = rng.uniform(62, 88)               # people differ at rest
    body.gsr = rng.uniform(300, 700)
    t0 = datetime(2026, 10, 26, 10, 0, 0)
    rows = []
    for sec in range(S.BASELINE_SECONDS + live_s):
        live = sec - S.BASELINE_SECONDS
        body.slouch = live >= 0 and slouch[live]
        body.stressed = live >= 0 and stressed[live]
        body.finger = not (poor_contact and live >= 0)
        if sec == 0:
            body.calibrate()                     # starting the baseline zeroes posture
        clock["t"] = float(sec)
        r = body.step()
        if poor_contact and live >= 0:
            r["gsr_contact"], r["gsr_raw"] = False, 20
        d = {f: r[f] for f in FIELDS}
        d["received_at"] = t0 + timedelta(seconds=sec)
        rows.append(d)
    base_rows = [r for r in rows if t0 + timedelta(seconds=S.BASELINE_SKIP_S) <= r["received_at"]
                 < t0 + timedelta(seconds=S.BASELINE_SECONDS)]
    return rows, S.compute_baseline(base_rows), t0


def spearman(xs, ys) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=v.__getitem__)
        r = [0.0] * len(v)
        for rank, i in enumerate(order):
            r[i] = rank
        return r
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return cov / (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5


def confusion(pairs):
    """pairs = [(truth_bool, predicted_bool)] -> accuracy, sensitivity, specificity, counts."""
    tp = sum(t and p for t, p in pairs); tn = sum(not t and not p for t, p in pairs)
    fp = sum(not t and p for t, p in pairs); fn = sum(t and not p for t, p in pairs)
    acc = (tp + tn) / len(pairs) if pairs else 0
    sens = tp / (tp + fn) if tp + fn else float("nan")
    spec = tn / (tn + fp) if tn + fp else float("nan")
    return acc, sens, spec, tp, tn, fp, fn


def main() -> int:
    rng = random.Random(SEED)
    rows, problems = [], []
    for pid in range(1, N + 1):
        general = rng.random()
        levels = {"general": general,
                  "posture": rng.random(),          # reported posture and workload are drawn
                  "movement": rng.random(),         # separately, so answers can disagree
                  "workload": rng.random()}         # with what the body shows
        for cat in ("eyes", "pain", "recovery"):
            levels[cat] = min(1.0, max(0.0, general + rng.gauss(0, 0.15)))
        live_s = rng.randint(240, 480)
        slouch = blocks(rng, live_s, rng.uniform(0, 0.8))
        stressed = blocks(rng, live_s, rng.uniform(0, 0.8))
        poor = rng.random() < 0.05

        try:
            scores, _ = calculate_scores(answers_for(rng, levels))
            readings, baseline, t0 = wearable(rng, live_s, slouch, stressed, poor)
            w = score_session(readings, baseline, t0, scores)
        except Exception as exc:                  # robustness check
            problems.append(f"P{pid}: crashed - {exc!r}")
            continue

        truth_slouch = sum(slouch) / live_s
        truth_stress = sum(stressed) / live_s
        c, p, st = w.get("combined") or {}, w.get("posture") or {}, w.get("stress")
        titles = [i["title"] for i in w.get("insights", [])]
        sc = scores.model_dump()
        checks = []

        vals = [v for v in sc.values()] + [c.get("index"), c.get("objective"), p.get("score"),
                                           (st or {}).get("score")]
        checks.append(("scores within 0-100", all(v is None or 0 <= v <= 100 for v in vals)))
        if w.get("available"):
            idx = round(0.6 * c["questionnaire"] + 0.4 * c["objective"], 1)
            band = "High" if c["index"] >= 70 else "Moderate" if c["index"] >= 40 else "Low"
            checks.append(("index = 0.6 q + 0.4 body", abs(c["index"] - idx) <= 0.1))
            checks.append(("index band", c["level"] == band))
            checks.append(("questionnaire part = overall risk", abs(c["questionnaire"] - sc["overall_risk"]) <= 0.1))
            body_stress = (st or {}).get("score")
            exp = set()
            if body_stress is not None:
                if body_stress >= 40:
                    exp.add("Hidden stress" if sc["workload_stress"] < 40 else "Stress confirmed")
                elif body_stress < 20 and sc["workload_stress"] >= 60:
                    exp.add("Calm during the test")
            if p and p["pct_time_bad"] >= 30:
                exp.add("Posture blind spot" if sc["posture_risk"] < 40 else "Posture problem confirmed")
            checks.append(("insight rules", set(titles) == exp))
        else:
            checks.append(("unavailable only with too little data", poor or live_s < 30))
        if poor:
            checks.append(("poor contact -> no stress result", st is None and not any("tress" in t for t in titles)))

        failed = [name for name, ok in checks if not ok]
        problems += [f"P{pid}: {f}" for f in failed]
        rows.append({
            "participant": pid, "true_risk_level": round(general, 3),
            "true_slouch_pct": round(100 * truth_slouch, 1), "true_stressed_pct": round(100 * truth_stress, 1),
            "poor_contact": poor, "session_s": live_s,
            "questionnaire_overall": sc["overall_risk"], "posture_risk": sc["posture_risk"],
            "workload_stress": sc["workload_stress"], "musculoskeletal_risk": sc["musculoskeletal_risk"],
            "eye_strain": sc["eye_strain"], "recovery_risk": sc["recovery_risk"],
            "measured_slouch_pct": p.get("pct_time_bad"), "body_stress_score": (st or {}).get("score"),
            "body_signal_score": c.get("objective"), "ergocare_index": c.get("index"), "index_level": c.get("level"),
            "insights": "; ".join(titles), "checks_failed": "; ".join(failed),
        })

    # ── Report ─────────────────────────────────────────────────────────────────
    good = [r for r in rows if not r["poor_contact"]]
    print(f"\n500 SIMULATED PARTICIPANTS - {len(rows)} scored, {len(problems)} problems")
    print(f"  robustness: {N - len([x for x in problems if 'crashed' in x])}/{N} ran without error")
    print(f"  rule checks (index formula, band, insights, 0-100, contact): "
          f"{len([r for r in rows if not r['checks_failed']])}/{len(rows)} participants passed all")

    for name, tkey, mkey, thr in (("Slouching >= 30% of the time", "true_slouch_pct", "measured_slouch_pct", 30),
                                  ("Stressed >= 40% of the time", "true_stressed_pct", "body_stress_score", 40)):
        pairs = [(r[tkey] >= thr, r[mkey] is not None and r[mkey] >= thr) for r in good]
        clear = [(r[tkey] >= thr, r[mkey] is not None and r[mkey] >= thr) for r in good
                 if abs(r[tkey] - thr) >= MARGIN * 100]
        a, se, sp, *_ = confusion(pairs)
        ca, cse, csp, tp, tn, fp, fn = confusion(clear)
        err = [abs(r[tkey] - r[mkey]) for r in good if r[mkey] is not None]
        print(f"\n  {name} (n={len(pairs)}):")
        print(f"    all cases   accuracy {100 * a:.1f}%  sensitivity {100 * se:.1f}%  specificity {100 * sp:.1f}%")
        print(f"    clear cases accuracy {100 * ca:.1f}%  sensitivity {100 * cse:.1f}%  specificity {100 * csp:.1f}%"
              f"  (n={len(clear)}, more than {int(MARGIN * 100)} points from the line; TP {tp} TN {tn} FP {fp} FN {fn})")
        print(f"    measured vs simulated: mean absolute difference {statistics.mean(err):.1f} points "
              f"(body signals take a few seconds to rise and to settle)")

    rho = spearman([r["true_risk_level"] for r in rows], [r["questionnaire_overall"] for r in rows])
    print(f"\n  questionnaire score vs true risk level: Spearman rho = {rho:.3f}")
    print("  index levels:", {lv: sum(r["index_level"] == lv for r in rows) for lv in ("Low", "Moderate", "High")})
    print("  insights:", {t: sum(t in r["insights"] for r in rows) for t in
                          ("Hidden stress", "Stress confirmed", "Calm during the test",
                           "Posture blind spot", "Posture problem confirmed")})
    for prob in problems[:20]:
        print("  PROBLEM", prob)

    out = ROOT.parent / "sample_data" / "participants_500.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    print(f"\nwrote {out.relative_to(ROOT.parent)}")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
