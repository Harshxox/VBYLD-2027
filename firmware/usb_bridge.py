"""
ErgoCare wearable - USB bridge.

Reads the ESP32's once-per-second JSON readings over USB and forwards each one
to the backend, exactly as the Wi-Fi firmware would:

    ESP32 --USB--> usb_bridge.py --HTTP--> POST {backend}/api/devices/{device_id}/readings

If the backend replies {"calibrate": true} (the app's baseline step), the
bridge tells the ESP32 to set the current posture as upright.

Keeps running through problems: re-opens the port if the cable is unplugged,
and keeps reading (with a warning) if the backend is not running.

Usage:
    python usb_bridge.py                          # auto-detect port, backend on localhost:8000
    python usb_bridge.py --port COM7
    python usb_bridge.py --backend http://127.0.0.1:8000
    python usb_bridge.py --no-backend             # just show readings (no forwarding)
    Type "cal" + Enter at any time to set the current posture as upright.

Close the Arduino IDE Serial Monitor / serial_monitor.py first - only one
program can use the COM port at a time.
"""
import argparse
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque

import serial
from serial.tools import list_ports

BAUD = 115200
USB_SERIAL_VIDS = {0x10C4, 0x1A86, 0x0403, 0x303A}  # CP210x, CH340, FTDI, Espressif native


def find_port() -> str | None:
    """Return the first COM port that looks like an ESP32 USB-serial chip."""
    for p in list_ports.comports():
        if p.vid in USB_SERIAL_VIDS:
            return p.device
    return None


def open_serial(port_arg: str | None) -> serial.Serial:
    """Open the ESP32 port, waiting (and retrying) until it is plugged in."""
    announced = False
    while True:
        port = port_arg or find_port()
        if port:
            try:
                ser = serial.Serial(port, BAUD, timeout=1)
                print(f"[usb] connected to {port}")
                return ser
            except serial.SerialException as exc:
                if not announced:
                    print(f"[usb] cannot open {port}: {exc} - is another program using it?")
                    announced = True
        elif not announced:
            print("[usb] ESP32 not found - plug it in (waiting...)")
            announced = True
        time.sleep(2)


class Forwarder:
    """
    Posts readings to the backend without losing any during short outages:
    unsent readings are buffered (up to BUFFER_MAX) and delivered in order once
    the backend answers again. Each carries age_ms so the backend stores the
    time it was measured, not the time it finally arrived.
    """
    BUFFER_MAX = 120      # ~2 minutes of readings
    TIMEOUT_S = 3

    def __init__(self, backend: str):
        self.backend = backend.rstrip("/")
        self.ok = None          # None = unknown yet, True/False = last result
        self.retry_at = 0.0
        self.failures = 0
        self.sent = 0
        self.pending = deque(maxlen=self.BUFFER_MAX)   # (reading, monotonic time measured)
        self.anchor = None      # laptop time minus ESP32 uptime (see measured_at)
        self.last_uptime = None

    def measured_at(self, reading: dict) -> float:
        """
        When the ESP32 took this reading, on the laptop's clock. Uses the device's
        own uptime_ms, so readings that queued up in the USB buffer (e.g. while
        the backend was down) still get exact 1-second spacing. The anchor is the
        smallest (arrival - uptime) seen, i.e. the least-delayed arrival.
        """
        now = time.monotonic()
        uptime = reading.get("uptime_ms")
        if uptime is None:
            return now
        up_s = uptime / 1000
        if self.anchor is None or self.last_uptime is None or uptime < self.last_uptime:
            self.anchor = now - up_s                    # first reading, or ESP32 restarted
        else:
            self.anchor = min(self.anchor, now - up_s)
        self.last_uptime = uptime
        return self.anchor + up_s

    def send(self, reading: dict) -> dict | None:
        """Queue this reading, then deliver everything queued. Returns the last reply."""
        self.pending.append((reading, self.measured_at(reading)))
        if time.monotonic() < self.retry_at:
            return None
        reply = None
        while self.pending:
            queued, read_at = self.pending[0]
            payload = dict(queued, age_ms=int((time.monotonic() - read_at) * 1000))
            result = self._post(payload)
            if result is None:
                return reply
            self.pending.popleft()
            reply = result if not reply or not reply.get("calibrate") else reply
        return reply

    def _post(self, payload: dict) -> dict | None:
        url = f"{self.backend}/api/devices/{payload['device_id']}/readings"
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            self._fail(f"backend answered HTTP {exc.code} for {url}")
            return None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            self._fail(f"backend not reachable at {self.backend} ({getattr(exc, 'reason', exc)})")
            return None
        self.sent += 1
        if self.ok is not True:
            backlog = len(self.pending) - 1
            print(f"[backend] forwarding readings to {url}"
                  + (f" (delivering {backlog} buffered)" if backlog > 0 else ""))
        self.ok, self.failures = True, 0
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError:
            return {}

    def _fail(self, msg: str) -> None:
        self.failures += 1
        if self.ok is not False:
            print(f"[backend] {msg} - buffering readings, retrying")
        self.ok = False
        if self.failures >= 3:                       # clearly down: stop hammering it
            self.retry_at = time.monotonic() + 3


