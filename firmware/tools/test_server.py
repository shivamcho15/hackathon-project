#!/usr/bin/env python3
"""Minimal WebSocket sink, to prove the node's transport end to end.

NOT the backend — Shivam's FastAPI server is. This exists so the hardware side can
verify its own output arrives intact without waiting on the backend to exist, and
so "the stream works" is a measured claim rather than an assumption.

It reports what actually matters about a stream: arrival rate, timestamp spacing,
and gaps. A batch counter alone would hide dropped samples, which is precisely the
bug class that bit us at 115200 baud.

  python test_server.py --port 48266 --out received.jsonl
  # then on the node:  server <laptop-ip>:48266   /   stream on
  # afterwards:        python verify_pipeline.py received.jsonl

Port note: 48266 is deliberate — it is the one inbound TCP port already allowed
through Windows Firewall for OTA, so this needs no extra admin step. Pass a
different -P to espota if flashing while this is running.
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
import time

import websockets


class Stats:
    """Running statistics with BOUNDED memory.

    ⚠ An earlier version kept every inter-sample delta in a list and called
    sorted() on it for each 5 s report. After an hour that list held ~700,000
    entries, and sorting it repeatedly blocked the asyncio event loop long enough
    for WebSocket ping timeouts - so the server dropped the client roughly once a
    minute, getting steadily worse as the run went on.

    That looked exactly like flaky hardware and nearly cost an hour chasing WiFi.
    A test harness that degrades over time is worse than no harness, because it
    manufactures the failures it is supposed to detect. Hence: fixed-size window.
    """

    WINDOW = 4000        # ~20 s of samples at 200 Hz; plenty for a median

    def __init__(self) -> None:
        self.batches = 0
        self.samples = 0
        self.first_wall = None
        self.last_ts: dict[str, int] = {}
        self.gaps: dict[str, int] = {}
        self.deltas: dict[str, collections.deque] = {}
        self.maxdt: dict[str, int] = {}
        self.nodes: set[str] = set()

    def add_batch(self, rows: list[dict]) -> None:
        if self.first_wall is None:
            self.first_wall = time.time()
        self.batches += 1
        self.samples += len(rows)
        for s in rows:
            n = s.get("node", "?")
            self.nodes.add(n)
            t = s.get("t")
            if n in self.last_ts and isinstance(t, int):
                d = t - self.last_ts[n]
                dq = self.deltas.get(n)
                if dq is None:
                    dq = self.deltas[n] = collections.deque(maxlen=self.WINDOW)
                dq.append(d)
                # Max is tracked separately so the bounded window cannot forget it.
                if d > self.maxdt.get(n, 0):
                    self.maxdt[n] = d
                # >3x the nominal 5 ms spacing means samples went missing.
                if d > 15:
                    self.gaps[n] = self.gaps.get(n, 0) + 1
            if isinstance(t, int):
                self.last_ts[n] = t

    def report(self) -> str:
        if not self.first_wall:
            return "no data yet"
        el = max(1e-6, time.time() - self.first_wall)
        out = [f"{self.batches} batches / {self.samples} samples in {el:.1f}s "
               f"= {self.batches/el:.1f} batch/s, {self.samples/el:.1f} samp/s"]
        for n in sorted(self.nodes):
            d = self.deltas.get(n)
            if d:
                srt = sorted(d)                      # bounded: WINDOW entries
                med = srt[len(srt) // 2]
                fs = 1000.0 / med if med else float("inf")
                out.append(f"  {n:7s} median dt={med} ms -> fs={fs:.2f} Hz, "
                           f"max dt={self.maxdt.get(n, 0)} ms, "
                           f"gaps={self.gaps.get(n, 0)}")
        return "\n".join(out)


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=48266)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--out", help="write received samples as JSONL for verify_pipeline")
    p.add_argument("--seconds", type=float, default=60.0)
    args = p.parse_args()

    stats = Stats()
    fh = open(args.out, "w", encoding="utf-8") if args.out else None

    async def handler(conn):
        peer = getattr(conn, "remote_address", ("?", 0))
        print(f"[conn] {peer[0]} connected", flush=True)
        try:
            async for msg in conn:
                try:
                    data = json.loads(msg)
                except json.JSONDecodeError:
                    print(f"[warn] non-JSON: {msg[:120]!r}", flush=True)
                    continue
                if isinstance(data, dict):
                    print(f"[{data.get('type', 'msg')}] {json.dumps(data)}", flush=True)
                elif isinstance(data, list):
                    stats.add_batch(data)
                    if fh:
                        fh.write(json.dumps(data) + "\n")
        except websockets.ConnectionClosed:
            pass
        print(f"[conn] {peer[0]} disconnected", flush=True)

    async with websockets.serve(handler, args.host, args.port, max_size=None):
        print(f"listening on ws://{args.host}:{args.port}/ws  for {args.seconds:.0f}s",
              flush=True)
        end = time.time() + args.seconds
        while time.time() < end:
            await asyncio.sleep(5)
            print(stats.report(), flush=True)

    if fh:
        fh.close()
    print("\n=== FINAL ===")
    print(stats.report())
    return 0 if stats.samples else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
