#!/usr/bin/env python3
"""Pre-flight check - one command, one verdict, before the build window opens.

At 8:30 AM with 200 people arriving there is no time to work out *which* of ten
things is wrong. This connects to whichever node is on USB, reboots it, reads its
own self-report, and prints a checklist.

It deliberately auto-detects the baud rate: stream_node runs at 921600 and
smoke_test at 115200, and "which firmware is on this board" is exactly the kind of
thing nobody remembers under pressure.

  python preflight.py                      # whatever is on USB
  python preflight.py --ping 10.0.0.146 10.0.0.216   # also check nodes over WiFi
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time

import serial
import serial.tools.list_ports

BAUDS = [921600, 115200]
BOOT_DONE = ("[BOOT] ready", "entering live mode")

GREEN, RED, YELLOW, DIM, RESET = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"


def find_ports() -> list[str]:
    return [p.device for p in serial.tools.list_ports.comports()]


def read_boot(port: str, baud: int, timeout: float = 40.0) -> list[str]:
    """Reset the node and capture its boot output."""
    lines: list[str] = []
    try:
        with serial.Serial(port, baud, timeout=0.2) as ser:
            ser.dtr = False
            ser.rts = True
            time.sleep(0.15)
            ser.reset_input_buffer()
            ser.rts = False
            buf = b""
            end = time.time() + timeout
            while time.time() < end:
                buf += ser.read(4096)
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.decode("utf-8", errors="replace").rstrip("\r")
                    lines.append(line)
                    if any(m in line for m in BOOT_DONE):
                        return lines
    except serial.SerialException as e:
        lines.append(f"__ERROR__ {e}")
    return lines


def detect(port: str) -> tuple[int | None, list[str]]:
    """Try each baud; the right one produces readable [TAG] lines."""
    for baud in BAUDS:
        lines = read_boot(port, baud, timeout=40.0)
        if any(l.startswith("[BOOT]") for l in lines):
            return baud, lines
        if any("__ERROR__" in l for l in lines):
            return None, lines
    return None, []


def check(label: str, ok: bool | None, detail: str = "") -> bool:
    mark = f"{GREEN}PASS{RESET}" if ok else (f"{YELLOW}WARN{RESET}" if ok is None else f"{RED}FAIL{RESET}")
    print(f"  [{mark}] {label:28s} {DIM}{detail}{RESET}")
    return bool(ok)


def grep1(lines: list[str], pattern: str) -> str | None:
    for l in lines:
        m = re.search(pattern, l)
        if m:
            return m.group(1) if m.groups() else l
    return None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", help="serial port; default = first found")
    p.add_argument("--ping", nargs="*", default=[], help="node IPs to check over WiFi")
    args = p.parse_args()

    print(f"\n{'='*62}\n  earthquake-assess PRE-FLIGHT\n{'='*62}")

    ports = find_ports()
    print(f"\nSerial ports: {', '.join(ports) if ports else 'NONE FOUND'}")
    if not ports:
        print(f"\n{RED}No node on USB.{RESET} Check the cable carries DATA, not just charge.")
        return 1

    port = args.port or ports[0]
    print(f"Using {port} - rebooting and reading its self-report (up to 40 s)...\n")

    baud, lines = detect(port)
    if baud is None:
        print(f"{RED}No readable output.{RESET}")
        for l in lines[-6:]:
            print(f"  {DIM}{l}{RESET}")
        return 1

    fw = "stream_node" if baud == 921600 else "smoke_test"
    print(f"{'-'*62}\n  NODE ON {port}   firmware={fw}  baud={baud}\n{'-'*62}")

    ok = True
    node = grep1(lines, r'node="?(\w+)"?')
    ok &= check("node identity", node in ("top", "ground"),
                node or "unset - run:  node top   |   node ground")

    addr = grep1(lines, r"MPU-6050 at (0x[0-9A-Fa-f]+)") or grep1(lines, r"using MPU at (0x[0-9A-Fa-f]+)")
    ok &= check("sensor on I2C", addr is not None, addr or "NOT FOUND - check VCC/GND/SDA/SCL")

    who = grep1(lines, r"\[WHOAMI\] (genuine MPU-6050)")
    check("genuine MPU-6050", who is not None or fw == "stream_node",
          who or "(stream_node doesn't re-check)")

    ip = grep1(lines, r"ip=(\d+\.\d+\.\d+\.\d+)")
    rssi = grep1(lines, r"rssi=(-?\d+)")
    ok &= check("WiFi", ip is not None,
                f"{ip} at {rssi} dBm" if ip else "NOT CONNECTED - hotspot on? 2.4 GHz?")
    if rssi and int(rssi) < -75:
        check("signal strength", None, f"{rssi} dBm is weak - move the hotspot closer")

    ota = grep1(lines, r'\[OTA\] ready as "([\w-]+)"')
    ok &= check("OTA (wireless flash)", ota is not None, ota or "unavailable")

    cal = grep1(lines, r"tilt ([\d.]+) deg")
    grav = grep1(lines, r"gravity=([\d.]+)")
    ok &= check("calibration", cal is not None,
                f"tilt {cal} deg, gravity {grav} m/s^2" if cal else "FAILED - hold sensor still, run: calibrate")

    epoch = grep1(lines, r"epoch_ms=(\d+)")
    check("NTP time", epoch is not None,
          "synced" if epoch else "relative millis only (fine, but nodes won't share a clock)")

    srv = grep1(lines, r"server=([\w.]*:\d+)")
    check("backend configured", srv is not None and not str(srv).startswith(":"),
          srv or "not set - run:  server <host>:<port>")

    for ipaddr in args.ping:
        r = subprocess.run(["ping", "-n", "2", "-w", "1500", ipaddr],
                           capture_output=True, text=True)
        check(f"reachable {ipaddr}", "TTL=" in r.stdout,
              "responds" if "TTL=" in r.stdout else "no reply - powered? same network?")

    print(f"\n{'='*62}")
    if ok:
        print(f"  {GREEN}READY{RESET} - this node is good to go")
    else:
        print(f"  {RED}NOT READY{RESET} - fix the FAIL lines above")
    print(f"{'='*62}\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