def describe(r: dict) -> str:
    if not r.get("pulse_ok", True):
        heart = "sensor error"
    elif r["finger"] and r["bpm_avg"] > 0:
        heart = f"{r['bpm_avg']:5.1f} BPM"
    else:
        heart = "reading..." if r["finger"] else "no finger"
    gsr = f"{r['gsr_raw']:.0f}" if r.get("gsr_contact", True) else "no contact"
    return (f"#{r['seq']:<5} heart {heart:<12} | gsr {gsr:<10} | "
            f"tilt {r['tilt']:5.1f} deg | {'moving' if r['moving'] else 'still '}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Forward ErgoCare wearable readings from USB to the backend.")
    ap.add_argument("--port", help="COM port (default: auto-detect)")
    ap.add_argument("--backend", default="http://127.0.0.1:8000", help="backend base URL")
    ap.add_argument("--no-backend", action="store_true", help="only display readings")
    args = ap.parse_args()

    fwd = None if args.no_backend else Forwarder(args.backend)
    state = {"ser": None}

    def read_commands() -> None:
        for line in sys.stdin:
            if line.strip().lower() == "cal" and state["ser"]:
                state["ser"].write(b"CAL\n")
                print("[usb] posture recalibration sent")

    threading.Thread(target=read_commands, daemon=True).start()
    print("ErgoCare USB bridge - Ctrl+C to stop, type 'cal' + Enter to recalibrate posture.")

    try:
        while True:
            ser = state["ser"] = open_serial(args.port)
            try:
                while True:
                    line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    if line.startswith("#"):
                        print(f"[esp32] {line[1:].strip()}")
                        continue
                    if not line.startswith("{"):
                        continue            # boot noise
                    try:
                        reading = json.loads(line)
                    except json.JSONDecodeError:
                        continue            # partial line after reconnect
                    status = ""
                    if fwd:
                        reply = fwd.send(reading)
                        status = (f" | sent {fwd.sent}" if fwd.ok
                                  else f" | buffered ({len(fwd.pending)} waiting)")
                        if reply and reply.get("calibrate"):
                            ser.write(b"CAL\n")
                            print("[usb] app requested posture calibration")
                    print(describe(reading) + status)
            except serial.SerialException:
                print("[usb] ESP32 disconnected - waiting for it to come back...")
                state["ser"] = None
                try:
                    ser.close()
                except serial.SerialException:
                    pass
                time.sleep(1)
    except KeyboardInterrupt:
        print("\nBridge stopped.")
    finally:
        if state["ser"]:
            state["ser"].close()


if __name__ == "__main__":
    main()
