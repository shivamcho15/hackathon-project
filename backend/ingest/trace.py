"""The live trace: display only, and never the analysis path.

The Measure screen's traces CANNOT be the analysis signal — the PCA projection
needs a completed baseline and a completed window, neither of which exists while
samples are merely arriving. Pushing raw samples instead would put 400 objects/sec
through the UI socket to draw a few hundred pixels.

So: a rolling mean as a cheap gravity estimate, the perpendicular component's
magnitude, decimated. No onset detection, no filtering, no PCA. The number on
screen still comes from `result`; this exists so the trace spikes at 0:12.
"""
import numpy as np
from collections import defaultdict, deque
from .. import config


class Trace:
    def __init__(self):
        self.recent = defaultdict(lambda: deque(maxlen=config.TRACE_GRAVITY_WINDOW))
        self.pending = defaultdict(list)
        self._i = defaultdict(int)

    def add(self, label, rows):
        for s in rows:
            v = (s["ax"], s["ay"], s["az"])
            self.recent[label].append(v)
            self._i[label] += 1
            if self._i[label] % config.TRACE_DECIMATE:
                continue
            g = np.mean(self.recent[label], axis=0)
            n = np.linalg.norm(g)
            if n == 0:
                continue
            g = g / n
            d = np.array(v) - np.mean(self.recent[label], axis=0)
            self.pending[label].append(round(float(np.linalg.norm(d - (d @ g) * g)), 5))

    def drain(self, label):
        v, self.pending[label] = self.pending[label], []
        return v
