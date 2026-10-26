"""
Answer matcher — understands free-form (spoken or typed) answers.

Voice answers rarely match an option word for word ("my eyes are really tired
by evening" vs "Very tired"). Without this, such answers scored a neutral 50.

Layers, first hit wins:
  1. exact      the text is an option
  2. number     0-5 scales: "about a four" -> "4"
  3. yes/no     Yes/No/Maybe questions: "yeah it hurts" -> "Yes", "not really" -> "No"
  4. contains   the option appears in the text (skipping negated mentions)
  5. quantity   time / volume answers: "about ten hours" -> "More than 8 hours"
  6. frequency  "all the time" -> "Always";  intensity  "a bit tiring" -> "Mildly exhausting"
  7. semantic   sentence-embedding similarity (MiniLM via FastEmbed, runs locally)
Nothing confident -> no match (scoring falls back to neutral 50).

Hindi / Kannada (auto-detected from the script, or passed as lang):
  - first the translated option labels shown on screen are matched,
  - then key words are glossed to English (indic_lexicon.py) and the same
    rule layers run. The English embedding model is never used on them.

The app shows the matched option to the user ("Understood as: ...") so they can
correct it before saving — the model suggests, the person decides.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.domain.indic_lexicon import gloss, gloss_romanized, normalize_label

log = logging.getLogger("ergocare.matcher")

MODEL_NAME = os.getenv("MATCHER_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_CACHE = os.getenv("MATCHER_CACHE_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "models_cache"))
SEMANTIC_MIN_SCORE = 0.30      # tuned on scripts/eval_matcher.py
SEMANTIC_MIN_MARGIN = 0.05     # best option must beat the runner-up by this much

NUMBER_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11",
                "twelve": "12", "fifteen": "15", "twenty": "20", "thirty": "30", "forty": "40",
                "forty-five": "45", "fifty": "50", "sixty": "60", "ninety": "90"}
PHRASES = [("half an hour", "30 minutes"), ("half hour", "30 minutes"),
           ("half a litre", "0.5 litres"), ("half a liter", "0.5 litres"),
           ("every hour", "1 hour"), ("hourly", "1 hour"), ("an hour", "1 hour"),
           ("a hour", "1 hour"), ("a litre", "1 litre"), ("a liter", "1 litre"), ("couple of", "2"),
           ("a couple", "2"), ("way below", "far below"), ("lower than", "below"),
           ("below my eyes", "below eye level"), ("below my eye level", "below eye level"),
           ("not sure", "uncertain"), ("unsure", "uncertain")]
# "an hour and a half" / "1 and a half litres" / "2 hours and a half" -> 1.5 hours / 1.5 litres / 2.5 hours
_AND_A_HALF = [(re.compile(r"\b(\d+) and a half (hours?|litres?|liters?)\b"), r"\1.5 \2"),
               (re.compile(r"\b(\d+) (hours?|litres?|liters?) and a half\b"), r"\1.5 \2")]

# Units for quantity answers ("about ten hours", "every twenty minutes")
TIME_UNITS = {"minute": 1, "minutes": 1, "min": 1, "mins": 1, "hour": 60, "hours": 60, "hr": 60, "hrs": 60}
VOLUME_UNITS = {"litre": 1, "litres": 1, "liter": 1, "liters": 1}

# Checked in this order (maybe before no before yes: "not sure" is Maybe, not No)
YN_MAYBE = ["not sure", "uncertain", "maybe", "sometimes","occasionally", "kind of", "sort of", "a little", "a bit",
            "slightly", "somewhat", "depends", "at times", "now and then", "not always", "mild", "once in a while"]
YN_NO = ["not really", "not at all", "never", "nope", "nah", "no", "don't", "do not", "doesn't", "dont",
         "not", "none", "nothing"]
YN_YES = ["yes", "yeah", "yep", "yup", "definitely", "sure", "of course", "always", "a lot", "often",
          "i do", "it does", "very much", "absolutely", "every day", "daily", "constantly", "hurts", "pain"]

# Frequency words -> level 0 (never) .. 4 (always); checked from 4 down
FREQUENCY = [
    (4, ["every day", "everyday", "daily", "always", "all the time", "constantly", "every single", "all day",
         "very often", "very frequently", "each day", "multiple times a day", "several times a day",
         "many times a day", "every evening", "every night", "every morning"]),
    (3, ["often", "frequently", "usually", "regularly", "most days", "a lot", "most of the time", "many times",
         "once a day", "once daily", "once every day", "once each day"]),
    (2, ["sometimes", "occasionally", "once in a while", "now and then", "at times", "some days", "a few times"]),
    (1, ["rarely", "seldom", "hardly", "barely", "almost never", "not often", "not much"]),
    (0, ["never", "not at all", "not once", "not even once", "no never", "don't", "do not", "not really"]),
]
# Intensity words -> level 0 (not) .. 3 (very); "not" is checked first
INTENSITY = [
    (0, ["not at all", "not", "no", "none", "don't", "doesn't", "isn't", "never", "nothing"]),
    (3, ["extremely", "very", "really", "severe", "severely", "terrible", "totally", "completely", "super",
         "way too", "unbearable"]),
    (2, ["quite", "moderately", "moderate", "fairly", "pretty", "rather", "mostly"]),
    (1, ["slightly", "mildly", "mild", "a bit", "a little", "somewhat", "little", "kind of", "sort of", "bit"]),
]
NEGATORS = ("not ", "never ", "isn't ", "isnt ", "aren't ", "no ", "hardly ", "almost ")


@dataclass
class Match:
    option: Optional[str]
    method: str                 # exact | number | yes_no | contains | frequency | semantic | none
    confidence: float
    alternatives: List[Dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"option": self.option, "method": self.method, "confidence": round(self.confidence, 3),
                "alternatives": self.alternatives}


# ── Text helpers ──────────────────────────────────────────────────────────────
def normalize(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"[^a-z0-9'<>.\-\s]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)          # keep decimal points only
    t = " ".join(NUMBER_WORDS.get(w, w) for w in t.split())
    t = re.sub(r"\b([2-9]0) ([1-9])\b", lambda m: str(int(m[1]) + int(m[2])), t)   # "forty five" -> 45
    t = re.sub(r"\b(\d+) (?:or|to) (\d+)\b", r"\1-\2", t)          # "3 or 4" -> "3-4"
    t = re.sub(r"\s+", " ", t).strip()
    for a, b in PHRASES:
        t = re.sub(rf"(?<![a-z0-9']){re.escape(a)}(?![a-z0-9'])", b, t)
    for pattern, repl in _AND_A_HALF:
        t = pattern.sub(repl, t)
    return t


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z0-9']){re.escape(phrase)}(?![a-z0-9'])", text) is not None


def _level(text: str, table) -> Optional[int]:
    if table is FREQUENCY:
        # Longest phrase wins: "once every day" is once a day, not "every day";
        # "not often" is rarely, not "often"; "very often" beats "often".
        hits = [(len(p), level) for level, phrases in table for p in phrases if _has(text, p)]
        return max(hits)[1] if hits else None
    for level, phrases in table:          # INTENSITY: negation ("not") is checked first
        if any(_has(text, p) for p in phrases):
            return level
    return None


def _frequency_level(text: str) -> Optional[int]:
    return _level(text, FREQUENCY)


def _nearest_level(options: List[str], text: str, table, min_options: int) -> Optional[str]:
    """Pick the option whose level (from table) is closest to the answer's level."""
    opt_levels = {o: _level(normalize(o), table) for o in options}
    known = [o for o, v in opt_levels.items() if v is not None]
    if len(known) < min_options:
        return None
    level = _level(text, table)
    if level is None:
        return None
    return min(known, key=lambda o: (abs(opt_levels[o] - level), -opt_levels[o]))


