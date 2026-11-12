// The Office: the team as real people in a 3D office, live from the console's state. Click someone to chat with
// them; a red bubble from someone's desk means they have something for you. Idle people get a coffee, sit on the sofa,
// play foosball or table tennis, scroll their phone or yawn at their desk, and walk the aisles between them.
// The people and their movements are Microsoft Rocketbox avatars (MIT, see office/NOTICE.md); three.js draws it all.
import * as THREE from "three";
import { GLTFLoader } from "./vendor/three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "./vendor/three/addons/libs/meshopt_decoder.module.js";
import { RoomEnvironment } from "./vendor/three/addons/environments/RoomEnvironment.js";
import { clone as cloneSkinned } from "./vendor/three/addons/utils/SkeletonUtils.js";

const BASE = "/static/office";

// ---- the room and everything in it (built once) ---------------------------------------------------------------------
function buildWorld(scene) {
const RW = 22, RD = 16, RH = 3;
const hemi = new THREE.HemisphereLight("#f4f1ea", "#6f604f", 0.45); scene.add(hemi);
const sun = new THREE.DirectionalLight("#ffe9c7", 2.0);
sun.position.set(20, 22, -10); sun.target.position.set(11, 0, 8);
sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
Object.assign(sun.shadow.camera, { left: -20, right: 20, top: 20, bottom: -20, near: 1, far: 80 });
sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.02; sun.shadow.radius = 4;
scene.add(sun, sun.target);
const fill = new THREE.DirectionalLight("#dfe8ff", 0.5); fill.position.set(20, 10, 20); scene.add(fill);
// ---- materials & helpers -------------------------------------------------------------
const mats = {};
const mat = (c, o = {}) => (mats[c + JSON.stringify(o)] ||= new THREE.MeshStandardMaterial({ color: c, roughness: 0.75, metalness: 0, ...o }));
function mesh(geo, m, x = 0, y = 0, z = 0, parent = scene, shadow = true) {
  const o = new THREE.Mesh(geo, typeof m === "string" ? mat(m) : m);
  o.position.set(x, y, z); o.castShadow = shadow; o.receiveShadow = true; parent.add(o); return o;
}
const boxG = (w, h, d) => new THREE.BoxGeometry(w, h, d);
const rbox = (w, h, d, r = 0.03) => { // a box with rounded vertical edges
  const s = new THREE.Shape(); const x = -w / 2, z = -d / 2;
  s.moveTo(x + r, z); s.lineTo(x + w - r, z); s.quadraticCurveTo(x + w, z, x + w, z + r); s.lineTo(x + w, z + d - r); s.quadraticCurveTo(x + w, z + d, x + w - r, z + d);
  s.lineTo(x + r, z + d); s.quadraticCurveTo(x, z + d, x, z + d - r); s.lineTo(x, z + r); s.quadraticCurveTo(x, z, x + r, z);
  const g = new THREE.ExtrudeGeometry(s, { depth: h, bevelEnabled: true, bevelThickness: Math.min(r, h / 3), bevelSize: Math.min(r, h / 3), bevelSegments: 3, curveSegments: 6 });
  g.rotateX(Math.PI / 2); g.translate(0, h / 2, 0); return g;
};
const cyl = (rt, rb, h, s = 20) => new THREE.CylinderGeometry(rt, rb, h, s);
const sph = (r, w = 20, h = 14) => new THREE.SphereGeometry(r, w, h);
const cap = (r, len) => new THREE.CapsuleGeometry(r, len, 6, 14);
function canvasTex(w, h, draw, repeat) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  if (repeat) { t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(...repeat); }
  return t;
}
let seed = 7; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);

// ---- the room ----------------------------------------------------------------------------
const wood = canvasTex(1024, 1024, (g, w, h) => {
  const rows = 16, ph = h / rows;
  for (let r = 0; r < rows; r++) {
    let x = -rnd() * 300;
    while (x < w) {
      const len = 220 + rnd() * 260, l = 40 + rnd() * 9, hue = 28 + rnd() * 6;
      g.fillStyle = `hsl(${hue} ${38 + rnd() * 8}% ${l}%)`; g.fillRect(x, r * ph, len, ph);
      for (let i = 0; i < 7; i++) { g.strokeStyle = `hsla(${hue} 40% ${l - 8}% / .35)`; g.lineWidth = 1; g.beginPath(); const yy = r * ph + rnd() * ph; g.moveTo(x, yy); g.bezierCurveTo(x + len * .3, yy + 3, x + len * .6, yy - 3, x + len, yy + 1); g.stroke(); }
      g.fillStyle = "rgba(60,40,20,.35)"; g.fillRect(x, r * ph, 2, ph); x += len;
    }
    g.fillStyle = "rgba(60,40,20,.3)"; g.fillRect(0, r * ph, w, 2);
  }
}, [3, 3]);
mesh(boxG(RW, 0.1, RD), new THREE.MeshStandardMaterial({ map: wood, roughness: 0.55 }), RW / 2, -0.05, RD / 2).castShadow = false;
const wallM = mat("#e2dccf", { roughness: 0.95 });
mesh(boxG(RW + 0.3, RH, 0.15), wallM, RW / 2 - 0.15, RH / 2, -0.075);
mesh(boxG(0.15, RH, RD), wallM, -0.075, RH / 2, RD / 2);
mesh(boxG(RW + 0.3, 0.1, 0.03), "#cdbfa8", RW / 2 - 0.15, 0.05, 0.015, scene, false);
mesh(boxG(0.03, 0.1, RD), "#cdbfa8", 0.015, 0.05, RD / 2, scene, false);
// windows on the back wall, with the light coming in
const windowGlass = new THREE.MeshStandardMaterial({ color: "#bfe1f1", emissive: "#bfe1f1", emissiveIntensity: 0.9 });
function windowAt(x) {
  const g = new THREE.Group(); g.position.set(x, 1.7, 0.01); scene.add(g);
  mesh(boxG(1.8, 1.5, 0.02), windowGlass, 0, 0, 0, g, false);
  for (const [w, h, xx, yy] of [[1.9, 0.07, 0, 0.78], [1.9, 0.07, 0, -0.78], [0.07, 1.6, 0.93, 0], [0.07, 1.6, -0.93, 0], [0.05, 1.5, 0, 0], [1.8, 0.05, 0, 0.1]]) mesh(boxG(w, h, 0.06), "#f6f4ef", xx, yy, 0.03, g, false);
  mesh(boxG(2, 0.05, 0.18), "#f6f4ef", 0, -0.8, 0.09, g);
}
[2.2, 6.2, 9.4, 14.2].forEach(windowAt);
// Hive sign
const logoImg = new Image(); logoImg.src = "/assets/hive-logo-512.png";
const sign = canvasTex(640, 200, (g, w, h) => { g.fillStyle = "#2f3a35"; g.fillRect(0, 0, w, h); });
logoImg.onload = () => { const g = sign.image.getContext("2d"); g.drawImage(logoImg, 30, 20, 160, 160); g.fillStyle = "#f4efe6"; g.font = "600 112px 'IBM Plex Sans', system-ui"; g.fillText("Hive", 220, 140); sign.needsUpdate = true; };
mesh(boxG(1.6, 0.5, 0.05), new THREE.MeshStandardMaterial({ map: sign, roughness: 0.6 }), 11.8, 1.85, 0.04, scene, false);
// the cork board on the wall: a sticky note per task in each column, the count on top
const boardCanvas = document.createElement("canvas"); boardCanvas.width = 800; boardCanvas.height = 400;
const board = new THREE.CanvasTexture(boardCanvas); board.colorSpace = THREE.SRGBColorSpace; board.anisotropy = 8;
const NOTE = ["#f7e48d", "#a9d4f5", "#f5b9c8", "#bfe3c7"];
function drawBoard(cols) {
  const g = boardCanvas.getContext("2d"), w = 800, h = 400;
  g.fillStyle = "#b8875a"; g.fillRect(0, 0, w, h); g.fillStyle = "#d4a978"; g.fillRect(14, 14, w - 28, h - 28);
  let s = 11;
  cols.forEach(([n, c], i) => { g.fillStyle = "#6b4a2a"; g.font = "bold 28px system-ui"; g.fillText(`${n} ${c}`, 34 + i * 190, 58);
    for (let j = 0; j < Math.min(c, 6); j++) { s = (s * 16807) % 2147483647; g.save(); g.translate(40 + i * 190 + (j % 2) * 80, 80 + Math.floor(j / 2) * 98); g.rotate(((s % 100) / 100 - .5) * .12);
      g.fillStyle = NOTE[i]; g.fillRect(0, 0, 70, 70); g.fillStyle = "#c0392b"; g.beginPath(); g.arc(35, 8, 6, 0, 7); g.fill(); g.restore(); } });
  board.needsUpdate = true;
}
drawBoard([["SPEC", 0], ["DEV", 0], ["REVIEW", 0], ["DONE", 0]]);
mesh(boxG(1.25, 0.95, 0.04), new THREE.MeshStandardMaterial({ map: board, roughness: 0.9 }), 7.8, 1.65, 0.03, scene, false);


const screenTex = (kind) => canvasTex(256, 160, (g, w, h) => {
  if (kind === "code") { g.fillStyle = "#1b2420"; g.fillRect(0, 0, w, h); const cs = ["#f2c14e", "#7fd3a8", "#a9d4f5", "#f5b9c8", "#d6d6d6"];
    for (let i = 0; i < 13; i++) { let x = 10 + (i % 4 ? 16 : 0) + (i % 3 ? 14 : 0); for (let k = 0; k < 3; k++) { const ww = 14 + rnd() * 50; g.fillStyle = cs[(i + k) % 5]; g.fillRect(x, 10 + i * 11, ww, 5); x += ww + 6; } } }
  else if (kind === "doc") { g.fillStyle = "#f7f4ec"; g.fillRect(0, 0, w, h); g.fillStyle = "#3a4640"; g.fillRect(14, 12, 120, 9); g.fillStyle = "#b7bfba"; for (let i = 0; i < 10; i++) g.fillRect(14, 30 + i * 12, 80 + rnd() * 140, 5); }
  else if (kind === "chart") { g.fillStyle = "#f7f6f2"; g.fillRect(0, 0, w, h); g.fillStyle = "#3f7a5f"; for (let i = 0; i < 14; i++) { const hh = 20 + rnd() * 90; g.fillRect(14 + i * 16, 140 - hh, 11, hh); } g.fillStyle = "#22302a"; g.fillRect(14, 12, 90, 9); }
  else { g.fillStyle = "#151a18"; g.fillRect(0, 0, w, h); }
});
const SCREENS = {};
const screenOf = (k) => (SCREENS[k] ||= screenTex(k));
function setScreen(m, k) {
  if (!m || m.userData.kind === k) return;
  m.userData.kind = k; m.material.map = screenOf(k); m.material.emissiveMap = m.material.map; m.material.emissiveIntensity = k === "off" ? 0 : 0.85; m.material.needsUpdate = true;
}
// ---- realistic materials ------------------------------------------------------------------------
const M = {
  steel: new THREE.MeshStandardMaterial({ color: "#c8cbcd", metalness: 1, roughness: 0.3 }),
  darkSteel: new THREE.MeshStandardMaterial({ color: "#3a3d40", metalness: 0.9, roughness: 0.35 }),
  black: new THREE.MeshStandardMaterial({ color: "#1c1e1f", roughness: 0.45 }),
  blackMatte: new THREE.MeshStandardMaterial({ color: "#222526", roughness: 0.85 }),
  white: new THREE.MeshStandardMaterial({ color: "#f3f1ec", roughness: 0.5 }),
  ceramic: new THREE.MeshPhysicalMaterial({ color: "#f7f5f0", roughness: 0.25, clearcoat: 0.8, clearcoatRoughness: 0.15 }),
  glass: new THREE.MeshPhysicalMaterial({ color: "#ffffff", metalness: 0, roughness: 0.04, transmission: 1, thickness: 0.02, ior: 1.45, transparent: true }),
  water: new THREE.MeshPhysicalMaterial({ color: "#bfe6f7", roughness: 0.03, transmission: 0.92, thickness: 0.3, ior: 1.33, transparent: true }),
  oak: null, walnut: null, fabric: new THREE.MeshStandardMaterial({ color: "#7d8b94", roughness: 1 }),
  coffee: new THREE.MeshStandardMaterial({ color: "#3b2414", roughness: 0.2 }),
};
const woodTex = (base, dark) => canvasTex(512, 512, (g, w, h) => { g.fillStyle = base; g.fillRect(0, 0, w, h);
  for (let i = 0; i < 90; i++) { g.strokeStyle = dark; g.globalAlpha = 0.08 + rnd() * 0.12; g.lineWidth = 1 + rnd() * 2; g.beginPath(); const y = rnd() * h; g.moveTo(0, y); g.bezierCurveTo(w * .3, y + (rnd() - .5) * 20, w * .7, y + (rnd() - .5) * 20, w, y + (rnd() - .5) * 10); g.stroke(); } g.globalAlpha = 1; });
