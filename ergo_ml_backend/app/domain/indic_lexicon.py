"""
Hindi / Kannada keyword glossary for the answer matcher.

Spoken Hindi/Kannada answers are turned into the English keywords the rule
layers already understand ("मुझे हमेशा दर्द होता है" -> "always pain"), then
matched with the same rules as English. Only the words that decide an answer
are listed: numbers, yes/no/maybe, frequency, intensity and units.

Hindi words are matched as whole words. Kannada adds suffixes to words
(ನೋವು -> ನೋವಾಗುತ್ತದೆ), so Kannada entries match the START of a word.
⚠ Have a native speaker extend and review these lists.
"""
import re
from typing import List, Tuple

DIGITS = str.maketrans("०१२३४५६७८९೦೧೨೩೪೫೬೭೮೯", "01234567890123456789")

# (phrase, English gloss). Longer phrases are tried first.
HI: List[Tuple[str, str]] = [
    ("बिल्कुल नहीं", "not at all"), ("कभी नहीं", "never"), ("कभी भी नहीं", "never"), ("पता नहीं", "not sure"),
    ("कभी-कभी", "sometimes"), ("कभी कभी", "sometimes"), ("कभी-कभार", "occasionally"), ("कभी कभार", "occasionally"),
    ("शायद ही", "rarely"), ("बहुत कम", "rarely"), ("हर दिन", "every day"), ("रोज़ाना", "every day"), ("रोजाना", "every day"),
    ("जी हाँ", "yes"), ("से ज़्यादा", "more than"), ("से ज्यादा", "more than"), ("से अधिक", "more than"), ("से कम", "less than"),
    ("आधा घंटा", "30 minutes"), ("दिन में कई बार", "multiple times a day"), ("दिन में एक बार", "once a day"),
    ("हाँ", "yes"), ("हां", "yes"), ("नहीं", "no"), ("नही", "no"), ("शायद", "maybe"),
    ("हमेशा", "always"), ("रोज़", "every day"), ("रोज", "every day"), ("प्रतिदिन", "every day"), ("दिनभर", "all day"),
    ("अक्सर", "often"), ("ज़्यादातर", "mostly"), ("ज्यादातर", "mostly"), ("बार-बार", "often"),
    ("बहुत", "very"), ("बेहद", "extremely"), ("अत्यधिक", "extremely"), ("काफ़ी", "quite"), ("काफी", "quite"),
    ("थोड़ा", "a little"), ("थोड़ी", "a little"), ("हल्का", "mild"), ("हल्की", "mild"), ("मध्यम", "moderate"),
    ("गंभीर", "severe"), ("दर्द", "pain"), ("पूरी तरह", "completely"),
    ("घंटे", "hours"), ("घंटा", "hour"), ("घंटों", "hours"), ("मिनट", "minutes"), ("लीटर", "litres"),
    ("शून्य", "0"), ("एक", "1"), ("दो", "2"), ("तीन", "3"), ("चार", "4"), ("पाँच", "5"), ("पांच", "5"),
    ("छह", "6"), ("छः", "6"), ("सात", "7"), ("आठ", "8"), ("नौ", "9"), ("दस", "10"),
]

