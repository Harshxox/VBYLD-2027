"""
Reports route — v3
POST /{session_id}/complete    → score + build report, persist, return
GET  /{session_id}/report      → JSON report
GET  /{session_id}/report.pdf  → PDF download with client name, audio list, full data

v4.1 — the JSON report and the PDF both contain the participant's name, email,
phone and every answer, so both now require the session access token
(X-Session-Token) or an admin token.
"""
import io
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.assessment import AssessmentSession
from app.models.schemas import CompleteSessionOut, RiskScores, ReportData
from app.models.sensors import SensorLink, SensorReading
from app.domain.sensor_scoring import score_session
from app.domain.sensors import POSTURE_BAD_DEG, history_points
from app.domain.scoring import calculate_scores, build_report
from app.security import require_session_access, session_token_matches
from app.api.routes.pdf_fonts import mark_script_runs, register_fonts

router = APIRouter()


def _load_session(db: Session, session_id: str, caller: str,
                  presented: Optional[str]) -> AssessmentSession:
    """
    Fetch a session and confirm the caller may read it.

    `caller` is "session:<token>" when an X-Session-Token header was supplied, or
    an admin identity from a valid admin token. A session token only unlocks the
    session it was minted for.
    """
    session = db.query(AssessmentSession).filter(AssessmentSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if caller.startswith("session:") and not session_token_matches(session.access_token, presented):
        raise HTTPException(
            status_code=403,
            detail="That access token belongs to a different session.",
        )
    return session


def _answers_as_dicts(session: AssessmentSession) -> list:
    return [
        {"question_id": a.question_id, "typed_answer": a.typed_answer, "transcript": a.transcript}
        for a in session.answers
    ]


def _wearable_section(session_id: str, scores: RiskScores, db: Session):
    """Body-signal scores + ErgoCare Index, or None when no wearable was linked."""
    link = db.query(SensorLink).filter(SensorLink.session_id == session_id).first()
    if not link:
        return None
    rows = (db.query(SensorReading)
            .filter(SensorReading.session_id == session_id)
            .order_by(SensorReading.received_at, SensorReading.id).all())
    return score_session([r.as_dict() for r in rows], link.baseline, link.baseline_started_at, scores)


# ── Complete session → score + report ────────────────────────────────────────

@router.post("/{session_id}/complete", response_model=CompleteSessionOut)
def complete_session(
    session_id: str,
    db: Session = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller: str = Depends(require_session_access),
):
    session = _load_session(db, session_id, caller, x_session_token)
    if not session.answers:
        raise HTTPException(status_code=422, detail="No answers — cannot score empty session")

    answers = _answers_as_dicts(session)
    scores, ml = calculate_scores(answers)
    report: ReportData = build_report(scores, ml, answers)

    # Wearable: objective body-signal score, ErgoCare Index and answer/body mismatches
    wearable = _wearable_section(session_id, scores, db)
    if wearable:
        report.wearable = wearable
        if wearable.get("available"):
            report.action_plan = wearable["actions"] + report.action_plan
            report.detailed_findings = (
                [f"{i['title']}: {i['message']}" for i in wearable["insights"]] + report.detailed_findings)

    session.completed_at         = datetime.now(timezone.utc)
    session.overall_risk         = scores.overall_risk
    session.posture_risk         = scores.posture_risk
    session.eye_strain           = scores.eye_strain
    session.workload_stress      = scores.workload_stress
    session.musculoskeletal_risk = scores.musculoskeletal_risk
    session.recovery_risk        = scores.recovery_risk
    session.report_json          = report.model_dump()
    # Assessment over: stop storing wearable readings against this session
    db.query(SensorLink).filter(SensorLink.session_id == session_id).update({"active": False})
    db.commit()

    return CompleteSessionOut(session_id=session_id, scores=scores, report=report)


# ── Get JSON report ───────────────────────────────────────────────────────────

@router.get("/{session_id}/report")
def get_report(
    session_id: str,
    db: Session = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller: str = Depends(require_session_access),
):
    session = _load_session(db, session_id, caller, x_session_token)
    if not session.completed_at or not session.report_json:
        raise HTTPException(status_code=409, detail="Session not yet completed")
    return {
        "session_id":   session_id,
        "completed_at": session.completed_at,
        "client": {
            "name":  session.client_name,
            "email": session.client_email,
            "phone": session.client_phone,
            "age":   session.client_age,
            "job":   session.client_job,
        },
        "scores": {
            "overall_risk":         session.overall_risk,
            "posture_risk":         session.posture_risk,
            "eye_strain":           session.eye_strain,
            "workload_stress":      session.workload_stress,
            "musculoskeletal_risk": session.musculoskeletal_risk,
            "recovery_risk":        session.recovery_risk,
        },
        "report":  session.report_json,
        "answers": [
            {
                "question_id":   a.question_id,
                "question_text": a.question_text,
                "typed_answer":  a.typed_answer,
                "transcript":    a.transcript,
                "audio_url":     a.audio_url,
            }
            for a in session.answers
        ],
        "audio_files": [
            {
                "question_id": af.question_id,
                "file_name":   af.file_name,
                "audio_url":   f"/api/sessions/{session_id}/audio/{af.file_name}",
                "size_bytes":  af.size_bytes,
            }
            for af in session.audio_files
        ],
    }


# ── Download PDF ──────────────────────────────────────────────────────────────

@router.get("/{session_id}/report.pdf")
def download_report_pdf(
    session_id: str,
    db: Session = Depends(get_db),
    x_session_token: Optional[str] = Header(default=None),
    caller: str = Depends(require_session_access),
):
    session = _load_session(db, session_id, caller, x_session_token)
    if not session.completed_at or not session.report_json:
        raise HTTPException(status_code=409, detail="Session not yet completed")

    history = None
    wearable = (session.report_json or {}).get("wearable") or {}
    if wearable.get("available"):
        link = db.query(SensorLink).filter(SensorLink.session_id == session_id).first()
        rows = (db.query(SensorReading)
                .filter(SensorReading.session_id == session_id)
                .order_by(SensorReading.received_at, SensorReading.id).all())
        history = history_points([r.as_dict() for r in rows], link.baseline if link else None,
                                 link.baseline_started_at if link else None, max_points=300)

    pdf_bytes = _generate_pdf(session, history)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": _pdf_disposition(session)},
    )


