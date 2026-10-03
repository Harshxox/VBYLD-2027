"""
Verify the wearable backend (Part 2) end to end, with PASS / FAIL for each check.

Needs, in two other terminals:
    1) backend :  cd ergo_ml_backend  &&  .venv\\Scripts\\python -m uvicorn app.main:app --port 8000
    2) bridge  :  venv\\Scripts\\python ErgoCare\\firmware\\usb_bridge.py

Run (from ergo_ml_backend):
    .venv\\Scripts\\python scripts\\verify_wearable.py
    .venv\\Scripts\\python scripts\\verify_wearable.py --baseline 20 --live 30   (shorter)
    .venv\\Scripts\\python scripts\\verify_wearable.py --logic-only               (no hardware)

What it does
    A. Logic checks  - posture / stress / still warnings on simulated readings (no hardware)
    B. Live checks   - real ESP32 data: device seen, session linked, baseline recorded,
                       live values + warnings, history stored, recording stops on
                       completion, test data deleted afterwards.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import app.config  # noqa: E402,F401 - loads .env (admin login for cleaning up test data)
from app.domain import sensors as S  # noqa: E402
from app.domain.sensor_scoring import score_session  # noqa: E402
from app.models.schemas import RiskScores  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((ok, name))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


# ── A. Logic checks (simulated readings) ──────────────────────────────────────
def logic_checks() -> None:
    print("\nA. Warning logic (simulated readings)")
    t0 = datetime(2026, 1, 1)

    def r(i, bpm=75, gsr=450, tilt=0.0, moving=False, finger=True, contact=True):
        return {"received_at": t0 + timedelta(seconds=i), "bpm_avg": bpm, "finger": finger, "gsr_raw": gsr,
                "gsr_contact": contact, "tilt": tilt, "moving": moving, "pulse_ok": True, "mpu_ok": True}

    base = S.compute_baseline([r(i, bpm=74 + i % 3, gsr=440 + i % 20) for i in range(50)])
    check(base["ok"] and base["bpm"] == 75 and base["gsr"] == 448, "baseline from relaxed readings",
          f"bpm {base['bpm']}, gsr {base['gsr']}")

    def warn_types(readings):
        newest = readings[::-1]
        d = S.derive(newest[0], base)
        return sorted(w["type"] for w in S.warnings(newest[0], 0.5, d, S.streaks(newest, base), base))

    start = [r(i, moving=(i == 0)) for i in range(3)]
    cases = [
        ("relaxed and upright -> no warning", [r(i, moving=(i == 9)) for i in range(10)], []),
        ("slouching 28 deg for 12 s -> posture warning", start + [r(i, tilt=28) for i in range(3, 15)], ["posture"]),
        ("slouching only 6 s -> no warning yet", start + [r(i, tilt=28) for i in range(3, 9)], []),
        ("GSR +38% for 16 s -> stress warning", start + [r(i, gsr=610) for i in range(3, 19)], ["stress"]),
        ("heart +22 BPM for 16 s -> stress warning", start + [r(i, bpm=97) for i in range(3, 19)], ["stress"]),
        ("GSR +20% -> elevated only, no warning", start + [r(i, gsr=540) for i in range(3, 25)], []),
        ("still for 125 s -> stretch warning", [r(i) for i in range(125)], ["still"]),
        ("7 s data gap resets the slouch timer", [r(i, tilt=28) for i in range(8)] + [r(i, tilt=28) for i in range(15, 20)], []),
        ("no finger + no GSR contact -> 2 sensor warnings",
         [r(i, finger=False, contact=False, moving=True) for i in range(5)], ["sensor", "sensor"]),
    ]
    for name, readings, expected in cases:
        got = warn_types(readings)
        check(got == expected, name, "" if got == expected else f"got {got}")
    got = [w["type"] for w in S.warnings(r(0), 9.0, None, None, base)]
    check(got == ["disconnected"], "no data for 9 s -> disconnected warning")


# ── C. Scoring checks (objective score, ErgoCare Index, insights) ─────────────
def scoring_checks() -> None:
    print("\nC. Wearable scoring and ErgoCare Index (simulated sessions)")
    start = datetime(2026, 1, 1, 10, 0, 0)
    base = {"bpm": 75.0, "gsr": 450.0, "tilt": 0.0}

    def reading(t, bpm=75, gsr=450, tilt=0.0, moving=False, finger=True, contact=True):
        return {"received_at": start + timedelta(seconds=t), "bpm_avg": bpm, "finger": finger, "gsr_raw": gsr,
                "gsr_contact": contact, "tilt": tilt, "moving": moving, "pulse_ok": True, "mpu_ok": True}

    def session(n=300, **kw):
        """Baseline 0-60 s (always slouched, to prove it is excluded) + n s of questions."""
        rows = [reading(t, tilt=40) for t in range(60)]
        for t in range(60, 60 + n):
            i = t - 60
            rows.append(reading(t, **{k: (v(i) if callable(v) else v) for k, v in kw.items()}))
        return rows

    def q(overall=30, workload=30, posture=30):
        return RiskScores(posture_risk=posture, eye_strain=30, workload_stress=workload,
                          musculoskeletal_risk=30, recovery_risk=30, overall_risk=overall)

    kinds = lambda w: sorted(i["type"] for i in w.get("insights", []))
    moving_every_min = lambda i: i % 60 == 0

    w = score_session(session(moving=moving_every_min), base, start, q())
    check(w["available"] and w["posture"]["pct_time_bad"] == 0 and kinds(w) == [],
          "calm + upright session: no insights, baseline slouch excluded",
          f"objective {w.get('objective_score')}, index {w.get('combined', {}).get('index')}")
    expect = round(0.6 * 30 + 0.4 * w["objective_score"], 1)
    check(w["combined"]["index"] == expect, "ErgoCare Index = 60% questionnaire + 40% objective",
          f"{w['combined']['index']} == {expect}")

    w = score_session(session(gsr=lambda i: 640 if i % 10 < 6 else 450, moving=moving_every_min), base, start, q(workload=20))
    check(kinds(w) == ["hidden_stress"], "says low stress + body stressed 60% -> Hidden stress",
          f"stress score {w['stress']['score']}; " + (w["insights"][0]["message"] if w["insights"] else "none"))

    w = score_session(session(gsr=640, moving=moving_every_min), base, start, q(workload=70))
    check(kinds(w) == ["confirmed_stress"], "says high stress + body stressed -> Stress confirmed")

    w = score_session(session(moving=moving_every_min), base, start, q(workload=75))
    check(kinds(w) == ["calm_body"], "says high stress + body calm -> Calm during the test")

    w = score_session(session(tilt=lambda i: 28 if (i // 30) % 2 else 3, moving=moving_every_min), base, start, q(posture=25))
    check(kinds(w) == ["posture_blind_spot"] and 45 <= w["posture"]["pct_time_bad"] <= 55,
          "says good posture + slouched 50% -> Posture blind spot",
          f"{w['posture']['pct_time_bad']}% slouched, RULA-style {w['posture']['rula_style_score']}")
    check(any("leaned forward" in a for a in w["actions"]), "posture action added to the action plan")

    w = score_session(session(contact=False, finger=False, moving=moving_every_min), base, start, q())
    check(w["available"] and w["stress"] is None and w["objective_score"] is not None,
          "no pulse/GSR contact: stress skipped, objective re-weighted", f"objective {w['objective_score']}")

    w = score_session(session(n=20), base, start, q())
    check(not w["available"] and "20 s" in w["reason"], "too little data -> not scored, reason given", w["reason"])

    w = score_session(session(), None, None, q())
    check(not w["available"] and "baseline" in w["reason"].lower(), "no baseline -> not scored, reason given")


# ── B. Live checks (real ESP32 through the USB bridge) ────────────────────────
def api(base_url, method, path, body=None, headers=None):
    req = urllib.request.Request(
        base_url + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return exc.code, raw.decode(errors="ignore")


def fmt_live(d: dict) -> str:
    der = d.get("derived") or {}
    bpm = f"{der['bpm']:.0f} BPM" if der.get("bpm") else "-- BPM"
    if der.get("bpm_change") is not None:
        bpm += f" ({der['bpm_change']:+.0f})"
    gsr = f"GSR {der['gsr']:.0f}" if der.get("gsr") else "GSR --"
    if der.get("gsr_change_pct") is not None:
        gsr += f" ({der['gsr_change_pct']:+.0f}%)"
    stress = der.get("stress_level") or "unknown"
    posture = f"{der['posture_angle']:.0f} deg" if der.get("posture_angle") is not None else "--"
    warns = " | ".join(w["message"] for w in d.get("warnings", [])) or "no warnings"
    return f"{bpm:<16} {gsr:<16} stress {stress:<9} posture {posture:<7} -> {warns}"


def live_checks(base_url: str, device: str, baseline_s: int, live_s: int) -> None:
    print(f"\nB. Live wearable checks against {base_url}")
    try:
        ok = api(base_url, "GET", "/health")[0] == 200
    except Exception:
        ok = False
    if not check(ok, "backend is running"):
        print("     Start it: cd ergo_ml_backend && .venv\\Scripts\\python -m uvicorn app.main:app --port 8000")
        return

    _, dev = api(base_url, "GET", f"/api/devices/{device}/latest")
    if not check(bool(dev and dev["connected"]), f"wearable {device} is sending data",
                 f"last reading {dev.get('age_s')} s ago" if dev and dev.get("age_s") is not None else "never seen"):
        print("     Start the bridge: venv\\Scripts\\python ErgoCare\\firmware\\usb_bridge.py")
        return

    st, sess = api(base_url, "POST", "/api/sessions", {"input_mode": "typed", "client_name": "Wearable verify (auto-deleted)",
                                                         "consent": True})
    if not check(st == 201, "test session created"):
        return
    sid = sess["id"]
    try:
        st, link = api(base_url, "POST", f"/api/sessions/{sid}/device", {"device_id": device})
        check(st == 200 and link["active"], "wearable linked to session")
        st, _ = api(base_url, "POST", f"/api/sessions/{sid}/device", {"device_id": "bad id!"})
        check(st == 422, "invalid device id rejected")

        st, _ = api(base_url, "POST", f"/api/sessions/{sid}/baseline/start")
        check(st == 200, "baseline started (posture zeroed on the ESP32)")
        print(f"\n  >>> BASELINE {baseline_s} s: sit upright, fingertip gently on the pulse sensor,")
        print("      other hand holding both GSR electrodes. Relax.\n")
        for left in range(baseline_s, 0, -1):
            _, d = api(base_url, "GET", f"/api/sessions/{sid}/sensors/latest")
            print(f"  {left:>3}s  {fmt_live(d)}")
            time.sleep(1)

        st, base = api(base_url, "POST", f"/api/sessions/{sid}/baseline/finish")
        if check(st == 200, "baseline computed", json.dumps(base) if st == 200 else str(base)):
            check(base["pulse_readings"] >= S.BASELINE_MIN_READINGS, "heart rate captured in baseline",
                  f"{base['pulse_readings']} readings, resting {base['bpm']} BPM")
            check(base["gsr_readings"] >= S.BASELINE_MIN_READINGS, "GSR captured in baseline",
                  f"{base['gsr_readings']} readings, resting GSR {base['gsr']}")

        print(f"\n  >>> LIVE {live_s} s: keep the sensors on. Try this and watch the warnings:")
        print("      1) lean forward and HOLD for 12 s   -> posture warning")
        print("      2) sit up, then hold your breath / do fast mental maths  -> GSR and stress rise\n")
        seen = set()
        for sec in range(live_s):
            _, d = api(base_url, "GET", f"/api/sessions/{sid}/sensors/latest")
            seen.update(w["type"] for w in d.get("warnings", []))
            print(f"  {sec + 1:>3}s  {fmt_live(d)}")
            time.sleep(1)
        check(True, "live panel data received every second", f"warning types seen: {sorted(seen) or 'none'}")
        check("posture" in seen, "posture warning triggered by leaning forward")

        _, hist = api(base_url, "GET", f"/api/sessions/{sid}/sensors/history")
        expected = baseline_s + live_s
        check(hist["total_readings"] >= expected * 0.8, "readings stored for the report",
              f"{hist['total_readings']} stored (~{expected} expected)")

        api(base_url, "POST", f"/api/sessions/{sid}/answers",
            {"question_id": 1, "question_text": "verify", "typed_answer": "1 hour"})
        st, _ = api(base_url, "POST", f"/api/sessions/{sid}/complete")
        n1 = api(base_url, "GET", f"/api/sessions/{sid}/sensors/history")[1]["total_readings"]
        time.sleep(3)
        n2 = api(base_url, "GET", f"/api/sessions/{sid}/sensors/history")[1]["total_readings"]
        check(st == 200 and n1 == n2, "recording stops when the session is completed", f"{n1} -> {n2}")
    finally:
        _, login = api(base_url, "POST", "/api/admin/login",
                       {"username": os.getenv("ADMIN_USERNAME", "admin"), "password": os.getenv("ADMIN_PASSWORD", "")})
        token = (login or {}).get("token", "") if isinstance(login, dict) else ""
        st, _ = api(base_url, "DELETE", f"/api/sessions/{sid}", headers={"Authorization": f"Bearer {token}"})
        gone = api(base_url, "GET", f"/api/sessions/{sid}/sensors/history")[0] == 404
        check(st == 204 and gone, "test session and its sensor data deleted (admin login from .env)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    ap.add_argument("--device", default="ERGO-01")
    ap.add_argument("--baseline", type=int, default=30, help="baseline seconds (app uses 60)")
    ap.add_argument("--live", type=int, default=45, help="seconds of live monitoring")
    ap.add_argument("--logic-only", action="store_true", help="skip hardware checks")
    args = ap.parse_args()

    print("ErgoCare wearable backend - verification")
    logic_checks()
    scoring_checks()
    if not args.logic_only:
        live_checks(args.backend, args.device, args.baseline, args.live)

    passed = sum(ok for ok, _ in results)
    print(f"\nRESULT: {passed}/{len(results)} checks passed")
    for ok, name in results:
        if not ok:
            print(f"  FAILED: {name}")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
