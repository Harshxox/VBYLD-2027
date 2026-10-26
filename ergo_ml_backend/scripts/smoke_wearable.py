"""
End-to-end smoke test: starts the real backend, drives a full wearable session
the way the app does, and checks the fixes hold over HTTP.

Run:  python scripts/smoke_wearable.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail and not ok else ""))


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ergocare-smoke-")
    env = {**os.environ,
           "DATABASE_URL": f"sqlite:///{Path(tmp) / 'smoke.db'}",
           "DEVICE_INGEST_TOKEN": "smoke-token-123",
           "ADMIN_PASSWORD": "smoke-admin-pw",
           "ADMIN_USERNAME": "admin"}

    port = 8765
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"

    import json
    import urllib.error
    import urllib.request

    def req(method, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", **(headers or {})}
        r = urllib.request.Request(f"{base}{path}", data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=20) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                return exc.code, json.loads(raw)
            except json.JSONDecodeError:
                return exc.code, raw[:200].decode(errors="replace")

    try:
        print("\n[1] Waiting for the backend to come up")
        up = False
        for _ in range(90):
            if proc.poll() is not None:
                print(proc.stdout.read())
                print("  backend exited during startup")
                return 1
            try:
                with urllib.request.urlopen(f"{base}/health", timeout=2) as resp:
                    if resp.status == 200:
                        up = True
                        break
            except Exception:
                time.sleep(1)
        check("backend healthy", up)
        if not up:
            return 1

        print("\n[2] Device auth enforced over real HTTP")
        reading = {"bpm": 68, "bpm_avg": 68, "finger": True, "ir": 60000,
                   "gsr_raw": 320, "gsr_mv": 900, "gsr_contact": True, "tilt": 3,
                   "ax": 0.1, "ay": 0.0, "az": 1.0, "gyro": 1, "acc_std": 0.05,
                   "moving": False, "pulse_ok": True, "mpu_ok": True,
                   "wifi": True, "seq": 1, "uptime_ms": 1000, "age_ms": 0}
        st, _ = req("POST", "/api/devices/ERGO-01/readings", reading)
        check("POST without token is 401", st == 401, f"got {st}")
        st, _ = req("POST", "/api/devices/ERGO-01/readings", reading,
                    {"X-Device-Token": "nope"})
        check("POST with wrong token is 401", st == 401, f"got {st}")
        st, _ = req("POST", "/api/devices/ERGO-01/readings", reading,
                    {"X-Device-Token": "smoke-token-123"})
        check("POST with correct token is 200", st == 200, f"got {st}")

        print("\n[3] NaN on the wire returns 422, not 500")
        req_obj = urllib.request.Request(
            f"{base}/api/devices/ERGO-01/readings",
            data=b'{"bpm": NaN, "tilt": Infinity, "gsr_raw": 300, "seq": 2}',
            method="POST",
            headers={"Content-Type": "application/json",
                     "X-Device-Token": "smoke-token-123"})
        try:
            with urllib.request.urlopen(req_obj, timeout=10) as resp:
                st = resp.status
        except urllib.error.HTTPError as exc:
            st = exc.code
        check("NaN body returns 422", st == 422, f"got {st}")

        print("\n[4] Session routes require their token")
        for method, path in [("GET", "/api/sessions/x/sensors/latest"),
                             ("GET", "/api/sessions/x/sensors/history"),
                             ("DELETE", "/api/sessions/x/device")]:
            st, _ = req(method, path)
            check(f"{method} {path} without token is 401", st == 401, f"got {st}")

        print("\n[5] Full wearable session with a correct token")
        st, sess = req("POST", "/api/sessions",
                      {"input_mode": "typed", "client_name": "Smoke Test", "consent": True})
        check("session created", st in (200, 201), f"got {st} {sess}")
        sid = sess["id"]
        tok = sess["access_token"]
        hdr = {"X-Session-Token": tok}

        st, _ = req("POST", f"/api/sessions/{sid}/device",
                    {"device_id": "ERGO-01"}, hdr)
        check("device linked", st == 200, f"got {st}")

        st, wrong = req("GET", f"/api/sessions/{sid}/sensors/latest", None, hdr)
        check("correct session token accepted", st == 200, f"got {st} {wrong}")

        # Wrong session's token must not open another session's data.
        st, s2 = req("POST", "/api/sessions",
                      {"input_mode": "typed", "client_name": "Other", "consent": True})
        st, _ = req("GET", f"/api/sessions/{sid}/sensors/latest", None,
                    {"X-Session-Token": s2["access_token"]})
        check("another session's token is rejected (403)", st == 403, f"got {st}")

        st, _ = req("POST", f"/api/sessions/{sid}/baseline/start", None, hdr)
        check("baseline started", st == 200, f"got {st}")

        st, early = req("POST", f"/api/sessions/{sid}/baseline/finish", None, hdr)
        check("finishing with no readings yet is 422", st == 422, f"got {st}")

        # The baseline window deliberately ignores the first BASELINE_SKIP_S (2 s)
        # while the device zeroes its posture, so wait that out before feeding.
        print("      waiting out the 2 s posture-settle window")
        time.sleep(2.5)

        print("      feeding 70 readings")
        for i in range(70):
            r = dict(reading, seq=100 + i, uptime_ms=1000 * (i + 1))
            st, _ = req("POST", "/api/devices/ERGO-01/readings", r,
                        {"X-Device-Token": "smoke-token-123"})
            if st != 200:
                check(f"reading {i} accepted", False, f"got {st}")
                break
        else:
            check("all 70 readings accepted", True)

        st, base_out = req("POST", f"/api/sessions/{sid}/baseline/finish", None, hdr)
        check("baseline computed", st == 200, f"got {st} {base_out}")
        if st == 200:
            check("baseline has bpm", "bpm" in (base_out or {}), str(base_out)[:120])
            check("baseline has gsr", "gsr" in (base_out or {}))

        st, live = req("GET", f"/api/sessions/{sid}/sensors/latest", None, hdr)
        check("live panel works", st == 200, f"got {st}")
        check("live shows connected", live.get("connected") is True, str(live)[:120])
        check("derived stress computed", live.get("derived") is not None)

        st, hist = req("GET", f"/api/sessions/{sid}/sensors/history", None, hdr)
        check("history works", st == 200, f"got {st}")
        check("history has points", len(hist.get("points", [])) > 0,
              str(hist.get("total_readings")))

        print("\n[6] Strict JSON: no NaN leaked into any response")
        for label, (st, payload) in [("live", (st, live)), ("history", (st, hist))]:
            try:
                json.dumps(payload, allow_nan=False)
                strict = True
            except ValueError as exc:
                strict = False
                print(f"      {exc}")
            check(f"{label} payload is strict-JSON", strict)

        print("\n[7] Question + report path still works after the changes")
        st, qs = req("GET", "/api/questions")
        check("questions served", st == 200 and len(qs) == 40,
              f"got {st} {len(qs) if isinstance(qs, list) else qs}")

        # One answer per request, exactly as index.html sends it. Options are plain strings.
        saved = 0
        for q in qs[:5]:
            st, ans = req("POST", f"/api/sessions/{sid}/answers",
                          {"question_id": q["id"], "question_text": q["text"],
                           "typed_answer": q["options"][0]}, hdr)
            if st in (200, 201):
                saved += 1
        check("answers saved (5/5)", saved == 5, f"saved {saved}")

        st, noauth = req("POST", f"/api/sessions/{sid}/answers",
                         {"question_id": qs[6]["id"], "question_text": qs[6]["text"],
                          "typed_answer": qs[6]["options"][0]})
        check("saving an answer without a token is 401", st == 401, f"got {st}")

        st, comp = req("POST", f"/api/sessions/{sid}/complete", None, hdr)
        check("session completed", st in (200, 201), f"got {st} {str(comp)[:150]}")

        st, second = req("POST", f"/api/sessions/{sid}/complete", None, hdr)
        check("completing twice is idempotent (200)", st == 200, f"got {st}")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()

    print(f"\n{'=' * 60}")
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())