def _pdf_disposition(session) -> str:
    """
    Build a Content-Disposition that survives any name a participant types.

    Starlette encodes header values as latin-1, so a name like "Rahul" written
    in Devanagari raised UnicodeEncodeError and turned every PDF download into a
    500 - on a product whose whole point is Hindi and Kannada support. RFC 5987
    carries the real name in filename*, with a plain ASCII filename= fallback for
    older clients.

    Quotes, backslashes and CR/LF are stripped: they would either break out of the
    quoted-string or inject extra headers.
    """
    def clean(value: str) -> str:
        value = "".join(ch for ch in value if ch.isprintable())
        return value.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "").strip()

    stem = clean(session.client_name or "") or "client"
    ascii_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-.")[:40].lower() or "client"
    filename = f"ergocare-{ascii_stem}-{session.id[:8]}.pdf"

    disposition = f'attachment; filename="{filename}"'
    if stem != ascii_stem:
        quoted = urllib.parse.quote(stem, safe="")
        disposition += f"; filename*=UTF-8''{quoted}"
    return disposition


# ── PDF generator ─────────────────────────────────────────────────────────────

def _fmt_dur(s) -> str:
    s = int(s or 0)
    return f"{s}s" if s < 60 else f"{s // 60}m {s % 60:02d}s"