M.oak = new THREE.MeshStandardMaterial({ map: woodTex("#c49a6c", "#7a5232"), roughness: 0.55 });
M.walnut = new THREE.MeshStandardMaterial({ map: woodTex("#6b4a33", "#2e1d12"), roughness: 0.5 });
const lathe = (pts, seg = 32) => new THREE.LatheGeometry(pts.map(([r, y]) => new THREE.Vector2(r, y)), seg);

// ---- accessories --------------------------------------------------------------------------------
function mug(parent, x, y, z, color = "#f7f5f0", rot = 0) {
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = rot; parent.add(g);
  const m = new THREE.MeshPhysicalMaterial({ color, roughness: 0.3, clearcoat: 0.7, clearcoatRoughness: 0.2, side: THREE.DoubleSide });
  mesh(lathe([[0.001, 0], [0.036, 0], [0.04, 0.005], [0.041, 0.09], [0.037, 0.095], [0.035, 0.09], [0.035, 0.008]]), m, 0, 0, 0, g);
  mesh(cyl(0.034, 0.034, 0.002), M.coffee, 0, 0.075, 0, g, false);
  const h = mesh(new THREE.TorusGeometry(0.024, 0.006, 8, 16, Math.PI), m, 0.04, 0.047, 0, g); h.rotation.z = -Math.PI / 2;
  return g;
}
function laptop(parent, x, y, z, rot = 0, screen = "code") {
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = rot; parent.add(g);
  const alu = new THREE.MeshStandardMaterial({ color: "#b9bcc0", metalness: 0.85, roughness: 0.35 });
  mesh(rbox(0.32, 0.012, 0.22, 0.01), alu, 0, 0.006, 0, g);
  mesh(boxG(0.28, 0.002, 0.11), M.black, 0, 0.013, -0.03, g, false);
  const lid = new THREE.Group(); lid.position.set(0, 0.012, -0.11); lid.rotation.x = -1.85; g.add(lid);
  mesh(rbox(0.32, 0.006, 0.22, 0.01), alu, 0, 0.003, 0.11, lid);
  const tex = screenOf(screen);
  const sc = mesh(new THREE.PlaneGeometry(0.29, 0.19), new THREE.MeshStandardMaterial({ map: tex, emissive: "#fff", emissiveMap: tex, emissiveIntensity: screen === "off" ? 0 : 0.9 }), 0, -0.001, 0.11, lid, false);
  sc.rotation.x = Math.PI / 2; sc.userData.kind = screen; g.userData.screen = sc;
  return g;
}
function monitor(parent, x, y, z, rot = 0, screen = "code") {
  const g = new THREE.Group(); g.position.set(x, y, z); g.rotation.y = rot; parent.add(g);
  mesh(rbox(0.24, 0.012, 0.17, 0.03), M.darkSteel, 0, 0.006, 0, g);
  const arm = mesh(boxG(0.035, 0.32, 0.02), M.darkSteel, 0, 0.17, -0.05, g); arm.rotation.x = -0.08;
  mesh(rbox(0.6, 0.355, 0.018, 0.008), M.black, 0, 0.36, -0.02, g).rotation.x = Math.PI / 2;
  const tex = screenOf(screen);
  const sc = mesh(new THREE.PlaneGeometry(0.585, 0.33), new THREE.MeshStandardMaterial({ map: tex, emissive: "#fff", emissiveMap: tex, emissiveIntensity: screen === "off" ? 0 : 0.85, roughness: 0.2 }), 0, 0.36, -0.01, g, false);
  sc.userData.kind = screen; g.userData.screen = sc;
  return g;
}
function keyboard(parent, x, y, z, rot = 0) {
  const kt = canvasTex(256, 96, (g, w, h) => { g.fillStyle = "#2b2e30"; g.fillRect(0, 0, w, h); g.fillStyle = "#e9e9e6"; for (let r = 0; r < 5; r++) for (let c = 0; c < 15; c++) g.fillRect(6 + c * 16.4, 6 + r * 17.5, 14, 15); });
  const k = mesh(rbox(0.42, 0.015, 0.13, 0.008), new THREE.MeshStandardMaterial({ map: kt, roughness: 0.6 }), x, y + 0.008, z, parent); k.rotation.y = rot;
  const m = mesh(sph(0.03, 16, 10), M.white, x + 0.28 * Math.cos(rot), y + 0.012, z - 0.28 * Math.sin(rot), parent); m.scale.set(0.65, 0.4, 1);
}
function deskLamp(parent, x, y, z) {
  const g = new THREE.Group(); g.position.set(x, y, z); parent.add(g);
  mesh(cyl(0.07, 0.075, 0.015, 32), M.black, 0, 0.008, 0, g);
  const a1 = mesh(cyl(0.007, 0.007, 0.36, 8), M.darkSteel, 0, 0.18, 0.04, g); a1.rotation.x = 0.25;
  const a2 = mesh(cyl(0.007, 0.007, 0.3, 8), M.darkSteel, 0, 0.42, 0.15, g); a2.rotation.x = 1.1;
  const sh = mesh(lathe([[0.02, 0.07], [0.05, 0.03], [0.085, 0], [0.08, 0.005], [0.045, 0.035], [0.015, 0.075]]), M.black, 0, 0.47, 0.28, g); sh.rotation.x = 0.4;
  const light = new THREE.SpotLight("#ffd9a0", 0, 2.2, 0.8, 0.6); light.position.set(0, 0.46, 0.28); light.target.position.set(0, -0.3, 0.45); g.add(light, light.target);
  const bulb = mesh(sph(0.025, 12, 8), new THREE.MeshStandardMaterial({ color: "#fff4d8", emissive: "#ffe2a8", emissiveIntensity: 2 }), 0, 0.455, 0.3, g, false); bulb.visible = false;
  return { light, bulb };
}
function plant(x, z, s = 1, parent = scene, kind = "leafy", y = 0) {
  const g = new THREE.Group(); g.position.set(x, y, z); g.scale.setScalar(s); parent.add(g);
  const potM = kind === "snake" ? new THREE.MeshStandardMaterial({ color: "#9a9893", roughness: 0.95 }) : kind === "fiddle" ? new THREE.MeshStandardMaterial({ color: "#b5643e", roughness: 0.9 }) : M.ceramic;
  mesh(lathe([[0.001, 0], [0.15, 0], [0.19, 0.38], [0.2, 0.4], [0.185, 0.4], [0.17, 0.39]]), potM, 0, 0, 0, g);
  mesh(cyl(0.175, 0.175, 0.02, 24), "#3b2a1e", 0, 0.37, 0, g, false);
  const greens = ["#2f5d3a", "#3d6e45", "#4a7d4f", "#365f3c", "#29523a"].map((c) => mat(c, { roughness: 0.5, side: THREE.DoubleSide }));
  if (kind === "snake") {
    const blade = new THREE.SphereGeometry(0.1, 10, 8); blade.scale(0.28, 4.5, 0.06); blade.translate(0, 0.42, 0);
    const bm = new THREE.MeshStandardMaterial({ color: "#3f6b3c", roughness: 0.45, side: THREE.DoubleSide });
    for (let i = 0; i < 16; i++) { const b = mesh(blade, bm, (rnd() - .5) * 0.2, 0.36, (rnd() - .5) * 0.2, g); b.rotation.set((rnd() - .5) * 0.3, rnd() * 3, (rnd() - .5) * 0.3); b.scale.y = 0.6 + rnd() * 0.6; }
  } else if (kind === "fiddle") {
    const trunk = mesh(cyl(0.015, 0.025, 1.3, 8), "#6b5440", 0, 1.0, 0, g);
    const leafGeo = new THREE.SphereGeometry(0.12, 14, 8); leafGeo.scale(0.75, 0.05, 1.05); leafGeo.translate(0, 0, 0.11);
    for (let i = 0; i < 30; i++) { const h = 0.8 + rnd() * 1.0; const st = new THREE.Group(); st.position.set(0, h, 0); st.rotation.y = rnd() * 6.3; g.add(st);
      const lf = mesh(leafGeo, greens[i % 5], 0, 0, 0.04, st); lf.rotation.x = -0.4 + rnd() * 0.9; lf.scale.setScalar(0.9 + rnd() * 0.6); }
  } else {
    const leafGeo = new THREE.SphereGeometry(0.1, 12, 6); leafGeo.scale(0.32, 0.04, 1); leafGeo.translate(0, 0, 0.1);
    for (let i = 0; i < 28; i++) {
      const stem = new THREE.Group(); stem.position.set(0, 0.4, 0); stem.rotation.y = rnd() * Math.PI * 2; g.add(stem);
      const len = 0.35 + rnd() * 0.55, tilt = 0.15 + rnd() * 0.9;
      mesh(cyl(0.006, 0.008, len, 5), "#557a45", 0, len / 2, 0, stem, false); stem.rotation.x = tilt * 0.6;
      const lf = mesh(leafGeo, greens[i % 5], 0, len, 0, stem); lf.scale.setScalar(1.3 + rnd() * 1.6); lf.rotation.x = -0.3 + tilt;
    }
  }
  return g;
}
function succulent(parent, x, y, z) {
  const g = new THREE.Group(); g.position.set(x, y, z); parent.add(g);
  mesh(lathe([[0.001, 0], [0.045, 0], [0.05, 0.07], [0.046, 0.07]]), new THREE.MeshStandardMaterial({ color: "#d8d2c7", roughness: 0.9 }), 0, 0, 0, g);
  const lm = mat("#6f9a6a", { roughness: 0.5 });
  for (let i = 0; i < 9; i++) { const l = mesh(sph(0.02, 8, 6), lm, Math.cos(i * 2.4) * 0.018, 0.08, Math.sin(i * 2.4) * 0.018, g); l.scale.set(0.6, 1.4, 0.6); l.rotation.set(Math.sin(i) * 0.6, 0, Math.cos(i) * 0.6); }
}
function officeChair(parent, x, z, rot = 0) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = rot; parent.add(g);
  for (let i = 0; i < 5; i++) { const a = i / 5 * Math.PI * 2; const l = mesh(boxG(0.3, 0.025, 0.035), M.darkSteel, Math.cos(a) * 0.15, 0.07, Math.sin(a) * 0.15, g); l.rotation.y = -a;
    mesh(sph(0.028, 10, 8), M.black, Math.cos(a) * 0.29, 0.028, Math.sin(a) * 0.29, g); }
  mesh(cyl(0.022, 0.022, 0.33), M.steel, 0, 0.25, 0, g, false);
  mesh(rbox(0.5, 0.07, 0.48, 0.07), M.blackMatte, 0, 0.45, 0, g);
  const back = mesh(rbox(0.46, 0.58, 0.05, 0.07), M.blackMatte, 0, 0.82, 0.25, g); back.rotation.x = -0.1;
  for (const s of [-1, 1]) { mesh(boxG(0.03, 0.2, 0.03), M.darkSteel, s * 0.26, 0.56, 0.05, g); mesh(rbox(0.06, 0.025, 0.26, 0.012), M.blackMatte, s * 0.26, 0.67, 0.02, g); }
  return g;
}
// a desk with a person's working things on it; the person faces `face` (radians, 0 = toward +z)
function workDesk(x, z, face, o = {}) {
  const g = new THREE.Group(); g.position.set(x, 0, z); g.rotation.y = face + Math.PI; scene.add(g);   // local -z is the far side
  mesh(rbox(1.4, 0.035, 0.72, 0.015), o.top || M.oak, 0, 0.74, 0, g);
  for (const s of [-1, 1]) { mesh(boxG(0.04, 0.72, 0.04), M.darkSteel, s * 0.66, 0.36, 0.3, g); mesh(boxG(0.04, 0.72, 0.04), M.darkSteel, s * 0.66, 0.36, -0.3, g); mesh(boxG(0.04, 0.04, 0.6), M.darkSteel, s * 0.66, 0.06, 0, g); }
  if (o.screen !== "none") { g.userData.screen = monitor(g, 0, 0.76, -0.2, 0, o.screen || "off").userData.screen; keyboard(g, 0, 0.76, 0.12); }
  if (o.lamp !== undefined) g.userData.lamp = deskLamp(g, -0.55, 0.76, -0.25);
  if (o.mug) mug(g, 0.52, 0.76, 0.08, o.mug, 2.2);
  if (o.plant) succulent(g, 0.55, 0.76, -0.22);
  if (o.papers) { const p = mesh(boxG(0.21, 0.006, 0.3), M.white, -0.42, 0.763, 0.0, g); p.rotation.y = 0.2; }
  if (o.box) { const b = mesh(rbox(0.5, 0.32, 0.38, 0.01), "#c9b48a", 0.1, 0.92, -0.05, g); b.rotation.y = 0.3; }
  g.userData.chair = officeChair(g, 0, o.empty ? 0.8 : 0.72, o.empty ? 0.5 : 0);
  return g;
}

