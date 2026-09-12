#!/usr/bin/env python3
"""One command to record a building measurement. Finds the node, records, reports.

Written so the person holding the laptop on the top floor does not have to know a
COM port number, a baud rate, or what a flag is:

    python measure.py floor5

Everything else is automatic. The node is found by USB vendor ID, the baud rate is
fixed by the firmware, and the output filename carries the label and a timestamp so
two laptops can never overwrite each other's file.

The recording is deliberately long (default 90 s). The two nodes' clocks are
NTP-synced and every sample carries absolute epoch time, so the two laptops do NOT
need to start or stop together - the files are merged on timestamp afterwards. A
generous window costs nothing (a minute of data is ~1 MB) and removes the only
remaining way to get this wrong: cutting the recording before the stomp.
"""

import argparse
import datetime
import sys
import time

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("pyserial is missing. Install it with:  pip install pyserial")

BAUD = 921600           # stream_node's rate; 115200 cannot carry 200 Hz of JSON
CP210X = (0x10C4, 0xEA60)


def find_port(explicit=None):
    ports = list(serial.tools.list_ports.comports())
    if explicit:
        return explicit
    matches = [p for p in ports
               if (p.vid, p.pid) == CP210X or "CP210" in (p.description or "")]
    if not matches:
        sys.exit("No sensor node found on USB.\n"
                 "  - is the cable plugged in at both ends?\n"
                 "  - is it a DATA cable, not a charge-only one?\n"
                 f"  - ports seen: {[p.device for p in ports] or 'none'}")
    if len(matches) > 1:
        print(f"note: {len(matches)} nodes found, using {matches[0].device}")
    return matches[0].device


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label", help="where this is, e.g. floor5 / floor1 / lobby")
    ap.add_argument("--seconds", type=float, default=90.0)
    ap.add_argument("--port", default=None, help="override auto-detection")
    a = ap.parse_args()

    port = find_port(a.port)
    stamp = datetime.datetime.now().strftime("%H%M%S")
    out = f"{a.label}_{stamp}.log"

    print(f"node on {port}  ->  {out}")
    print(f"recording {a.seconds:.0f}s. STOMP whenever you like - just not in the "
          f"first 5 seconds.\n")

    # Attach WITHOUT resetting: the board is already streaming (autostream), already
    # clock-synced, and resetting it would throw away the NTP sync that makes the two
    # floors comparable. This is why the firmware persists `serial on` in NVS.
    # Configure the control lines BEFORE opening. serial.Serial(port, ...) opens
    # immediately and Windows asserts DTR/RTS as it does so - and RTS drives EN on
    # this board, so the constructor itself reboots the node. Setting them after the
    # fact is too late; the reset has already happened.
    #
    # That reset costs ~8 s of boot, but far worse: the node re-runs NTP on boot, and
    # on a top floor the hotspot may be out of range - so a node that WAS synced at
    # the table comes back on relative time, and its file can no longer be aligned
    # with the other floor's. The measurement would look fine and be unmergeable.
    ser = serial.Serial()
    ser.port = port
    ser.baudrate = BAUD
    ser.timeout = 0.2
    ser.dtr = False
    ser.rts = False
    ser.open()

    samples = batches = 0
    first_t = last_t = None
    buf = b""
    end = time.time() + a.seconds
    with open(out, "w", encoding="utf-8") as f:
        while time.time() < end:
            buf += ser.read(8192)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                line = raw.decode("utf-8", errors="replace").rstrip("\r")
                f.write(line + "\n")
                if line.startswith("[DATA] "):
                    batches += 1
                    n = line.count('{"t"')
                    samples += n
                    if first_t is None:
                        try:
                            first_t = int(line.split('"t":')[1].split(",")[0])
                        except Exception:
                            pass
                    try:
                        last_t = int(line.rsplit('"t":', 1)[1].split(",")[0])
                    except Exception:
                        pass
            left = end - time.time()
            print(f"\r  {samples:6d} samples   {max(0, left):4.0f}s left ", end="")
    ser.close()
    print("\n")

    if samples == 0:
        print("NO DATA RECORDED.")
        print("  The node is connected but sent nothing. Ask Saahil to run:")
        print(f'     python send_command.py --port {port} --baud {BAUD} --cmd "serial on"')
        return 1

    span = (last_t - first_t) / 1000.0 if first_t and last_t else 0
    fs = samples / span if span else 0
    print(f"saved {out}")
    print(f"  {samples} samples over {span:.1f}s  =  {fs:.2f} Hz")
    if first_t and first_t > 1_700_000_000_000:
        print(f"  clock: real time, starts {datetime.datetime.fromtimestamp(first_t/1000)}")
        print("  -> this file can be merged with the other floor's file")
    else:
        print("  ⚠ clock: RELATIVE, not real time. This file CANNOT be aligned with")
        print("    the other floor. The node did not reach the hotspot at boot -")
        print("    get it back in range and re-run before trusting this.")
    if fs and abs(fs - 200) > 10:
        print(f"  ⚠ sample rate {fs:.1f} Hz is not ~200 Hz - tell Saahil before moving on")
    return 0


if __name__ == "__main__":
    sys.exit(main())