KN: List[Tuple[str, str]] = [
    ("ಇಲ್ಲವೇ ಇಲ್ಲ", "not at all"), ("ಎಂದಿಗೂ ಇಲ್ಲ", "never"), ("ಎಂದೂ ಇಲ್ಲ", "never"), ("ತುಂಬಾ ಕಡಿಮೆ", "rarely"),
    ("ದಿನಕ್ಕೆ ಹಲವು ಬಾರಿ", "multiple times a day"), ("ದಿನಕ್ಕೆ ಒಮ್ಮೆ", "once a day"),
    ("ಗೊತ್ತಿಲ್ಲ", "not sure"), ("ಖಚಿತವಿಲ್ಲ", "not sure"), ("ಹೌದು", "yes"), ("ಹೂಂ", "yes"), ("ಖಂಡಿತ", "yes"),
    ("ಬಹುಶಃ", "maybe"), ("ಕೆಲವೊಮ್ಮೆ", "sometimes"), ("ಒಮ್ಮೊಮ್ಮೆ", "occasionally"),
    ("ಯಾವಾಗಲೂ", "always"), ("ಸದಾ", "always"), ("ಪ್ರತಿದಿನ", "every day"), ("ದಿನಾಲೂ", "every day"), ("ದಿನವೂ", "every day"),
    ("ಆಗಾಗ್ಗೆ", "often"), ("ಹೆಚ್ಚಾಗಿ", "often"), ("ಅಪರೂಪ", "rarely"), ("ವಿರಳ", "rarely"),
    ("ತುಂಬಾ", "very"), ("ಬಹಳ", "very"), ("ಅತಿಯಾ", "extremely"), ("ಸಾಕಷ್ಟು", "quite"), ("ಸ್ವಲ್ಪ", "a little"),
    ("ಮಧ್ಯಮ", "moderate"), ("ತೀವ್ರ", "severe"), ("ನೋವ", "pain"), ("ಸಂಪೂರ್ಣ", "completely"),
    ("ಗಂಟೆ", "hours"), ("ನಿಮಿಷ", "minutes"), ("ಲೀಟರ್", "litres"), ("ಹೆಚ್ಚು", "more than"), ("ಕಡಿಮೆ", "less than"),
    ("ಇಲ್ಲ", "no"), ("ಬೇಡ", "no"),
    ("ಸೊನ್ನೆ", "0"), ("ಒಂದು", "1"), ("ಎರಡು", "2"), ("ಮೂರು", "3"), ("ನಾಲ್ಕು", "4"), ("ಐದು", "5"),
    ("ಆರು", "6"), ("ಏಳು", "7"), ("ಎಂಟು", "8"), ("ಒಂಬತ್ತು", "9"), ("ಹತ್ತು", "10"),
]

LEXICONS = {"hi": HI, "kn": KN}

# Fractions and the larger numbers people use for minutes ("बीस मिनट", "ಒಂದೂವರೆ ಗಂಟೆ")
HI += [
    ("हर घंटे", "1 hour"), ("हर एक घंटे", "1 hour"), ("डेढ़", "1.5"), ("डेढ", "1.5"), ("ढाई", "2.5"),
    ("सवा", "1.25"), ("पौने", "0.75"), ("आधा", "0.5"), ("आधे", "0.5"),
    ("ग्यारह", "11"), ("बारह", "12"), ("पंद्रह", "15"), ("बीस", "20"), ("पच्चीस", "25"), ("तीस", "30"),
    ("चालीस", "40"), ("पैंतालीस", "45"), ("पचास", "50"), ("साठ", "60"),
]
KN += [
    ("ಪ್ರತಿ ಗಂಟೆ", "1 hour"), ("ಒಂದೂವರೆ", "1.5"), ("ಎರಡೂವರೆ", "2.5"), ("ಅರ್ಧ", "0.5"),
    ("ಹದಿನೈದು", "15"), ("ಇಪ್ಪತ್ತು", "20"), ("ಮೂವತ್ತು", "30"), ("ನಲವತ್ತು", "40"), ("ಐವತ್ತು", "50"),
    ("ಅರವತ್ತು", "60"),
]

# English words that a Hindi speech recogniser writes in Devanagari
# ("one hour" -> "वन आवर"); added to the Hindi list.
HI += [
    ("ऑवर्स", "hours"), ("आवर्स", "hours"), ("ऑवर", "hour"), ("आवर", "hour"), ("मिनट्स", "minutes"),
    ("यस", "yes"), ("नेवर", "never"), ("ऑलवेज", "always"), ("समटाइम्स", "sometimes"), ("सम टाइम्स", "sometimes"),
    ("ऑफन", "often"), ("रेयरली", "rarely"), ("वेरी", "very"), ("डेली", "every day"), ("मेबी", "maybe"),
]