def _line_chart(title, series, width, height, y_min, y_max, threshold=None, shade_until=None):
    """
    Small ReportLab line chart. series: [(label, [(x_minutes, y), ...], color)].
    threshold: (y, label) dashed red line. shade_until: x (minutes) to grey out as baseline.
    """
    from reportlab.graphics.shapes import Drawing, String, Line, Rect
    from reportlab.graphics.charts.lineplots import LinePlot
    from reportlab.lib import colors

    series = [(lbl, pts, c) for lbl, pts, c in series if len(pts) >= 2]
    d = Drawing(width, height)
    d.add(String(0, height - 10, title, fontName="Helvetica-Bold", fontSize=8.5, fillColor=colors.HexColor("#005f73")))
    if not series:
        d.add(String(0, height - 26, "Not enough data for this signal.", fontName="Helvetica", fontSize=8, fillColor=colors.grey))
        return d

    x_max = max(p[0] for _, pts, _ in series for p in pts) or 1
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 32, 30, width - 44, height - 52
    lp.data = [pts for _, pts, _ in series]
    for i, (_, _, c) in enumerate(series):
        lp.lines[i].strokeColor = c
        lp.lines[i].strokeWidth = 1.1
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0, x_max
    lp.yValueAxis.valueMin, lp.yValueAxis.valueMax = y_min, y_max
    for axis in (lp.xValueAxis, lp.yValueAxis):
        axis.labels.fontName = "Helvetica"
        axis.labels.fontSize = 6.5
        axis.strokeColor = colors.HexColor("#94a3b8")
    lp.xValueAxis.labelTextFormat = lambda v: f"{v:.0f}m" if x_max >= 3 else f"{v * 60:.0f}s"

    def px(x):
        return lp.x + x / x_max * lp.width

    def py(y):
        return lp.y + (min(max(y, y_min), y_max) - y_min) / (y_max - y_min) * lp.height

    if shade_until and shade_until > 0:
        d.add(Rect(lp.x, lp.y, px(min(shade_until, x_max)) - lp.x, lp.height,
                   fillColor=colors.HexColor("#eef2f6"), strokeColor=None))
        d.add(String(lp.x + 3, lp.y + lp.height - 9, "baseline", fontName="Helvetica", fontSize=6.5, fillColor=colors.HexColor("#64748b")))
    d.add(lp)
    if threshold:
        y, lbl = threshold
        d.add(Line(lp.x, py(y), lp.x + lp.width, py(y), strokeColor=colors.HexColor("#dc2626"),
                   strokeWidth=0.8, strokeDashArray=[3, 2]))
        d.add(String(lp.x + lp.width - 70, py(y) + 2, lbl, fontName="Helvetica", fontSize=6.5, fillColor=colors.HexColor("#dc2626")))
    x0 = lp.x
    for lbl, _, c in series:                       # legend
        d.add(Line(x0, 4, x0 + 12, 4, strokeColor=c, strokeWidth=2))
        d.add(String(x0 + 15, 1.5, lbl, fontName="Helvetica", fontSize=7, fillColor=colors.HexColor("#334155")))
        x0 += 20 + len(lbl) * 4
    return d


