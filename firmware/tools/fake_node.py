#!/usr/bin/env python3
"""Fake sensor node — a drop-in replacement for the hardware.

PROD_DOC.md §7.2 makes this Saahil's first deliverable at 9:10, ahead of touching
a sensor, because Shivam is otherwise blocked until the hardware works and
hardware always overruns. This is that generator, built to the real contract:

  * identical wire format to stream_node.ino — SCHEMA.md §1 samples, batched 20
    per message (PIPELINE.md §1), same `hello` handshake
  * same transport — WebSocket client to the backend, same URL shape
  * same timing — 200 Hz, a batch every 100 ms

So the backend cannot tell it from a real node, and swapping to real hardware is
"stop this script", not a code change.

It does NOT emit noise. It synthesises a physically sensible stomp ringdown at a
frequency you choose, so the pipeline can be checked against a known answer:
run it at 3.2 Hz and the FFT had better say 3.2 Hz. The ground truth is printed
to stderr at startup.

  # two nodes, stomp every 12 s at 3.2 Hz, to a local backend
  python fake_node.py --server ws://localhost:8000/ws

  # see the JSON without a backend
  python fake_node.py --stdout

  # exercise the failure paths the pipeline must survive
  python fake_node.py --stdout --mode quiet      # nobody stomped  -> frequency_hz null
  python fake_node.py --stdout --mode noisy      # no clear peak   -> frequency_hz null
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import sys
import time

FS = 200.0            # PIPELINE.md §1
BATCH_N = 20          # 100 ms per message
G = 9.807


class FakeNode:
    """One simulated sensor node.

    `gain` scales the sway amplitude. A building's fundamental mode grows with
    height, so the top node is given a larger gain than the ground node - that is
    what makes the transmissibility in PIPELINE_TWO_SENSOR.md non-trivial and
    worth computing. Ratio here is deliberately modest (~4x), matching that file's
    warning not to expect a dramatic double-digit number from a low-rise building.
    """

    def __init__(self, name: str, gain: float, freq: float, damping: float,
                 tilt_deg: float, mode: str, noise: float):
        self.name = name
        self.gain = gain
        self.freq = freq
        self.damping = damping
        self.mode = mode
        self.noise = noise
        self.t0 = time.time()
        self.last_stomp = -1e9

        # Put gravity on a tilted axis. The real modules are hand-soldered and sit
        # crooked - node B measured 85.7 deg off level - so a generator that emits
        # perfectly axis-aligned gravity would let a bug in the vertical-axis
        # identification (PIPELINE.md §2 step 2) pass unnoticed.
        tilt = math.radians(tilt_deg)
        azim = random.uniform(0, 2 * math.pi)
        self.grav = (
            G * math.sin(tilt) * math.cos(azim),
            G * math.sin(tilt) * math.sin(azim),
            G * math.cos(tilt),
        )
        # Sway direction in the horizontal plane: one fixed axis, which is what
        # makes the PCA projection meaningful (linearly polarised motion).
        self.sway_dir = (math.cos(azim + math.pi / 2), math.sin(azim + math.pi / 2))

    def stomp(self, now: float) -> None:
        self.last_stomp = now

    def sample(self, now: float) -> tuple[float, float, float]:
        ax, ay, az = self.grav
        n = self.noise
        ax += random.gauss(0, n)
        ay += random.gauss(0, n)
        az += random.gauss(0, n)

        if self.mode == "quiet":
            return ax, ay, az                      # never any excitation
        dt = now - self.last_stomp

        if self.mode == "noisy":
            # Broadband burst with no coherent mode: real motion arrives, but
            # nothing resonates. Exercises PIPELINE.md §12 case 2 - onset detected,
            # no peak clears prominence.
            #
            # The burst MUST be gated on the stomp, not applied continuously. A
            # constant noise floor never exceeds 6x its own baseline RMS, so onset
            # detection never fires and the run falls through to case 1 instead -
            # which is what an earlier version of this did, silently testing the
            # wrong failure path.
            if 0 <= dt <= 6.0:
                k = 0.5 * math.exp(-dt / 3.0)
                ax += random.gauss(0, k)
                ay += random.gauss(0, k)
                az += random.gauss(0, k)
            return ax, ay, az
        if dt < 0 or dt > 12.0:
            return ax, ay, az

        # Decaying sinusoid: the ringdown. tau = 1/(2*pi*zeta*f), PIPELINE.md §5.
        tau = 1.0 / (2 * math.pi * self.damping * self.freq)
        amp = self.gain * math.exp(-dt / tau)
        s = amp * math.sin(2 * math.pi * self.freq * dt)

        ax += s * self.sway_dir[0]
        ay += s * self.sway_dir[1]
        # Vertical transient from the impact itself, sharply damped. The pipeline
        # discards the vertical axis, but it must be present or the data is too
        # clean to be a fair test.
        az += 2.5 * self.gain * math.exp(-dt / 0.08) * math.sin(2 * math.pi * 18 * dt)
        return ax, ay, az

    def hello(self) -> str:
        return json.dumps({
            "type": "hello", "node": self.name, "fs_hz": int(FS),
            "mac": "fa:ke:00:00:00:01", "rssi": -50,
            "tilt_deg": 0.0, "gravity_ms2": G, "calibrated": True,
            "firmware": "fake_node",
        })


async def run(args: argparse.Namespace) -> None:
    nodes = [FakeNode("ground", 0.28, args.freq, args.damping, args.tilt, args.mode, args.noise)]
    if not args.single:
        nodes.append(FakeNode("top", 1.15, args.freq, args.damping, args.tilt, args.mode, args.noise))

    print(f"--- GROUND TRUTH -------------------------------", file=sys.stderr)
    print(f"  frequency   : {args.freq} Hz  (period {1/args.freq:.3f} s)", file=sys.stderr)
    print(f"  damping     : {args.damping}", file=sys.stderr)
    print(f"  mode        : {args.mode}", file=sys.stderr)
    print(f"  nodes       : {', '.join(n.name for n in nodes)}", file=sys.stderr)
    if len(nodes) > 1:
        print(f"  amp ratio   : {nodes[1].gain / nodes[0].gain:.2f}x top/ground", file=sys.stderr)
    print(f"  stomp every : {args.stomp_every}s", file=sys.stderr)
    print(f"------------------------------------------------", file=sys.stderr)

    ws = None
    if args.server:
        import websockets
        ws = await websockets.connect(args.server)
        for n in nodes:
            await ws.send(n.hello())
        print(f"connected to {args.server}", file=sys.stderr)

    # Timestamps come from a sample COUNTER, not from the wall clock per sample.
    #
    # Sleeping per sample does not work on Windows: the scheduler's resolution is
    # ~15 ms against a 5 ms target, so the loop oversleeps, then sprints to catch
    # up and stamps a dozen samples with the same millisecond. Measured as
    # median(diff(t)) == 0 - which would have broken the backend's fs derivation
    # on contact, since it divides by that.
    #
    # Generating a whole batch at once and sleeping 100 ms between batches is both
    # robust to scheduler jitter and a closer match to the real firmware, which
    # holds 199.96 Hz with sub-microsecond spacing.
    t0_ms = int(time.time() * 1000)
    i = 0                       # global sample index -> exact 5 ms spacing
    sent = 0
    next_batch = time.perf_counter()
    next_stomp_i = int(2.0 * FS)

    try:
        while True:
            batch = {n.name: [] for n in nodes}
            for _ in range(BATCH_N):
                if i >= next_stomp_i:
                    for n in nodes:
                        n.stomp(i / FS)
                    next_stomp_i = i + int(args.stomp_every * FS)
                    print(f"[stomp] t={i / FS:.1f}s", file=sys.stderr)

                ts = t0_ms + round(i * 1000.0 / FS)
                for n in nodes:
                    ax, ay, az = n.sample(i / FS)
                    batch[n.name].append({
                        "t": ts, "node": n.name,
                        "ax": round(ax, 4), "ay": round(ay, 4), "az": round(az, 4),
                    })
                i += 1

            for n in nodes:
                payload = json.dumps(batch[n.name])
                if ws:
                    await ws.send(payload)
                if args.stdout:
                    print(payload, flush=True)
                sent += 1

            next_batch += BATCH_N / FS
            delay = next_batch - time.perf_counter()
            if delay < -0.5:
                next_batch = time.perf_counter()     # fell far behind; resync
            elif delay > 0:
                await asyncio.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        if ws:
            await ws.close()
        print(f"\nsent {sent} batches", file=sys.stderr)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--server", help="backend WebSocket URL, e.g. ws://localhost:8000/ws")
    p.add_argument("--stdout", action="store_true", help="print batches to stdout")
    p.add_argument("--freq", type=float, default=3.2, help="true building frequency (Hz)")
    p.add_argument("--damping", type=float, default=0.03, help="damping ratio, PROD_DOC §4.2")
    p.add_argument("--tilt", type=float, default=25.0, help="sensor tilt in degrees")
    p.add_argument("--noise", type=float, default=0.02, help="per-axis noise sd (m/s^2)")
    p.add_argument("--stomp-every", type=float, default=12.0)
    p.add_argument("--single", action="store_true", help="ground node only")
    p.add_argument("--mode", choices=["stomp", "quiet", "noisy"], default="stomp")
    args = p.parse_args()

    if not args.server and not args.stdout:
        args.stdout = True
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