# ── Quantities ("about ten hours", "every twenty minutes", "1-2 litres") ──────
def _unit_of(text: str) -> Optional[tuple]:
    for w in re.findall(r"[a-z]+", text):
        if w in TIME_UNITS:
            return "time", TIME_UNITS[w]
        if w in VOLUME_UNITS:
            return "volume", VOLUME_UNITS[w]
    return None


def _option_range(option: str, default_unit: Optional[tuple]) -> Optional[tuple]:
    """'Less than 30 minutes' -> ('time', 0, 30); '1-2 hours' -> ('time', 60, 120); '>8' + hours -> ('time', 480, inf)."""
    o = normalize(option)
    unit = _unit_of(o) or default_unit
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", o)]
    if not unit or not nums or "times" in o:
        return None
    kind, mult = unit
    if re.search(r"less than|under|<", o):
        return kind, 0.0, nums[0] * mult
    if re.search(r"more than|over|>", o):
        return kind, nums[0] * mult, float("inf")
    if len(nums) >= 2:
        return kind, nums[0] * mult, nums[1] * mult
    return kind, nums[0] * mult * 0.75, nums[0] * mult * 1.25


def _quantity_match(question: dict, t: str) -> Optional[str]:
    q_text = normalize(question.get("text", ""))
    default_unit = _unit_of(q_text)
    ranges = {o: _option_range(o, default_unit) for o in question["options"]}
    if not all(ranges.values()):
        return None
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", t)]
    unit = _unit_of(t) or default_unit
    if not nums or not unit or unit[0] != next(iter(ranges.values()))[0]:
        return None
    value = (sum(nums[:2]) / len(nums[:2])) * unit[1]    # "between 1 and 2 hours" -> 1.5 h
    if re.search(r"less than|under|below", t):
        value *= 0.9
    elif re.search(r"more than|over|above", t):
        value *= 1.1
    inside = [o for o, (_, lo, hi) in ranges.items() if lo <= value <= hi]
    if inside:                                           # narrowest range that contains it
        return min(inside, key=lambda o: ranges[o][2] - ranges[o][1])
    return min(ranges, key=lambda o: min(abs(value - ranges[o][1]), abs(value - ranges[o][2])))


