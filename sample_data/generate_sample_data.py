"""
Regenerates every file in sample_data/ - deterministic, no hardware or server needed.

    ergo_ml_backend\\.venv\\Scripts\\python sample_data\\generate_sample_data.py

Outputs
  wearable_session.jsonl   200 one-per-second readings in the exact JSON the ESP32
                           sends (via the demo simulator's body model, seed 42):
                           0-60 s calm (baseline) | 60-100 calm | 100-140 slouching
                           | 140-180 stressed, upright | 180-200 calm
  answers_low_risk.json    40 answers - the lowest-risk option of every question
  answers_high_risk.json   40 answers - the highest-risk option of every question
  voice_answers.csv        the answer-matcher test cases (English, Hindi, Kannada,
                           romanised) with the option each should match

The readings are SIMULATED (labelled as such in each file) - never present them
as a measurement of a real person.
"""
import csv
import importlib.util
import json
import random
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "ergo_ml_backend"))
sys.path.insert(0, str(ROOT / "firmware"))

from app.domain.indic_lexicon import KN_ROMAN, gloss_romanized  # noqa: E402
from app.domain.questions import QUESTIONS                         # noqa: E402
from app.domain.scoring import option_risk                         # noqa: E402
import demo_simulator                                              # noqa: E402

# (start second, state) - the scripted story of the sample session
TIMELINE = [(0, "calm"), (100, "slouch"), (140, "stressed"), (180, "calm")]
SECONDS = 200
BASELINE_S = 60


def wearable_readings() -> list:
    random.seed(42)
    clock = {"t": 0.0}
    demo_simulator.time = types.SimpleNamespace(monotonic=lambda: clock["t"])   # simulated clock
    body = demo_simulator.Body()
    body.start = 0.0
    out = []
    for sec in range(SECONDS):
        state = [s for start, s in TIMELINE if sec >= start][-1]
        body.slouch, body.stressed = state == "slouch", state == "stressed"
        if sec == 0:
            body.calibrate()                      # starting the baseline zeroes the ESP32's posture
        clock["t"] = float(sec)
        r = body.step()
        r["device_id"] = "SAMPLE-01"
        r["_t"], r["_phase"] = sec, ("baseline" if sec < BASELINE_S else state)
        r["_simulated"] = True                    # "_" fields are notes; strip them before sending
        out.append(r)
    return out


def answer_set(pick) -> list:
    rows = []
    for q in QUESTIONS:
        risks = {o: option_risk(q, o) for o in q["options"]}
        opt = pick(risks, key=risks.get)
        rows.append({"question_id": q["id"], "question_text": q["text"],
                     "typed_answer": opt, "_risk": risks[opt]})
    return rows


def voice_cases() -> list:
    spec = importlib.util.spec_from_file_location("eval_matcher", ROOT / "ergo_ml_backend" / "scripts" / "eval_matcher.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    by_id = {q["id"]: q for q in QUESTIONS}
    kn_words = {p for p, _ in KN_ROMAN}

    def language(text: str) -> str:
        if any("ऀ" <= c <= "ॿ" for c in text):
            return "Hindi (Devanagari)"
        if any("ಀ" <= c <= "೿" for c in text):
            return "Kannada (Kannada script)"
        if gloss_romanized(text) is not None:
            words = text.lower().split()
            return "Kannada (romanised)" if any(w.startswith(k) for w in words for k in kn_words) else "Hindi (romanised)"
        return "English"

    rows = []
    for name, cases in (("development", ev.CASES), ("held-out", ev.HOLDOUT), ("indic", ev.INDIC)):
        for qid, said, want in cases:
            rows.append({"test_set": name, "question_id": qid, "question_text": by_id[qid]["text"],
                         "spoken_answer": said, "language": language(said), "expected_option": want})
    return rows


def main() -> None:
    readings = wearable_readings()
    with open(HERE / "wearable_session.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for r in readings:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    for name, pick in (("answers_low_risk.json", min), ("answers_high_risk.json", max)):
        doc = {"_note": "Sample answers for POST /api/sessions/{id}/answers (fields question_id, "
                        "question_text, typed_answer). _risk = server option_risk, for reference.",
               "answers": answer_set(pick)}
        (HERE / name).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = voice_cases()
    with open(HERE / "voice_answers.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    print(f"wearable_session.jsonl  {len(readings)} readings (simulated, device SAMPLE-01)")
    print("answers_low_risk.json / answers_high_risk.json  40 answers each")
    print(f"voice_answers.csv  {len(rows)} matcher test cases")


if __name__ == "__main__":
    main()
