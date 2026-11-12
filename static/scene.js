/* Escena 3D: tres fuentes (Síntesis, LUKA, Banco) que convergen en un anillo de conciliación. */
(function () {
  const canvas = document.getElementById("scene");
  const api = { setLoaded() {}, setStatus() {} };
  window.Scene3D = api;
  if (!canvas || !window.THREE) return;

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  } catch (e) {
    canvas.style.display = "none";
    return;
  }
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const C = {
    ink: new THREE.Color(dark ? 0x9db7d9 : 0x0b2545),
    ink2: new THREE.Color(dark ? 0x2a4a73 : 0x13315c),
    gold: new THREE.Color(0xb08d57),
    ok: new THREE.Color(0x2e7d4f),
    bad: new THREE.Color(0xb3261e),
    line: new THREE.Color(dark ? 0x2a3d59 : 0xc9d2de),
  };

  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 100);
  camera.position.set(0, 0.6, 9.8);

  scene.add(new THREE.AmbientLight(0xffffff, dark ? 0.45 : 0.65));
  const key = new THREE.DirectionalLight(0xffffff, 0.9);
  key.position.set(4, 6, 6);
  scene.add(key);
  const rim = new THREE.PointLight(0xb08d57, 0.8, 30);
  rim.position.set(-5, -2, 4);
  scene.add(rim);

  const root = new THREE.Group();
  scene.add(root);

  // Anillo central (conciliación)
  const ringMat = new THREE.MeshStandardMaterial({ color: C.ink2, metalness: 0.55, roughness: 0.3, emissive: C.gold, emissiveIntensity: 0.05 });
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.95, 0.07, 32, 140), ringMat);
  root.add(ring);
  const ring2 = new THREE.Mesh(new THREE.TorusGeometry(0.72, 0.018, 16, 120), new THREE.MeshBasicMaterial({ color: C.gold, transparent: true, opacity: 0.6 }));
  root.add(ring2);
  const core = new THREE.Mesh(new THREE.IcosahedronGeometry(0.28, 1), new THREE.MeshStandardMaterial({ color: C.gold, metalness: 0.7, roughness: 0.25, flatShading: true }));
  root.add(core);

  // Nodos (fuentes)
  const R = 2.45;
  const nodes = [];
  for (let i = 0; i < 3; i++) {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / 3 + Math.PI;
    const pos = new THREE.Vector3(Math.cos(a) * R, Math.sin(a) * R * 0.62, Math.sin(a) * 0.9);
    const g = new THREE.Group();
    g.position.copy(pos);
    const mat = new THREE.MeshStandardMaterial({ color: C.ink, metalness: 0.35, roughness: 0.4, flatShading: true, emissive: C.gold, emissiveIntensity: 0 });
    const solid = new THREE.Mesh(new THREE.IcosahedronGeometry(0.42, 0), mat);
    const wire = new THREE.Mesh(new THREE.IcosahedronGeometry(0.62, 1), new THREE.MeshBasicMaterial({ color: C.gold, wireframe: true, transparent: true, opacity: 0.18 }));
    g.add(solid, wire);
    root.add(g);
    // conexión al centro
    const pts = [];
    for (let t = 0; t <= 1.0001; t += 0.05) {
      const p = pos.clone().multiplyScalar(1 - t);
      p.y += Math.sin(t * Math.PI) * 0.35;
      pts.push(p);
    }
    const curve = new THREE.CatmullRomCurve3(pts);
    const lineGeo = new THREE.BufferGeometry().setFromPoints(curve.getPoints(60));
    const line = new THREE.Line(lineGeo, new THREE.LineBasicMaterial({ color: C.line, transparent: true, opacity: 0.9 }));
    root.add(line);
    // partículas
    const parts = [];
    for (let k = 0; k < 5; k++) {
      const m = new THREE.Mesh(new THREE.SphereGeometry(0.045, 10, 10), new THREE.MeshBasicMaterial({ color: C.gold, transparent: true, opacity: 0 }));
      root.add(m);
      parts.push({ m, t: k / 5 });
    }
    nodes.push({ g, solid, wire, mat, line, curve, parts, loaded: false, glow: 0 });
  }

  // Campo de puntos de fondo
  const starGeo = new THREE.BufferGeometry();
  const N = 260, arr = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    arr[i * 3] = (Math.random() - 0.5) * 16;
    arr[i * 3 + 1] = (Math.random() - 0.5) * 9;
    arr[i * 3 + 2] = -3 - Math.random() * 6;
  }
  starGeo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
  scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: C.line, size: 0.035 })));

  const labels = document.querySelectorAll(".scene-labels span");
  let phase = 0;
  let status = "idle", speed = 0.25, targetSpeed = 0.25, ringColor = C.ink2.clone();
  const mouse = { x: 0, y: 0 };
  canvas.parentElement.addEventListener("pointermove", (e) => {
    const r = canvas.getBoundingClientRect();
    mouse.x = (e.clientX - r.left) / r.width - 0.5;
    mouse.y = (e.clientY - r.top) / r.height - 0.5;
  });

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.position.z = w / h < 1.1 ? 11.5 : 9.8;
    camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  const v = new THREE.Vector3();
  function placeLabels() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    nodes.forEach((n, i) => {
      n.g.getWorldPosition(v);
      v.y -= 0.85;
      v.project(camera);
      const el = labels[i];
      if (!el) return;
      el.style.left = ((v.x + 1) / 2) * w + "px";
      el.style.top = ((1 - v.y) / 2) * h + "px";
      el.classList.toggle("on", n.loaded);
    });
  }

  let last = performance.now();
  function frame(now) {
    const dt = Math.max(0, Math.min((now - last) / 1000, 0.05));
    last = now;
    speed += (targetSpeed - speed) * 0.05;
    phase += dt * speed * 0.35;
    root.rotation.y = Math.sin(phase) * 0.32 + mouse.x * 0.25;
    root.rotation.x += ((-mouse.y * 0.25) - root.rotation.x) * 0.04;
    root.rotation.z += ((mouse.x * 0.1) - root.rotation.z) * 0.04;
    ring.rotation.x = Math.PI / 2.4 + Math.sin(now / 2400) * 0.12;
    ring.rotation.z += dt * speed * 1.4;
    ring2.rotation.x = ring.rotation.x;
    ring2.rotation.z -= dt * speed * 2.2;
    core.rotation.y += dt * speed * 2;
    core.rotation.x += dt * speed;
    ringMat.color.lerp(ringColor, 0.06);

    nodes.forEach((n, i) => {
      n.solid.rotation.y += dt * (0.4 + i * 0.1);
      n.wire.rotation.y -= dt * 0.25;
      n.wire.rotation.x += dt * 0.15;
      n.glow += ((n.loaded ? 1 : 0) - n.glow) * 0.08;
      n.mat.emissiveIntensity = n.glow * 0.55;
      n.wire.material.opacity = 0.14 + n.glow * 0.35;
      n.line.material.color.lerpColors(C.line, C.gold, n.glow * 0.8);
      const s = 1 + Math.sin(now / 600 + i) * 0.03 * n.glow;
      n.g.scale.setScalar(s);
      const flowing = n.loaded && status !== "error";
      n.parts.forEach((p) => {
        p.t = (p.t + dt * (status === "running" ? 0.9 : 0.22)) % 1;
        if (!(p.t >= 0 && p.t <= 1)) p.t = 0;
        n.curve.getPointAt(p.t, p.m.position);
        const target = flowing ? Math.sin(p.t * Math.PI) * 0.95 : 0;
        p.m.material.opacity += (target - p.m.material.opacity) * 0.1;
      });
    });
    renderer.render(scene, camera);
    placeLabels();
    if (!reduce) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  api.setLoaded = (i, on) => {
    if (nodes[i]) nodes[i].loaded = !!on;
    if (reduce) requestAnimationFrame(frame);
  };
  api.setStatus = (s) => {
    status = s;
    targetSpeed = s === "running" ? 2.4 : s === "done" ? 0.55 : 0.25;
    ringColor = s === "done" ? C.ok.clone() : s === "error" ? C.bad.clone() : s === "warn" ? C.gold.clone() : C.ink2.clone();
    if (reduce) requestAnimationFrame(frame);
  };
})();
