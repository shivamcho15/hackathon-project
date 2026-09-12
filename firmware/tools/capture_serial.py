#!/usr/bin/env python3
"""Capture serial output from an ESP32 node for a fixed duration.

Used by the smoke test so results land in a file instead of a screenshot.
Pulses RTS to reset the board first, so boot-time output is never missed.

  python capture_serial.py --port COM4 --seconds 25 --out run.log
"""

import argparse
import sys
import time

import serial


def main() -> int:
    # Force UTF-8 on stdout. Redirected to a file, Python falls back to the
    # Windows ANSI codepage, which cannot encode the ROM bootloader's binary
    # garbage (it prints at 115200 regardless of our baud) - the script then dies
    # with UnicodeEncodeError partway through a long capture. Interactive runs
    # happen to work, so this only bites exactly when logging unattended.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    p = argparse.ArgumentParser()
    p.add_argument("--port", default="COM4")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--seconds", type=float, default=25.0)
    p.add_argument("--out", default=None)
    p.add_argument("--no-reset", action="store_true",
                   help="attach to a running board instead of resetting it")
    args = p.parse_args()

    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2)
    except serial.SerialException as e:
        print(f"ERROR opening {args.port}: {e}", file=sys.stderr)
        print("Is the Arduino IDE serial monitor open? Only one process can hold the port.",
              file=sys.stderr)
        return 1

    with ser:
        if not args.no_reset:
            # On a CP2102-based ESP32, RTS drives EN. Pulse it low->high to reset
            # into a normal boot (DTR must stay deasserted or we land in bootloader).
            ser.dtr = False
            ser.rts = True
            time.sleep(0.15)
            ser.reset_input_buffer()
            ser.rts = False

        lines = []
        deadline = time.time() + args.seconds
        buf = b""
        while time.time() < deadline:
            chunk = ser.read(4096)
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").rstrip("\r")
                print(line, flush=True)
                lines.append(line)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\n--- {len(lines)} lines written to {args.out} ---")

    return 0


if __name__ == "__main__":
    sys.exit(main())
