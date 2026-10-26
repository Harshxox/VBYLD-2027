"""
500-answer test of the AI answer matcher - English, Hindi and Kannada, in their
own script and romanised (the way a browser set to English writes Hindi speech).

    cd ergo_ml_backend
    .venv\\Scripts\\python scripts\\eval_matcher_500.py           # rules + MiniLM (as the app runs)
    .venv\\Scripts\\python scripts\\eval_matcher_500.py --rules   # rules only

The answers are SYNTHETIC: built (seed 500) from meaning-based phrase lists the
team wrote - "never", "रोज़", "tumba", "about three hours"... - inside everyday
sentence frames ("I'd say ...", "मुझे लगता है ...", "nanage ..."). Each answer's
expected option is fixed by its meaning, not by what the matcher does. Some
phrasings are deliberately hard ("every hour", "बीस मिनट", "one glass").
This set was NOT used to tune the matcher, so its first result is the honest one.
It is not real user speech - testing with native speakers is still needed.

Writes sample_data/voice_answers_500.csv (with what the matcher answered).
"""
import argparse
import csv
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.domain import answer_matcher as M          # noqa: E402
from app.domain.questions import QUESTIONS           # noqa: E402

Q = {q["id"]: q for q in QUESTIONS}
FORMS = ["English", "Hindi (Devanagari)", "Hindi (romanised)", "Kannada (script)", "Kannada (romanised)"]
EN, HI, HR, KN, KR = FORMS
QUOTA = {EN: 200, HI: 75, HR: 75, KN: 75, KR: 75}       # = 500

# ── Sentence frames ───────────────────────────────────────────────────────────
FRAMES = {
    EN: ["{x}", "I'd say {x}", "{x}, to be honest", "hmm, {x}", "honestly {x}"],
    HI: ["{x}", "मुझे लगता है {x}", "{x} होता है", "सच कहूँ तो {x}"],
    HR: ["{x}", "mujhe lagta hai {x}", "{x} hota hai", "sach kahun to {x}"],
    KN: ["{x}", "{x} ಅನ್ನಿಸುತ್ತೆ", "ನನಗೆ {x}"],
    KR: ["{x}", "{x} annisutte", "nanage {x}"],
}