// ---- kitchen ----------------------------------------------------------------------------------
{
  const k = new THREE.Group(); k.position.set(19.8, 0, 0.36); scene.add(k);
  mesh(rbox(3.8, 0.86, 0.6, 0.01), M.white, 0, 0.43, 0, k);
  for (let i = 0; i < 5; i++) { mesh(boxG(0.74, 0.8, 0.01), "#ecebe6", -1.52 + i * 0.76, 0.43, 0.305, k, false); mesh(boxG(0.2, 0.015, 0.02), M.steel, -1.52 + i * 0.76, 0.78, 0.32, k, false); }
  mesh(rbox(3.86, 0.04, 0.66, 0.01), M.oak, 0, 0.88, 0.0, k);
  mesh(rbox(3.8, 0.7, 0.36, 0.01), M.white, 0, 2.05, -0.12, k);
  for (let i = 0; i < 5; i++) mesh(boxG(0.2, 0.015, 0.02), M.steel, -1.52 + i * 0.76, 1.75, 0.07, k, false);
  // sink + tap
  mesh(rbox(0.6, 0.02, 0.42, 0.04), M.steel, 0.9, 0.895, 0.02, k); mesh(boxG(0.54, 0.01, 0.36), M.darkSteel, 0.9, 0.89, 0.02, k, false);
  const tap = mesh(new THREE.TorusGeometry(0.12, 0.012, 8, 20, Math.PI), M.steel, 0.9, 0.9, -0.14, k); tap.rotation.y = Math.PI / 2;
  // espresso machine
  const em = new THREE.Group(); em.position.set(-1.0, 0.9, -0.02); k.add(em);
  mesh(rbox(0.56, 0.42, 0.42, 0.03), M.steel, 0, 0.21, 0, em);
  mesh(boxG(0.5, 0.012, 0.18), M.darkSteel, 0, 0.03, 0.17, em);
  for (const s of [-1, 1]) { mesh(cyl(0.035, 0.035, 0.05, 20), M.steel, s * 0.13, 0.26, 0.2, em); const h = mesh(cap(0.014, 0.12), M.black, s * 0.13, 0.24, 0.31, em); h.rotation.x = Math.PI / 2; }
  const gauge = canvasTex(64, 64, (g) => { g.fillStyle = "#f4f1e8"; g.beginPath(); g.arc(32, 32, 30, 0, 7); g.fill(); g.strokeStyle = "#222"; g.lineWidth = 3; g.beginPath(); g.moveTo(32, 32); g.lineTo(48, 18); g.stroke(); });
  mesh(cyl(0.04, 0.04, 0.01, 24), new THREE.MeshStandardMaterial({ map: gauge }), 0, 0.36, 0.215, em, false).rotation.x = Math.PI / 2;
  const wand = mesh(cyl(0.006, 0.006, 0.18, 8), M.steel, 0.25, 0.2, 0.2, em); wand.rotation.z = 0.25;
  for (let i = 0; i < 4; i++) { const c = mesh(lathe([[0.001, 0], [0.028, 0], [0.034, 0.05], [0.03, 0.05]]), M.ceramic, -0.15 + i * 0.1, 0.42, 0, em); }
  // grinder with beans
  const gr = new THREE.Group(); gr.position.set(-1.55, 0.9, 0.0); k.add(gr);
  mesh(rbox(0.16, 0.3, 0.22, 0.02), M.darkSteel, 0, 0.15, 0, gr);
  mesh(lathe([[0.07, 0], [0.09, 0.16], [0.1, 0.17]]), M.glass, 0, 0.3, 0, gr, false);
  mesh(lathe([[0.001, 0], [0.068, 0], [0.08, 0.1], [0.001, 0.1]]), new THREE.MeshStandardMaterial({ color: "#4a2a17", roughness: 0.8 }), 0, 0.305, 0, gr);
  // fruit bowl and a few mugs
  const bowl = mesh(lathe([[0.001, 0], [0.08, 0], [0.16, 0.07], [0.155, 0.075], [0.075, 0.008]]), M.ceramic, 0.1, 0.9, 0.05, k);
  for (const [x, z, c, r] of [[0.06, 0.04, "#d9382a", 0.042], [0.14, 0.08, "#e8a83a", 0.04], [0.1, 0.0, "#8bb83f", 0.038], [0.16, 0.0, "#d9382a", 0.04]]) mesh(sph(r, 16, 12), new THREE.MeshPhysicalMaterial({ color: c, roughness: 0.35, clearcoat: 0.6 }), x, 0.94, z, k);
  mug(k, -0.45, 0.9, 0.12, "#e7e3da"); mug(k, -0.35, 0.9, 0.18, "#3f7a5f", 1);
  // fridge
  const fr = new THREE.Group(); fr.position.set(2.3, 0, -0.02); k.add(fr);
  mesh(rbox(0.75, 1.95, 0.68, 0.02), M.steel, 0, 0.975, 0, fr); mesh(boxG(0.74, 0.01, 0.01), M.darkSteel, 0, 1.3, 0.345, fr, false);
  for (const y of [0.9, 1.6]) mesh(cyl(0.012, 0.012, 0.36, 8), M.darkSteel, 0.3, y, 0.37, fr);
}
// water cooler
{
  const w = new THREE.Group(); w.position.set(16.9, 0, 0.45); scene.add(w);
  mesh(rbox(0.32, 0.96, 0.32, 0.03), M.white, 0, 0.48, 0, w);
  mesh(boxG(0.22, 0.24, 0.02), M.black, 0, 0.72, 0.16, w, false);
  mesh(boxG(0.03, 0.04, 0.04), "#2e6fb0", -0.05, 0.8, 0.18, w); mesh(boxG(0.03, 0.04, 0.04), "#c23a3a", 0.05, 0.8, 0.18, w);
  mesh(rbox(0.2, 0.02, 0.1, 0.01), M.steel, 0, 0.62, 0.17, w);
  const bottle = lathe([[0.001, 0], [0.025, 0], [0.025, 0.06], [0.13, 0.11], [0.135, 0.42], [0.12, 0.45], [0.001, 0.46]]);
  bottle.rotateX(Math.PI); bottle.translate(0, 1.42, 0);
  mesh(bottle, M.water, 0, 0, 0, w, false).renderOrder = 3;
  mesh(cyl(0.06, 0.06, 0.06, 16), M.white, 0, 0.99, 0, w);
  mesh(lathe([[0.001, 0], [0.03, 0], [0.034, 0.1], [0.03, 0.1]]), new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.6 }), 0.24, 0, 0.1, w);   // cup bin
}
// beehive on a little wall shelf, with bees
mesh(boxG(0.6, 0.04, 0.25), M.walnut, 16.1, 1.75, 0.13);
const hive = new THREE.Group(); hive.position.set(16.1, 1.98, 0.14); scene.add(hive);
for (let i = 0; i < 5; i++) mesh(sph(0.16 - Math.abs(i - 2) * 0.028, 24, 10), new THREE.MeshStandardMaterial({ color: i % 2 ? "#c9952f" : "#ddb14e", roughness: 0.85 }), 0, 0.2 - i * 0.07, 0, hive).scale.y = 0.55;
mesh(sph(0.03), "#4a3210", 0, 0.02, 0.13, hive);
const bees = [0, 1, 2].map((i) => { const b = mesh(sph(0.018), "#e2b33a", 0, 0, 0, scene, false); b.userData.p = i * 2.1; return b; });

// ---- lounge, games -------------------------------------------------------------------------------
const rugTex = canvasTex(512, 384, (g, w, h) => { g.fillStyle = "#b9aa98"; g.fillRect(0, 0, w, h); g.strokeStyle = "#8f7f6b"; g.lineWidth = 10; g.strokeRect(20, 20, w - 40, h - 40);
  for (let i = 0; i < 4000; i++) { g.fillStyle = `rgba(${90 + rnd() * 60},${80 + rnd() * 50},${60 + rnd() * 40},.08)`; g.fillRect(rnd() * w, rnd() * h, 2, 2); } });
