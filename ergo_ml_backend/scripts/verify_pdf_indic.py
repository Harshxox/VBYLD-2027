"""
End-to-end check that the PDF report renders Indic scripts.

Builds a throwaway session with Hindi and Kannada answers, generates the PDF and
reads the text back out. Checking the bytes alone is not enough - a PDF with
missing glyphs still returns HTTP 200 and still opens - so this decodes the
embedded ToUnicode CMap and asserts the original codepoints survive the round
trip. That is the difference between "the font is embedded" and "the user's own
words are actually in the document".

Extraction is font-aware on purpose. ReportLab subsets each embedded font into
its OWN single-byte code space (<00>-<7F>), so code 0x08 means U+0914 in
NotoSansDevanagari but something else entirely in NotoSansKannada. Merging both
CMaps into one dict silently lets whichever font was parsed last overwrite the
other, which makes correct PDFs look broken. So the content stream is walked with
the current /Fn font tracked, and each string is decoded with that font's CMap.
Latin is drawn with a base-14 Type-1 font, which has no ToUnicode CMap at all -
those strings are literal and are read as-is.

Run from ergo_ml_backend:  python scripts/verify_pdf_indic.py
"""
import base64
import io
import os
import re
import sys
import tempfile
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import Base                                # noqa: E402
from app.models.assessment import (                             # noqa: E402
    AssessmentSession, AssessmentAnswer,
)
from app.domain.questions import QUESTIONS                      # noqa: E402
from app.domain.scoring import calculate_scores, build_report   # noqa: E402
from app.api.routes.pdf_fonts import register_fonts             # noqa: E402
from app.api.routes.reports import _generate_pdf                # noqa: E402
from sqlalchemy import create_engine                            # noqa: E402
from sqlalchemy.orm import sessionmaker                         # noqa: E402

HINDI = "मेरे गर्दन और कमर में बहुत दर्द होता है"
KANNADA = "ನನ್ನ ಕಾವಯದಲ್ಲಿ ಬಹಳ ಗಾರಡಕೆ ಇದೆ"
LATIN_NAME = "Ravi Kumar"


def build_session(db):
    sess = AssessmentSession(
        id="indic-verify-0001",
        client_name=LATIN_NAME,
        client_email="ravi@example.com",
        client_phone="+91 90000 00000",
        client_age=34,
        client_job="Data entry",
        input_mode="voice",
    )
    db.add(sess)
    db.flush()

    picks = [(31, HINDI), (35, KANNADA), (33, "Moderate")]
    for qid, text in picks:
        q = next(x for x in QUESTIONS if x["id"] == qid)
        db.add(AssessmentAnswer(
            session_id=sess.id, question_id=qid, question_text=q["text"],
            typed_answer=None, transcript=text, audio_url=None,
        ))

    answers = [{"question_id": qid, "typed_answer": None, "transcript": t}
               for qid, t in picks]
    scores, ml = calculate_scores(answers)
    sess.report_json = build_report(scores, ml, answers).model_dump()
    sess.overall_risk = scores.overall_risk
    db.commit()
    return sess


# ── Minimal PDF reader ────────────────────────────────────────────────────────

_OBJ_RE = re.compile(r"(\d+)\s+0\s+obj\b(.*?)\bendobj", re.S)


def _inflate(body: str) -> str | None:
    """
    Decode a stream's /Filter chain and return it as latin-1 text, or None.

    ReportLab's default is ASCII85 followed by Flate, and page content is the one
    stream that matters here - decoding only the Flate layer silently finds
    nothing, which looks exactly like a PDF with no text in it.
    """
    m = re.search(r"stream\r?\n", body)
    if not m:
        return None
    start = m.end()
    end = body.find("endstream", start)
    if end == -1:
        return None
    data = body[start:end].encode("latin-1")

    header = body[:m.start()]
    filters = re.findall(r"/(ASCII85Decode|FlateDecode|ASCIIHexDecode)", header)
    for filt in filters:
        try:
            if filt == "ASCII85Decode":
                payload = data.split(b"~>")[0]
                data = base64.a85decode(payload, adobe=False, ignorechars=b" \t\r\n\x0c")
            elif filt == "ASCIIHexDecode":
                hexpart = data.split(b">")[0]
                data = bytes.fromhex(re.sub(rb"[^0-9A-Fa-f]", b"", hexpart).decode())
            else:
                data = zlib.decompress(data)
        except Exception:
            return None
    return data.decode("latin-1")