# ── Meaning -> phrases, per form ──────────────────────────────────────────────
FREQ = {
    "never": {EN: ["never", "not even once", "that never happens to me", "no, never really"],
              HI: ["कभी नहीं", "कभी भी नहीं"], HR: ["kabhi nahi", "kabhi bhi nahi"],
              KN: ["ಎಂದಿಗೂ ಇಲ್ಲ", "ಎಂದೂ ಇಲ್ಲ"], KR: ["endigu illa", "endu illa"]},
    "rarely": {EN: ["rarely", "hardly ever", "almost never", "very rarely, maybe once a month"],
               HI: ["बहुत कम", "शायद ही कभी"], HR: ["bahut kam", "shayad hi kabhi"],
               KN: ["ಅಪರೂಪ", "ತುಂಬಾ ಕಡಿಮೆ"], KR: ["aparupa", "tumba kadime"]},
    "sometimes": {EN: ["sometimes", "now and then", "once in a while", "it happens occasionally", "some days, not all"],
                  HI: ["कभी कभी", "कभी-कभार"], HR: ["kabhi kabhi", "kabhi kabhar"],
                  KN: ["ಕೆಲವೊಮ್ಮೆ", "ಒಮ್ಮೊಮ್ಮೆ"], KR: ["kelavomme", "ommomme"]},
    "often": {EN: ["often", "quite often", "pretty frequently", "most days", "a lot of the time"],
              HI: ["अक्सर", "बार-बार"], HR: ["aksar", "baar baar"],
              KN: ["ಆಗಾಗ್ಗೆ", "ಹೆಚ್ಚಾಗಿ"], KR: ["agagge", "hecchagi"]},
    "always": {EN: ["always", "every single day", "all the time", "it happens daily", "constantly"],
               HI: ["हमेशा", "रोज़", "हर दिन"], HR: ["hamesha", "roz", "har din"],
               KN: ["ಯಾವಾಗಲೂ", "ಪ್ರತಿದಿನ"], KR: ["yavaglu", "pratidina"]},
}
YN = {
    "Yes": {EN: ["yes", "yeah, it hurts", "yes, quite a lot", "definitely"],
            HI: ["हाँ", "जी हाँ", "हाँ, होता है"], HR: ["haan", "haan hota hai", "ji haan"],
            KN: ["ಹೌದು", "ಹೌದು, ಆಗುತ್ತೆ"], KR: ["houdu", "haudu agutte"]},
    "No": {EN: ["no", "nope", "not really", "no, never"],
           HI: ["नहीं", "बिल्कुल नहीं"], HR: ["nahi", "bilkul nahi"],
           KN: ["ಇಲ್ಲ", "ಇಲ್ಲವೇ ಇಲ್ಲ"], KR: ["illa", "illave illa"]},
    "Maybe": {EN: ["maybe", "not sure", "sometimes a little", "I'm not sure"],
              HI: ["शायद", "पता नहीं"], HR: ["shayad", "pata nahi"],
              KN: ["ಬಹುಶಃ", "ಗೊತ್ತಿಲ್ಲ"], KR: ["bahusha", "gottilla"]},
}
NUM_WORDS = {
    EN: ["zero", "one", "two", "three", "four", "five"],
    HI: ["शून्य", "एक", "दो", "तीन", "चार", "पाँच"], HR: ["shunya", "ek", "do", "teen", "char", "paanch"],
    KN: ["ಸೊನ್ನೆ", "ಒಂದು", "ಎರಡು", "ಮೂರು", "ನಾಲ್ಕು", "ಐದು"], KR: ["sonne", "ondu", "eradu", "mooru", "naalku", "aidu"],
}
NUM_FRAMES = {EN: ["{n}", "about a {n}", "I'd rate it {n}", "{w}", "{w} out of five"],
              HI: ["{w}", "{n}", "{w} नंबर"], HR: ["{w}", "{w} number"],
              KN: ["{w}", "{n}", "{w} ಅಂಕ"], KR: ["{w}", "{w} anka"]}
INTENSITY = {
    "none": {EN: ["not at all", "not really", "none"], HI: ["बिल्कुल नहीं"], HR: ["bilkul nahi"],
             KN: ["ಇಲ್ಲವೇ ಇಲ್ಲ"], KR: ["illave illa"]},
    "slight": {EN: ["slightly", "a little bit", "mildly"], HI: ["थोड़ा", "हल्का सा"], HR: ["thoda", "halka sa"],
               KN: ["ಸ್ವಲ್ಪ"], KR: ["swalpa"]},
    "moderate": {EN: ["moderately", "quite", "fairly"], HI: ["काफ़ी", "मध्यम"], HR: ["kaafi", "madhyam"],
                 KN: ["ಸಾಕಷ್ಟು", "ಮಧ್ಯಮ"], KR: ["saakashtu", "madhyama"]},
    "very": {EN: ["very", "extremely", "really really"], HI: ["बहुत", "बहुत ज़्यादा"], HR: ["bahut", "bahut zyada"],
             KN: ["ತುಂಬಾ", "ಬಹಳ"], KR: ["tumba", "bahala"]},
}