# ── Semantic layer (lazy, optional) ───────────────────────────────────────────
class _Semantic:
    def __init__(self) -> None:
        self._model = None
        self._failed = False
        self._lock = threading.Lock()
        self._option_cache: Dict[tuple, list] = {}

    @property
    def available(self) -> bool:
        return self._model is not None

    def load(self) -> bool:
        with self._lock:
            if self._model is not None or self._failed:
                return self._model is not None
            try:
                from fastembed import TextEmbedding
                os.makedirs(MODEL_CACHE, exist_ok=True)
                self._model = TextEmbedding(MODEL_NAME, cache_dir=MODEL_CACHE)
                log.info("answer matcher: loaded %s", MODEL_NAME)
            except Exception as exc:          # not installed / offline on first run
                self._failed = True
                log.warning("answer matcher: semantic layer unavailable (%s) - using rules only", exc)
            return self._model is not None

    def _embed(self, texts: List[str]):
        import numpy as np
        vecs = np.array(list(self._model.embed(texts)))
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)

    def rank(self, question: dict, text: str) -> List[tuple]:
        """[(option, cosine similarity)] best first."""
        key = (question["id"], tuple(question["options"]))
        if key not in self._option_cache:
            if len(self._option_cache) > 100:
                self._option_cache.clear()
            self._option_cache[key] = self._embed(question["options"])
        opts = self._option_cache[key]
        q = self._embed([text])[0]
        sims = opts @ q
        return sorted(zip(question["options"], sims.tolist()), key=lambda x: -x[1])


semantic = _Semantic()


def warm_up() -> None:
    """Load the model in the background at start-up so the first answer is fast."""
    threading.Thread(target=semantic.load, daemon=True).start()


# ── Language helpers ──────────────────────────────────────────────────────────
def detect_lang(text: str) -> str:
    """'hi' for Devanagari, 'kn' for Kannada script, else 'en'."""
    deva = sum("ऀ" <= ch <= "ॿ" for ch in text)
    kan = sum("ಀ" <= ch <= "೿" for ch in text)
    if max(deva, kan) == 0:
        return "en"
    return "hi" if deva >= kan else "kn"