# ── Romanised Hindi / Kannada ("ek ghanta", "tumba sustagutte") ──────────────
# A browser set to English writes Hindi/Kannada speech in Latin letters, and many
# people type that way too. Same idea as above: key words -> English keywords.
HI_ROMAN: List[Tuple[str, str]] = [
    ("bilkul nahi", "not at all"), ("bilkul nahin", "not at all"), ("kabhi bhi nahi", "never"),
    ("kabhi nahi", "never"), ("kabhi nahin", "never"), ("pata nahi", "not sure"), ("pata nahin", "not sure"),
    ("kabhi kabhi", "sometimes"), ("kabhi kabhar", "occasionally"), ("shayad hi", "rarely"),
    ("bahut kam", "rarely"), ("bohot kam", "rarely"), ("har din", "every day"), ("har roz", "every day"),
    ("din mein kai baar", "multiple times a day"), ("din me kai baar", "multiple times a day"),
    ("din mein ek baar", "once a day"), ("din me ek baar", "once a day"), ("ji haan", "yes"),
    ("se zyada", "more than"), ("se jyada", "more than"), ("se jada", "more than"), ("se adhik", "more than"),
    ("se kam", "less than"), ("aadha ghanta", "30 minutes"), ("adha ghanta", "30 minutes"),
    ("aadhe ghante", "30 minutes"), ("dedh ghanta", "1.5 hours"), ("dedh ghante", "1.5 hours"),
    ("dhai ghante", "2.5 hours"), ("baar baar", "often"), ("puri tarah", "completely"), ("poori tarah", "completely"),
    ("haan", "yes"), ("haanji", "yes"), ("haa", "yes"), ("nahi", "no"), ("nahin", "no"), ("nai", "no"),
    ("shayad", "maybe"), ("hamesha", "always"), ("humesha", "always"), ("hamesa", "always"),
    ("roz", "every day"), ("roj", "every day"), ("rozana", "every day"), ("rojana", "every day"),
    ("pratidin", "every day"), ("aksar", "often"), ("zyadatar", "mostly"), ("jyadatar", "mostly"),
    ("bahut", "very"), ("bohot", "very"), ("bahot", "very"), ("bhot", "very"), ("behad", "extremely"),
    ("kaafi", "quite"), ("kafi", "quite"), ("thoda", "a little"), ("thodi", "a little"), ("thora", "a little"),
    ("halka", "mild"), ("halki", "mild"), ("madhyam", "moderate"), ("gambhir", "severe"), ("dard", "pain"),
    ("ghanta", "hour"), ("ghante", "hours"), ("ghanton", "hours"), ("ghantey", "hours"), ("minat", "minutes"),
    ("shunya", "0"), ("ek", "1"), ("do", "2"), ("teen", "3"), ("char", "4"), ("chaar", "4"),
    ("paanch", "5"), ("panch", "5"), ("chhe", "6"), ("chhah", "6"), ("saat", "7"), ("aath", "8"),
    ("nau", "9"), ("das", "10"),
    ("har ghante", "1 hour"), ("har ek ghante", "1 hour"), ("dedh", "1.5"), ("dhai", "2.5"), ("sawa", "1.25"),
    ("paune", "0.75"), ("aadha", "0.5"), ("adha", "0.5"), ("aadhe", "0.5"), ("adhe", "0.5"),
    ("minute", "minutes"), ("gyarah", "11"), ("barah", "12"), ("pandrah", "15"), ("bees", "20"), ("pachees", "25"), ("tees", "30"),
    ("chalis", "40"), ("paintalis", "45"), ("pachas", "50"),
]
KN_ROMAN: List[Tuple[str, str]] = [
    ("illave illa", "not at all"), ("yavattu illa", "never"), ("endigu illa", "never"), ("endu illa", "never"),
    ("tumba kadime", "rarely"), ("thumba kadime", "rarely"), ("dinakke halavu baari", "multiple times a day"),
    ("dinakke omme", "once a day"), ("gottilla", "not sure"), ("gothilla", "not sure"), ("houdu", "yes"),
    ("haudu", "yes"), ("bahusha", "maybe"), ("kelavomme", "sometimes"), ("ommomme", "occasionally"),
    ("yavaglu", "always"), ("yavagalu", "always"), ("pratidina", "every day"), ("dinalu", "every day"),
    ("agagge", "often"), ("aagaagge", "often"), ("hecchagi", "often"), ("aparupa", "rarely"),
    ("aparoopa", "rarely"), ("virala", "rarely"), ("tumba", "very"), ("thumba", "very"), ("bahala", "very"),
    ("saakashtu", "quite"), ("swalpa", "a little"), ("svalpa", "a little"), ("madhyama", "moderate"),
    ("teevra", "severe"), ("tivra", "severe"), ("novu", "pain"), ("noovu", "pain"), ("nova", "pain"),
    ("sampurna", "completely"), ("gante", "hours"), ("nimisha", "minutes"), ("hecchu", "more than"),
    ("hechchu", "more than"), ("kadime", "less than"), ("illa", "no"), ("beda", "no"), ("sonne", "0"),
    ("ondu", "1"), ("eradu", "2"), ("yeradu", "2"), ("mooru", "3"), ("muru", "3"), ("naalku", "4"),
    ("nalku", "4"), ("aidu", "5"), ("aaru", "6"), ("elu", "7"), ("yelu", "7"), ("entu", "8"),
    ("yentu", "8"), ("ombattu", "9"), ("hattu", "10"),
    ("prati gante", "1 hour"), ("ondoovare", "1.5"), ("onduvare", "1.5"), ("eradoovare", "2.5"), ("ardha", "0.5"),
    ("hadinaidu", "15"), ("ippattu", "20"), ("moovattu", "30"), ("nalavattu", "40"), ("aivattu", "50"),
    ("aravattu", "60"),
]
# Also everyday English words: only translated when the answer has other Hindi/Kannada words.
ROMAN_AMBIGUOUS = {"do", "char", "das", "nai", "haa", "elu", "nova", "beda", "bees", "minute"}
_KN_ROMAN_KEYS = {p for p, _ in KN_ROMAN}