# question -> {meaning: expected option}
FREQ_Q = {
    4: {"never": "Never", "sometimes": "Once in a while", "often": "Often", "always": "Every Day"},
    7: {"never": "Never", "sometimes": "Sometimes", "often": "Often", "always": "Always"},
    12: {"never": "Never", "rarely": "Rarely", "often": "Often", "always": "Very often"},
    13: {"never": "Never", "sometimes": "Occasionally", "often": "Frequently", "always": "Always"},
    14: {"never": "Never", "sometimes": "Sometimes", "often": "Often", "always": "Everyday"},
    15: {"always": "Very frequently", "sometimes": "Sometimes", "rarely": "Rarely", "never": "Never"},
    16: {"never": "Never", "sometimes": "Sometimes", "often": "Often", "always": "Always"},
    18: {"never": "Never", "sometimes": "Sometimes", "often": "Often", "always": "Always"},
    19: {"never": "Never", "rarely": "Rarely", "sometimes": "Sometimes", "often": "Often"},
    20: {"never": "Never", "sometimes": "Sometimes", "often": "Often", "always": "Always"},
    30: {"never": "Never", "rarely": "Rarely", "sometimes": "Sometimes", "often": "Often"},
    32: {"always": "Always", "often": "Often", "sometimes": "Sometimes", "rarely": "Rarely", "never": "Never"},
}
INT_Q = {
    2: {"none": "Not tired", "slight": "Slightly tired", "moderate": "Moderately tired", "very": "Very tired"},
    6: {"none": "Not exhausting", "slight": "Mildly exhausting", "moderate": "Quite exhausting", "very": "Extremely exhausting"},
    11: {"none": "None", "slight": "Mild", "moderate": "Moderate", "very": "Severe"},
    29: {"none": "Not draining at all", "slight": "Mildly tiring", "moderate": "Moderately exhausting",
         "very": "Severely fatiguing, it impacts my workday"},
}
YN_Q = [34, 36, 38, 40]
NUM_Q = [31, 33, 35, 37, 39]

