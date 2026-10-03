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
