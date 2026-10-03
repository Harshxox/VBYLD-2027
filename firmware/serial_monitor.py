"""
ErgoCare wearable - live serial monitor.

Shows the ESP32's once-per-second JSON readings in a readable form so you can
check each sensor. Close the Arduino IDE Serial Monitor first (only one program
can use the COM port at a time).

Usage:
    python serial_monitor.py            # COM7 by default
    python serial_monitor.py COM5
    Type "cal" + Enter at any time to set the current posture as upright.
"""
import json
import sys
import threading

import serial

PORT = sys.argv[1] if len(sys.argv) > 1 else "COM7"


def read_commands(ser: serial.Serial) -> None:
    for line in sys.stdin:
        if line.strip().lower() == "cal":
            ser.write(b"CAL\n")


def main() -> None:
    ser = serial.Serial(PORT, 115200, timeout=1)
    print(f"Listening on {PORT} - Ctrl+C to stop, type 'cal' + Enter to recalibrate posture.\n")
    threading.Thread(target=read_commands, args=(ser,), daemon=True).start()
    try:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if line.startswith("#"):
                print(line)
                continue
            if not line.startswith("{"):
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            pulse = f"{r['bpm_avg']:5.1f} BPM" if r["finger"] and r["bpm_avg"] > 0 else (
                "reading... " if r["finger"] else "no finger  ")
            gsr = f"{r['gsr_raw']:>4.0f} raw" if r.get("gsr_contact", True) else "no contact"
            print(
                f"#{r['seq']:<5} HEART {pulse} (IR {r['ir']:>6}) | "
                f"GSR {gsr:>10} | "
                f"TILT {r['tilt']:5.1f} deg | "
                f"{'MOVING' if r['moving'] else 'still '} (gyro {r['gyro']:4.1f}) | "
                f"wifi {'on' if r['wifi'] else 'off'}"
            )
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()


if __name__ == "__main__":
    main()