# Quantities: question -> expected option -> {form: phrases}
QTY = {
    1: {"Less than 30 minutes": {EN: ["about twenty minutes", "every 15 minutes or so", "less than half an hour"],
                                 HI: ["बीस मिनट", "आधा घंटा से कम"], HR: ["bees minute", "aadhe ghante se kam"],
                                 KN: ["ಇಪ್ಪತ್ತು ನಿಮಿಷ", "ಅರ್ಧ ಗಂಟೆಗಿಂತ ಕಡಿಮೆ"], KR: ["ippattu nimisha", "ardha gantegintha kadime"]},
        "1 hour": {EN: ["about an hour", "one hour", "every hour"],
                   HI: ["एक घंटा", "हर एक घंटे में"], HR: ["ek ghanta", "har ek ghante mein"],
                   KN: ["ಒಂದು ಗಂಟೆ", "ಪ್ರತಿ ಗಂಟೆಗೆ"], KR: ["ondu gante", "prati gantege"]},
        "1-2 hours": {EN: ["an hour and a half", "between one and two hours", "90 minutes"],
                      HI: ["डेढ़ घंटा", "एक से दो घंटे"], HR: ["dedh ghanta", "ek se do ghante"],
                      KN: ["ಒಂದೂವರೆ ಗಂಟೆ", "ಒಂದರಿಂದ ಎರಡು ಗಂಟೆ"], KR: ["ondoovare gante", "ondarinda eradu gante"]},
        "More than 2 hours": {EN: ["three hours", "more than two hours", "about four hours straight"],
                              HI: ["दो घंटे से ज़्यादा", "तीन घंटे"], HR: ["do ghante se zyada", "teen ghante"],
                              KN: ["ಎರಡು ಗಂಟೆಗಿಂತ ಹೆಚ್ಚು", "ಮೂರು ಗಂಟೆ"], KR: ["eradu gantegintha hechchu", "mooru gante"]}},
    3: {"1-2": {EN: ["about two hours", "one or two hours"], HR: ["do ghante"], KR: ["eradu gante"]},
        "3-4": {EN: ["three or four hours", "around three hours"], HR: ["teen chaar ghante"], KR: ["mooru naalku gante"]},
        "6-7": {EN: ["six or seven hours", "about seven hours"], HR: ["saat ghante"], KR: ["elu gante"]},
        ">8": {EN: ["more than eight hours", "ten hours"], HR: ["das ghante"], KR: ["hattu gante"]}},
    21: {"Less than 4 hours": {EN: ["about three hours", "less than four hours", "two or three hours"],
                               HI: ["तीन घंटे", "चार घंटे से कम"], HR: ["teen ghante", "chaar ghante se kam"],
                               KN: ["ಮೂರು ಗಂಟೆ", "ನಾಲ್ಕು ಗಂಟೆಗಿಂತ ಕಡಿಮೆ"], KR: ["mooru gante", "naalku gantegintha kadime"]},
         "4-6 hours": {EN: ["around five hours", "four to six hours", "five hours or so"],
                       HI: ["पाँच घंटे"], HR: ["paanch ghante"], KN: ["ಐದು ಗಂಟೆ"], KR: ["aidu gante"]},
         "6-8 hours": {EN: ["seven hours", "six to eight hours", "about seven hours a day"],
                       HI: ["सात घंटे"], HR: ["saat ghante"], KN: ["ಏಳು ಗಂಟೆ"], KR: ["elu gante"]},
         "More than 8 hours": {EN: ["ten hours", "more than eight hours", "nine or ten hours"],
                               HI: ["दस घंटे", "आठ घंटे से ज़्यादा"], HR: ["das ghante", "aath ghante se zyada"],
                               KN: ["ಹತ್ತು ಗಂಟೆ", "ಎಂಟು ಗಂಟೆಗಿಂತ ಹೆಚ್ಚು"], KR: ["hattu gante", "entu gantegintha hechchu"]}},
    27: {"Less than 1 litre": {EN: ["half a litre", "less than a litre", "just one glass"],
                               HI: ["आधा लीटर", "एक लीटर से कम"], HR: ["aadha litre", "ek litre se kam"],
                               KN: ["ಅರ್ಧ ಲೀಟರ್"], KR: ["ardha litre"]},
         "1-2 litres": {EN: ["one and a half litres", "about 1.5 litres", "between one and two litres"],
                        HI: ["डेढ़ लीटर"], HR: ["dedh litre"], KN: ["ಒಂದೂವರೆ ಲೀಟರ್"], KR: ["ondoovare litre"]},
         "More than 2 litres": {EN: ["three litres", "more than two litres", "around 3 litres"],
                                HI: ["तीन लीटर", "दो लीटर से ज़्यादा"], HR: ["teen litre", "do litre se zyada"],
                                KN: ["ಮೂರು ಲೀಟರ್"], KR: ["mooru litre"]}},
    28: {"Under 30 minutes": {EN: ["twenty minutes", "less than half an hour"], HR: ["bees minute"]},
         "30-60 minutes": {EN: ["forty five minutes", "about 45 minutes", "around fifty minutes"], HR: ["paune ghanta"]},
         "1-2 hours": {EN: ["an hour and a half", "about 90 minutes"], HR: ["dedh ghanta"]},
         "Over 2 hours": {EN: ["three hours", "more than two hours"], HR: ["teen ghante"], KR: ["mooru gante"]}},
}
# English answers that need understanding rather than keywords (where the AI model helps)
SEMANTIC_EN = [
    (5, "several times a day", "Multiple times a day"), (5, "once every day", "Once a day"),
    (5, "I never stretch", "Never"), (5, "a couple of times a week", "A few times a week"),
    (8, "my chair is really comfortable and supportive", "Very supportive"),
    (8, "it has no back support at all", "Not supportive at all"),
    (9, "right at eye level", "At eye level"), (9, "a bit lower than my eyes", "Slightly below eye level"),
    (9, "way down, I look down at my laptop", "Far below eye level"),
    (17, "I recover completely after a night's sleep", "Completely"), (17, "mostly fine the next day", "Mostly"),
    (17, "not at all, I wake up sore", "Not at all"),
    (23, "very confident", "Very confident"), (23, "I'm not sure about that", "Uncertain"),
    (23, "not confident at all", "Not confident at all"),
    (24, "only when my back starts hurting", "Only when I feel pain"), (24, "I never think about it", "Never think about it"),
    (24, "all through the day", "Frequently throughout the day"),
    (26, "I mostly sit all day", "Mostly seated with minimal movement"),
    (26, "I go to the gym every evening", "Structured activity like yoga or a gym session"),
    (26, "I just walk between classes", "Light movement such as walking between buildings"),
    (26, "I run hard every single morning", "Vigorous daily exercise routine"),
    (10, "I'm on my phone constantly", "Very frequently"), (10, "hardly ever", "Rarely"),
    (25, "never, I always take a lunch break", "Never"), (25, "very often", "Often"),
    (22, "yes, I have plenty of time for myself", "Yes, comfortably"), (22, "never, work takes everything", "Never"),
]


