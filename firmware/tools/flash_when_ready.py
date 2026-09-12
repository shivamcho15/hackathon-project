#!/usr/bin/env python3
"""Flash an ESP32 that has no auto-download circuit.

This board's DTR line is not wired to GPIO0, so esptool cannot put it into
download mode on its own (it reports boot:0x13 SPI_FAST_FLASH_BOOT and gives up).

Worse, on this board *opening the serial port at all* resets the chip: the CP210x
driver asserts RTS on open and RTS drives EN. So the usual "tap BOOT+RST, then
flash" dance does not survive - the port open knocks the chip straight back out of
download mode before esptool can talk to it.

The procedure that does work: hold BOOT down CONTINUOUSLY while this script runs.
Each attempt deliberately pulses EN via RTS (--before default-reset); with GPIO0
physically held low, that reset lands in download mode every time. No timing to
get right, and nothing to race against.

  python flash_when_ready.py --port COM4 --bin ../build/smoke_test.ino.merged.bin
"""

import argparse
import subprocess
import sys
import time


def attempt(port: str, baud: int, image: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable, "-m", "esptool",
            "--port", port,
            "--baud", str(baud),
            # Pulse EN ourselves. With BOOT physically held, GPIO0 is low when EN
            # releases, so this reset lands in download mode. Using no-reset here
            # instead would be pointless: opening the port already reset the chip.
            "--before", "default-reset",
            "--after", "hard-reset",     # boot straight into the new firmware
            "--connect-attempts", "1",   # fail fast so the retry loop stays responsive
            "write-flash", "0x0", image,
        ],
        capture_output=True,
        text=True,
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", default="COM4")
    p.add_argument("--baud", type=int, default=460800)
    p.add_argument("--bin", required=True, help="merged full-flash image, written at 0x0")
    p.add_argument("--timeout", type=float, default=240.0)
    args = p.parse_args()

    print("HOLD THE BOOT BUTTON DOWN NOW and keep holding it.")
    print("  (labelled BOOT or IO0 - do not tap it, hold it)")
    print("  No BOOT button? Jumper GPIO0 to GND and leave the jumper in place.")
    print(f"  Retrying on {args.port} for up to {args.timeout:.0f}s ...\n")

    deadline = time.time() + args.timeout
    tries = 0
    while time.time() < deadline:
        tries += 1
        r = attempt(args.port, args.baud, args.bin)
        if r.returncode == 0:
            print(r.stdout)
            print(f"--- FLASHED OK after {tries} attempt(s) ---")
            return 0

        # Distinguish "not in download mode yet" from a real problem worth showing.
        blob = (r.stdout + r.stderr)
        if "Wrong boot mode" in blob or "Failed to connect" in blob:
            if tries % 5 == 1:
                print(f"  [{tries}] still in normal boot, waiting ...")
        else:
            print(f"--- unexpected esptool failure on attempt {tries} ---")
            print(blob.strip()[:3000])
            return 1
        time.sleep(1.0)

    print("--- timed out waiting for download mode ---")
    return 1


if __name__ == "__main__":
    sys.exit(main())
