"""Reference implementation of the modal model. The frontend JS mirrors this.

Kept in Python so the closed forms can be asserted by pytest against numpy's own
eigensolver — the JS has no test harness on this clock, and these are exactly the
formulas where a plausible-looking wrong answer is invisible on screen.
"""
import numpy as np


def stiffness_for(frequency_hz, n_floors, m=1.0):
    """Tune k so the chain's FUNDAMENTAL equals the measured frequency. No search.

    omega_j = 2*sqrt(k/m)*sin((2j-1)*pi / (2(2N+1)))  for a uniform fixed-base,
    free-top shear chain. Invert at j=1.
    """
    w1 = 2 * np.pi * frequency_hz
    return float((w1 / (2 * np.sin(np.pi / (2 * (2 * n_floors + 1))))) ** 2 * m)


def stiffness_matrix(k, n, retrofit_floor=None, factor=2.0):
    """K = k * tridiag(-1, 2, -1), with K[N-1][N-1] = k.

    THE TRAP: the last diagonal is k, NOT 2k, because the top floor has no floor
    above it. A straightforward assembly loop writes 2k everywhere — it is the
    obvious way, it looks right, and it is wrong: N=5 tuned for 3.24 Hz then
    oscillates at 5.89 Hz, 82% high, with no error raised.
    """
    ks = np.full(n, float(k))
    if retrofit_floor is not None:
        ks[retrofit_floor] *= factor
    K = np.zeros((n, n))
    for i in range(n):
        below = ks[i]
        above = ks[i + 1] if i + 1 < n else 0.0
        K[i, i] = below + above
        if i + 1 < n:
            K[i, i + 1] = K[i + 1, i] = -ks[i + 1]
    return K


def modes(K, m=1.0):
    """Returns (frequencies_hz ascending, mode shapes as columns)."""
    w2, v = np.linalg.eigh(K / m)
    return np.sqrt(np.maximum(w2, 0)) / (2 * np.pi), v


def mode_shape(K, m=1.0):
    f, v = modes(K, m)
    phi = v[:, 0]
    if phi[np.argmax(np.abs(phi))] < 0:
        phi = -phi
    return float(f[0]), phi / np.abs(phi).max()      # normalise so the top is 1


def drift_profile(phi):
    """Inter-storey drift from the MODE SHAPE — a static structural property, not a
    snapshot of the animation at some instant."""
    return np.abs(np.diff(np.concatenate([[0.0], phi])))


def critical_floor(phi):
    return int(np.argmax(drift_profile(phi)))


def magnification(f_drive, f1, zeta):
    """Steady-state dynamic magnification H(r). This is what makes the building
    surge at resonance without any time integration — no timestep, so no stability
    bound, so nothing to destabilise on stage."""
    r = f_drive / f1
    return float(1.0 / np.sqrt((1 - r * r) ** 2 + (2 * zeta * r) ** 2))