def build_pool() -> dict:
    pool = defaultdict(list)                     # form -> [(qid, said, expected, kind)]
    for qid, mp in FREQ_Q.items():
        for meaning, opt in mp.items():
            for form, phrases in FREQ[meaning].items():
                for ph in phrases:
                    for fr in FRAMES[form]:
                        pool[form].append((qid, fr.format(x=ph), opt, "frequency"))
    for qid, mp in INT_Q.items():
        for meaning, opt in mp.items():
            for form, phrases in INTENSITY[meaning].items():
                for ph in phrases:
                    for fr in FRAMES[form]:
                        pool[form].append((qid, fr.format(x=ph), opt, "intensity"))
    for qid in YN_Q:
        for opt, by_form in YN.items():
            for form, phrases in by_form.items():
                for ph in phrases:
                    for fr in FRAMES[form]:
                        pool[form].append((qid, fr.format(x=ph), opt, "yes/no"))
    for qid in NUM_Q:
        for n in range(6):
            for form in FORMS:
                for fr in NUM_FRAMES[form]:
                    pool[form].append((qid, fr.format(n=n, w=NUM_WORDS[form][n]), str(n), "0-5 scale"))
    for qid, mp in QTY.items():
        for opt, by_form in mp.items():
            for form, phrases in by_form.items():
                for ph in phrases:
                    for fr in (FRAMES[form][:2] if form != EN else FRAMES[EN][:3]):
                        pool[form].append((qid, fr.format(x=ph), opt, "quantity"))
    for qid, said, opt in SEMANTIC_EN:
        pool[EN].append((qid, said, opt, "meaning"))
    return pool


def sample(pool: dict) -> list:
    rng = random.Random(500)
    rows = []
    for form, n in QUOTA.items():
        items = sorted(set(pool[form]))
        must = [it for it in items if it[3] in ("meaning", "quantity")]     # always include the hard ones
        rest = [it for it in items if it not in must]
        rng.shuffle(rest)
        rows += [(form, *it) for it in (must + rest)[:n]]
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rules", action="store_true", help="rules only (no MiniLM)")
    args = ap.parse_args()
    use_sem = not args.rules and (M.semantic.available or M.semantic.load())
    rows = sample(build_pool())
    assert len(rows) == 500, len(rows)

    t0 = time.perf_counter()
    results = []
    for form, qid, said, want, kind in rows:
        got = M.match_answer(Q[qid], said, use_semantic=use_sem)
        results.append({"id": len(results) + 1, "language": form, "kind": kind, "question_id": qid,
                        "question_text": Q[qid]["text"], "spoken_answer": said, "expected_option": want,
                        "matched_option": got.option or "", "method": got.method,
                        "correct": got.option == want, "no_match": got.option is None})
    ms = (time.perf_counter() - t0) / len(rows) * 1000

    ok = sum(r["correct"] for r in results)
    wrong = sum(1 for r in results if not r["correct"] and not r["no_match"])
    none = sum(r["no_match"] for r in results)
    mode = "rules + all-MiniLM-L6-v2" if use_sem else "rules only"
    print(f"\n500-ANSWER TEST ({mode}): {ok}/500 correct = {ok / 5:.1f}%   "
          f"| wrong option: {wrong} | no match (person taps): {none} | {ms:.1f} ms per answer")
    for key in ("language", "kind"):
        print(f"\nBy {key}:")
        tot, cor = Counter(r[key] for r in results), Counter(r[key] for r in results if r["correct"])
        for k in tot:
            print(f"  {k:<22} {cor[k]:>3}/{tot[k]:<3} = {100 * cor[k] / tot[k]:.0f}%")
    print("\nMisses:")
    for r in results:
        if not r["correct"]:
            print(f"  [{r['language']}] Q{r['question_id']} '{r['spoken_answer']}' -> "
                  f"{r['matched_option'] or 'no match'} (want {r['expected_option']!r})")

    out = ROOT.parent / "sample_data" / "voice_answers_500.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0]))
        w.writeheader()
        w.writerows(results)
    print(f"\nwrote {out.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
