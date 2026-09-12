#!/usr/bin/env python3
"""Replay a recorded session through the real WebSocket, at real time.

The third data source, on equal footing with hardware and fake_node. If the nodes
die at 1:30 PM the answer is not "our app doesn't work" — it is "switch to the
Founders Hall recording", and every screen behaves identically, because this enters
through the same socket in the same wire format and runs the same pipeline. The FFT
executes, the peak is found, the confidence is computed. The number appears because
it was COMPUTED, not because it was baked into a video frame.

And it is real data: actual accelerometer samples from the actual building.

Written by Shivam's side (plan Phase 2b) rather than waiting, so it is proven
against synthetic data hours before the recording it exists for is taken.
Input is backend/data/sessions/<id>.jsonl, written automatically for every session.
"""
import argparse
import asyncio
import json
import sys
import time


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["t"])
    return rows


async def run(args):
    rows = load(args.file)
    if not rows:
        print(f"{args.file}: empty", file=sys.stderr)
        return 1
    labels = sorted({r["node"] for r in rows})
    t0 = rows[0]["t"]
    span = (rows[-1]["t"] - t0) / 1000.0
    print(f"--- REPLAY ---\n  file   : {args.file}\n  samples: {len(rows)}"
          f"\n  nodes  : {', '.join(labels)}\n  span   : {span:.1f}s", file=sys.stderr)

    import websockets
    async with websockets.connect(args.server) as ws:
        for label in labels:
            await ws.send(json.dumps({
                "type": "hello", "node": label, "fs_hz": 200,
                "mac": "re:pl:ay:00:00:01", "rssi": -50, "tilt_deg": 0.0,
                "gravity_ms2": 9.81, "calibrated": True,
                "firmware": "replay_node"}))     # -> source "replay", REPLAY badge

        while True:
            start = time.time()
            # Re-stamp t to now while PRESERVING the original spacing: the pipeline
            # derives fs from timestamps, so keeping the spacing is what makes a
            # replay analyse identically to the original recording.
            batch, batch_node = [], None
            for r in rows:
                offset = (r["t"] - t0) / 1000.0 / args.speed
                if batch and (r["node"] != batch_node or len(batch) >= 20):
                    await ws.send(json.dumps(batch))
                    batch = []
                batch_node = r["node"]
                wait = start + offset - time.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                batch.append({"t": int((start + offset) * 1000), "node": r["node"],
                              "ax": r["ax"], "ay": r["ay"], "az": r["az"]})
            if batch:
                await ws.send(json.dumps(batch))
            if not args.loop:
                break
            print("  looping", file=sys.stderr)
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--server", default="ws://localhost:48266/ws")
    p.add_argument("--file", required=True, help="backend/data/sessions/<id>.jsonl")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--speed", type=float, default=1.0)
    return asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
