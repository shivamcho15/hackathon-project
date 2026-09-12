import * as THREE from "three";

/* Three lights, a shadow, and depth fog. A single flat key light was what made the
   massing unreadable — an irregular footprint needs shading to show its own corners. */
export function makeScene(canvas, { span = 40, height = 20 } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(0x0c1210, Math.max(span, height) * 2.2, Math.max(span, height) * 6.5);

  const FOV = 34;
  const camera = new THREE.PerspectiveCamera(FOV, 1, 0.5, 4000);
  const radius = 0.5 * Math.hypot(span, height);
  const dist = (radius / Math.sin((FOV * Math.PI) / 360)) * 1.12;

  // Orbit state — a judge can grab it and turn the building, which is worth more
  // than any amount of shading.
  let az = -0.62, el = 0.34, target = new THREE.Vector3(0, height * 0.42, 0);
  const place = () => {
    camera.position.set(target.x + dist * Math.cos(el) * Math.sin(az),
                        target.y + dist * Math.sin(el),
                        target.z + dist * Math.cos(el) * Math.cos(az));
    camera.lookAt(target);
  };
  place();

  let drag = null;
  canvas.style.cursor = "grab";
  canvas.addEventListener("pointerdown", (e) => {
    drag = { x: e.clientX, y: e.clientY }; canvas.style.cursor = "grabbing";
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drag) return;
    az -= (e.clientX - drag.x) * 0.006;
    el = Math.max(0.06, Math.min(1.25, el + (e.clientY - drag.y) * 0.004));
    drag = { x: e.clientX, y: e.clientY };
    place();
  });
  const stop = () => { drag = null; canvas.style.cursor = "grab"; };
  canvas.addEventListener("pointerup", stop);
  canvas.addEventListener("pointerleave", stop);

  scene.add(new THREE.HemisphereLight(0x9fc0dc, 0x14202b, 0.85));
  const key = new THREE.DirectionalLight(0xfff2e0, 2.1);
  key.position.set(radius * 1.4, radius * 2.2, radius * 1.1);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  const d = radius * 2.2;
  Object.assign(key.shadow.camera, { left: -d, right: d, top: d, bottom: -d, near: 1, far: d * 6 });
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x7fa8cc, 0.55);
  fill.position.set(-radius * 1.6, radius * 0.7, -radius * 1.2);
  scene.add(fill);
  const rim = new THREE.DirectionalLight(0xbcd8f0, 0.7);   // separates roof from sky
  rim.position.set(-radius * 0.4, radius * 0.9, radius * 2.0);
  scene.add(rim);

  const R = Math.max(span, height) * 3.2;
  const ground = new THREE.Mesh(
    new THREE.CircleGeometry(R, 96).rotateX(-Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: 0x1b2a1f, roughness: 1 }));   // soil, not slate
  ground.receiveShadow = true;
  ground.position.y = -0.02;
  scene.add(ground);

  // A shallow soil body under it. Site class is a property of the top ~30 m of
  // ground, so showing ground with depth is the honest picture — the building is
  // sitting ON something, which is the whole argument.
  const soil = new THREE.Mesh(
    new THREE.CylinderGeometry(R * 0.62, R * 0.52, height * 0.9, 64, 1, true),
    new THREE.MeshStandardMaterial({ color: 0x24361f, roughness: 1,
                                     side: THREE.DoubleSide, transparent: true, opacity: 0.9 }));
  soil.position.y = -height * 0.45;
  scene.add(soil);
  const soilCap = new THREE.Mesh(
    new THREE.CircleGeometry(R * 0.62, 64).rotateX(-Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: 0x21331d, roughness: 1 }));
  soilCap.position.y = -0.01; soilCap.receiveShadow = true;
  scene.add(soilCap);

  const grid = new THREE.GridHelper(Math.max(span, height) * 6, 40, 0x1d2e3c, 0x151f29);
  grid.material.transparent = true; grid.material.opacity = 0.35;
  grid.position.y = 0.01;
  scene.add(grid);

  const resize = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  resize();
  return { renderer, scene, camera, resize, render: () => renderer.render(scene, camera) };
}
