import * as THREE from "three";

/* Massing from the real OSM outline. Founders Hall is a 14-point chevron, 59 x 67 m,
   five levels, built 2022 — so a contemporary curtain-wall reading is right for it
   rather than invented. Glazing and mullions are decorative (plan §14.1 "purely
   visual"); the OUTLINE, the level count and the sway are the measured parts. */

const GROUND_H = 4.6;      // lobby floors are taller than the ones above
const FLOOR_H = 3.5;       // illustrative — real per-floor heights are not in OSM
const BAND = 0.62;         // fraction of each floor that reads as glass

const PALETTE = {
  concrete: { solid: 0x8a929b, glass: 0x2d4a63 },
  steel:    { solid: 0x9aa6b2, glass: 0x27455f },
  wood:     { solid: 0xa8845c, glass: 0x35566e },
  urm:      { solid: 0x9c6b52, glass: 0x3a5a72 },
};

function toMetres(poly) {
  const lat0 = poly.reduce((a, p) => a + p[0], 0) / poly.length;
  const lon0 = poly.reduce((a, p) => a + p[1], 0) / poly.length;
  const k = Math.cos((lat0 * Math.PI) / 180);
  return poly.map(([la, lo]) => [(lo - lon0) * k * 111320, (la - lat0) * 110540]);
}
const DEFAULT_BOX = [[0, 0], [30, 0], [30, 20], [0, 20]]
  .map(([x, y]) => [y / 110540, x / (111320 * 0.67)]);

function shapeFrom(pts) {
  const sh = new THREE.Shape();
  pts.forEach(([x, y], i) => (i ? sh.lineTo(x, y) : sh.moveTo(x, y)));
  sh.closePath();
  return sh;
}

/** A slab plus an inset glazing band, grouped so the pair shears together. */
function floorGroup(shape, insetShape, h, mats, y) {
  const g = new THREE.Group();
  const solidH = h * (1 - BAND);
  const glassH = h * BAND;

  const slab = new THREE.Mesh(
    new THREE.ExtrudeGeometry(shape, { depth: solidH, bevelEnabled: false }).rotateX(-Math.PI / 2),
    mats.solid);
  slab.castShadow = slab.receiveShadow = true;
  slab.position.y = glassH;

  // Inset so the spandrel reads as a shadow line, which is what makes a stack of
  // extrusions look like a building instead of a stack of extrusions.
  const glass = new THREE.Mesh(
    new THREE.ExtrudeGeometry(insetShape, { depth: glassH * 0.94, bevelEnabled: false })
      .rotateX(-Math.PI / 2),
    mats.glass);
  glass.castShadow = true;

  g.add(glass, slab);
  g.position.y = y;
  return g;
}

/* Shrink a polygon toward its centroid — cheap inset that behaves on concave
   outlines, where a true offset would self-intersect. */
function inset(pts, m) {
  const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length;
  const cy = pts.reduce((a, p) => a + p[1], 0) / pts.length;
  const r = Math.max(...pts.map(([x, y]) => Math.hypot(x - cx, y - cy)));
  const k = Math.max(0.9, (r - m) / r);
  return pts.map(([x, y]) => [cx + (x - cx) * k, cy + (y - cy) * k]);
}

export function buildBuilding({ footprint, floors, type = "concrete" }) {
  const group = new THREE.Group();
  const usingFallback = !footprint || footprint.length < 3;
  const pts = toMetres(usingFallback ? DEFAULT_BOX : footprint);
  const pal = PALETTE[type] || PALETTE.concrete;

  const mats = {
    solid: new THREE.MeshStandardMaterial({ color: pal.solid, roughness: 0.82, metalness: 0.05 }),
    glass: new THREE.MeshStandardMaterial({ color: pal.glass, roughness: 0.16, metalness: 0.65,
                                            emissive: 0x0d1a26, emissiveIntensity: 0.7 }),
    roof:  new THREE.MeshStandardMaterial({ color: 0x59626c, roughness: 0.95 }),
  };
  const shape = shapeFrom(pts);
  const glassShape = shapeFrom(inset(pts, 0.55));
  const edgeMat = new THREE.LineBasicMaterial({ color: 0x0a1219, transparent: true, opacity: 0.5 });

  const slabs = [];
  let y = 0;
  for (let i = 0; i < floors; i++) {
    const h = i === 0 ? GROUND_H : FLOOR_H;
    const g = floorGroup(shape, glassShape, h, mats, y);
    g.add(new THREE.LineSegments(
      new THREE.EdgesGeometry(new THREE.ExtrudeGeometry(shape, { depth: h, bevelEnabled: false })
        .rotateX(-Math.PI / 2)), edgeMat));
    group.add(g);
    slabs.push(g);
    y += h;
  }

  // Parapet: a thin cap stops the top floor looking sliced off.
  const cap = new THREE.Mesh(
    new THREE.ExtrudeGeometry(shape, { depth: 0.9, bevelEnabled: false }).rotateX(-Math.PI / 2),
    mats.roof);
  cap.castShadow = cap.receiveShadow = true;
  cap.position.y = y;
  group.add(cap);
  slabs.push(cap);                       // the roof shears with the top floor

  const span = Math.max(...pts.map(([x]) => Math.abs(x)), ...pts.map(([, y2]) => Math.abs(y2))) * 2;
  return { group, slabs, span, usingFallback, height: y + 0.9 };
}

/** display_displacement_normalized ONLY — never a physical value (plan §14.2). */
export function applyDisplacement(slabs, x, scale) {
  slabs.forEach((s, i) => { s.position.x = (x[Math.min(i, x.length - 1)] ?? 0) * scale; });
}
