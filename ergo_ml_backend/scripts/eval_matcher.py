"""
Accuracy test for the answer matcher (app/domain/answer_matcher.py).

50 natural, spoken-style answers written for the ErgoCare questions, each
labelled with the option a human would pick. Reports accuracy for:
  - old behaviour (exact match only - everything else scored a neutral 50)
  - rules only (no ML model)
  - rules + sentence-embedding model(s)

Run (from ergo_ml_backend):
    .venv\\Scripts\\python scripts\\eval_matcher.py
    .venv\\Scripts\\python scripts\\eval_matcher.py --models sentence-transformers/all-MiniLM-L6-v2
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.domain import answer_matcher as M  # noqa: E402
from app.domain.questions import QUESTIONS_BY_ID as Q  # noqa: E402

CASES = [
    # (question id, what the person said, correct option)
    (1, "I usually go more than two hours without a break", "More than 2 hours"),
    (1, "about an hour or so", "1 hour"),
    (1, "honestly I never take breaks until lunch", "More than 2 hours"),
    (1, "every twenty minutes or so I get up", "Less than 30 minutes"),
    (1, "somewhere between one and two hours", "1-2 hours"),
    (2, "my eyes are really really tired by evening", "Very tired"),
    (2, "they feel fine, not tired at all", "Not tired"),
    (2, "a little bit tired", "Slightly tired"),
    (2, "moderately I would say", "Moderately tired"),
    (4, "almost every day", "Every Day"),
    (4, "once in a while after long meetings", "Once in a while"),
    (4, "I never feel stiff", "Never"),
    (4, "quite often actually", "Often"),
    (5, "I don't really stretch at all", "Never"),
    (5, "a couple of times every day", "Multiple times a day"),
    (5, "just once in the morning", "Once a day"),
    (6, "it's extremely exhausting honestly", "Extremely exhausting"),
    (6, "not really exhausting", "Not exhausting"),
    (6, "a bit tiring but okay", "Mildly exhausting"),
    (8, "my chair is terrible, no back support", "Not supportive at all"),
    (8, "it is very comfortable and supportive", "Very supportive"),
    (8, "it's okay, somewhat supportive", "Somewhat supportive"),
    (9, "the laptop screen is way below my eyes", "Far below eye level"),
    (9, "right at eye level on a monitor stand", "At eye level"),
    (9, "a little lower than my eyes", "Slightly below eye level"),
    (10, "I check my phone constantly", "Very frequently"),
    (10, "hardly ever, I keep it away", "Rarely"),
    (11, "severe pain by friday", "Severe"),
    (11, "no discomfort", "None"),
    (11, "mild discomfort", "Mild"),
    (12, "my wrists hurt very often while typing", "Very often"),
    (12, "never had wrist strain", "Never"),
    (13, "my room is always dim", "Always"),
    (14, "my shoulders get tense every single day", "Everyday"),
    (16, "yes I keep working even when it hurts, always", "Always"),
    (17, "I recover completely after sleep", "Completely"),
    (17, "I don't recover at all", "Not at all"),
    (21, "around ten hours a day on screens", "More than 8 hours"),
    (21, "maybe three hours", "Less than 4 hours"),
    (27, "I drink less than a litre", "Less than 1 litre"),
    (27, "more than two litres every day", "More than 2 litres"),
    (30, "I often lie awake thinking about work", "Often"),
    (31, "it's about a four", "4"),
    (31, "zero, no neck pain", "0"),
    (35, "I'd rate my back pain three out of five", "3"),
    (34, "yes it hurts a lot", "Yes"),
    (34, "no, not at all", "No"),
    (36, "not sure, sometimes I feel numbness", "Maybe"),
    (38, "yeah after long typing sessions", "Yes"),
    (40, "nope, I feel fine", "No"),
]

# Held-out answers: written AFTER the rules were tuned on CASES and never used
# for tuning. Accuracy on these is the honest estimate for new users.
HOLDOUT = [
    (1, "I work for like three hours straight", "More than 2 hours"),
    (1, "I take a short break every half an hour", "Less than 30 minutes"),
    (2, "they're pretty tired by the end of the day", "Moderately tired"),
    (2, "super tired, they burn", "Very tired"),
    (3, "around six hours on the laptop without a mouse", "6-7"),
    (4, "i feel stiff pretty much daily", "Every Day"),
    (6, "most days it's quite exhausting", "Quite exhausting"),
    (7, "deadlines never really bother my posture", "Never"),
    (8, "the chair has no lumbar support at all", "Not supportive at all"),
    (12, "my fingers ache quite often when I type", "Often"),
    (13, "our office lighting is good", "Never"),
    (15, "I just sit the whole day", "Never"),
    (18, "headaches almost every evening", "Always"),
    (21, "roughly seven hours including my phone", "6-8 hours"),
    (25, "I eat at my desk three or four times a week", "3-4 times a week"),
    (28, "about forty five minutes each way", "30-60 minutes"),
    (30, "I sleep fine", "Never"),
    (33, "I'd give it a two", "2"),
    (36, "no numbness", "No"),
    (39, "my vision gets blurry, maybe a five", "5"),
]


# Hindi and Kannada, in their own script and romanised (what a browser set to
# English writes for Hindi speech: "Ek Ghanta."). The rules layer handles these.
INDIC = [
    (1, "Ek Ghanta.", "1 hour"),
    (1, "do ghante se zyada", "More than 2 hours"),
    (1, "aadha ghanta", "Less than 30 minutes"),
    (1, "dedh ghanta", "1-2 hours"),
    (1, "एक घंटा", "1 hour"),
    (1, "दो घंटे से ज़्यादा", "More than 2 hours"),
    (1, "ondu gante", "1 hour"),
    (1, "eradu gantegintha hechchu", "More than 2 hours"),
    (1, "ಎರಡು ಗಂಟೆಗಿಂತ ಹೆಚ್ಚು", "More than 2 hours"),
    (2, "aankhein bahut thak jaati hain", "Very tired"),
    (2, "thodi thak jaati hain", "Slightly tired"),
    (2, "kannu tumba sustagutte", "Very tired"),
    (2, "शाम तक आँखें बहुत थक जाती हैं", "Very tired"),
    (4, "kabhi kabhi", "Once in a while"),
    (4, "roz", "Every Day"),
    (4, "kabhi nahi", "Never"),
    (4, "kelavomme", "Once in a while"),
    (4, "कभी कभी", "Once in a while"),
    (11, "halka dard", "Mild"),
    (27, "do litre se zyada", "More than 2 litres"),
    (31, "teen", "3"),
    (31, "char", "4"),
    (31, "mooru", "3"),
    (31, "ಮೂರು", "3"),
    (34, "haan", "Yes"),
    (34, "nahi", "No"),
    (34, "shayad", "Maybe"),
    (34, "houdu", "Yes"),
    (34, "illa", "No"),
    (34, "हाँ", "Yes"),
]


def evaluate(label: str, fn, cases=None) -> float:
    cases = cases or CASES
    ok, wrong = 0, []
    t0 = time.perf_counter()
    for qid, said, want in cases:
        got = fn(Q[qid], said)
        if got == want:
            ok += 1
        else:
            wrong.append(f"Q{qid} '{said}' -> {got!r} (want {want!r})")
    ms = (time.perf_counter() - t0) / len(cases) * 1000
    acc = ok / len(cases) * 100
    print(f"\n{label}: {ok}/{len(cases)} correct = {acc:.0f}%   ({ms:.1f} ms per answer)")
    for w in wrong:
        print("   x", w)
    return acc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=[
        "sentence-transformers/all-MiniLM-L6-v2",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"])
    args = ap.parse_args()

    evaluate("OLD: exact match only (everything else = neutral 50)",
             lambda q, s: next((o for o in q["options"] if o.lower() == s.strip().lower()), None))
    evaluate("Rules only (no ML model)", lambda q, s: M.match_answer(q, s, use_semantic=False).option)
    evaluate("HELD-OUT - rules only", lambda q, s: M.match_answer(q, s, use_semantic=False).option, HOLDOUT)
    evaluate("HINDI / KANNADA (script + romanised) - rules only",
             lambda q, s: M.match_answer(q, s, use_semantic=False).option, INDIC)
    for name in args.models:
        M.MODEL_NAME = name
        M.semantic = M._Semantic()
        if not M.semantic.load():
            print(f"\n{name}: could not load")
            continue
        evaluate(f"Rules + {name.split('/')[-1]}", lambda q, s: M.match_answer(q, s).option)
        evaluate(f"HELD-OUT - rules + {name.split('/')[-1]}", lambda q, s: M.match_answer(q, s).option, HOLDOUT)


if __name__ == "__main__":
    main()
