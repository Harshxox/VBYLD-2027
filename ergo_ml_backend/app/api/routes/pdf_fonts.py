"""
Unicode fonts for the PDF report.

ReportLab's built-in Type-1 fonts (Helvetica, Times, Courier) only cover WinAnsi.
Anything outside Latin-1 - Hindi in Devanagari, Kannada in Kannada script - is drawn
as a black box or dropped silently. Participants answer in Hindi and Kannada, and
the PDF prints their own words back to them (free-text answers and voice
transcripts), so the fonts have to be embedded.

Noto Sans Devanagari and Noto Sans Kannada are bundled under app/fonts/ and are
licensed under the SIL Open Font License 1.1 (see app/fonts/OFL.txt).

ReportLab has no automatic font fallback: a Paragraph renders every glyph with
the one font in its style. :func:`mark_script_runs` therefore splits a string into
runs and wraps each run in a <font> tag pointing at a font that actually has the
glyphs, which is what lets a single sentence mix Latin and Indic.
"""
import os
import re
import threading

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "fonts"
)
FONT_DIR = os.path.normpath(FONT_DIR)

DEVA_FONT = "NotoSansDevanagari"
KNDA_FONT = "NotoSansKannada"

_registered = False
_lock = threading.Lock()

# Unicode blocks that decide which embedded font a character needs.
_DEVA_RE = re.compile(
    "[\u0900-\u097f\u1cd0-\u1cff\u200c\u200d\u20b9\u25cc\u0964\u0965]"
)
_KNDA_RE = re.compile("[\u0c80-\u0cff\u1cd0-\u1cff\u200c\u200d\u20b9]")

# Markup that must never be interpreted inside user-supplied text.
_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def register_fonts() -> bool:
    """Register the bundled Unicode fonts. Returns True if Indic is available.

    Failure is not fatal: the report still renders, it just cannot show
    Devanagari or Kannada glyphs.
    """
    global _registered
    with _lock:
        if _registered:
            return True
        ok = True
        for name in (DEVA_FONT, KNDA_FONT):
            path = os.path.join(FONT_DIR, f"{name}-Regular.ttf")
            try:
                pdfmetrics.registerFont(TTFont(name, path))
            except Exception:  # missing file or unreadable font
                ok = False
        _registered = ok
        return ok


def _escape(text: str) -> str:
    for old, new in _ESCAPES:
        text = text.replace(old, new)
    return text


def _font_for(char: str):
    if _DEVA_RE.match(char):
        return DEVA_FONT
    if _KNDA_RE.match(char):
        return KNDA_FONT
    return None


def has_indic(text: str) -> bool:
    return bool(_DEVA_RE.search(text or "") or _KNDA_RE.search(text or ""))


def mark_script_runs(text, base_font: str = "Helvetica") -> str:
    """Wrap each run of text in a <font> tag that can actually render it.

    Keeps Latin runs on `base_font` so the document keeps its original
    typography, and switches only the Indic runs to the embedded Noto fonts.
    Safe to call on user input: markup characters are escaped first.
    """
    if not text:
        return ""
    text = str(text)
    if not has_indic(text):
        return _escape(text)

    register_fonts()

    # Font needed for each character. None means "script-neutral" (Latin,
    # spaces, punctuation, digits).
    fonts = [_font_for(c) for c in text]

    out = []
    run = []
    run_font = None

    def flush():
        if not run:
            return
        chunk = _escape("".join(run))
        if run_font and run_font != base_font:
            out.append(f'<font name="{run_font}">{chunk}</font>')
        else:
            out.append(chunk)
        run.clear()

    for i, want in enumerate(fonts):
        if want is None:
            # Neutral characters join the run they are surrounded by, so the
            # spaces between two words of one script do not split it into
            # dozens of tiny <font> tags.
            prev = next((f for f in reversed(fonts[:i]) if f), None)
            nxt = next((f for f in fonts[i + 1:] if f), None)
            join = prev if prev == nxt else nxt
            if run and join == run_font:
                run.append(text[i])
                continue
            if not run:
                run_font = None          # leading neutral text, base font
                run.append(text[i])
                continue
            flush()
            run_font = None
            run.append(text[i])
            continue
        if want != run_font:
            flush()
            run_font = want
        run.append(text[i])
    flush()
    return "".join(out)