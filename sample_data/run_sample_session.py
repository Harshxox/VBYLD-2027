"""
End-to-end test with the sample data: drives one full ErgoCare session through a
RUNNING backend exactly like the app + wearable do, then checks the results.

    cd ergo_ml_backend
    .venv\\Scripts\\python -m uvicorn app.main:app --port 8000        (window 1)
    .venv\\Scripts\\python ..\\sample_data\\run_sample_session.py      (window 2, ~2.5 min)

Uses wearable_session.jsonl (SIMULATED readings, device SAMPLE-01) and
answers_low_risk.json, sent at the real rate of one reading per second, because
the server scores by the time each reading arrives. Run it while no other
wearable is linked to a session. The test session is deleted at the end
(needs ADMIN_USERNAME / ADMIN_PASSWORD in ergo_ml_backend/.env).

Expected story: calm 60-s baseline -> low-risk answers -> 40 s of slouching ->
30 s of stress. So the report must show the wearable, a posture warning and a
"Posture blind spot" (answers said posture is fine, the sensor says otherwise).
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ergo_ml_backend"))
try:
    from app.config import load_env          # reads ergo_ml_backend/.env (admin login, device token)
    load_env()
except Exception:
    pass

DEVICE = "SAMPLE-01"
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  - {detail}" if detail else ""))
    return ok


def call(base, method, path, body=None, headers=None, raw=False):
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
            return resp.status, (data if raw else (json.loads(data) if data else None))
    except urllib.error.HTTPError as exc:
        data = exc.read()
        try:
            return exc.code, json.loads(data)
        except ValueError:
            return exc.code, data


def send_reading(base, reading, device_token):
    body = {k: v for k, v in reading.items() if not k.startswith("_")}
    hdr = {"X-Device-Token": device_token} if device_token else {}
    return call(base, "POST", f"/api/devices/{DEVICE}/readings", body, hdr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.backend.rstrip("/")
    device_token = os.getenv("DEVICE_INGEST_TOKEN", "").strip()

    readings = [json.loads(l) for l in (HERE / "wearable_session.jsonl").read_text(encoding="utf-8").splitlines() if l]
    answers = json.loads((HERE / "answers_low_risk.json").read_text(encoding="utf-8"))["answers"]
    # All 60 s: the server only scores readings from 60 s after the baseline starts
    baseline = [r for r in readings if r["_phase"] == "baseline"]
    live = [r for r in readings if r["_phase"] in ("slouch", "stressed")]

    print("1. Backend and consent")
    if not check("backend is running", call(base, "GET", "/health")[0] == 200, base):
        return 1
    st, _ = call(base, "POST", "/api/sessions", {"input_mode": "typed", "client_name": "Sample replay", "consent": False})
    check("session WITHOUT consent is refused", 400 <= st < 500, f"HTTP {st}")
    st, sess = call(base, "POST", "/api/sessions", {"input_mode": "typed", "client_name": "Sample replay (auto-deleted)",
                                                   "client_email": "sample@example.com", "client_age": 22,
                                                   "client_job": "Student", "consent": True})
    if not check("session with consent is created", st == 201, f"HTTP {st}"):
        return 1
    sid, auth = sess["id"], {"X-Session-Token": sess["access_token"]}
    try:
        st, _ = call(base, "GET", f"/api/sessions/{sid}/sensors/latest")
        check("participant data WITHOUT session token is refused", st == 401, f"HTTP {st}")

        print(f"\n2. Wearable baseline ({len(baseline)} s of calm sample readings)")
        st, _ = call(base, "POST", f"/api/sessions/{sid}/device", {"device_id": DEVICE}, auth)
        check("wearable SAMPLE-01 linked to the session", st == 200, f"HTTP {st}")
        st, _ = call(base, "POST", f"/api/sessions/{sid}/baseline/start", None, auth)
        check("baseline started", st == 200, f"HTTP {st}")
        codes = []
        for r in baseline:
            codes.append(send_reading(base, r, device_token)[0])
            time.sleep(1)
        check("baseline readings accepted", codes and all(c == 200 for c in codes), f"{codes.count(200)}/{len(codes)}")
        st, b = call(base, "POST", f"/api/sessions/{sid}/baseline/finish", None, auth)
        check("personal baseline computed", st == 200 and b.get("bpm") and b.get("gsr"),
              f"resting {b.get('bpm')} BPM, skin response {b.get('gsr')}" if st == 200 else f"HTTP {st} {b}")

        print("\n3. Answers (answers_low_risk.json)")
        ok = sum(call(base, "POST", f"/api/sessions/{sid}/answers",
                      {k: a[k] for k in ("question_id", "question_text", "typed_answer")}, auth)[0] == 201
                 for a in answers)
        check("all 40 answers saved", ok == len(answers), f"{ok}/{len(answers)}")

        print(f"\n4. Live readings ({len(live)} s: slouching, then stressed)")
        seen = set()
        for i, r in enumerate(live):
            send_reading(base, r, device_token)
            if i % 3 == 0:
                _, d = call(base, "GET", f"/api/sessions/{sid}/sensors/latest", headers=auth)
                seen.update(w["type"] for w in (d or {}).get("warnings", []))
            time.sleep(1)
        check("on-screen posture warning raised while slouching", "posture" in seen, f"warnings seen: {sorted(seen)}")

        print("\n5. Report")
        st, done = call(base, "POST", f"/api/sessions/{sid}/complete", None, auth)
        if check("session completed and scored", st == 200, f"HTTP {st}"):
            w = (done["report"] or {}).get("wearable") or {}
            check("report includes the wearable section", w.get("available") is True)
            c = w.get("combined") or {}
            if c:
                expected = round(0.6 * c["questionnaire"] + 0.4 * c["objective"], 1)
                check("ErgoCare Index = 60% questionnaire + 40% body signals",
                      abs(c["index"] - expected) <= 0.1,
                      f"{c['index']} = 0.6 x {c['questionnaire']} + 0.4 x {c['objective']}")
            titles = [i["title"] for i in w.get("insights", [])]
            p = w.get("posture") or {}
            check("'Posture blind spot' found (low-risk answers, but slouching)", "Posture blind spot" in titles,
                  f"insights: {titles}; leaning > 20 deg {p.get('pct_time_bad')}% of the time")
        st, pdf = call(base, "GET", f"/api/sessions/{sid}/report.pdf", headers=auth, raw=True)
        check("PDF report downloads", st == 200 and isinstance(pdf, bytes) and pdf[:4] == b"%PDF",
              f"{len(pdf) if isinstance(pdf, bytes) else 0:,} bytes")
    finally:
        print("\n6. Clean-up")
        st, login = call(base, "POST", "/api/admin/login",
                         {"username": os.getenv("ADMIN_USERNAME", "admin"), "password": os.getenv("ADMIN_PASSWORD", "")})
        token = login.get("token", "") if isinstance(login, dict) else ""
        st, _ = call(base, "DELETE", f"/api/sessions/{sid}", headers={"Authorization": f"Bearer {token}"})
        check("test session and its data deleted", st == 204, f"HTTP {st}")

    print(f"\nRESULT: {len(PASS)}/{len(PASS) + len(FAIL)} checks passed")
    for f in FAIL:
        print("  FAILED:", f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