def _parse_cmap(text: str) -> dict[int, str]:
    """code -> unicode, from one ToUnicode CMap."""
    cmap: dict[int, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", text, re.S):
        for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            cmap[int(src, 16)] = "".join(
                chr(int(dst[i:i + 4], 16)) for i in range(0, len(dst), 4))
    for block in re.findall(r"beginbfrange(.*?)endbfrange", text, re.S):
        for lo, hi, dst in re.findall(
                r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
            lo_i, hi_i, base = int(lo, 16), int(hi, 16), int(dst, 16)
            for k in range(lo_i, min(hi_i, lo_i + 4096) + 1):
                cmap[k] = chr(base + k - lo_i)
    return cmap


def _literal_codes(body: str) -> list[int]:
    """
    Decode a PDF literal string body into its byte values.

    Handles \\( \\) \\\\ and \\ddd octal escapes, plus the usual single-character
    escapes. ReportLab emits Indic text like (\\001\\002\\003) for subset codes
    1,2,3, so the octal form is the normal case here, not an edge case.
    """
    codes: list[int] = []
    i, n = 0, len(body)
    simple = {"n": 10, "r": 13, "t": 9, "b": 8, "f": 12,
              "(": 40, ")": 41, "\\": 92}
    while i < n:
        ch = body[i]
        if ch != "\\":
            codes.append(ord(ch))
            i += 1
            continue
        i += 1
        if i >= n:
            break
        esc = body[i]
        if esc in "01234567":                       # up to 3 octal digits
            digits = ""
            while i < n and len(digits) < 3 and body[i] in "01234567":
                digits += body[i]
                i += 1
            codes.append(int(digits, 8) & 0xFF)
            continue
        if esc == "\n":                             # line continuation
            i += 1
            continue
        codes.append(simple.get(esc, ord(esc)))
        i += 1
    return codes


class PdfText:
    """Pulls visible text out of a ReportLab PDF, tracking the active font."""

    def __init__(self, pdf_bytes: bytes):
        self.raw = pdf_bytes.decode("latin-1")
        bodies = {int(n): b for n, b in _OBJ_RE.findall(self.raw)}

        # font object number -> its ToUnicode cmap (absent for base-14 fonts)
        self.font_cmaps: dict[int, dict[int, str]] = {}
        # resource name (/F1) -> font object number
        self.resources: dict[str, int] = {}
        for num, body in bodies.items():
            if "/Type" in body and "/Font" in body:
                tu = re.search(r"/ToUnicode\s+(\d+)\s+0\s+R", body)
                if tu:
                    stream = _inflate(bodies.get(int(tu.group(1)), "") or "")
                    if stream:
                        self.font_cmaps[num] = _parse_cmap(stream)
            for name, ref in re.findall(r"/(F\d+(?:\+\d+)?)\s+(\d+)\s+0\s+R", body):
                self.resources.setdefault(name, int(ref))

        self.content = [b for b in (_inflate(v) for v in bodies.values()) if b]
        self.drawn: set[str] = set()
        self.text: list[str] = []

    def extract(self) -> str:
            # ReportLab writes subset-font text in whichever of the two string forms
            # is shorter: hex <...> or a literal (...) with octal escapes. Indic text
            # arrives as literal single-byte codes ((\001\002) == codes 1,2), so the
            # literal branch must decode octal escapes and map each byte through the
            # active font's CMap - reading those bytes as Latin-1 turns real Hindi
            # into control characters.
            token = re.compile(
                r"/(F\d+(?:\+\d+)?)\s+[\d.]+\s+Tf"           # 1: select font
                r"|<([0-9A-Fa-f\s]+)>"                      # 2: hex string
                r"|\(((?:[^()\\]|\\.)*)\)"                  # 3: literal string
            )
            for stream in self.content:
                if "beginbfchar" in stream or "bfrange" in stream:
                    continue                              # a CMap, not page content
                current: dict[int, str] = {}
                for m in token.finditer(stream):
                    if m.group(1):
                        current = self.font_cmaps.get(self.resources.get(m.group(1), -1), {})
                    elif m.group(2) is not None:
                        hx = re.sub(r"\s", "", m.group(2))
                        if len(hx) % 4:
                            hx = hx[:len(hx) - len(hx) % 4]
                        chars = [current.get(int(hx[i:i + 4], 16), "")
                                 for i in range(0, len(hx), 4)]
                        s = "".join(chars)
                        self.text.append(s)
                        self.drawn.update(chars)
                    elif m.group(3) is not None:
                        codes = _literal_codes(m.group(3))
                        if current:
                            chars = [current.get(c, "") for c in codes]
                        else:
                            # base-14 / WinAnsi text: the bytes are the characters
                            chars = [chr(c) for c in codes]
                        s = "".join(chars)
                        self.text.append(s)
                        self.drawn.update(chars)
            return " ".join(self.text)

    def drawn_codepoints(self) -> set[str]:
        """Every codepoint actually written, from any font, incl. base-14 Latin."""
        self.extract()
        return {c for c in self.drawn if c and not c.isspace()}


def main() -> int:
    if not register_fonts():
        print("FAIL  Indic fonts are not registered - app/fonts is missing the TTFs")
        return 1

    db_path = os.path.join(tempfile.gettempdir(), "ergocare_pdf_indic.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    # A private engine so the developer's real ergocare.db is never touched.
    eng = create_engine("sqlite:///" + db_path)
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng)()
    try:
        sess = build_session(db)
        pdf = _generate_pdf(sess, None)
    finally:
        db.close()

    reader = PdfText(pdf)
    drawn = reader.drawn_codepoints()
    text = reader.extract()

    failures = []
    if not pdf.startswith(b"%PDF"):
        failures.append("output is not a PDF")
    if b"/FontFile2" not in pdf:
        failures.append("no embedded font program (/FontFile2) - glyphs are not in the file")
    if "NotoSans" not in reader.raw:
        failures.append("neither Noto font is referenced by the PDF")

    # The decisive check: every character the participant typed must have been
    # given a glyph. A missing font would leave these out entirely.
    for label, sample in (("Hindi", HINDI), ("Kannada", KANNADA)):
        missing = sorted({c for c in sample if not c.isspace() and c not in drawn})
        if missing:
            failures.append(
                f"{label} characters have no glyph in the PDF: "
                + " ".join("U+%04X" % ord(c) for c in missing))

    # Latin must still be present, and drawn with the built-in font - i.e. the
    # fallback did not swallow it. Checked against the extracted text, because
    # base-14 Helvetica has no ToUnicode CMap to inspect.
    if LATIN_NAME not in text:
        failures.append(f"Latin text {LATIN_NAME!r} is missing from the PDF "
                        "- font selection broke it")

    deva = sum(1 for c in drawn if 0x0900 <= ord(c) <= 0x097F)
    knda = sum(1 for c in drawn if 0x0C80 <= ord(c) <= 0x0CFF)

    print(f"PDF {len(pdf):,} bytes | embedded font programs: "
          f"{reader.raw.count('/FontFile2')} | {len(reader.font_cmaps)} embedded CMaps")
    print(f"   Devanagari glyphs drawn: {deva} | Kannada glyphs drawn: {knda}")

    if failures:
        print("FAIL")
        for f in failures:
            print("   -", f)
        return 1
    print("PASS  Hindi, Kannada and Latin all render in the PDF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