mesh(boxG(3.0, 0.012, 2.6), new THREE.MeshStandardMaterial({ map: rugTex, roughness: 1 }), 6.9, 0.006, 13.9, scene, false);
{
  const s = new THREE.Group(); s.position.set(6.9, 0, 15.1); scene.add(s);
  mesh(rbox(2.3, 0.3, 0.92, 0.08), M.fabric, 0, 0.3, 0, s);
  mesh(rbox(2.3, 0.45, 0.22, 0.09), M.fabric, 0, 0.62, 0.36, s);
  for (const x of [-1.07, 1.07]) mesh(rbox(0.18, 0.36, 0.92, 0.08), M.fabric, x, 0.56, 0, s);
  for (const x of [-0.5, 0.5]) mesh(rbox(1.0, 0.13, 0.7, 0.06), new THREE.MeshStandardMaterial({ color: "#8996a0", roughness: 1 }), x, 0.5, -0.06, s);
  for (const [x, z] of [[-1.05, -0.38], [1.05, -0.38], [-1.05, 0.38], [1.05, 0.38]]) mesh(cyl(0.02, 0.015, 0.15, 8), M.walnut, x, 0.075, z, s);
  const pil = mesh(rbox(0.4, 0.36, 0.12, 0.06), new THREE.MeshStandardMaterial({ color: "#c9a24a", roughness: 1 }), -0.75, 0.68, 0.2, s); pil.rotation.set(-0.3, 0.2, 0.1);
}
{
  const t = new THREE.Group(); t.position.set(6.9, 0, 13.7); scene.add(t);
  mesh(cyl(0.45, 0.45, 0.04, 40), M.walnut, 0, 0.42, 0, t);
  for (let i = 0; i < 3; i++) { const a = i * 2.1; const l = mesh(cyl(0.015, 0.012, 0.44, 8), M.darkSteel, Math.cos(a) * 0.3, 0.21, Math.sin(a) * 0.3, t); l.rotation.set(Math.sin(a) * 0.2, 0, -Math.cos(a) * 0.2); }
  const mag = mesh(boxG(0.22, 0.01, 0.3), "#e6dccb", -0.1, 0.445, 0, t); mag.rotation.y = 0.5;
  mug(t, 0.2, 0.44, 0.05, "#c8536d");
}
// bookshelf as a room divider by the lounge
{
  const b = new THREE.Group(); b.position.set(5.2, 0, 13.4); b.rotation.y = Math.PI / 2; scene.add(b);
  mesh(boxG(1.8, 1.6, 0.36), M.walnut, 0, 0.8, 0, b); mesh(boxG(1.72, 1.52, 0.34), "#2a1c13", 0, 0.8, 0.02, b, false);
  for (const y of [0.42, 0.82, 1.22]) mesh(boxG(1.72, 0.03, 0.34), M.walnut, 0, y, 0.02, b);
  const cols = ["#8b2f2f", "#2f4b6e", "#c9a24a", "#3f6b4a", "#6b5a8e", "#d8d2c4", "#24323d"];
  for (const y of [0.06, 0.44, 0.84, 1.24]) { let x = -0.82; while (x < 0.78) { const w = 0.03 + rnd() * 0.04, h = 0.24 + rnd() * 0.1; if (rnd() < 0.12) { x += 0.12; continue; }
    mesh(boxG(w, h, 0.22), cols[Math.floor(rnd() * cols.length)], x + w / 2, y + h / 2, 0.04, b); x += w + 0.004; } }
  plant(0, 0, 0.5, b, "leafy", 1.62);
}
// table tennis
const ball = mesh(sph(0.02, 12, 8), "#f6f2e8", 0, 0, 0, scene, false);
{
  const p = new THREE.Group(); p.position.set(19.4, 0, 4.7); scene.add(p);
  const top = canvasTex(1024, 570, (g, w, h) => { g.fillStyle = "#1f4f86"; g.fillRect(0, 0, w, h); g.strokeStyle = "#fff"; g.lineWidth = 8; g.strokeRect(4, 4, w - 8, h - 8); g.lineWidth = 3; g.beginPath(); g.moveTo(0, h / 2); g.lineTo(w, h / 2); g.stroke(); });
  mesh(boxG(2.74, 0.03, 1.525), new THREE.MeshStandardMaterial({ map: top, roughness: 0.55 }), 0, 0.76, 0, p);
  for (const x of [-1.1, 1.1]) for (const z of [-0.6, 0.6]) mesh(boxG(0.05, 0.74, 0.05), M.darkSteel, x, 0.37, z, p);
  for (const x of [-1.1, 1.1]) mesh(boxG(0.05, 0.05, 1.2), M.darkSteel, x, 0.2, 0, p);
  const net = canvasTex(256, 32, (g, w, h) => { g.clearRect(0, 0, w, h); g.strokeStyle = "rgba(20,20,20,.8)"; for (let i = 0; i < w; i += 6) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, h); g.stroke(); } for (let j = 0; j < h; j += 6) { g.beginPath(); g.moveTo(0, j); g.lineTo(w, j); g.stroke(); } g.fillStyle = "#fff"; g.fillRect(0, 0, w, 4); });
  const nm = mesh(new THREE.PlaneGeometry(1.7, 0.15), new THREE.MeshStandardMaterial({ map: net, transparent: true, side: THREE.DoubleSide, alphaTest: 0.1 }), 0, 0.85, 0, p, false); nm.rotation.y = Math.PI / 2;
  for (const z of [-0.85, 0.85]) mesh(cyl(0.01, 0.01, 0.16, 8), M.black, 0, 0.85, z, p);
  for (const [x, z, r, c] of [[-0.9, 0.35, 0.3, "#b8232b"], [0.95, -0.4, -2.4, "#1b1b1b"]]) { const pd = new THREE.Group(); pd.position.set(x, 0.79, z); pd.rotation.y = r; p.add(pd);
    mesh(cyl(0.075, 0.075, 0.012, 24), c, 0, 0, 0, pd); const h = mesh(boxG(0.03, 0.02, 0.1), M.oak, 0, 0, 0.11, pd); }
}
// foosball
{
  const f = new THREE.Group(); f.position.set(19.4, 0, 8.0); scene.add(f);
  const field = canvasTex(512, 300, (g, w, h) => { g.fillStyle = "#2f7a3f"; g.fillRect(0, 0, w, h); g.strokeStyle = "#fff"; g.lineWidth = 3; g.strokeRect(6, 6, w - 12, h - 12); g.beginPath(); g.moveTo(w / 2, 6); g.lineTo(w / 2, h - 6); g.stroke(); g.beginPath(); g.arc(w / 2, h / 2, 34, 0, 7); g.stroke(); });
  mesh(boxG(1.22, 0.06, 0.7), new THREE.MeshStandardMaterial({ map: field, roughness: 0.8 }), 0, 0.74, 0, f);
  for (const [w, d, x, z] of [[1.3, 0.04, 0, 0.37], [1.3, 0.04, 0, -0.37], [0.04, 0.78, 0.65, 0], [0.04, 0.78, -0.65, 0]]) mesh(boxG(w, 0.2, d), M.walnut, x, 0.84, z, f);
  for (const x of [-0.6, 0.6]) for (const z of [-0.33, 0.33]) mesh(boxG(0.08, 0.74, 0.08), M.walnut, x, 0.37, z, f);
  const rods = [-0.5, -0.36, -0.2, -0.07, 0.07, 0.2, 0.36, 0.5];
  rods.forEach((x, i) => {
    const r = mesh(cyl(0.008, 0.008, 1.1, 8), M.steel, x, 0.85, 0, f); r.rotation.x = Math.PI / 2;
    mesh(cyl(0.018, 0.018, 0.12, 10), M.black, x, 0.85, i % 2 ? 0.58 : -0.58, f).rotation.x = Math.PI / 2;
    const n = [1, 2, 5, 3, 3, 5, 2, 1][i], team = (i === 0 || i === 1 || i === 3 || i === 5) ? "#c23a3a" : "#2e5fb0";
    for (let k2 = 0; k2 < n; k2++) { const z = n === 1 ? 0 : -0.25 + (0.5 / (n - 1)) * k2; mesh(boxG(0.025, 0.09, 0.03), team, x, 0.81, z, f); mesh(sph(0.016, 10, 8), "#e9c9a6", x, 0.87, z, f); }
  });
}

// ---- glass offices: Coach, Orchestrator, HR, you ---------------------------------------------------
function glassRoom(x0, z0, x1, z1, door) {
  const glass = new THREE.MeshPhysicalMaterial({ color: "#e4f2ee", roughness: 0.05, transmission: 0.9, thickness: 0.01, transparent: true, opacity: 0.35, depthWrite: false });
  const frame = new THREE.MeshStandardMaterial({ color: "#2f3433", metalness: 0.6, roughness: 0.4 });
  const walls = [];
  if (x0 > 0) walls.push(["x", x0, z0, z1]); if (x1 < RW) walls.push(["x", x1, z0, z1]);
  if (z0 > 0) walls.push(["z", z0, x0, x1]); if (z1 < RD) walls.push(["z", z1, x0, x1]);
  for (const [axis, c, a, b] of walls) {
    const segs = axis === door[0] && c === door[1] ? [[a, door[2] - 0.5], [door[2] + 0.5, b]] : [[a, b]];
    for (const [s0, s1] of segs) {
      const l = s1 - s0, m = (s0 + s1) / 2, X = axis === "z", px = X ? m : c, pz = X ? c : m;
      const gl = mesh(boxG(X ? l : 0.02, 2.4, X ? 0.02 : l), glass, px, 1.2, pz, scene, false); gl.receiveShadow = false; gl.renderOrder = 2;
      for (const y of [0.02, 2.4]) mesh(boxG(X ? l : 0.05, 0.04, X ? 0.05 : l), frame, px, y, pz, scene, false);
      for (const e of [s0, s1]) mesh(boxG(0.05, 2.42, 0.05), frame, X ? e : c, 1.21, X ? c : e, scene, false);
      const film = mesh(boxG(X ? l : 0.025, 0.12, X ? 0.025 : l), new THREE.MeshStandardMaterial({ color: "#ffffff", transparent: true, opacity: 0.55, roughness: 0.9 }), px, 1.15, pz, scene, false);
    }
  }
  const carpet = mesh(boxG(x1 - x0 - 0.1, 0.008, z1 - z0 - 0.1), new THREE.MeshStandardMaterial({ color: "#8e948f", roughness: 1 }), (x0 + x1) / 2, 0.004, (z0 + z1) / 2, scene, false);
}
glassRoom(0, 0, 4.4, 4.0, ["z", 4.0, 3.2]);
glassRoom(0, 5.0, 4.2, 8.8, ["x", 4.2, 6.9]);
glassRoom(0, 11.4, 4.4, RD, ["x", 4.4, 12.3]);
glassRoom(17.0, 11.0, RW, RD, ["x", 17.0, 12.0]);
glassRoom(9.0, 12.6, 13.4, RD, ["z", 12.6, 11.2]);
// each room's name on its glass, as frosted vinyl lettering: the name, a thin rule and what the room is for
function glassSign(name, sub, x, z, rotY, w = 1.7) {
  const c = document.createElement("canvas"); c.width = 1024; c.height = 300;
  const g = c.getContext("2d");
  g.shadowColor = "rgba(15, 25, 20, 0.55)"; g.shadowBlur = 10; g.shadowOffsetY = 2;
  g.fillStyle = "rgba(255, 255, 255, 0.96)"; g.textBaseline = "alphabetic";
  let size = 136; do { g.font = `600 ${size}px 'IBM Plex Sans', system-ui, sans-serif`; size -= 4; } while (g.measureText(name).width > 980 && size > 48);
  g.fillText(name, 18, 150);
  g.fillRect(20, 186, Math.min(980, g.measureText(name).width * 0.42), 5);
  g.font = "400 50px 'IBM Plex Sans', system-ui, sans-serif"; if ("letterSpacing" in g) g.letterSpacing = "5px";
  g.fillText(sub.toUpperCase(), 20, 262);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  const m = new THREE.Mesh(new THREE.PlaneGeometry(w, w * 300 / 1024), new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false, toneMapped: false }));
  m.position.set(x, 1.66, z); m.rotation.y = rotY; m.renderOrder = 4; scene.add(m);
}
// on the glass you look at, where no other wall or the bookshelf comes in front
glassSign("Coach", "Team practices", 4.425, 1.05, Math.PI / 2, 1.9);
glassSign("Orchestrator", "Runs the team", 2.0, 8.825, 0, 2.5);
glassSign("HR", "Hiring & onboarding", 1.9, 11.425, 0, 2.3);
glassSign("Finance", "Budget & spending", 13.425, 14.4, Math.PI / 2, 2.4);
glassSign("Your office", "Team lead", 19.2, 11.025, 0, 2.6);
// Finance: a desk with the spending on screen, a filing cabinet, a plant
const finDesk = workDesk(11.2, 14.7, 0, { screen: "chart", lamp: true, mug: "#3f7a5f", papers: true });
{ const fc = new THREE.Group(); fc.position.set(9.5, 0, 15.6); scene.add(fc); mesh(rbox(0.5, 1.3, 0.6, 0.01), M.steel, 0, 0.65, 0, fc); for (const y of [0.3, 0.72, 1.12]) mesh(boxG(0.16, 0.02, 0.02), M.darkSteel, 0, y, 0.31, fc, false); }
plant(13.0, 15.6, 0.8, scene, "snake");
// Coach: desk + a whiteboard full of notes
const coachDesk = workDesk(2.0, 1.4, 0, { screen: "off", lamp: true, mug: "#6b5a8e", plant: true });
{ const wbT = canvasTex(512, 300, (g, w, h) => { g.fillStyle = "#fbfbf8"; g.fillRect(0, 0, w, h); g.strokeStyle = "#2f5aa8"; g.lineWidth = 3; for (let i = 0; i < 7; i++) { g.beginPath(); g.moveTo(30, 40 + i * 34); g.lineTo(80 + rnd() * 300, 40 + i * 34); g.stroke(); } g.strokeStyle = "#c23a3a"; g.beginPath(); g.arc(400, 120, 50, 0, 7); g.stroke(); });
  const wb = mesh(boxG(0.04, 1.0, 1.6), new THREE.MeshStandardMaterial({ map: wbT, roughness: 0.3 }), 0.03, 1.5, 2.2, scene, false); }
plant(0.45, 3.55, 0.85, scene, "snake");
// Orchestrator
const orchDesk = workDesk(1.65, 6.9, Math.PI / 2, { screen: "off", lamp: true, mug: "#3f7a5f", papers: true });
plant(0.45, 8.35, 0.8, scene, "leafy");
// HR: desk, a chair for candidates, a "hiring" poster
const hrDesk = workDesk(1.7, 13.7, Math.PI / 2, { screen: "doc", lamp: true, mug: "#c9a24a", papers: true });
officeChair(scene, 3.05, 13.7, -Math.PI / 2);
{ const hrT = canvasTex(512, 640, (g, w, h) => { g.fillStyle = "#3f7a5f"; g.fillRect(0, 0, w, h); g.fillStyle = "#fff"; g.font = "bold 84px system-ui"; g.fillText("We're", 40, 160); g.fillText("hiring", 40, 260);
  g.font = "36px system-ui"; ["Tech Lead", "Developer", "Reviewer"].forEach((t, i) => g.fillText("· " + t, 50, 360 + i * 60)); if (logoImg.complete) g.drawImage(logoImg, 340, 470, 140, 140); });
  logoImg.addEventListener("load", () => { hrT.image.getContext("2d").drawImage(logoImg, 340, 470, 140, 140); hrT.needsUpdate = true; });
  const pos = mesh(boxG(0.03, 0.9, 0.72), new THREE.MeshStandardMaterial({ map: hrT }), 0.03, 1.6, 14.8, scene, false); }