def _generate_pdf(session: AssessmentSession, history=None) -> bytes:
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    except ImportError:
        raise HTTPException(status_code=500, detail="reportlab not installed — run: pip install reportlab")

    # Embed the Devanagari/Kannada fonts so Hindi and Kannada answers render as
    # text instead of empty boxes. Falls back to Helvetica-only if unavailable.
    register_fonts()

    report = session.report_json
    W = A4[0] - 40 * mm

    # ── Colours ───────────────────────────────────────────────────────────────
    TEAL      = colors.HexColor("#01696f")
    TEAL_DARK = colors.HexColor("#005f73")
    RED       = colors.HexColor("#c1121f")
    AMBER     = colors.HexColor("#d97706")
    GREEN     = colors.HexColor("#2a9d8f")
    LIGHT     = colors.HexColor("#f4f9f7")
    WHITE     = colors.white
    GREY      = colors.HexColor("#6b7a99")
    BORDER    = colors.HexColor("#d4d1ca")

    level       = report.get("level", "Unknown")
    lv_color    = RED if level == "High" else AMBER if level == "Moderate" else GREEN
    overall     = session.overall_risk or 0

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=20*mm, leftMargin=20*mm,
                            topMargin=18*mm, bottomMargin=18*mm)
    styles = getSampleStyleSheet()

    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    title_s   = sty("T",  fontSize=24, textColor=TEAL_DARK, fontName="Helvetica-Bold", spaceAfter=2)
    sub_s     = sty("S",  fontSize=10, textColor=GREY, spaceAfter=10)
    sec_s     = sty("H",  fontSize=12, textColor=TEAL_DARK, fontName="Helvetica-Bold", spaceBefore=14, spaceAfter=5)
    body_s    = sty("B",  fontSize=9,  leading=14, spaceAfter=3)
    bullet_s  = sty("BL", fontSize=9,  leading=14, leftIndent=10, spaceAfter=3)
    pos_s     = sty("P",  fontSize=9,  leading=14, leftIndent=10, textColor=GREEN, spaceAfter=3)
    badge_s   = sty("BD", fontSize=13, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_CENTER)
    small_s   = sty("SM", fontSize=8,  textColor=GREY, spaceAfter=1)
    right_s   = sty("R",  fontSize=9,  textColor=GREY, alignment=TA_RIGHT)
    q_s       = sty("Q",  fontSize=8,  textColor=TEAL_DARK, fontName="Helvetica-Bold", spaceAfter=2)
    a_s       = sty("A",  fontSize=8,  textColor=colors.HexColor("#334155"), spaceAfter=4, leftIndent=8)

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    hdr = Table([[Paragraph("ErgoCare AI", title_s),
                  Paragraph("Ergonomic Risk Assessment Report", right_s)]],
                colWidths=[W*0.6, W*0.4])
    hdr.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"BOTTOM"),
                              ("BOTTOMPADDING",(0,0),(-1,-1),4)]))
    story.append(hdr)
    story.append(HRFlowable(width="100%", thickness=1.5, color=TEAL, spaceAfter=10))

    # ── Risk badge ────────────────────────────────────────────────────────────
    badge = Table([[Paragraph(f"Overall Risk: {level}  —  {overall:.0f}%", badge_s)]],
                  colWidths=[W])
    badge.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,-1), lv_color),
                                ("TOPPADDING",(0,0),(-1,-1),10),
                                ("BOTTOMPADDING",(0,0),(-1,-1),10),
                                ("ROUNDEDCORNERS",[5])]))
    story.append(badge)
    wearable = report.get("wearable") or {}
    combined = wearable.get("combined") if wearable.get("available") else None
    if combined:
        c_color = RED if combined["level"] == "High" else AMBER if combined["level"] == "Moderate" else GREEN
        ib = Table([[Paragraph(f"ErgoCare Index (answers + body signals): {combined['level']}  —  {combined['index']:.0f}%",
                               sty("IB", fontSize=11, textColor=c_color, fontName="Helvetica-Bold", alignment=TA_CENTER))]],
                   colWidths=[W])
        ib.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1.2, c_color), ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
                                ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
        story.append(Spacer(1, 5))
        story.append(ib)
    story.append(Spacer(1, 4))
    story.append(Paragraph("<i>ErgoCare is a screening tool, not a medical diagnosis. For persistent pain, numbness "
                           "or severe symptoms, please consult a doctor or physiotherapist.</i>",
                           sty("DISC", fontSize=8, textColor=GREY, alignment=TA_CENTER)))
    story.append(Spacer(1, 8))

    # ── Client info ───────────────────────────────────────────────────────────
    if session.client_name:
        story.append(Paragraph("Client Information", sec_s))
        # These four are participant-supplied: escape them and give any Indic
        # script a font that has the glyphs.
        cdata = [
            ["Name",    mark_script_runs(session.client_name  or "—"), "Email",   mark_script_runs(session.client_email or "—")],
            ["Phone",   mark_script_runs(session.client_phone or "—"), "Age",     str(session.client_age or "—")],
            ["Job Role",mark_script_runs(session.client_job   or "—"), "Session", session.id[:12] + "…"],
        ]
        ctbl = Table([[Paragraph(str(v), small_s if i%2==0 else body_s) for i,v in enumerate(row)] for row in cdata],
                     colWidths=[25*mm, W/2-25*mm-2*mm, 22*mm, W/2-22*mm-2*mm])
        ctbl.setStyle(TableStyle([
            ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),("FONTNAME",(2,0),(2,-1),"Helvetica-Bold"),
            ("FONTSIZE",(0,0),(-1,-1),8),("TEXTCOLOR",(0,0),(0,-1),GREY),("TEXTCOLOR",(2,0),(2,-1),GREY),
            ("TOPPADDING",(0,0),(-1,-1),4),("BOTTOMPADDING",(0,0),(-1,-1),4),
            ("GRID",(0,0),(-1,-1),0.3,BORDER),("BACKGROUND",(0,0),(-1,-1),LIGHT),
        ]))
        story.append(ctbl)
        story.append(Spacer(1, 6))

    # ── Meta ─────────────────────────────────────────────────────────────────
    completed = session.completed_at.strftime("%d %B %Y, %H:%M UTC") if session.completed_at else "N/A"
    story.append(Paragraph(f"Completed: {completed}  ·  Mode: {session.input_mode.capitalize()}  ·  Session: {session.id[:16]}…", small_s))
    story.append(Spacer(1, 8))

    # ── Score breakdown table ─────────────────────────────────────────────────
    story.append(Paragraph("Risk Score Breakdown", sec_s))
    score_rows = [
        [Paragraph("Category", sty("TH", fontSize=9, textColor=WHITE, fontName="Helvetica-Bold")),
         Paragraph("Score",    sty("TH2",fontSize=9, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_CENTER)),
         Paragraph("Level",    sty("TH3",fontSize=9, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_CENTER))],
    ]
    score_data = [
        ("Overall Risk",         session.overall_risk),
        ("Posture & Movement",   session.posture_risk),
        ("Eye Strain",           session.eye_strain),
        ("Workload Stress",      session.workload_stress),
        ("Body Discomfort",      session.musculoskeletal_risk),
        ("Recovery & Sleep",     session.recovery_risk),
    ]
    for label, val in score_data:
        v = val or 0
        lv = "High" if v >= 70 else "Moderate" if v >= 40 else "Low"
        c  = RED if lv=="High" else AMBER if lv=="Moderate" else GREEN
        bar = "█" * int(v / 5)
        score_rows.append([
            Paragraph(label, body_s),
            Paragraph(f"{bar}  <b>{v:.0f}%</b>", sty(f"SB{label}", fontSize=8, textColor=c, leading=12)),
            Paragraph(lv, sty(f"LV{label}", fontSize=9, textColor=c, fontName="Helvetica-Bold", alignment=TA_CENTER)),
        ])
    stbl = Table(score_rows, colWidths=[55*mm, 85*mm, 28*mm])
    stbl.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),TEAL_DARK),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[LIGHT, WHITE]),
        ("GRID",(0,0),(-1,-1),0.3,BORDER),
        ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
        ("LEFTPADDING",(0,0),(-1,-1),6),
    ]))
    story.append(stbl)
    story.append(Spacer(1, 8))

    # ── Body signals (wearable) ───────────────────────────────────────────────
    if wearable.get("used"):
        story.append(Paragraph("Body Signals (ErgoCare Wearable)", sec_s))
        if not wearable.get("available"):
            story.append(Paragraph(mark_script_runs(wearable.get("reason") or "Wearable data could not be scored."), body_s))
        else:
            post, stress, still = wearable.get("posture"), wearable.get("stress"), wearable["stillness"]
            cov = wearable.get("coverage", {})
            idx_tbl = Table([[
                Paragraph(f"<b>{combined['index']:.0f}%</b><br/><font size=7 color='#6b7a99'>ErgoCare Index ({combined['level']})</font>",
                          sty("I1", fontSize=16, leading=19, alignment=TA_CENTER, textColor=TEAL_DARK)),
                Paragraph(f"<b>{combined['questionnaire']:.0f}%</b><br/><font size=7 color='#6b7a99'>Questionnaire × 60%</font>",
                          sty("I2", fontSize=13, leading=17, alignment=TA_CENTER)),
                Paragraph(f"<b>{combined['objective']:.0f}%</b><br/><font size=7 color='#6b7a99'>Body signals × 40%</font>",
                          sty("I3", fontSize=13, leading=17, alignment=TA_CENTER)),
            ]], colWidths=[W / 3] * 3)
            idx_tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, BORDER), ("BACKGROUND", (0, 0), (0, 0), LIGHT),
                                         ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
            story.append(idx_tbl)
            story.append(Spacer(1, 6))

            for ins in wearable.get("insights", []):
                c = "#c2410c" if ins["severity"] == "warning" else "#1d4ed8"
                story.append(Paragraph(f"<font color='{c}'><b>{ins['title']}:</b></font> {ins['message']}", bullet_s))

            def pct(v):
                return "—" if v is None else f"{v:.0f}%"
            rows = [["Measure", "Result", "Meaning"],
                    ["Time analysed", _fmt_dur(wearable.get("duration_s")),
                     f"Sensor contact: pulse {pct(cov.get('pulse_pct'))}, skin {pct(cov.get('gsr_pct'))}"]]
            if stress:
                rows += [
                    ["Average heart rate", f"{stress['avg_bpm']:.0f} BPM" if stress.get("avg_bpm") else "—",
                     f"{stress['avg_bpm_change']:+.0f} BPM vs resting" if stress.get("avg_bpm_change") is not None else ""],
                    ["Time stressed", pct(stress["pct_time_high"] + stress["pct_time_elevated"]),
                     f"high {pct(stress['pct_time_high'])}, elevated {pct(stress['pct_time_elevated'])}"],
                    ["Peak skin-response rise", f"{stress['peak_gsr_rise_pct']:+.0f}%" if stress.get("peak_gsr_rise_pct") is not None else "—",
                     "vs your resting baseline"],
                ]
            if post:
                rows += [
                    ["Time slouching", pct(post["pct_time_bad"]), f"leaning more than {POSTURE_BAD_DEG}°"],
                    ["Average / max lean", f"{post['avg_angle']:.0f}° / {post['max_angle']:.0f}°",
                     f"Typical posture: RULA-style band {post['rula_style_score']} ({post['rula_label']})"],
                ]
            alerts = (post["alerts"] if post else 0) + (stress["alerts"] if stress else 0) + still["alerts"]
            rows += [["Longest time still", _fmt_dur(still["longest_still_s"]), f"{pct(still['pct_time_still'])} of the time not moving"],
                     ["On-screen warnings", str(alerts), "posture, stress and movement alerts shown live"]]
            wt = Table([[Paragraph(str(c), small_s if i != 1 else body_s) for i, c in enumerate(r)] for r in rows],
                       colWidths=[48 * mm, 38 * mm, W - 86 * mm])
            wt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
                                    ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            story.append(Spacer(1, 4))
            story.append(wt)

            if history and history.get("points"):
                pts = history["points"]
                shade = (history.get("baseline_end_t") or 0) / 60
                series = lambda key: [(p["t"] / 60, p[key]) for p in pts if p[key] is not None]
                ch_w, ch_h = W, 48 * mm
                bpm_vals = [y for _, y in series("bpm")] or [60, 100]
                story.append(Spacer(1, 6))
                story.append(_line_chart("Heart rate over the session (BPM)",
                                         [("Heart rate", series("bpm"), colors.HexColor("#dc2626"))],
                                         ch_w, ch_h, max(0, min(bpm_vals) - 10), max(bpm_vals) + 10, shade_until=shade))
                gsr_vals = [y for _, y in series("gsr_change_pct")] or [0, 50]
                story.append(Spacer(1, 6))
                story.append(_line_chart("Skin response vs your baseline (%)",
                                         [("Skin response change", series("gsr_change_pct"), colors.HexColor("#2563eb"))],
                                         ch_w, ch_h, min(-10, min(gsr_vals) - 5), max(40, max(gsr_vals) + 5),
                                         threshold=(30, "high stress (+30%)"), shade_until=shade))
                ang_vals = [y for _, y in series("posture_angle")] or [0, 30]
                story.append(Spacer(1, 6))
                story.append(_line_chart("Posture: forward lean (degrees)",
                                         [("Lean angle", series("posture_angle"), colors.HexColor("#0a9396"))],
                                         ch_w, ch_h, 0, max(35, max(ang_vals) + 5),
                                         threshold=(POSTURE_BAD_DEG, f"slouch ({POSTURE_BAD_DEG}°)"), shade_until=shade))
            story.append(Paragraph(mark_script_runs(wearable.get("method", "")), small_s))
        story.append(Spacer(1, 6))

    # ── Top factors ───────────────────────────────────────────────────────────
    if report.get("top_factors"):
        story.append(Paragraph("Top Risk Factors", sec_s))
        for f in report["top_factors"]:
            story.append(Paragraph(f"▸  {f}", bullet_s))
        story.append(Spacer(1, 4))

    # ── Detailed findings ─────────────────────────────────────────────────────
    if report.get("detailed_findings"):
        story.append(Paragraph("Detailed Findings & Recommendations", sec_s))
        for f in report["detailed_findings"]:
            story.append(Paragraph(f"•  {f}", bullet_s))
        story.append(Spacer(1, 4))

    # ── Positive habits ───────────────────────────────────────────────────────
    if report.get("positive_habits"):
        story.append(Paragraph("Positive Habits Detected", sec_s))
        for p in report["positive_habits"]:
            story.append(Paragraph(f"✓  {p}", pos_s))
        story.append(Spacer(1, 4))

    # ── Action plan ───────────────────────────────────────────────────────────
    if report.get("action_plan"):
        story.append(Paragraph("Prioritised Action Plan", sec_s))
        for i, a in enumerate(report["action_plan"], 1):
            story.append(Paragraph(f"{i}.  {mark_script_runs(a)}", bullet_s))
        story.append(Spacer(1, 8))

    # ── All 40 Q&A answers ────────────────────────────────────────────────────
    if session.answers:
        story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceAfter=6))
        story.append(Paragraph("All 40 Answers", sec_s))
        for ans in sorted(session.answers, key=lambda x: x.question_id):
            val = ans.typed_answer or ans.transcript or "—"
            audio_note = f"  [audio recorded]" if ans.audio_url else ""
            # The participant's own words: a Hindi or Kannada answer must come
            # out as readable text, and stray "<" or "&" must not be read as markup.
            story.append(Paragraph(
                f"Q{ans.question_id}. {mark_script_runs(ans.question_text, 'Helvetica-Bold')}", q_s))
            story.append(Paragraph(
                f"→ {mark_script_runs(val)}{audio_note}", a_s))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER, spaceBefore=10, spaceAfter=4))
    story.append(Paragraph(
        "This report is generated by ErgoCare AI and is for informational purposes only. "
        "Consult a qualified healthcare or occupational health professional for clinical advice. "
        f"Generated: {datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')}",
        sty("FT", fontSize=7.5, textColor=GREY, spaceBefore=2),
    ))

    doc.build(story)
    return buffer.getvalue()