def _match_indic(question: dict, text: str, lang: str, labels: Optional[List[str]]) -> Match:
    options: List[str] = question["options"]
    yes_no = {o.lower() for o in options} == {"yes", "no", "maybe"}
    if labels and len(labels) == len(options):
        t = normalize_label(text)
        by_label = {normalize_label(lbl): opt for lbl, opt in zip(labels, options)}
        if t in by_label:
            return Match(by_label[t], "label", 1.0)
        if not yes_no:                     # "पता नहीं" must not match the label "नहीं"
            for lbl in sorted(by_label, key=len, reverse=True):
                if len(lbl) >= 2 and lbl in t:
                    return Match(by_label[lbl], "label", 0.9)
    english = gloss(text, lang)
    if english:
        m = match_answer(question, english, use_semantic=False, lang="en")
        if m.option:
            return Match(m.option, f"{m.method} ({lang})", round(m.confidence * 0.95, 3))
    return Match(None, "none", 0.0)


# ── Matcher ───────────────────────────────────────────────────────────────────
def match_answer(question: dict, text: Optional[str], use_semantic: bool = True,
                 lang: Optional[str] = None, labels: Optional[List[str]] = None,
                 romanized: bool = True) -> Match:
    if not text or not text.strip():
        return Match(None, "none", 0.0)
    script = detect_lang(text)
    if script in ("hi", "kn"):
        return _match_indic(question, text, script, labels)
    # Latin script: may still be Hindi/Kannada ("ek ghanta") - try its English keywords first
    if romanized:
        english = gloss_romanized(text)
        if english:
            m = match_answer(question, english, use_semantic=False, romanized=False)
            if m.option:
                return Match(m.option, f"{m.method} (romanised)", round(m.confidence * 0.95, 3))
    options: List[str] = question["options"]
    t = normalize(text)
    norm_opts = {normalize(o): o for o in options}

    # 1. exact
    if t in norm_opts:
        return Match(norm_opts[t], "exact", 1.0)
        
    # Issue 10: Specific positive phrasing for "Never" options
    POSITIVE_TO_NEVER = [
        "sleep fine", "sleep well", "sleep great", "lighting is good",
        "good lighting", "sit all day", "sit the whole day",
    ]
    if any(p in t for p in POSITIVE_TO_NEVER) and "Never" in norm_opts.values():
        return Match("Never", "positive_to_never", 0.95)

    # 2. number scales (0-5)
    if all(o.strip().isdigit() for o in options):
        for n in re.findall(r"\d+", t):
            if n in norm_opts:
                return Match(norm_opts[n], "number", 0.95)

    # 3. yes / no / maybe
    if {o.lower() for o in options} == {"yes", "no", "maybe"}:
        by_lower = {o.lower(): o for o in options}
        for label, phrases in (("maybe", YN_MAYBE), ("no", YN_NO), ("yes", YN_YES)):
            if any(_has(t, p) for p in phrases):
                return Match(by_lower[label], "yes_no", 0.9)

    # 4. option text inside the answer (longest option first, skip "not <option>")
    for no in sorted(norm_opts, key=len, reverse=True):
        if len(no) < 3:
            continue
        m = re.search(rf"(?<![a-z0-9']){re.escape(no)}(?![a-z0-9'])", t)
        if m and not any(t[:m.start()].endswith(neg) for neg in NEGATORS):
            return Match(norm_opts[no], "contains", 0.9)

    # 5. quantities (time / volume ranges)
    q = _quantity_match(question, t)
    if q:
        return Match(q, "quantity", 0.85)

    # 6. frequency and intensity scales
    f = _nearest_level(options, t, FREQUENCY, min_options=2)
    if f:
        return Match(f, "frequency", 0.8)
    i = _nearest_level(options, t, INTENSITY, min_options=3)
    if i:
        return Match(i, "intensity", 0.8)

    # 7. semantic similarity
    if use_semantic and (semantic.available or semantic.load()):
        ranked = semantic.rank(question, text)
        alts = [{"option": o, "score": round(s, 3)} for o, s in ranked[:3]]
        (best, s1), s2 = ranked[0], (ranked[1][1] if len(ranked) > 1 else 0.0)
        if s1 >= SEMANTIC_MIN_SCORE and s1 - s2 >= SEMANTIC_MIN_MARGIN:
            return Match(best, "semantic", s1, alts)
        return Match(None, "none", s1, alts)

    return Match(None, "none", 0.0)
