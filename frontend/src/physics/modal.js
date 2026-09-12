/* Closed-form steady-state response. No integrator, so no timestep, so no stability
   bound and nothing to destabilise on stage.

   An earlier design used symplectic Euler at 60fps with adaptive sub-stepping. Its
   stability was argued from omega_N ~ 80-85 rad/s, computed under f1 ~ 10/N — i.e.
   2 Hz at N=5. The real demo configuration is N=5 at ~3.24 Hz, giving
   omega_5 = 137 rad/s and omega*dt = 2.29 > 2.0: unstable. This removes the failure
   mode rather than guarding against it. */

/** Dynamic magnification. Peaks at 1/(2*zeta) when fDrive == f1 — that peak IS the
 *  resonance beat, the software mirror of the two-tower rig. */
export function magnification(fDrive, f1, zeta) {
  const r = fDrive / f1;
  return 1 / Math.sqrt((1 - r * r) ** 2 + (2 * zeta * r) ** 2);
}

/** x_i(t) = A * H(r) * phi_i * sin(2 pi fDrive t) */
export function displacement(t, { fDrive, f1, zeta, phi, amplitude = 1 }) {
  const h = magnification(fDrive, f1, zeta);
  const s = Math.sin(2 * Math.PI * fDrive * t);
  return phi.map((p) => amplitude * h * p * s);
}

export const DAMPING_DEFAULT = { wood: 0.035, urm: 0.035, concrete: 0.0325, steel: 0.014 };
