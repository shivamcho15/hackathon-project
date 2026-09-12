#!/usr/bin/env python3
"""Send a runtime command to a node over USB and capture the reply.

Opening the port resets this board (RTS drives EN), and setup() then spends ~15s
running the staged hardware checks. Commands sent during that window are missed,
so this waits for the node to reach live mode before sending anything.

  python send_command.py --port COM4 --cmd "status"
  python send_command.py --port COM4 --cmd "wifi MySSID|hunter2" --listen 30

Credentials passed this way are stored in the ESP32's NVS. They are never written
to any file in this repo.
"""

import argparse
import sys
import time

import serial

# Either firmware's "I have finished booting" line. smoke_test drops into live
# mode; stream_node prints a ready banner and waits for commands.
READY_MARKERS = ("entering live mode", "[BOOT] ready")


def main() -> int:
    # Force UTF-8 on stdout - the same fix capture_serial.py already carries, which
    # this tool never got. Without it every run at 921600 dies with
    # UnicodeEncodeError partway through: the ROM bootloader always prints at
    # 115200 regardless of our baud, so its output arrives as bytes that cp1252
    # (the Windows console default) cannot encode. The traceback appears BEFORE the
    # command is sent, so the command silently never happens - which looks exactly
    # like a dead node. This blocked setting WiFi credentials on any stream_node
    # board, i.e. the one thing that has to work first on the day.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    p = argparse.ArgumentParser()
    p.add_argument("--port", default="COM4")
    p.add_argument("--baud", type=int, default=115200)
    p.add_argument("--cmd", required=True, action="append",
                   help="repeatable; commands are sent in order")
    p.add_argument("--listen", type=float, default=20.0,
                   help="seconds to capture after sending")
    p.add_argument("--boot-timeout", type=float, default=45.0)
    args = p.parse_args()

    with serial.Serial(args.port, args.baud, timeout=0.2) as ser:
        # Deliberate reset so we see a known-good starting state.
        ser.dtr = False
        ser.rts = True
        time.sleep(0.15)
        ser.reset_input_buffer()
        ser.rts = False

        buf = b""
        ready = False
        deadline = time.time() + args.boot_timeout
        print("--- waiting for node to finish its boot checks ---")
        while time.time() < deadline and not ready:
            buf += ser.read(4096)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").rstrip("\r")
                print(line, flush=True)
                if any(m in line for m in READY_MARKERS):
                    ready = True
                    break

        if not ready:
            print("--- node never reached live mode; sending anyway ---")

        for cmd in args.cmd:
            # Local pseudo-command: let time pass without resetting the board.
            # Reopening the port would reset it, so "measure, wait, measure again"
            # has to happen inside a single connection.
            if cmd.startswith("sleep "):
                secs = float(cmd.split()[1])
                print(f"\n--- waiting {secs}s ---\n")
                t_end = time.time() + secs
                while time.time() < t_end:
                    buf += ser.read(1024)
                    while b"\n" in buf:
                        raw, buf = buf.split(b"\n", 1)
                        print(raw.decode("utf-8", errors="replace").rstrip("\r"), flush=True)
                continue

            time.sleep(0.4)
            # Echo the command, but never the password.
            shown = cmd.split("|")[0] + "|<redacted>" if "|" in cmd else cmd
            print(f"\n--- sending: {shown} ---\n")
            ser.write((cmd + "\n").encode("utf-8"))
            ser.flush()
            # Drain the reply to this command before sending the next, so their
            # output doesn't interleave confusingly.
            t_end = time.time() + 1.5
            while time.time() < t_end:
                buf += ser.read(1024)
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    print(raw.decode("utf-8", errors="replace").rstrip("\r"), flush=True)

        end = time.time() + args.listen
        while time.time() < end:
            buf += ser.read(4096)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                print(raw.decode("utf-8", errors="replace").rstrip("\r"), flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