plant(3.9, 15.5, 0.8, scene, "fiddle");
// your office
workDesk(19.8, 13.9, -Math.PI / 2, { screen: "doc", lamp: true, mug: "#22302a", papers: true, top: M.walnut });
{ const tray = mesh(rbox(0.32, 0.07, 0.24, 0.01), "#cfc4ae", 19.62, 0.81, 14.4); for (const i of [0, 1, 2]) mesh(boxG(0.21, 0.004, 0.29), M.white, 19.62, 0.85 + i * 0.008, 14.4, scene, false); }
{ const arm = new THREE.Group(); arm.position.set(21.2, 0, 15.3); arm.rotation.y = -2.4; scene.add(arm);
  mesh(rbox(0.8, 0.4, 0.8, 0.1), new THREE.MeshStandardMaterial({ color: "#8a5a3c", roughness: 0.6 }), 0, 0.3, 0, arm); mesh(rbox(0.8, 0.45, 0.18, 0.08), new THREE.MeshStandardMaterial({ color: "#8a5a3c", roughness: 0.6 }), 0, 0.6, 0.32, arm); }
plant(21.4, 11.5, 0.9, scene, "snake");
// entrance door and a coat stand
const door = new THREE.Group(); door.position.set(0.02, 0, 10.1); scene.add(door);
mesh(boxG(0.05, 2.2, 1.0), M.walnut, 0, 1.1, 0, door); mesh(boxG(0.07, 2.3, 1.12), M.blackMatte, -0.01, 1.15, 0, door, false);
mesh(cyl(0.012, 0.012, 0.14, 8), M.steel, 0.06, 1.0, 0.36, door).rotation.x = Math.PI / 2;
mesh(boxG(0.9, 0.01, 1.3), "#585f5a", 0.55, 0.006, 10.1, scene, false);
{ const cs = new THREE.Group(); cs.position.set(0.5, 0, 9.2); scene.add(cs); mesh(cyl(0.015, 0.02, 1.8, 8), M.walnut, 0, 0.9, 0, cs); mesh(cyl(0.2, 0.22, 0.03, 20), M.walnut, 0, 0.015, 0, cs);
  const coat = mesh(cap(0.12, 0.55), new THREE.MeshStandardMaterial({ color: "#3c4a5a", roughness: 1 }), 0.08, 1.35, 0, cs); coat.scale.z = 0.5; }
// plants around the open space
plant(5.3, 4.6, 1.15, scene, "fiddle"); plant(21.5, 2.6, 1.0, scene, "snake"); plant(21.5, 9.9, 1.1, scene, "leafy"); plant(4.85, 10.6, 0.8, scene, "snake"); plant(16.8, 6.4, 0.9, scene, "fiddle");

// a wall clock above the sign
const clockG = new THREE.Group(); clockG.position.set(11.8, 2.62, 0.04); scene.add(clockG);
const cf = mesh(cyl(0.22, 0.22, 0.04, 48), M.ceramic, 0, 0, 0, clockG, false); cf.rotation.x = Math.PI / 2;
const rim = mesh(new THREE.TorusGeometry(0.22, 0.015, 8, 48), M.darkSteel, 0, 0, 0.02, clockG, false);
for (let i = 0; i < 12; i++) { const tk = mesh(boxG(0.012, i % 3 ? 0.025 : 0.045, 0.005), M.black, Math.sin(i * Math.PI / 6) * 0.18, Math.cos(i * Math.PI / 6) * 0.18, 0.025, clockG, false); tk.rotation.z = -i * Math.PI / 6; }
const hand = (len, w) => { const g = new THREE.Group(); g.position.z = 0.03; clockG.add(g); mesh(boxG(w, len, 0.004), M.black, 0, len / 2 - 0.02, 0, g, false); return g; };
const clockHands = { hour: hand(0.11, 0.014), minute: hand(0.17, 0.009) };

  // ---- where people sit and spend their time ------------------------------------------------------------
  // A seat: where the person sits (x, z), the way they face, the screen to light up and the chair to pull in.
  const seats = [];
  const deskSeat = (desk, kind, x, z, face) => { seats.push({ kind, x, z, face, screen: desk.userData.screen, chair: desk.userData.chair, lamp: desk.userData.lamp,
    chairIn: { z: 0.72, r: 0 }, chairOut: { z: 0.8, r: 0.5 } }); };
  // desks by the windows, the person facing the window
  for (const [x, plantIt] of [[6.2, false], [9.4, true], [14.2, false]]) {
    const d = workDesk(x, 1.15, Math.PI, { screen: "off", lamp: false, mug: plantIt ? "" : "#c8536d", plant: plantIt, papers: !plantIt });
    deskSeat(d, "window", x, 1.82, Math.PI);
  }
  // the shared table: the north side faces the camera, the south side faces away
  function sharedTable(cx, cz) {
    const T = new THREE.Group(); T.position.set(cx, 0, cz); scene.add(T);
    mesh(rbox(5.0, 0.05, 1.6, 0.04), M.oak, 0, 0.74, 0, T);
    for (const x of [-2.1, 2.1]) mesh(boxG(0.06, 0.7, 1.3), M.darkSteel, x, 0.37, 0, T);
    mesh(boxG(4.3, 0.06, 0.06), M.darkSteel, 0, 0.62, 0, T);
    for (const x of [-0.6, 0, 0.6]) succulent(T, x, 0.765, 0);
    for (const [dx, side] of [[-1.6, 1], [0, 1], [1.6, 1], [-1.6, -1], [0, -1], [1.6, -1]]) {
      const x = cx + dx, z = cz - side * 1.18, face = side > 0 ? 0 : Math.PI;
      const lap = laptop(scene, x, 0.765, cz - side * 0.55, face, "off");
      if ((dx + side) % 2) mug(scene, x + 0.42, 0.765, cz - side * 0.6, ["#3f7a5f", "#e2b04a", "#2f4b6e"][Math.abs(Math.round(dx)) % 3]);
      const ch = officeChair(scene, x, z, side > 0 ? Math.PI : 0);
      seats.push({ kind: "table", x, z, face, screen: lap.userData.screen, chair: ch, chairIn: { z, r: side > 0 ? Math.PI : 0 }, chairOut: { z: z - side * 0.25, r: (side > 0 ? Math.PI : 0) + 0.4 }, world: true });
    }
  }
  sharedTable(11.0, 6.6);
  let extraTable = false;
  const moreSeats = () => { if (!extraTable) { extraTable = true; sharedTable(11.0, 10.9); } };
  const coachSeat = { kind: "coach", x: 2.0, z: 0.68, face: 0, screen: coachDesk.userData.screen, chair: coachDesk.userData.chair, lamp: coachDesk.userData.lamp, chairIn: { z: 0.72, r: 0 }, chairOut: { z: 0.8, r: 0.5 }, via: [[3.2, 4.4]] };
  const orchSeat = { kind: "orch", x: 0.98, z: 6.9, face: Math.PI / 2, screen: orchDesk.userData.screen, chair: orchDesk.userData.chair, lamp: orchDesk.userData.lamp, chairIn: { z: 0.72, r: 0 }, chairOut: { z: 0.8, r: 0.5 }, via: [[4.7, 6.9]] };
  const SPOTS = {
    coffee: [{ x: 18.85, z: 1.3, face: Math.PI * 0.95 }, { x: 20.05, z: 1.4, face: Math.PI * 1.04 }],
    sofa: [{ x: 6.48, z: 15.0, face: Math.PI }, { x: 7.34, z: 15.0, face: Math.PI }],
    games: [{ x: 19.4, z: 8.62, face: Math.PI }, { x: 19.4, z: 7.38, face: 0 }, { x: 17.7, z: 4.7, face: Math.PI / 2 }, { x: 21.1, z: 4.7, face: -Math.PI / 2 }],
    window: [{ x: 7.8, z: 2.5, face: Math.PI }, { x: 12.0, z: 2.5, face: Math.PI }],
    coachWindow: [{ x: 3.3, z: 2.9, face: -0.5, via: [[3.2, 4.4]] }],
    door: [{ x: 0.9, z: 10.1, face: Math.PI / 2 }],
  };
  return { seats, coachSeat, orchSeat, moreSeats, SPOTS, windowGlass, sun, hemi, fill, ball, bees, drawBoard, clockHands, hrDesk, finDesk, setScreen };
}

