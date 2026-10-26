"""
Verifies the wearable security and data-integrity fixes.

Run:  python scripts/verify_sensor_security.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASS, FAIL = [], []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" - {detail}" if detail and not ok else ""))


def main() -> int:
    print("\n[0] Isolated database")
    tmp = tempfile.mkdtemp(prefix="ergocare-verify-")
    os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp) / 'verify.db'}"

    # Import the app first so every model is registered on Base.metadata,
    # otherwise create_all builds an empty database.
    import app.main as main_mod
    from app.db.database import Base, engine
    Base.metadata.create_all(bind=engine)
    check("test database created", engine.url.database.endswith("verify.db"))

    print("\n[1] Schema rejects non-finite and out-of-range sensor values")
    from pydantic import ValidationError
    from app.models.schemas import SensorReadingIn

    ok = True
    try:
        SensorReadingIn(bpm=float("nan"))
        ok = False
    except ValidationError:
        pass
    check("NaN bpm rejected", ok)

    ok = True
    try:
        SensorReadingIn(tilt=float("inf"))
        ok = False
    except ValidationError:
        pass
    check("Infinity tilt rejected", ok)

    ok = True
    try:
        SensorReadingIn(gsr_raw=99999)
        ok = False
    except ValidationError:
        pass
    check("gsr_raw above ADC range rejected", ok)

    ok = True
    try:
        SensorReadingIn(gsr_raw=-5)
        ok = False
    except ValidationError:
        pass
    check("negative gsr_raw rejected", ok)

    ok = True
    try:
        SensorReadingIn(age_ms=10_000_000)
        ok = False
    except ValidationError:
        pass
    check("absurd age_ms rejected", ok)

    good = SensorReadingIn(bpm=72.5, gsr_raw=300, tilt=12.0, age_ms=1000)
    check("normal reading still accepted", good.bpm == 72.5)

    print("\n[2] sanitize_reading strips NaN/Inf out of the live registry")
    from app.domain import sensors as S

    dirty = {"bpm": float("nan"), "tilt": float("inf"), "gsr_raw": 300,
             "ax": 0.1, "nested": {"x": float("nan")}, "moving": False, "seq": 4}
    clean = S.sanitize_reading(dirty)
    check("top-level NaN cleared", clean["bpm"] is None)
    check("top-level Inf cleared", clean["tilt"] is None)
    check("nested NaN cleared", clean["nested"]["x"] is None)
    check("valid values untouched", clean["gsr_raw"] == 300 and clean["ax"] == 0.1)
    check("bools/ints untouched", clean["moving"] is False and clean["seq"] == 4)

    import json
    try:
        json.dumps(clean, allow_nan=False)
        serialisable = True
    except ValueError:
        serialisable = False
    check("result is strict-JSON serialisable", serialisable)
    check("sanitize_reading(None) is safe", S.sanitize_reading(None) is None)

    print("\n[3] Device routes require the token when one is configured")
    from fastapi.testclient import TestClient

    # The token is read from the environment on every request, so no reload needed.
    os.environ["DEVICE_INGEST_TOKEN"] = "s3cret-device-token"
    client = TestClient(main_mod.app)

    body = {"bpm": 70, "bpm_avg": 70, "finger": True, "gsr_raw": 300,
            "gsr_contact": True, "tilt": 5, "seq": 1, "age_ms": 0}

    r = client.post("/api/devices/ERGO-01/readings", json=body)
    check("POST without token is 401", r.status_code == 401, f"got {r.status_code}")

    r = client.post("/api/devices/ERGO-01/readings", json=body,
                    headers={"X-Device-Token": "wrong"})
    check("POST with wrong token is 401", r.status_code == 401, f"got {r.status_code}")

    r = client.post("/api/devices/ERGO-01/readings", json=body,
                    headers={"X-Device-Token": "s3cret-device-token"})
    check("POST with correct token is 200", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")

    r = client.get("/api/devices")
    check("GET /api/devices without token is 401", r.status_code == 401, f"got {r.status_code}")
    r = client.get("/api/devices", headers={"X-Device-Token": "s3cret-device-token"})
    check("GET /api/devices with token is 200", r.status_code == 200, f"got {r.status_code}")
    check("listing contains the device", any(d["device_id"] == "ERGO-01" for d in r.json()))

    # By design the browser's "Connect wearable" screen reads this without the
    # device secret (it never has it), before any session is linked. So it must
    # stay readable - and must never carry anything that identifies a person.
    r = client.get("/api/devices/ERGO-01/latest")
    check("GET latest without token is readable (connect screen)", r.status_code == 200, f"got {r.status_code}")
    personal = {"session_id", "client_name", "client_email", "client_phone", "access_token", "baseline"}
    check("GET latest carries no personal or session data",
          not (personal & set(r.json())) and not (personal & set(r.json().get("reading") or {})),
          f"keys {sorted(r.json())}")
    r = client.get("/api/devices/ERGO-01/latest",
                   headers={"X-Device-Token": "s3cret-device-token"})
    check("GET latest with token is 200", r.status_code == 200, f"got {r.status_code}")

    print("\n[4] NaN posted to the device endpoint does not 500 the read endpoints")
    # httpx refuses to *encode* NaN, but a real client (or a lenient one) can put a
    # literal NaN on the wire, and Python's json decoder accepts it. Send it raw.
    raw = ('{"bpm": NaN, "bpm_avg": 70, "finger": true, "gsr_raw": 300, '
           '"gsr_contact": true, "tilt": Infinity, "seq": 2, "age_ms": 0}')
    r = client.post("/api/devices/ERGO-01/readings", content=raw,
                    headers={"Content-Type": "application/json",
                             "X-Device-Token": "s3cret-device-token"})
    check("NaN/Inf reading is rejected at the schema (422)", r.status_code == 422,
          f"got {r.status_code}")

    r = client.get("/api/devices/ERGO-01/latest",
                   headers={"X-Device-Token": "s3cret-device-token"})
    check("latest still returns 200 after a rejected NaN reading", r.status_code == 200,
          f"got {r.status_code} {r.text[:160]}")

    print("\n[4b] Out-of-range values are rejected, valid ones stored")
    r = client.post("/api/devices/ERGO-01/readings", json={**body, "gsr_raw": 50000},
                    headers={"X-Device-Token": "s3cret-device-token"})
    check("gsr_raw=50000 rejected (422)", r.status_code == 422, f"got {r.status_code}")
    r = client.post("/api/devices/ERGO-01/readings", json={**body, "tilt": -3},
                    headers={"X-Device-Token": "s3cret-device-token"})
    check("negative tilt rejected (422)", r.status_code == 422, f"got {r.status_code}")
    r = client.post("/api/devices/ERGO-01/readings", json={**body, "seq": 3},
                    headers={"X-Device-Token": "s3cret-device-token"})
    check("normal reading still stored (200)", r.status_code == 200, f"got {r.status_code}")

    print("\n[5] Session sensor routes require the session token")
    for method, path in [
        ("get", "/api/sessions/some-id/sensors/latest"),
        ("get", "/api/sessions/some-id/sensors/history"),
        ("post", "/api/sessions/some-id/device"),
        ("delete", "/api/sessions/some-id/device"),
        ("post", "/api/sessions/some-id/baseline/start"),
        ("post", "/api/sessions/some-id/baseline/finish"),
    ]:
        kw = {"json": {"device_id": "ERGO-01"}} if method == "post" and path.endswith("/device") else {}
        r = getattr(client, method)(path, **kw)
        check(f"{method.upper()} {path} without token is 401", r.status_code == 401,
              f"got {r.status_code}")

    r = client.post("/api/sessions/not-a-real-session/device", json={"device_id": "ERGO-01"},
                    headers={"X-Session-Token": "x" * 43})
    check("link with unknown session is 404", r.status_code == 404, f"got {r.status_code}")

    print("\n[6] Open mode still works when no token is configured")
    del os.environ["DEVICE_INGEST_TOKEN"]
    r = client.post("/api/devices/ERGO-01/readings", json=body)
    check("POST without token allowed when unset", r.status_code == 200, f"got {r.status_code} {r.text[:120]}")

    print(f"\n{'=' * 60}")
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())