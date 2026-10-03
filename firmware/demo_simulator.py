"""
ErgoCare wearable - DEMO MODE simulator (backup if the hardware fails on stage).

Sends realistic readings to the backend exactly like the real ESP32 + usb_bridge,
as device "DEMO-01", so the whole app works: connect screen, baseline, live
panel, on-screen warnings, report and PDF. It is clearly labelled DEMO-01 in
the app - never present simulated data as a real measurement.

Controls (press a key, no Enter needed on Windows):
    s  slouch (lean forward ~27 deg)      u  sit upright
    t  stress rises (skin response +45%, heart rate +16)
    c  calm down                           m  move / fidget for 3 s
    f  take finger off / put it back       q  quit

Usage:
    python demo_simulator.py                         # backend on localhost:8000
    python demo_simulator.py --backend http://127.0.0.1:8000

Run either this OR usb_bridge.py, not both (the app connects to the first device it sees).
"""
import argparse
import json
import math
import random
import sys
import threading
import time
import urllib.error
import urllib.request

DEVICE_ID = "DEMO-01"


class Body:
    """A person at a desk: values drift smoothly towards the chosen state."""

    def __init__(self):
        self.start = time.monotonic()
        self.seq = 0
        self.slouch = False
        self.stressed = False
        self.finger = True
        self.move_until = 0.0
        self.bpm = 74.0
        self.gsr = 450.0
        self.tilt = 2.0
        self.tilt_zero = 0.0

    def step(self) -> dict:
        self.seq += 1
        t = time.monotonic() - self.start
        # heart rate and skin response approach their targets over ~5-10 s
        bpm_target = 74 + (16 if self.stressed else 0)
        gsr_target = 450 * (1.45 if self.stressed else 1.0)
        self.bpm += (bpm_target - self.bpm) * 0.25
        self.gsr += (gsr_target - self.gsr) * (0.18 if self.stressed else 0.08)
        tilt_target = 27 if self.slouch else 3
        self.tilt += (tilt_target - self.tilt) * 0.35
        moving = time.monotonic() < self.move_until
        bpm = self.bpm + 2.5 * math.sin(t / 7) + random.gauss(0, 1.0)
        gsr = self.gsr * (1 + 0.02 * math.sin(t / 5)) + random.gauss(0, 4)
        tilt = max(0.0, self.tilt - self.tilt_zero + random.gauss(0, 0.8) + (random.uniform(-6, 6) if moving else 0))
        return {
            "device_id": DEVICE_ID, "seq": self.seq, "uptime_ms": int(t * 1000),
            "bpm": round(bpm, 1) if self.finger else 0, "bpm_avg": round(bpm, 1) if self.finger else 0,
            "finger": self.finger, "ir": 90000 if self.finger else 1200,
            "gsr_raw": round(gsr), "gsr_mv": round(gsr * 0.9), "gsr_contact": True,
            "tilt": round(tilt, 1), "ax": 0.5, "ay": 0.2, "az": 9.8,
            "gyro": 25.0 if moving else 3.5, "acc_std": 0.8 if moving else 0.04, "moving": moving,
            "pulse_ok": True, "mpu_ok": True, "wifi": False,
        }

    def calibrate(self):
        """The app's baseline step: current posture becomes 'upright' (tilt 0)."""
        self.tilt_zero = self.tilt


def post(backend: str, reading: dict):
    req = urllib.request.Request(f"{backend}/api/devices/{DEVICE_ID}/readings", method="POST",
                                 data=json.dumps(reading).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read() or b"{}")


def read_keys(body: Body, stop: threading.Event):
    try:
        import msvcrt                      # Windows: single key presses
        getkey = lambda: msvcrt.getwch().lower()
    except ImportError:                    # elsewhere: type a letter + Enter
        getkey = lambda: (sys.stdin.readline().strip()[:1] or " ").lower()
    while not stop.is_set():
        k = getkey()
        if k == "s": body.slouch = True
        elif k == "u": body.slouch = False
        elif k == "t": body.stressed = True
        elif k == "c": body.stressed = False
        elif k == "m": body.move_until = time.monotonic() + 3
        elif k == "f": body.finger = not body.finger
        elif k == "q": stop.set()


def main():
    ap = argparse.ArgumentParser(description="ErgoCare demo-mode wearable simulator")
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    backend = args.backend.rstrip("/")

    print(__doc__.split("Usage:")[0].strip())
    print(f"\nSending as {DEVICE_ID} to {backend} - press q to quit.\n")
    body, stop = Body(), threading.Event()
    threading.Thread(target=read_keys, args=(body, stop), daemon=True).start()
    ok_before = None
    while not stop.is_set():
        r = body.step()
        try:
            reply = post(backend, r)
            if reply.get("calibrate"):
                body.calibrate()
            if ok_before is False:
                print("\n[backend] reachable again")
            ok_before = True
            state = (f"{'SLOUCHING' if body.slouch else 'upright  '} | {'STRESSED' if body.stressed else 'calm    '} | "
                     f"{'finger on ' if body.finger else 'finger OFF'} | HR {r['bpm']:5.1f} | GSR {r['gsr_raw']:4d} | tilt {r['tilt']:4.1f}")
            print(f"\r#{r['seq']:<5} {state}   ", end="", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            if ok_before is not False:
                print(f"\n[backend] not reachable at {backend} ({getattr(exc, 'reason', exc)}) - retrying...")
            ok_before = False
        time.sleep(1)
    print("\nDemo simulator stopped.")


if __name__ == "__main__":
    main()