// ---- walking: along the aisles, never through the furniture ------------------------------------------------------
const AISLES = [[[5.0, 3.2], [16.6, 3.2]], [[0.9, 10.1], [16.6, 10.1]], [[5.0, 3.2], [5.0, 10.1]], [[16.6, 1.9], [16.6, 12.0]]];
function nearestOnAisle(p) {
  let best = null;
  AISLES.forEach(([a, b], i) => {
    const dx = b[0] - a[0], dz = b[1] - a[1], t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / (dx * dx + dz * dz)));
    const q = [a[0] + t * dx, a[1] + t * dz], d = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (!best || d < best.d) best = { q, d, i };
  });
  return best;
}
function route(from, to) {
  const fromVia = from.via || [], toVia = to.via || [];
  const s = fromVia.at(-1) || [from.x, from.z], e = toVia.at(-1) || [to.x, to.z];
  const A = nearestOnAisle(s), B = nearestOnAisle(e);
  // the aisle corners, plus where we step on and off, as a small graph
  const key = (p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`;
  const nodes = new Map();
  const add = (p) => { nodes.set(key(p), p); return key(p); };
  const onSeg = AISLES.map(([a, b]) => [a, b]);
  const pts = new Set(AISLES.flat().map(add));
  const ka = add(A.q), kb = add(B.q);
  const segPts = onSeg.map(([a, b], i) => [...nodes.values()].filter((p) => Math.abs((b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])) < 1e-6
    && p[0] >= Math.min(a[0], b[0]) - 1e-6 && p[0] <= Math.max(a[0], b[0]) + 1e-6 && p[1] >= Math.min(a[1], b[1]) - 1e-6 && p[1] <= Math.max(a[1], b[1]) + 1e-6)
    .sort((p, q) => (p[0] - q[0]) || (p[1] - q[1])));
  const edges = new Map();
  for (const list of segPts) for (let i = 1; i < list.length; i++) {
    const u = key(list[i - 1]), v = key(list[i]), w = Math.hypot(list[i][0] - list[i - 1][0], list[i][1] - list[i - 1][1]);
    (edges.get(u) || edges.set(u, []).get(u)).push([v, w]); (edges.get(v) || edges.set(v, []).get(v)).push([u, w]);
  }
  const dist = new Map([[ka, 0]]), prev = new Map(), todo = new Set(nodes.keys());
  while (todo.size) {
    let u = null; for (const k of todo) if (dist.has(k) && (u === null || dist.get(k) < dist.get(u))) u = k;
    if (u === null || u === kb) break;
    todo.delete(u);
    for (const [v, w] of edges.get(u) || []) if (!dist.has(v) || dist.get(u) + w < dist.get(v)) { dist.set(v, dist.get(u) + w); prev.set(v, u); }
  }
  const mid = []; for (let k = kb; k; k = prev.get(k)) mid.unshift(nodes.get(k)); if (mid[0] !== nodes.get(ka)) mid.unshift(nodes.get(ka));
  void pts;
  const path = [[from.x, from.z], ...fromVia, ...mid, ...[...toVia].reverse(), [to.x, to.z]];
  return path.filter((p, i) => i === 0 || Math.hypot(p[0] - path[i - 1][0], p[1] - path[i - 1][1]) > 0.05);
}

// ---- the people -----------------------------------------------------------------------------------------------
const FEMALE = new Set("laila layla leila yara yasmine yasmin nour noor sara sarah mariam maryam salma hana hanna farah dina reem rana mona aya malak jana lina nada heba amira rania noha dalia habiba fatma fatima esraa menna shahd jasmine jessica emma olivia sophia mia ava amelia zeinab nadia samira rasha ghada huda iman eman asmaa basma doaa lamia lamis marwa mai may nermeen nesma rehab sally shaimaa sherine yomna youmna".split(" "));
const POOL = { f: ["Female_Adult_15", "Female_Adult_14", "Female_Adult_09"], m: ["Male_Adult_08", "Male_Adult_07", "Male_Adult_13", "Male_Adult_14", "Male_Adult_03"] };
const hashOf = (s) => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
const genderOf = (name) => (FEMALE.has(String(name).split(/\s+/)[0].toLowerCase()) ? "f" : "m");

const ANIM = { work: "sit_table_breathe_01", think: "sit_table_gestic_thoughtful", wait: "sit_chair_idle_waiting_01", nap: "sit_table_idle_yawn", idle: "sit_table_idle_neutral_01",
  phone: "cell_phone_textmessage", coffee: "drink_drinking", sofa: "sit_chair_idle_relaxed_01", games: "idle_look_around_01", walk: "walk_neutral_01" };

const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const texLoader = new THREE.TextureLoader();
const cache = new Map();
const loadOnce = (url) => { if (!cache.has(url)) cache.set(url, loader.loadAsync(url)); return cache.get(url); };
async function moves(g) {
  const gl = await loadOnce(`${BASE}/moves_${g}.glb`);
  if (!gl.userData.fixed) {
    gl.userData.fixed = true;
    // the walk carries the body forward: keep it on the spot, the code moves the person
    const walk = gl.animations.find((c) => c.name === ANIM.walk);
    for (const t of walk?.tracks || []) if (t.name.endsWith(".position")) {
      const v = t.values, n = v.length / 3, range = [0, 1, 2].map((a) => { let lo = Infinity, hi = -Infinity; for (let i = 0; i < n; i++) { lo = Math.min(lo, v[i * 3 + a]); hi = Math.max(hi, v[i * 3 + a]); } return hi - lo; });
      range.forEach((r, a) => { if (r > 30) for (let i = 0; i < n; i++) v[i * 3 + a] = v[a]; });
    }
  }
  return gl.animations;
}
async function body(avatar) {
  const gl = await loadOnce(`${BASE}/people/${avatar}.glb`);
  const o = cloneSkinned(gl.scene);
  const tex = (n, srgb = true) => { const t = texLoader.load(`${BASE}/tex/${n}.webp`); if (srgb) t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t; };   // the UVs keep three.js's own orientation (they were exported from three.js)
  o.traverse((m) => {
    if (!m.isMesh) return;
    m.castShadow = true; m.receiveShadow = true; m.frustumCulled = false;
    const one = (mm) => { const code = mm.name.split("_")[0];
      if (/_(body|head)$/.test(mm.name)) { const part = mm.name.endsWith("_body") ? "body" : "head";
        return new THREE.MeshStandardMaterial({ map: tex(`${code}_${part}_color`), normalMap: tex(`${code}_${part}_normal`, false), roughness: part === "head" ? 0.6 : 0.88 }); }
      return new THREE.MeshStandardMaterial({ map: tex(`${code}_opacity_color`), alphaTest: 0.4, side: THREE.DoubleSide, roughness: 0.75 }); };
    m.material = Array.isArray(m.material) ? m.material.map(one) : one(m.material);
  });
  o.scale.setScalar(0.01);
  return o;
}

// One person: their body, what they're doing and where. `spot` is {x, z, face, via?}.
class Person {
  constructor(id, avatar, gender) { this.id = id; this.avatar = avatar; this.gender = gender; this.G = new THREE.Group(); this.ready = this.load(); this.visible = false; }
  async load() {
    const [o, clips] = await Promise.all([body(this.avatar), moves(this.gender)]);
    this.o = o; this.G.add(o); W.scene.add(this.G);
    this.mixer = new THREE.AnimationMixer(o);
    this.clips = Object.fromEntries(clips.map((c) => [c.name, c]));
    this.head = o.getObjectByName("Bip01_Head");
    this.G.visible = this.visible;
    if (this.want) this.setPose(this.want);
  }
  setPose(pose) {
    this.want = pose;
    if (!this.mixer || this.pose === pose) return;
    this.pose = pose;
    this.mixer.stopAllAction();
    const clip = this.clips[ANIM[pose]] || this.clips[ANIM.idle];
    const act = this.mixer.clipAction(clip); act.reset().play(); act.time = (hashOf(this.id) % 997) / 997 * clip.duration;
    // the clip moves and turns the body: put the hips over the spot and face the way the spot faces
    this.o.rotation.set(0, 0, 0); this.o.position.set(0, 0, 0);
    this.mixer.update(0); this.G.updateMatrixWorld(true);
    const at = (n) => this.G.worldToLocal(this.o.getObjectByName(n).getWorldPosition(new THREE.Vector3()));
    const r = at("Bip01_R_Thigh").sub(at("Bip01_L_Thigh")), fwd = new THREE.Vector3(0, 1, 0).cross(r).setY(0).normalize();
    this.o.rotation.y = -Math.atan2(fwd.x, fwd.z); this.G.updateMatrixWorld(true);
    const hips = at("Bip01_Pelvis"); this.o.position.x = -hips.x; this.o.position.z = -hips.z;
  }
  show(on) { this.visible = on; this.G.visible = on; }
  placeAt(spot) { this.G.position.set(spot.x, 0, spot.z); this.G.rotation.y = spot.face; }
  walk(path, then) { this.path = path; this.leg = 1; this.then = then; this.setPose("walk"); this.show(true); this.G.position.set(path[0][0], 0, path[0][1]); }
  tick(dt) {
    this.mixer?.update(dt);
    if (!this.path) return;
    let step = 1.25 * dt;
    while (step > 0 && this.path) {
      const [tx, tz] = this.path[this.leg], p = this.G.position, dx = tx - p.x, dz = tz - p.z, d = Math.hypot(dx, dz);
      const want = Math.atan2(dx, dz); let diff = want - this.G.rotation.y; diff = Math.atan2(Math.sin(diff), Math.cos(diff)); this.G.rotation.y += diff * Math.min(1, dt * 8);
      if (d <= step) { p.set(tx, 0, tz); step -= d; this.leg += 1; if (this.leg >= this.path.length) { const then = this.then; this.path = null; then?.(); } }
      else { p.x += (dx / d) * step; p.z += (dz / d) * step; step = 0; }
    }
  }
}

// ---- the world: built once, kept while the console is open ---------------------------------------------------------
let W = null;
function makeWorld() {
  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.9;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#cfd6d2");
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.32;
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0.1, 200);
  W = { renderer, scene, camera, people: new Map(), npcs: [], clock: new THREE.Clock(), zoom: 1, zoomTo: 1, T: new THREE.Vector3(11, 0, 8), Tto: new THREE.Vector3(11, 0, 8), places: new Map() };
  W.R = buildWorld(scene);
  camera.position.copy(W.T).add(OFF); camera.lookAt(W.T); camera.updateMatrixWorld();
  W.RIGHT = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
  W.UP = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
  // HR and Finance: two people who aren't agents, at their desks
  W.npcs = [
    { role: "hr", avatar: "Female_Adult_05", g: "f", seat: { x: 1.02, z: 13.7, face: Math.PI / 2 }, names: ["Hana", "Salma", "Dina"] },
    { role: "finance", avatar: "Male_Adult_02", g: "m", seat: { x: 11.2, z: 13.98, face: 0 }, names: ["Karim", "Hesham", "Tarek"] },
  ];
  for (const n of W.npcs) { const p = new Person(`npc-${n.role}`, n.avatar, n.g); p.placeAt(n.seat); p.show(true); p.setPose(n.role === "hr" ? "idle" : "think"); n.p = p; }
}
const OFF = new THREE.Vector3(20, 17, 20), VIEW = 10.8;
function viewSize() { const el = W.renderer.domElement.parentElement; return [el?.clientWidth || innerWidth, el?.clientHeight || innerHeight]; }
const wpp = (z) => { const [w, h] = viewSize(); return (2 * VIEW * (w / h) / z) / w; };
function panPx(dx, dy, z = W.zoomTo) { W.Tto.addScaledVector(W.RIGHT, -dx * wpp(z)).addScaledVector(W.UP, dy * wpp(z)); }
function fit(instant) {
  const [w, h] = viewSize(), phone = w < 720;
  W.Tto.set(phone ? 11 : 11.2, 0, phone ? 6.5 : 7.8);
  W.zoomTo = phone ? 1.5 : Math.min(1.25, Math.max(0.7, (w / h) / 1.6));
  if (chatOpen()) panPx(-Math.min(440, w) / 2, 0);
  if (instant) { W.T.copy(W.Tto); W.zoom = W.zoomTo; }
}

// ---- the page --------------------------------------------------------------------------------------------------------
let H = null;
export function setupOffice(hive) { H = hive; }
let finance = { today: 0, month: 0, at: 0 };
export async function OfficePage() {
  const [tasks, reviews] = await Promise.all([H.api("/api/tasks"), H.api("/api/reviews").catch(() => H.state.reviews || [])]);
  H.state.tasks = tasks; H.state.reviews = reviews;
  return `<div class="o3" id="o3">
    <div class="o3-stage" id="o3-stage"></div>
    <div class="o3-labels" id="o3-labels"></div>
    <div class="o3-loading" id="o3-loading">Setting up the office…</div>
    <div class="o3-tl"><button class="o3-chip o3-icon" id="o3-menu" title="Show the menu" aria-label="Show the menu">☰</button>
      <a class="o3-chip" href="#/" title="Home"><img src="/assets/hive-logo.svg" alt="" width="18" height="18"><b>Hive</b><span class="muted">· Office</span></a></div>
    <div class="o3-tr"><span class="o3-chip" id="o3-summary"></span></div>
    <div class="o3-br" role="group" aria-label="Zoom"><button class="o3-chip o3-icon" data-o3-zoom="out" aria-label="Zoom out">−</button><button class="o3-chip" data-o3-zoom="fit">Fit</button><button class="o3-chip o3-icon" data-o3-zoom="in" aria-label="Zoom in">+</button></div>
    <div class="o3-tip" id="o3-tip" hidden></div>
    <div class="o3-hire" id="o3-hire" hidden><b>Hire</b><p>Who should join the team?</p>
      <button class="btn small" data-o3-hire="techlead">Tech Lead</button><button class="btn small" data-o3-hire="dev">Dev</button><button class="btn small" data-o3-hire="reviewer">Reviewer</button></div>
    <div class="o3-hire o3-fin" id="o3-fin" hidden></div>
    <aside class="o3-chat" id="o3-chat" hidden><header><span id="o3-chat-who"></span><a class="btn small" id="o3-chat-full" href="#/">Open full page</a><button class="o3-x" id="o3-chat-close" aria-label="Close the chat">✕</button></header>
      <iframe id="o3-chat-frame" title="Chat"></iframe></aside>
  </div>`;
}
const chatOpen = () => !document.getElementById("o3-chat")?.hidden;

export function mountOffice() {
  const stage = document.getElementById("o3-stage");
  if (!stage) return;
  document.body.classList.add("office-full");
  try { document.body.classList.toggle("office-rail", localStorage.getItem("officeRail") === "1"); } catch { /* menu hidden */ }
  try { if (!W) makeWorld(); } catch (e) { document.getElementById("o3-loading").textContent = "This browser can't show the 3D office (WebGL is off)."; console.error(e); return; }
  stage.appendChild(W.renderer.domElement);
  W.places = new Map();
  labels.clear();
  resize(); fit(true);
  refresh();
  loadFinance();
  Promise.all([...W.people.values(), ...W.npcs.map((n) => n.p)].map((p) => p.ready)).finally(() => document.getElementById("o3-loading")?.remove());
  setTimeout(() => document.getElementById("o3-loading")?.remove(), 15000);
  wire(stage);
  cancelAnimationFrame(W.raf);
  W.clock.getDelta();
  W.raf = requestAnimationFrame(frame);
}
export function unmountOffice() { document.body.classList.remove("office-full", "office-rail"); }

function resize() {
  const [w, h] = viewSize();
  W.renderer.setSize(w, h, false);
  W.renderer.domElement.style.width = "100%"; W.renderer.domElement.style.height = "100%";
  const a = w / h; Object.assign(W.camera, { left: -VIEW * a, right: VIEW * a, top: VIEW, bottom: -VIEW }); W.camera.updateProjectionMatrix();
}

let lastMinute = -1;
function frame() {
  if (!W.renderer.domElement.isConnected) { unmountOffice(); return; }
  W.raf = requestAnimationFrame(frame);
  const dt = Math.min(0.05, W.clock.getDelta()), t = W.clock.elapsedTime;
  W.zoom += (W.zoomTo - W.zoom) * Math.min(1, dt * 9); W.T.lerp(W.Tto, Math.min(1, dt * 9));
  W.camera.zoom = W.zoom; W.camera.updateProjectionMatrix(); W.camera.position.copy(W.T).add(OFF);
  for (const p of W.people.values()) p.tick(dt);
  for (const n of W.npcs) n.p.tick(dt);
  const R = W.R;
  R.bees.forEach((b) => { const a = t * 1.3 + b.userData.p; b.position.set(16.1 + Math.cos(a) * 0.45, 2.1 + Math.sin(a * 1.7) * 0.2, 0.55 + Math.sin(a) * 0.35); });
  const playing = [...W.people.values()].some((p) => p.pose === "games" && p.spot?.kind === "pingpong");
  R.ball.visible = playing;
  if (playing) R.ball.position.set(19.4 + Math.sin(t * 2.2) * 1.1, 0.95 + Math.abs(Math.sin(t * 4.4)) * 0.28, 4.7 + Math.sin(t * 1.3) * 0.25);
  const m = new Date().getMinutes(); if (m !== lastMinute) { lastMinute = m; light(); }
  W.renderer.render(W.scene, W.camera);
  placeLabels();
}

// ---- light: day, dusk, night from the local time ------------------------------------------------------------------
function light() {
  const now = new Date(), h = now.getHours() + now.getMinutes() / 60;
  const phase = h >= 20 || h < 6 ? "night" : h < 8 || h >= 17 ? "dusk" : "day";
  const R = W.R;
  const set = { day: [2.0, "#ffe9c7", 0.45, 0.32, 0.5, "#bfe1f1", 0.9], dusk: [1.1, "#ffb987", 0.35, 0.25, 0.35, "#f3c79c", 0.7], night: [0, "#ffffff", 0.22, 0.16, 0.12, "#1f2c48", 0.25] }[phase];
  R.sun.intensity = set[0]; R.sun.color.set(set[1]); R.hemi.intensity = set[2]; W.scene.environmentIntensity = set[3]; R.fill.intensity = set[4];
  R.windowGlass.color.set(set[5]); R.windowGlass.emissive.set(set[5]); R.windowGlass.emissiveIntensity = set[6];
  W.scene.background.set(phase === "night" ? "#9aa3a6" : "#cfd6d2");
  W.night = phase !== "day";
  const [hr, mi] = [now.getHours() % 12, now.getMinutes()];
  R.clockHands.hour.rotation.z = -((hr + mi / 60) / 12) * Math.PI * 2; R.clockHands.minute.rotation.z = -(mi / 60) * Math.PI * 2;
  refreshDesks();
}

// ---- who is where, from the console's state ------------------------------------------------------------------------
function bubbleOf(id) {
  const a = H.state.agents[id] || {};
  if (a.pending?.length) return { text: `Approve ${a.pending[0].tool}`, cta: "Open", count: a.pending.length };
  const w = a.status === "idle" && a.waiting_for_lead;
  if (w) {
    const q = H.parseQuestions(w.text || ""), n = q?.questions?.length || 0;
    return { text: n ? `${n} question${n > 1 ? "s" : ""}${w.task ? ` · ${w.task}` : ""}` : `Waiting for you${w.task ? ` · ${w.task}` : ""}`, cta: "Answer", count: n || 1 };
  }
  if (H.roleOf(id) === "coach" && H.state.improvements) { const n = H.state.improvements; return { text: `${n} proposal${n > 1 ? "s" : ""}`, cta: "Review", count: n, href: "#/improvements" }; }
  const blocked = (H.state.tasks || []).find((t) => t.status === "blocked" && (t.blocked_by || t.assignee) === id);
  if (blocked) return { text: `Blocked · ${blocked.id}`, cta: "Answer", count: 1 };
  return null;
}
const TEAM_ORDER = { techlead: 0, reviewer: 1, dev: 2 };
function assignSeats(ids) {
  const R = W.R, out = new Map();
  const team = ids.filter((id) => !["orchestrator", "coach"].includes(H.roleOf(id)))
    .sort((a, b) => (TEAM_ORDER[H.roleOf(a)] ?? 9) - (TEAM_ORDER[H.roleOf(b)] ?? 9) || a.localeCompare(b, undefined, { numeric: true }));
  if (team.length > 9) R.moreSeats();
  const free = [...R.seats];
  const take = (pred) => { const i = free.findIndex(pred); return i < 0 ? null : free.splice(i, 1)[0]; };
  for (const id of team) {
    const role = H.roleOf(id);
    const s = role === "dev" ? (take((s) => s.kind === "table") || take(() => true)) : (take((s) => s.kind === "window") || take(() => true));
    if (s) out.set(id, s);
  }
  for (const id of ids) {
    if (H.roleOf(id) === "orchestrator") out.set(id, R.orchSeat);
    else if (H.roleOf(id) === "coach") out.set(id, out.size && [...out.values()].includes(R.coachSeat) ? take(() => true) : R.coachSeat);
  }
  W.free = free;
  return out;
}
function whereabouts(ids) {
  const out = new Map(), taken = { coffee: 0, sofa: 0, games: 0, window: 0 };
  const slot = Math.floor(Date.now() / 1200000);   // idle people change spot every 20 minutes
  for (const id of ids) {
    const a = H.state.agents[id] || {}, role = H.roleOf(id);
    if (!a.status || a.status === "stopped") { out.set(id, { place: "off" }); continue; }
    if (a.status === "starting") { out.set(id, { place: "door", pose: "walk" }); continue; }
    if (a.status === "working") { out.set(id, { place: "desk", pose: role === "dev" ? "work" : "think" }); continue; }
    if (a.status === "waiting" || bubbleOf(id)) { out.set(id, { place: "desk", pose: "wait" }); continue; }
    let idle = ["nap", "phone", "coffee", "sofa", "games", "idle", "coffee", "games"][hashOf(id + slot) % 8];
    if (role === "orchestrator") idle = "idle";
    if (role === "coach") idle = idle === "nap" ? "nap" : "coachWindow";
    const cap = { coffee: 2, sofa: 2, games: 4, window: 2 }[idle];
    if (idle === "coachWindow") out.set(id, { place: "coachWindow:0", pose: "phone" });
    else if (cap !== undefined && taken[idle] < cap) out.set(id, { place: `${idle}:${taken[idle]++}`, pose: idle === "window" ? "phone" : idle });
    else if (idle === "phone" && taken.window < 2) out.set(id, { place: `window:${taken.window++}`, pose: "phone" });
    else out.set(id, { place: "desk", pose: idle === "nap" ? "nap" : "idle" });
  }
  return out;
}
function spotOf(id, place) {
  if (place === "desk") return W.seatOf.get(id);
  const [k, i] = place.split(":"); const s = W.R.SPOTS[k]?.[+i || 0];
  return s && { ...s, kind: k === "games" ? (+i >= 2 ? "pingpong" : "foosball") : k };
}
function avatarFor(id, used) {
  const g = genderOf(H.personOf(id)), pool = POOL[g];
  const start = hashOf(id) % pool.length;
  for (let k = 0; k < pool.length; k++) { const a = pool[(start + k) % pool.length]; if (!used.has(a)) { used.add(a); return [a, g]; } }
  return [pool[start], g];
}

export function officeRefresh() { if (W?.renderer.domElement.isConnected) refresh(); }
function refresh() {
  const ids = H.agentIds();
  W.seatOf = assignSeats(ids);
  const where = whereabouts(ids);
  const used = new Set([...W.people.values()].filter((p) => ids.includes(p.id)).map((p) => p.avatar));
  for (const id of ids) {
    const w = where.get(id);
    let p = W.people.get(id);
    if (!p && w.place !== "off") { const [a, g] = avatarFor(id, used); p = new Person(id, a, g); W.people.set(id, p); }
    if (!p) continue;
    const before = W.places.get(id), target = w.place === "door" ? { ...W.R.SPOTS.door[0] } : w.place === "off" ? null : spotOf(id, w.place);
    if (before === undefined) {   // first look at the office: everyone is already where they are
      if (target) { p.placeAt(target); p.spot = target; p.setPose(w.pose); p.show(true); } else p.show(false);
    } else if (before !== w.place || (target && p.spot && (target.x !== p.spot.x || target.z !== p.spot.z))) {
      const from = p.path ? { x: p.G.position.x, z: p.G.position.z } : before === "off" ? W.R.SPOTS.door[0] : p.spot || W.R.SPOTS.door[0];
      const to = target || W.R.SPOTS.door[0];
      p.ready.then(() => p.walk(route(from, to), () => { if (target) { p.placeAt(target); p.spot = target; p.setPose(w.pose === "walk" ? "idle" : w.pose); } else { p.show(false); p.spot = null; } refreshDesks(); }));
    } else if (!p.path) { p.setPose(w.pose); }
    W.places.set(id, w.place);
  }
  for (const [id, p] of W.people) if (!ids.includes(id)) { p.show(false); W.people.delete(id); }
  W.where = where;
  refreshDesks();
  drawLabels();
}
// Screens, lamps and chairs follow who is sitting where.
const SCREEN = (id, w) => (!w || w.place !== "desk" ? "off" : H.state.agents[id]?.status === "working" ? (H.roleOf(id) === "dev" ? "code" : "doc") : w.pose === "wait" ? "doc" : "off");
function refreshDesks() {
  if (!W?.seatOf) return;
  const all = [...W.R.seats, W.R.coachSeat, W.R.orchSeat];
  const byseat = new Map([...W.seatOf].map(([id, s]) => [s, id]));
  for (const s of all) {
    const id = byseat.get(s), p = id && W.people.get(id), w = id && W.where?.get(id);
    const here = !!(p && !p.path && w?.place === "desk" && p.visible);
    W.R.setScreen(s.screen, here ? SCREEN(id, w) : "off");
    if (s.chair) { const c = here ? s.chairIn : s.chairOut; if (s.world) { s.chair.position.z = c.z; } else s.chair.position.z = c.z; s.chair.rotation.y = c.r; }
    if (s.lamp) { const on = here && W.night; s.lamp.light.intensity = on ? 3 : 0; s.lamp.bulb.visible = on; }
  }
}

// ---- name tags, bubbles, the hire and finance desks -------------------------------------------------------------------
const labels = new Map();
const DOT = { attention: "#d04a6a", working: "#3fa06a", away: "#d9a441", idle: "#9aa39e", off: "#c3c9c6" };
const roleWords = (id) => (H.roleOf(id) === "orchestrator" ? "Orchestrator" : H.OWNER_LABEL[H.roleOf(id)] || H.roleOf(id));
function statusOf(id) {
  const a = H.state.agents[id] || {}, w = W.where?.get(id) || {}, t = H.busyWith(id);
  if (w.place === "off") return [`${roleWords(id)} · not started`, "off"];
  if (w.place === "door") return [`${roleWords(id)} · coming in`, "working"];
  if (bubbleOf(id) || a.status === "waiting") return [`${roleWords(id)} · waiting for you`, "attention"];
  if (a.status === "working") { const mins = H.state.since[id] ? Math.max(1, Math.round((Date.now() - H.state.since[id]) / 60000)) : 0; return [`${roleWords(id)} · ${t ? t.id : "working"}${mins ? ` · ${mins} min` : ""}`, "working"]; }
  const away = { coffee: "coffee break", sofa: "on the sofa", games: "playing", phone: "on the phone", nap: "taking a break" }[w.pose];
  if (away) return [`${roleWords(id)} · ${away}`, ["coffee", "sofa", "games"].includes(w.pose) ? "away" : "idle"];
  return [`${roleWords(id)} · ${t ? t.id : "nothing to do"}`, "idle"];
}
function drawLabels() {
  const host = document.getElementById("o3-labels");
  if (!host) return;
  const ids = new Set(H.agentIds());
  for (const [k, l] of labels) if (!ids.has(k) && !k.startsWith("npc") && k !== "you") { l.el.remove(); l.pill?.remove(); labels.delete(k); }
  const ensure = (k) => { let l = labels.get(k); if (!l) { l = { el: document.createElement("button") }; l.el.className = "o3-tag"; l.el.type = "button"; host.appendChild(l.el); labels.set(k, l); } return l; };
  const pillOf = (l, html, cls = "") => { if (!html) { l.pill?.remove(); l.pill = null; return; } if (!l.pill) { l.pill = document.createElement("button"); l.pill.type = "button"; host.appendChild(l.pill); } l.pill.className = `o3-pill ${cls}`; l.pill.innerHTML = html; };
  for (const id of ids) {
    const l = ensure(id), [words, dot] = statusOf(id);
    l.el.innerHTML = `<b><i style="background:${DOT[dot]}"></i>${H.esc(H.personOf(id))}</b><small>${H.esc(words)}</small>`;
    l.el.dataset.agent = id; l.el.classList.toggle("off", dot === "off");
    const b = bubbleOf(id);
    pillOf(l, b && `<span class="n">${b.count}</span>${H.esc(b.text)}<span class="cta">${b.cta} →</span>`);
    if (l.pill) { l.pill.dataset.agent = id; if (b.href) l.pill.dataset.href = b.href; else delete l.pill.dataset.href; }
    l.anchor = () => { const p = W.people.get(id); if (p?.head && p.visible) return p.head.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, 0.36, 0));
      const s = W.seatOf.get(id); return s ? new THREE.Vector3(s.x, 1.3, s.z) : null; };
  }
  const taken = new Set([...ids].map((id) => H.personOf(id).toLowerCase()));
  for (const n of W.npcs) {
    n.name = n.names.find((x) => !taken.has(x.toLowerCase())) || n.names[0];
    const l = ensure(`npc-${n.role}`);
    l.el.innerHTML = `<b><i style="background:${DOT.working}"></i>${n.name}</b><small>${n.role === "hr" ? "HR · click to hire" : "Finance · click for spending"}</small>`;
    l.el.dataset.npc = n.role;
    pillOf(l, null);
    l.anchor = () => n.p.head ? n.p.head.getWorldPosition(new THREE.Vector3()).add(new THREE.Vector3(0, 0.36, 0)) : new THREE.Vector3(n.seat.x, 1.3, n.seat.z);
  }
  // your desk
  const reviews = H.state.reviews || [], toReview = reviews.filter((r) => r.needs_you).length, prs = reviews.filter((r) => r.pr && !r.merged).length;
  const you = ensure("you");
  you.el.innerHTML = `<b>Your desk</b><small>${toReview} review${toReview === 1 ? "" : "s"} · ${prs} pull request${prs === 1 ? "" : "s"}</small>`;
  you.el.dataset.href = "#/reviews"; you.anchor = () => new THREE.Vector3(19.8, 1.6, 13.9);
  // the summary at the top
  const inOffice = [...ids].filter((id) => W.where?.get(id)?.place !== "off").length, needYou = [...ids].filter((id) => bubbleOf(id)).length;
  const sum = document.getElementById("o3-summary");
  if (sum) sum.innerHTML = `${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · ${inOffice} of ${ids.size} in${needYou ? ` · <b class="attn">${needYou} need${needYou === 1 ? "s" : ""} you</b>` : ""}`;
  // the board on the wall
  const tasks = H.state.tasks || [];
  W.R.drawBoard([["SPEC", ["draft"]], ["DEV", ["ready-for-dev", "in-dev", "changes-requested"]], ["REVIEW", ["ready-for-review", "in-review"]], ["DONE", ["done"]]]
    .map(([n, sts]) => [n, tasks.filter((t) => sts.includes(t.status)).length]));
}
const usd = (x) => `$${(x || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
async function loadFinance() {
  if (Date.now() - finance.at < 120000) return;
  try {
    const { lines } = await H.api("/api/finance");
    const d = new Date(), day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    finance = { at: Date.now(), today: lines.filter((l) => l.ts.startsWith(day)).reduce((a, l) => a + (l.cost_usd || 0), 0), month: lines.filter((l) => l.ts.startsWith(day.slice(0, 7))).reduce((a, l) => a + (l.cost_usd || 0), 0) };
    drawLabels();
  } catch { /* the bubble just shows $0 */ }
}
const v3 = new THREE.Vector3();
function placeLabels() {
  const [w, h] = viewSize();
  document.getElementById("o3")?.classList.toggle("far", W.zoom < 1.5);
  for (const l of labels.values()) {
    const p = l.anchor?.(); if (!p) { l.el.hidden = true; continue; }
    v3.copy(p).project(W.camera);
    const x = (v3.x + 1) / 2 * w, y = (1 - v3.y) / 2 * h, out = x < -100 || x > w + 100 || y < -60 || y > h + 60;
    l.el.hidden = out; l.el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
    if (l.pill) { l.pill.hidden = out; l.pill.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`; }
    l.x = x; l.y = y;
  }
}

// ---- input: zoom, pan, click someone to chat, hover for what they're on ----------------------------------------------
function wire(stage) {
  const root = document.getElementById("o3");
  const tip = document.getElementById("o3-tip"), hire = document.getElementById("o3-hire");
  new ResizeObserver(() => { resize(); }).observe(stage);
  const zoomAt = (f, cx, cy) => {
    const r = stage.getBoundingClientRect(), z0 = W.zoomTo, z1 = Math.min(5, Math.max(0.45, z0 * f));
    const dx = cx === undefined ? 0 : cx - r.left - r.width / 2, dy = cy === undefined ? 0 : cy - r.top - r.height / 2;
    W.Tto.addScaledVector(W.RIGHT, dx * (wpp(z0) - wpp(z1))).addScaledVector(W.UP, -dy * (wpp(z0) - wpp(z1)));
    W.zoomTo = z1;
  };
  root.addEventListener("wheel", (e) => { if (e.target.closest(".o3-chat")) return; e.preventDefault(); zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.0015)), e.clientX, e.clientY); }, { passive: false });
  root.querySelector(".o3-br").addEventListener("click", (e) => { const z = e.target.closest("[data-o3-zoom]")?.dataset.o3Zoom; if (z === "fit") fit(); else if (z) zoomAt(z === "in" ? 1.35 : 1 / 1.35); });
  const pts = new Map(); let drag = null, pinch = null;
  stage.addEventListener("pointerdown", (e) => { pts.set(e.pointerId, [e.clientX, e.clientY]); stage.setPointerCapture(e.pointerId);
    if (pts.size === 1) drag = { x: e.clientX, y: e.clientY, moved: false };
    if (pts.size === 2) { const [a, b] = [...pts.values()]; pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) }; drag = null; } });
  stage.addEventListener("pointermove", (e) => {
    if (pts.has(e.pointerId)) pts.set(e.pointerId, [e.clientX, e.clientY]);
    if (pinch && pts.size === 2) { const [a, b] = [...pts.values()], d = Math.hypot(a[0] - b[0], a[1] - b[1]); zoomAt(d / pinch.d, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2); pinch.d = d; return; }
    if (drag) { const dx = e.clientX - drag.x, dy = e.clientY - drag.y; if (!drag.moved && Math.hypot(dx, dy) > 4) { drag.moved = true; stage.classList.add("dragging"); tip.hidden = true; }
      if (drag.moved) { panPx(dx, dy); W.T.copy(W.Tto); drag.x = e.clientX; drag.y = e.clientY; } return; }
    hover(e);
  });
  const up = (e) => { pts.delete(e.pointerId); if (pts.size < 2) pinch = null; if (!pts.size) { stage.classList.remove("dragging"); setTimeout(() => { drag = null; }, 0); } };
  stage.addEventListener("pointerup", up); stage.addEventListener("pointercancel", up);
  stage.addEventListener("pointerleave", () => { tip.hidden = true; });
  stage.addEventListener("click", (e) => { if (drag?.moved) return; hire.hidden = true; document.getElementById("o3-fin").hidden = true; const id = nearest(e); if (id) act(id, e); });
  stage.addEventListener("dblclick", () => fit());
  root.addEventListener("click", (e) => {
    const role = e.target.closest("[data-o3-hire]")?.dataset.o3Hire;
    if (role) { hire.hidden = true; H.actions["add-agent"]({ dataset: { role } }); return; }
    const t = e.target.closest(".o3-tag, .o3-pill");
    if (!t) return;
    if (t.dataset.href) { location.hash = t.dataset.href; return; }
    if (t.dataset.npc) { act(`npc-${t.dataset.npc}`, e); return; }
    if (t.dataset.agent) openChat(t.dataset.agent);
  });
  document.getElementById("o3-menu").addEventListener("click", (e) => {
    if (innerWidth <= 720) { e.stopPropagation(); H.openRail(); return; }   // (the console closes the menu on clicks that reach it)   // a phone: the menu slides in, as everywhere
    const on = document.body.classList.toggle("office-rail");
    try { localStorage.setItem("officeRail", on ? "1" : ""); } catch { /* this visit only */ }
  });
  document.getElementById("o3-chat-close").addEventListener("click", closeChat);
  addEventListener("keydown", function esc(e) { if (!root.isConnected) { removeEventListener("keydown", esc); return; } if (e.key === "Escape") { if (chatOpen()) closeChat(); hire.hidden = true; document.getElementById("o3-fin").hidden = true; } });
}
// The person closest to where you clicked or hovered (their name tag or their body on screen).
function nearest(e) {
  const r = document.getElementById("o3-stage").getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  let best = null, bd = 70;
  for (const [k, l] of labels) {
    if (k.startsWith("room") || k === "you" || l.el.hidden) continue;
    const d = Math.hypot(l.x - x, Math.max(0, y - l.y - 90) + Math.max(0, l.y - y - 10));
    if (d < bd) { bd = d; best = k; }
  }
  return best;
}
function act(k, e) {
  if (k === "npc-finance") { const fin = document.getElementById("o3-fin"), r = document.getElementById("o3").getBoundingClientRect();
    document.getElementById("o3-hire").hidden = true;
    fin.innerHTML = `<b>Spending</b><div class="o3-fin-row"><span>Today</span><b>${usd(finance.today)}</b></div><div class="o3-fin-row"><span>This month</span><b>${usd(finance.month)}</b></div><a class="btn small" href="#/finance">Open Finance</a>`;
    fin.hidden = false; loadFinance();
    fin.style.left = `${Math.min(e.clientX - r.left, r.width - fin.offsetWidth - 12)}px`; fin.style.top = `${Math.min(e.clientY - r.top + 12, r.height - fin.offsetHeight - 12)}px`; return; }
  if (k === "npc-hr") { const hire = document.getElementById("o3-hire"), r = document.getElementById("o3").getBoundingClientRect(); hire.hidden = false; document.getElementById("o3-fin").hidden = true;
    hire.style.left = `${Math.min(e.clientX - r.left, r.width - hire.offsetWidth - 12)}px`; hire.style.top = `${Math.min(e.clientY - r.top + 12, r.height - hire.offsetHeight - 12)}px`; return; }
  openChat(k);
}
function hover(e) {
  const tip = document.getElementById("o3-tip"), k = nearest(e);
  document.querySelectorAll(".o3-tag.hover").forEach((x) => x.classList.remove("hover"));
  if (!k || k.startsWith("npc")) { tip.hidden = true; document.getElementById("o3-stage").style.cursor = k ? "pointer" : ""; return; }
  labels.get(k)?.el.classList.add("hover");
  document.getElementById("o3-stage").style.cursor = "pointer";
  const a = H.state.agents[k] || {}, t = H.busyWith(k), b = bubbleOf(k);
  tip.innerHTML = `<b>${H.esc(H.nameOf(k))}</b><span class="muted">${H.esc(H.STATUS_TEXT[a.status] || a.status || "Not started")}</span>
    ${t ? `<span>On <b>${H.esc(t.id)}</b> ${H.esc(t.title.length > 60 ? `${t.title.slice(0, 59)}…` : t.title)}</span>` : ""}${b ? `<span class="attn">${H.esc(b.text)}</span>` : ""}
    <span class="muted">${a.status && a.status !== "stopped" ? H.esc(H.doing(k).slice(0, 110)) : "Click to open the chat and start them."}</span>`;
  tip.hidden = false;
  const r = document.getElementById("o3").getBoundingClientRect();
  tip.style.left = `${Math.min(e.clientX - r.left + 16, r.width - tip.offsetWidth - 8)}px`; tip.style.top = `${Math.min(e.clientY - r.top + 16, r.height - tip.offsetHeight - 8)}px`;
}

// ---- the chat panel: the agent's own chat, beside the office ------------------------------------------------------
function openChat(id) {
  const panel = document.getElementById("o3-chat"), was = chatOpen();
  document.getElementById("o3-chat-who").innerHTML = `${H.avatarHtml(id)}<span><b>${H.esc(H.personOf(id))}</b><small>${H.esc(roleWords(id))}</small></span>`;
  document.getElementById("o3-chat-full").href = `#/agents/${id}`;
  const frame = document.getElementById("o3-chat-frame"), src = `/?embed=1#/agents/${encodeURIComponent(id)}`;
  if (panel.dataset.agent !== id) { frame.src = src; panel.dataset.agent = id; }
  panel.hidden = false;
  document.getElementById("o3").classList.add("chatting");
  // keep the person in view, to the right of the panel
  const [w] = viewSize(), p = W.people.get(id), s = W.seatOf.get(id);
  const at = p?.visible ? p.G.position : s ? new THREE.Vector3(s.x, 0, s.z) : null;
  if (at) { v3.copy(at).project(W.camera); const x = (v3.x + 1) / 2 * w, want = w < 720 ? w / 2 : Math.min(440, w * 0.45) + (w - Math.min(440, w * 0.45)) / 2; panPx(want - x, 0); }
  else if (!was) panPx(-Math.min(440, w) / 2, 0);
}
function closeChat() {
  const panel = document.getElementById("o3-chat");
  panel.hidden = true; document.getElementById("o3").classList.remove("chatting");
}
