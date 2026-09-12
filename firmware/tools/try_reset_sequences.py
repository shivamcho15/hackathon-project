#!/usr/bin/env python3
"""Sweep esptool reset sequences to find one that reaches download mode.

This board fails esptool's default reset with boot:0x13 (SPI_FAST_FLASH_BOOT),
meaning GPIO0 was high when EN released. Usually that means DTR is not wired to
GPIO0 at all - but it can also mean the board inverts one of the control lines,
or has enough capacitance on EN that the default 100ms hold is too short.

Those are cheap to rule out. Each candidate only toggles DTR/RTS and then runs a
READ-ONLY chip-id, so nothing is written to flash during the sweep.

Mini-language: D0/D1 = DTR low/high, R0/R1 = RTS low/high, W<sec> = wait.

  python try_reset_sequences.py --port COM4
"""

import argparse
import os
import subprocess
import sys
import tempfile

# (label, sequence). The first is esptool's own classic_reset, included as a
# control so a pass on it would mean the earlier failures were timing flukes.
CANDIDATES = [
    ("default classic (control)",      "D0|R1|W0.1|D1|R0|W0.05|D0"),
    ("longer hold + settle",           "D0|R1|W0.5|D1|R0|W0.5|D0"),
    ("very long hold",                 "D0|R1|W1.0|D1|R0|W1.0|D0"),
    ("DTR inverted",                   "D1|R1|W0.1|D0|R0|W0.05|D1"),
    ("DTR inverted, longer",           "D1|R1|W0.5|D0|R0|W0.5|D1"),
    ("RTS inverted",                   "D0|R0|W0.1|D1|R1|W0.05|D0"),
    ("both inverted",                  "D1|R0|W0.1|D0|R1|W0.05|D1"),
    ("both inverted, longer",          "D1|R0|W0.5|D0|R1|W0.5|D1"),
    ("IO0 low before EN even moves",   "D1|W0.2|R1|W0.3|R0|W0.3|D0"),
    ("IO0 held through whole reset",   "D1|R1|W0.3|R0|W0.5|D1"),
]


def try_sequence(port: str, seq: str) -> tuple[bool, str]:
    """Return (reached_download_mode, combined_output)."""
    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "esptool.cfg")
        with open(cfg, "w", encoding="utf-8") as f:
            f.write("[esptool]\n")
            f.write(f"custom_reset_sequence = {seq}\n")

        env = dict(os.environ, ESPTOOL_CFGFILE=cfg)
        r = subprocess.run(
            [sys.executable, "-m", "esptool",
             "--port", port,
             "--connect-attempts", "1",
             "chip-id"],               # read-only: never writes flash
            capture_output=True, text=True, env=env,
        )
        return r.returncode == 0, (r.stdout + r.stderr)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", default="COM4")
    args = p.parse_args()

    print(f"Sweeping {len(CANDIDATES)} reset sequences on {args.port}.")
    print("Read-only chip-id only - nothing is written to flash.\n")

    winners = []
    for label, seq in CANDIDATES:
        ok, out = try_sequence(args.port, seq)
        if ok:
            print(f"  PASS  {label:32s} {seq}")
            winners.append((label, seq))
        else:
            reason = "wrong boot mode" if "Wrong boot mode" in out else \
                     "no response"     if "Failed to connect" in out else \
                     "other error"
            print(f"  fail  {label:32s} {seq}   ({reason})")

    print()
    if winners:
        print("--- WORKING SEQUENCE(S) FOUND ---")
        for label, seq in winners:
            print(f"  {label}: {seq}")
        print("\nUse by writing an esptool.cfg containing:")
        print("  [esptool]")
        print(f"  custom_reset_sequence = {winners[0][1]}")
        return 0

    print("--- no sequence reached download mode ---")
    print("DTR is almost certainly not connected to GPIO0 on this board.")
    print("The BOOT button (or a GPIO0-to-GND jumper) is required.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
