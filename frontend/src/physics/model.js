/* Uniform fixed-base, free-top shear chain. Mirrors backend/physics_ref.py, which
   pytest pins (P1/P3) — if you change one, check the other. */

/** Tune k so the chain's FUNDAMENTAL equals the measured frequency. No search:
 *  omega_j = 2*sqrt(k/m)*sin((2j-1)pi / (2(2N+1))), inverted at j=1. */
export function stiffnessFor(frequencyHz, n, m = 1) {
  const w1 = 2 * Math.PI * frequencyHz;
  return (w1 / (2 * Math.sin(Math.PI / (2 * (2 * n + 1))))) ** 2 * m;
}

/** K = k*tridiag(-1,2,-1) with K[N-1][N-1] = k.
 *  THE TRAP: the last diagonal is k, NOT 2k — the top floor has no floor above it.
 *  A naive loop writes 2k everywhere; N=5 tuned for 3.24 Hz then runs at 5.89 Hz,
 *  82% high, with no error and a perfectly plausible building on screen. */
export function stiffnessMatrix(k, n, retrofitFloor = null, factor = 2) {
  const ks = Array.from({ length: n }, () => k);
  if (retrofitFloor != null && ks[retrofitFloor] != null) ks[retrofitFloor] *= factor;
  const K = Array.from({ length: n }, () => new Array(n).fill(0));
  for (let i = 0; i < n; i++) {
    const above = i + 1 < n ? ks[i + 1] : 0;
    K[i][i] = ks[i] + above;
    if (i + 1 < n) { K[i][i + 1] = -above; K[i + 1][i] = -above; }
  }
  return K;
}

/* Thomas algorithm — solves a tridiagonal system in O(n). */
function triSolve(K, b) {
  const n = b.length, c = new Array(n), d = new Array(n);
  let denom = K[0][0];
  c[0] = n > 1 ? K[0][1] / denom : 0;
  d[0] = b[0] / denom;
  for (let i = 1; i < n; i++) {
    denom = K[i][i] - K[i][i - 1] * c[i - 1];
    c[i] = i + 1 < n ? K[i][i + 1] / denom : 0;
    d[i] = (b[i] - K[i][i - 1] * d[i - 1]) / denom;
  }
  const x = new Array(n);
  x[n - 1] = d[n - 1];
  for (let i = n - 2; i >= 0; i--) x[i] = d[i] - c[i] * x[i + 1];
  return x;
}

/** Fundamental frequency + mode shape by inverse power iteration.
 *  Inverse iteration converges to the SMALLEST eigenvalue, which is exactly the
 *  fundamental, and each step is one tridiagonal solve. Needed rather than the
 *  closed form because a non-uniform chain (one spring different) has no analytic
 *  solution. The stiffness-exploration screen that used that is gone; the parameter
 *  stays because backend/physics_ref.py mirrors it and pytest P3 exercises it. */
export function modeShape(K, m = 1) {
  const n = K.length;
  let v = new Array(n).fill(1);
  let lambda = 0;
  for (let it = 0; it < 200; it++) {
    const w = triSolve(K, v);
    const norm = Math.hypot(...w);
    if (!isFinite(norm) || norm === 0) break;
    const next = w.map((x) => x / norm);
    let num = 0;   // Rayleigh quotient on the normalised vector = the eigenvalue
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) num += next[i] * K[i][j] * next[j];
    const converged = Math.abs(num - lambda) < 1e-12 * Math.max(1, Math.abs(num));
    lambda = num; v = next;
    if (converged && it > 3) break;
  }
  let phi = v.slice();
  const peak = phi.reduce((a, b) => (Math.abs(b) > Math.abs(a) ? b : a), 0);
  if (peak < 0) phi = phi.map((x) => -x);
  const max = Math.max(...phi.map(Math.abs)) || 1;
  return { f1: Math.sqrt(Math.max(lambda, 0) / m) / (2 * Math.PI), phi: phi.map((x) => x / max) };
}

/** Inter-storey drift from the MODE SHAPE — a static structural property, not a
 *  snapshot of the animation at some instant. */
export function driftProfile(phi) {
  return phi.map((x, i) => Math.abs(x - (i ? phi[i - 1] : 0)));
}

export function criticalFloor(phi) {
  const d = driftProfile(phi);
  return d.indexOf(Math.max(...d));
}