def gloss_romanized(text: str) -> "str | None":
    """'ek ghanta' -> '1 hour'; 'kannu tumba sustagutte' -> 'kannu very sustagutte'.

    Returns None when the text has no clear Hindi/Kannada word, so English
    answers ("I do it") are never rewritten - unless every word is Hindi/Kannada
    ("char" alone on a 0-5 scale is 4). Words it doesn't know are kept.
    """
    words = re.findall(r"\d+(?:\.\d+)?|[a-z']+", text.lower())     # "Ghanta." -> "ghanta"
    phrases = sorted(HI_ROMAN + KN_ROMAN, key=lambda p: -len(p[0].split()))

    def hit_at(i: int):
        for phrase, en in phrases:
            parts = phrase.split()
            window = words[i:i + len(parts)]
            if len(window) < len(parts):
                continue
            # Kannada adds suffixes (gantege, novagutte): longer words match word starts
            if phrase in _KN_ROMAN_KEYS:
                ok = all(w.startswith(p) if len(p) >= 4 else w == p for w, p in zip(window, parts))
            else:
                ok = window == parts
            if ok:
                return phrase, en, len(parts)
        return None

    out: List[str] = []
    found_clear, all_known, any_hit = False, True, False
    i = 0
    while i < len(words):
        h = hit_at(i)
        if h:
            phrase, en, n = h
            found_clear |= phrase not in ROMAN_AMBIGUOUS
            any_hit = True
            out.append(en)
            i += n
        else:
            all_known &= words[i][0].isdigit()
            out.append(words[i])
            i += 1
    return " ".join(out) if found_clear or (any_hit and all_known) else None


def tokens(text: str) -> List[str]:
    t = text.translate(DIGITS)
    t = re.sub(r"[।,.!?;:()\"'“”‘’]", " ", t)
    return t.split()


def gloss(text: str, lang: str) -> str:
    """Translate the answer's key words into English keywords (others are dropped)."""
    lexicon = LEXICONS.get(lang)
    if not lexicon:
        return text
    words = tokens(text)
    out: List[str] = []
    i = 0
    phrases = sorted(lexicon, key=lambda p: -len(p[0].split()))
    while i < len(words):
        w = words[i]
        if re.fullmatch(r"[0-9a-zA-Z\-.]+", w):          # digits / English words (code-mixing) pass through
            out.append(w.lower())
            i += 1
            continue
        for phrase, en in phrases:
            parts = phrase.split()
            window = words[i:i + len(parts)]
            if len(window) < len(parts):
                continue
            if lang == "kn":                              # agglutinative: match word starts
                hit = all(a.startswith(b) for a, b in zip(window, parts))
            else:
                hit = window == parts
            if hit:
                out.append(en)
                i += len(parts)
                break
        else:
            i += 1
    return " ".join(out)


def normalize_label(text: str) -> str:
    return " ".join(tokens(text)).lower()
