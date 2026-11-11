// The Office: the team drawn as people in an isometric office, from the same live state as the rest of the console.
// Click someone to chat, click a bubble to act on it. Idle agents nap, scroll their phone, get a coffee or sit on the
// sofa, and walk between their desk and those spots when their status changes.

let H = null;   // the console's state and helpers, handed over by app.js
export function setupOffice(hive) { H = hive; }

// ---- geometry ---------------------------------------------------------------------------------------------------
// World units: x runs along the right wall, y along the left wall, z up. The room grows deeper as the team grows.
const K = 0.76, WALL = 230, W = 1150, M = 34;
let OX = 0, OY = 0, D = 860;
const P = (x, y, z = 0) => [OX + (x - y) * 0.866 * K, OY + ((x + y) * 0.5 - z) * K];
const pts = (a) => a.map(([x, y, z]) => P(x, y, z).map((n) => n.toFixed(1)).join(",")).join(" ");
const poly = (a, fill, extra = "") => `<polygon points="${pts(a)}" fill="${fill}" ${extra}/>`;
function box(x, y, z, w, d, h, top, left, right, extra = "") {
  return `<g ${extra}>${poly([[x, y + d, z], [x + w, y + d, z], [x + w, y + d, z + h], [x, y + d, z + h]], left)}
    ${poly([[x + w, y, z], [x + w, y + d, z], [x + w, y + d, z + h], [x + w, y, z + h]], right)}
    ${poly([[x, y, z + h], [x + w, y, z + h], [x + w, y + d, z + h], [x, y + d, z + h]], top)}</g>`;
}
const at = (x, y, z, inner, extra = "") => { const [sx, sy] = P(x, y, z); return `<g transform="translate(${sx.toFixed(1)},${sy.toFixed(1)}) scale(${K})" ${extra}>${inner}</g>`; };
const FLOOR = () => `matrix(${0.866 * K} ${0.5 * K} ${-0.866 * K} ${0.5 * K} ${OX} ${OY})`;
const LWALL = (u, v) => `matrix(${0.866 * K} ${-0.5 * K} 0 ${K} ${OX + K * (-0.866 * D + 0.866 * u)} ${OY + K * (0.5 * D - 0.5 * u - v)})`;
const RWALL = (u, v) => `matrix(${0.866 * K} ${0.5 * K} 0 ${K} ${OX + K * 0.866 * u} ${OY + K * (0.5 * u - v)})`;

function sizeRoom(rows) {
  D = Math.max(860, 220 + (rows - 1) * 260 + 380);
  OX = M + D * 0.866 * K;
  OY = M + WALL * K + 14;
  return { w: (W + D) * 0.866 * K + 2 * M, h: OY + (W + D) * 0.5 * K + M };
}

// ---- small helpers ----------------------------------------------------------------------------------------------
const hash = (s) => { let h = 2166136261; for (const c of String(s)) { h ^= c.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
const pick = (list, s) => list[hash(s) % list.length];
const shade = (hex, f) => { const n = parseInt(hex.slice(1), 16); return "#" + [n >> 16, (n >> 8) & 255, n & 255]
  .map((v) => Math.max(0, Math.min(255, Math.round(v * f))).toString(16).padStart(2, "0")).join(""); };
const clip = (s, n) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

// What each person looks like, steady for a given agent.
const SHIRTS = ["#3f4d73", "#4c6656", "#7a5d40", "#56505e", "#38506a", "#7b4b58", "#5d6b46", "#6a4f3c", "#45606b", "#5a4f6e"];
const HAIRS = ["#1b1410", "#2b1a12", "#4a2c1a", "#141414", "#6b4a2a", "#3a2418", "#8c8c8c"];
const SKINS = ["#e0b896", "#d6a988", "#c99a76", "#a8754f", "#8a5a3c", "#f0caa8"];
const STYLES = ["short", "long", "bun", "short", "long", "bald"];
const MUGS = ["#d16d8a", "#4f9a76", "#f2c14e", "#8a6cc4", "#3b82c4", "#e07b39"];
const looks = (id) => ({ shirt: pick(SHIRTS, id + "s"), hair: pick(HAIRS, id + "h"), skin: pick(SKINS, id + "k"), hairStyle: pick(STYLES, id + "y"), pants: pick(["#2f3a4f", "#3a3a3a", "#4a4036", "#2e3d36"], id + "p") });

// ---- people -----------------------------------------------------------------------------------------------------
function face(skin, hair, style, eyes = "open") {
  const hairSvg = style === "long" ? `<path d="M-8 -1 Q-9 10 -7 15 L-5 3 Q0 -3 5 1 L6 15 Q9 9 8 -1 Q8 -10 0 -10 Q-8 -10 -8 -1Z" fill="${hair}"/>`
    : style === "bun" ? `<path d="M-8 0 Q-8 -10 0 -10 Q8 -10 8 0 Q3 -5 -8 0Z" fill="${hair}"/><ellipse cx="2" cy="-11" rx="4" ry="3.5" fill="${hair}"/>`
    : style === "bald" ? `<path d="M-8 3 Q-8.5 -1 -7 -3 M8 3 Q8.5 -1 7 -3" stroke="${hair}" stroke-width="2.5" fill="none"/>`
    : `<path d="M-8 1 Q-9 -10 0 -10 Q9 -10 8 0 Q2 -5 -6 -3 Q-7 0 -8 1Z" fill="${hair}"/>`;
  const e = eyes === "closed" ? `<path d="M-5 1 h3 M1 0.5 h3" stroke="#3a2a22" stroke-width="1"/>`
    : `<rect x="-5" y="${eyes === "down" ? 1 : 0}" width="2.6" height="1.3" fill="#2a1e18"/><rect x="1" y="${eyes === "down" ? 0.7 : -0.3}" width="2.6" height="1.3" fill="#2a1e18"/>
       <path d="M-4.6 -1.6 h3 M1.2 -2 h3" stroke="${hair}" stroke-width="1"/>`;
  return `<ellipse rx="7.6" ry="8.8" fill="${skin}"/><path d="M2 -8 Q8 -6 7.6 1 Q7 7 2 8.6 Q5 2 2 -8Z" fill="${shade(skin, 0.82)}"/>
    <ellipse cx="7.4" cy="1.5" rx="1.6" ry="2.6" fill="${shade(skin, 0.85)}"/>${e}
    ${eyes === "closed" ? "" : `<path d="M-0.5 2 v3 h1.6" stroke="${shade(skin, 0.7)}" stroke-width=".9" fill="none"/><path d="M-3 6.6 h4" stroke="${shade(skin, 0.62)}" stroke-width="1"/>`}${hairSvg}`;
}
function chair(turned = false) {
  const back = `<path d="M-13 -70 h26 q3 0 3 4 v30 q0 4 -3 4 h-26 q-3 0 -3 -4 v-30 q0 -4 3 -4z" fill="#2f3532" ${turned ? 'transform="rotate(-14) translate(-10,0)"' : ""}/>`;
  return `<g filter="url(#o-sh)">${[[-16, 4], [14, 6], [0, 10], [-12, -4], [12, -5]].map(([x, y]) => `<path d="M0 0 L${x} ${y}" stroke="#222" stroke-width="3"/><circle cx="${x}" cy="${y}" r="2.4" fill="#151715"/>`).join("")}
    <rect x="-2" y="-24" width="4" height="24" fill="#4a4a4a"/>${back}<ellipse cx="0" cy="-26" rx="18" ry="7" fill="#3a413d"/></g>`;
}
function torso(s, top, bottom, wTop = 15, wBot = 12) {
  return `<path d="M${-wTop} ${top + 3} Q${-wTop} ${top} ${-wTop + 4} ${top - 1} H${wTop - 4} Q${wTop} ${top} ${wTop} ${top + 3} L${wBot} ${bottom} H${-wBot}Z" fill="${s}"/>
    <path d="M3 ${top - 1} H${wTop - 4} Q${wTop} ${top} ${wTop} ${top + 3} L${wBot} ${bottom} H5Z" fill="${shade(s, 0.78)}"/><path d="M-3 ${top - 1} L0 ${top + 6} L3 ${top - 1}" fill="none" stroke="${shade(s, 0.6)}" stroke-width="1"/>`;
}
const arm = (s, d) => `<path d="${d}" stroke="${s}" stroke-width="6.5" stroke-linecap="round" fill="none"/>`;
function sitter(o, pose) {
  const s = o.shirt, k = o.skin;
  const arms = pose === "phone"
    ? arm(s, "M-13 -64 Q-18 -50 -12 -40") + `<circle cx="-11" cy="-39" r="3" fill="${k}"/>` + arm(shade(s, 0.8), "M13 -64 Q18 -74 8 -80")
      + `<circle cx="6" cy="-81" r="3.2" fill="${k}"/><rect x="0" y="-95" width="7" height="12" rx="1.5" fill="#151816" transform="rotate(-10 3 -89)"/><rect x="1.2" y="-93.5" width="4.6" height="8" fill="#6fa8d0" transform="rotate(-10 3 -89)"/>`
    : pose === "relax" ? arm(s, "M-13 -64 Q-18 -48 -8 -40") + arm(shade(s, 0.8), "M13 -64 Q18 -48 8 -40") + `<circle cx="-7" cy="-39" r="3" fill="${k}"/><circle cx="7" cy="-39" r="3" fill="${k}"/>`
    : arm(s, "M-13 -64 Q-22 -50 -20 -38") + arm(shade(s, 0.8), "M13 -64 Q6 -48 -2 -38");
  const legs = pose === "relax" ? `<path d="M-6 -32 L-12 -14 L-12 0 M6 -32 L0 -14 L0 0" stroke="${o.pants}" stroke-width="7" stroke-linecap="round" fill="none"/>` : "";
  return `<g filter="url(#o-sh)">${legs}${torso(s, -68, -32)}<rect x="-3.5" y="-74" width="7" height="7" fill="${shade(k, 0.85)}"/>${arms}
    <g transform="translate(-1,-83)">${face(k, o.hair, o.hairStyle, pose === "phone" ? "down" : "open")}</g></g>`;
}
function napper(o) {
  const s = o.shirt;
  return `<g filter="url(#o-sh)">${torso(s, -62, -30)}
    ${arm(s, "M-14 -58 Q-22 -48 -16 -44 L6 -46")}${arm(shade(s, 0.8), "M14 -58 Q20 -50 12 -45 L-8 -46")}
    <g transform="translate(-3,-56) rotate(-75)">${face(o.skin, o.hair, o.hairStyle, "closed")}</g></g>`;
}
function stander(o, cup = false) {
  const s = o.shirt, k = o.skin, p = o.pants;
  const right = cup
    ? arm(shade(s, 0.8), "M12 -82 Q18 -70 9 -66") + `<rect x="3" y="-74" width="9" height="11" rx="1.5" fill="#f2f0ea" stroke="#bdb6a8"/><path d="M12 -71 q4 2 0 5" stroke="#bdb6a8" stroke-width="1.6" fill="none"/>
      <path class="o-steam" d="M6 -78 q2 -4 0 -7 M9 -78 q2 -4 0 -7" stroke="#bbb" stroke-width="1.2" fill="none"/><circle cx="8" cy="-66" r="3" fill="${k}"/>`
    : arm(shade(s, 0.8), "M12 -82 Q17 -66 13 -54") + `<circle cx="13" cy="-52" r="3" fill="${k}"/>`;
  return `<g filter="url(#o-sh)"><ellipse cx="0" cy="0" rx="14" ry="5" fill="#000" opacity=".15"/>
    <g class="o-legs"><path class="o-leg-l" d="M-6 -46 L-6 -2" stroke="${p}" stroke-width="7.5" stroke-linecap="round"/><path class="o-leg-r" d="M6 -46 L6 -2" stroke="${shade(p, 0.75)}" stroke-width="7.5" stroke-linecap="round"/>
    <ellipse cx="-7" cy="0" rx="5" ry="2.8" fill="#1b1d1c"/><ellipse cx="7" cy="0" rx="5" ry="2.8" fill="#1b1d1c"/></g>
    ${torso(s, -86, -44, 13, 11)}<rect x="-3.5" y="-92" width="7" height="7" fill="${shade(k, 0.85)}"/>
    ${arm(s, "M-12 -82 Q-17 -66 -13 -54")}<circle cx="-13" cy="-52" r="3" fill="${k}"/>${right}
    <g transform="translate(-1,-101)">${face(k, o.hair, o.hairStyle)}</g></g>`;
}

// ---- where everyone is --------------------------------------------------------------------------------------------
const TEAM_ORDER = { techlead: 0, dev: 1, reviewer: 2, coach: 3 };
const COFFEE = [[958, 96], [904, 104]];
const sofaSpots = () => [[240, D - 140], [240, D - 92]];
const doorSpot = () => [52, D - 118];
const receptionSeat = () => [105, D - 316];

let desks = [];            // [{id, x, y}], the last one is the free desk to hire into
let prevPlaces = null;     // agent -> place, from the last drawing, to see who moved
const walking = new Map(); // agent -> timer, while they walk across the room

function seatOf(d) { return [d.x + 62, d.y - 14]; }
function deskOf(id) { return desks.find((d) => d.id === id); }

// The work that needs the lead, per agent: shown as a red bubble from their computer.
function bubbleOf(id) {
  const a = H.state.agents[id] || {};
  if (a.pending?.length) return { text: `Approve ${a.pending[0].tool}`, cta: "Open →", count: a.pending.length, href: `#/agents/${id}` };
  const w = a.status === "idle" && a.waiting_for_lead;
  if (w) {
    const q = H.parseQuestions(w.text || "");
    const n = q?.questions?.length || 0;
    return { text: n ? `${n} question${n > 1 ? "s" : ""}${w.task ? ` · ${w.task}` : ""}` : `Waiting for you${w.task ? ` · ${w.task}` : ""}`, cta: "Answer →", count: n || 1, href: `#/agents/${id}` };
  }
  if (H.roleOf(id) === "coach" && H.state.improvements) {
    const n = H.state.improvements;
    return { text: `${n} proposal${n > 1 ? "s" : ""}`, cta: "Review →", count: n, href: "#/improvements" };
  }
  const blocked = (H.state.tasks || []).find((t) => t.status === "blocked" && (t.blocked_by || t.assignee) === id);
  if (blocked) return { text: `Blocked · ${blocked.id}`, cta: "Answer →", count: 1, href: `#/agents/${id}` };
  return null;
}

// Where an agent is and what they're doing: at their desk (working, waiting for you, napping, on the phone),
// at the coffee machine, on the sofa, coming in through the door, or not in today.
function whereabouts(ids) {
  const out = {};
  const taken = { coffee: 0, sofa: 0 };
  const slot = Math.floor(Date.now() / 1200000);   // idle people change spot every 20 minutes
  for (const id of ids) {
    const a = H.state.agents[id] || {};
    const role = H.roleOf(id);
    if (!a.status || a.status === "stopped") { out[id] = { place: "off", pose: "off" }; continue; }
    if (a.status === "starting") { out[id] = { place: "door", pose: "stand" }; continue; }
    if (a.status === "working") { out[id] = { place: "desk", pose: "typing" }; continue; }
    if (a.status === "waiting" || bubbleOf(id)) { out[id] = { place: "desk", pose: "look" }; continue; }
    let idle = pick(["nap", "phone", "coffee", "sofa", "look", "coffee", "sofa"], id + slot);
    if (role === "orchestrator") idle = idle === "nap" ? "nap" : "phone";   // the front desk is never left empty
    if (idle === "coffee" && taken.coffee < COFFEE.length) out[id] = { place: `coffee:${taken.coffee++}`, pose: "cup" };
    else if (idle === "sofa" && taken.sofa < 2) out[id] = { place: `sofa:${taken.sofa++}`, pose: "relax" };
    else out[id] = { place: "desk", pose: ["coffee", "sofa"].includes(idle) ? "phone" : idle };
  }
  return out;
}

function spotXY(id, place) {
  if (place === "desk") return H.roleOf(id) === "orchestrator" ? receptionSeat() : seatOf(deskOf(id) || { x: 0, y: 0 });
  if (place.startsWith("coffee:")) return COFFEE[+place.split(":")[1]];
  if (place.startsWith("sofa:")) return sofaSpots()[+place.split(":")[1]];
  return doorSpot();
}

// ---- the scene ----------------------------------------------------------------------------------------------------
const phase = (h = new Date().getHours()) => (h >= 20 || h < 6 ? "night" : h < 8 || h >= 17 ? "dusk" : "day");
const COLUMNS = [["SPEC", ["draft"]], ["DEV", ["ready-for-dev", "in-dev", "changes-requested"]], ["REVIEW", ["ready-for-review", "in-review"]], ["DONE", ["done"]]];
const NOTE = ["#f7e48d", "#a9d4f5", "#f5b9c8", "#bfe3c7"];

function shell(ph) {
  const out = [];
  out.push(`<g transform="${FLOOR()}"><rect width="${W}" height="${D}" fill="url(#o-planks)"/></g>`);
  out.push(poly([[0, 0, 0], [0, D, 0], [0, D, WALL], [0, 0, WALL]], "#e9e3d6"));
  out.push(poly([[0, 0, 0], [W, 0, 0], [W, 0, WALL], [0, 0, WALL]], "#f2ede3"));
  out.push(poly([[0, 0, 0], [0, D, 0], [0, D, 12], [0, 0, 12]], "#cdbfa8") + poly([[0, 0, 0], [W, 0, 0], [W, 0, 12], [0, 0, 12]], "#d8cbb5"));
  out.push(poly([[-14, -14, WALL], [W, -14, WALL], [W, 0, WALL], [0, 0, WALL], [0, D, WALL], [-14, D, WALL]], "#3a4640"));
  const glass = { day: "#bfe1f1", dusk: "#f3c79c", night: "#22314f" }[ph];
  for (const wx of [120, 520, 880]) {
    out.push(`<g transform="${RWALL(wx, 200)}"><rect width="130" height="110" rx="3" fill="${glass}" stroke="#8fb3c4" stroke-width="5"/>
      ${ph === "night" ? `<g fill="#fff">${[[20, 22], [90, 30], [50, 70], [110, 84], [30, 92], [74, 14]].map(([x, y]) => `<circle cx="${x}" cy="${y}" r="1.3"/>`).join("")}</g><circle cx="100" cy="24" r="9" fill="#f4efd8"/>` : ""}
      <path d="M65 0V110M0 55H130" stroke="#8fb3c4" stroke-width="4"/>${ph === "night" ? "" : `<path d="M14 90 L50 14 M30 96 L70 14" stroke="#fff" stroke-width="6" opacity=".45"/>`}</g>`);
    if (ph !== "night") out.push(`<g transform="${FLOOR()}"><path d="M${wx} 0 H${wx + 130} L${wx + 230} 210 H${wx + 100}Z" fill="url(#o-sun-${ph})"/></g>`);
  }
  out.push(`<g transform="${RWALL(320, 205)}" filter="url(#o-sh)"><rect width="150" height="54" rx="8" fill="#2f3a35"/>
    <path d="M22 15 l12 -7 l12 7 v14 l-12 7 l-12 -7z" fill="#4f9a76"/><path d="M34 22 l6 3.5 v7 l-6 3.5 l-6 -3.5 v-7z" fill="#f2c14e"/>
    <text x="56" y="35" font-size="24" font-weight="700" fill="#f4efe6">Hive</text></g>`);
  const now = new Date();
  out.push(`<g transform="${RWALL(470, 210)}"><circle cx="24" cy="24" r="24" fill="#fbf8f2" stroke="#3a4640" stroke-width="4"/>
    ${Array.from({ length: 12 }, (_, i) => `<path d="M24 5 v4" stroke="#3a4640" stroke-width="2" transform="rotate(${i * 30} 24 24)"/>`).join("")}
    <path d="M24 24 L24 12" stroke="#222" stroke-width="3" stroke-linecap="round" transform="rotate(${(now.getHours() % 12) * 30 + now.getMinutes() / 2} 24 24)"/>
    <path d="M24 24 L24 8" stroke="#222" stroke-width="2" stroke-linecap="round" transform="rotate(${now.getMinutes() * 6} 24 24)"/>
    <title>${now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</title></g>`);
  // the Board, live: a note per task in each column (up to eight), the count on top
  const tasks = H.state.tasks || [];
  const cols = COLUMNS.map(([label, sts], i) => {
    const n = tasks.filter((t) => sts.includes(t.status)).length;
    const x = 8 + i * 47;
    const notes = Array.from({ length: Math.min(n, 8) }, (_, j) => `<rect x="${x + (j % 2) * 21}" y="${24 + Math.floor(j / 2) * 17}" width="18" height="14" fill="${NOTE[i]}" transform="rotate(${(hash(label + j) % 7) - 3} ${x + (j % 2) * 21 + 9} ${31 + Math.floor(j / 2) * 17})"/>`).join("");
    return `<text x="${x}" y="17">${label} ${n}</text>${notes}`;
  }).join("");
  out.push(`<g transform="${LWALL(D - 460, 200)}" filter="url(#o-sh)" class="o-click" data-href="#/tasks"><title>The Board</title><rect width="200" height="96" rx="4" fill="#b8875a"/><rect x="5" y="5" width="190" height="86" fill="#d4a978"/>
    <g font-size="8" font-weight="700" fill="#6b4a2a">${cols}</g></g>`);
  out.push(`<g transform="${LWALL(D - 170, 150)}"><rect width="70" height="150" fill="#e4eef2" stroke="#8a97a0" stroke-width="4"/><circle cx="58" cy="80" r="4" fill="#6c7a82"/>
    <rect x="17" y="26" width="36" height="22" rx="4" fill="#3a4640"/><text x="35" y="42" font-size="12" font-weight="700" text-anchor="middle" fill="#fff">WC</text></g>`);
  out.push(`<g transform="${LWALL(70, 170)}"><rect width="96" height="170" fill="#8a6240" stroke="#5e4029" stroke-width="5"/><rect x="12" y="14" width="72" height="62" fill="#a07650"/><rect x="12" y="90" width="72" height="66" fill="#a07650"/>
    <circle cx="82" cy="94" r="5" fill="#e4c46a"/></g>`);
  out.push(`<g transform="${FLOOR()}"><rect x="10" y="${D - 165}" width="40" height="90" fill="#7b8a80" opacity=".55" rx="4"/><rect x="195" y="${D - 180}" width="170" height="150" rx="12" fill="url(#o-rug)"/></g>`);
  return out.join("");
}

function deskSvg(d, o) {
  const { x: dx, y: dy } = d, w = 130, dd = 70, z = 36;
  let g = "";
  const seat = seatOf(d);
  if (o.screen === "code" || o.screen === "doc") g += at(dx + 65, dy + 20, z, `<ellipse rx="60" ry="26" fill="url(#o-glow-${o.screen})"/>`);
  if (o.person && o.pose !== "nap") g += at(...seat, 0, chair() + sitter(o.person, o.pose));
  else g += at(...seat, 0, chair(!o.person));
  for (const [lx, ly] of [[2, 2], [w - 6, 2], [2, dd - 6], [w - 6, dd - 6]]) g += box(dx + lx, dy + ly, 0, 4, 4, z, "#6d6a64", "#5c5953", "#4d4a45");
  g += box(dx, dy, z, w, dd, 4, "#efe8dc", "#d5c9b5", "#c3b6a0", `filter="url(#o-sh)"`);
  if (o.hire) {
    g += at(dx + 70, dy + 34, z + 4, `<g filter="url(#o-sh)"><path d="M-22 0 L0 12 V-4 L-22 -16Z" fill="#b9a780"/><path d="M22 0 L0 12 V-4 L22 -16Z" fill="#a8966f"/><path d="M-22 -16 L0 -28 L22 -16 L0 -4Z" fill="#d8c8a2"/><path d="M-6 -19 l12 6" stroke="#8a7650" stroke-width="2"/></g>`);
    return g;
  }
  if (o.lamp) g += at(dx + 14, dy + 16, z, `<ellipse cx="6" cy="2" rx="46" ry="22" fill="url(#o-lamp)"/>`);
  g += poly([[dx + 38, dy + 14, z + 4.5], [dx + 88, dy + 14, z + 4.5], [dx + 88, dy + 28, z + 4.5], [dx + 38, dy + 28, z + 4.5]], "#fbfbf8", `stroke="#d6d2c8"`);
  g += at(dx + 98, dy + 20, z + 5, `<ellipse rx="4" ry="3" fill="#fbfbf8" stroke="#cfcac0"/>`);
  if (o.papers) g += poly([[dx + 100, dy + 34, z + 4.6], [dx + 124, dy + 30, z + 4.6], [dx + 126, dy + 56, z + 4.6], [dx + 102, dy + 60, z + 4.6]], "#ffffff", `stroke="#ddd"`);
  if (o.person && o.pose === "nap") g += at(...seat, 0, napper(o.person));
  g += box(dx + 58, dy + 40, z + 4, 14, 10, 3, "#4a504c", "#3b403d", "#333835");
  g += box(dx + 63, dy + 46, z + 6, 4, 4, 12, "#4a504c", "#3b403d", "#333835");
  g += box(dx + 33, dy + 48, z + 18, 64, 5, 36, "#4a504c", "#3a3f3c", "#2e3330");
  g += at(dx + 65, dy + 53, z + 36, `<path d="M-5 -3 l5 -3 l5 3 v6 l-5 3 l-5 -3z" fill="#5d6661"/>`);
  if (o.screen === "code" || o.screen === "doc") g += poly([[dx + 33, dy + 48, z + 54], [dx + 97, dy + 48, z + 54], [dx + 97, dy + 48, z + 56], [dx + 33, dy + 48, z + 56]], o.screen === "code" ? "#8ff0c4" : "#fffbe8", `opacity=".9"`);
  g += at(dx + 12, dy + 12, z + 4, `<ellipse rx="7" ry="3.5" fill="#3a3f3c"/><path d="M0 0 L4 -26 L18 -34" stroke="#3a3f3c" stroke-width="3" fill="none"/><path d="M12 -40 L28 -33 L20 -24 Z" fill="${o.lamp ? "#ffe39a" : "#bcb6aa"}" stroke="#3a3f3c" stroke-width="2"/>`);
  if (o.mug) g += at(dx + 112, dy + 18, z + 4, `<rect x="-6" y="-12" width="12" height="12" fill="${o.mug}"/><ellipse cy="0" rx="6" ry="3" fill="${o.mug}"/><ellipse cy="-12" rx="6" ry="3" fill="#5a3418" stroke="${o.mug}" stroke-width="1.5"/><path d="M6 -9 q6 2 0 7" stroke="${o.mug}" stroke-width="2" fill="none"/>`);
  if (o.plant) g += at(dx + 14, dy + 58, z + 4, `<path d="M-7 0 L-6 -12 H6 L7 0Z" fill="#b8784a"/><circle cx="-5" cy="-18" r="7" fill="#4e8a5c"/><circle cx="5" cy="-20" r="7" fill="#5f9e6b"/><circle cx="0" cy="-27" r="6" fill="#6aae77"/>`);
  if (o.pose === "nap") g += at(...seat, 0, `<g class="o-zz" font-weight="700" fill="#7f8fbf"><text x="70" y="-60" font-size="15">z</text><text x="82" y="-76" font-size="19">z</text><text x="96" y="-96" font-size="24">Z</text></g>`);
  return g;
}

function room() {
  const objs = [];
  const obj = (key, svg) => objs.push({ key, svg });
  // kitchen along the right wall
  obj(900, box(850, 0, 0, 160, 50, 44, "#ece6db", "#d8cfbf", "#c6bba8", `filter="url(#o-sh)"`) + box(850, 0, 44, 160, 50, 4, "#f7f3ec", "#e2dace", "#d2c8b8"));
  obj(910, box(866, 8, 48, 34, 30, 44, "#3a403c", "#2b302d", "#222624") + at(892, 38, 60, `<rect x="-8" y="-10" width="12" height="9" fill="#fff"/><circle cx="-2" cy="-26" r="2.5" fill="#7fd3a8"/>`)
    + at(886, 30, 100, `<path class="o-steam" d="M0 0 q4 -8 0 -16 M7 0 q4 -8 0 -16" stroke="#fff" stroke-width="2" fill="none" opacity=".8"/>`));
  obj(960, at(928, 30, 48, `<rect x="-5" y="-10" width="10" height="10" fill="#f2c14e"/><ellipse cy="-10" rx="5" ry="2.5" fill="#fff"/>`) + at(944, 26, 48, `<rect x="-5" y="-10" width="10" height="10" fill="#4f9a76"/><ellipse cy="-10" rx="5" ry="2.5" fill="#fff"/>`)
    + at(982, 25, 48, `<ellipse rx="16" ry="7" fill="#efe9dc" stroke="#cfc6b6"/><circle cx="-5" cy="-5" r="5" fill="#e0533f"/><circle cx="4" cy="-4" r="5" fill="#f2b33d"/><circle cx="0" cy="-9" r="4.5" fill="#86b84a"/>`));
  obj(1070, box(1032, 8, 0, 30, 30, 66, "#f4f7f8", "#dfe6e9", "#cfd8dc", `filter="url(#o-sh)"`) + at(1047, 23, 66, `<rect x="-11" y="-30" width="22" height="30" rx="5" fill="#9fd3ec" opacity=".9"/><ellipse cy="-30" rx="11" ry="5" fill="#bfe3f3"/><rect x="-5" y="-26" width="5" height="18" fill="#fff" opacity=".45"/>`)
    + at(1047, 38, 34, `<rect x="-8" y="0" width="5" height="5" fill="#3b82c4"/><rect x="3" y="-3" width="5" height="5" fill="#d24a4a"/>`));
  // beehive and plant in the corner
  obj(1250, at(1080, 110, 0, `<ellipse rx="26" ry="10" fill="#000" opacity=".12"/><path d="M-18 0 L-14 -30 H14 L18 0Z" fill="#9a6d43"/>
      <circle cx="-10" cy="-40" r="14" fill="#4e8a5c"/><circle cx="10" cy="-44" r="15" fill="#5f9e6b"/><circle cx="0" cy="-60" r="14" fill="#6aae77"/><circle cx="-16" cy="-58" r="10" fill="#4e8a5c"/>`)
    + at(1100, 50, 150, `<path d="M0 -40 V-10" stroke="#6b4a2a" stroke-width="3"/><ellipse cy="14" rx="26" ry="32" fill="#e8b84b" filter="url(#o-sh)"/>
      <path d="M-24 0 H24 M-25 14 H25 M-22 28 H22" stroke="#c99327" stroke-width="5"/><ellipse cx="0" cy="22" rx="6" ry="4" fill="#5a3e14"/>
      ${[[-40, -6, -20], [36, -20, 20], [30, 50, -10]].map(([x, y, r], i) => `<g class="o-bee o-bee-${i}"><g transform="translate(${x},${y}) rotate(${r})"><ellipse rx="6" ry="4" fill="#f2c94c"/><path d="M-2 -4v8M2 -4v8" stroke="#222" stroke-width="1.6"/><ellipse cx="-1" cy="-6" rx="4" ry="2.5" fill="#fff" opacity=".8"/></g></g>`).join("")}`));
  // bookshelf
  obj(700, box(690, 0, 0, 70, 26, 120, "#7a5537", "#6a4a30", "#5c4029", `filter="url(#o-sh)"`)
    + [10, 46, 82].map((zz, r) => [0, 1, 2, 3, 4].map((i) => box(694 + i * 12, 22, zz, 9, 3, 26 + (i % 2) * 6, "#eee", ["#c0392b", "#38506a", "#f2c14e", "#4f9a76", "#8a6cc4"][(i + r) % 5], "#333")).join("")).join(""));
  // lounge
  obj(205 + D - 170 + 60, box(205, D - 170, 0, 46, 130, 24, "#7e93a4", "#6c7f8f", "#5d6f7e", `filter="url(#o-sh)"`) + box(205, D - 170, 24, 14, 130, 26, "#8aa0b2", "#6c7f8f", "#647789")
    + box(205, D - 170, 24, 46, 12, 12, "#8aa0b2", "#6c7f8f", "#647789") + box(205, D - 52, 24, 46, 12, 12, "#8aa0b2", "#6c7f8f", "#647789")
    + box(222, D - 154, 24, 26, 48, 6, "#9cb2c4", "#7e93a4", "#7489a0") + box(222, D - 102, 24, 26, 48, 6, "#9cb2c4", "#7e93a4", "#7489a0"));
  obj(290 + D - 140 + 70, box(290, D - 140, 0, 56, 74, 22, "#8a6240", "#6e4c31", "#5e4029", `filter="url(#o-sh)"`)
    + poly([[300, D - 125, 22.5], [326, D - 130, 22.5], [330, D - 102, 22.5], [304, D - 98, 22.5]], "#efe6d4") + at(330, D - 82, 22, `<ellipse rx="6" ry="3" fill="#fff"/><ellipse rx="4" ry="2" fill="#6b3f22"/>`));
  return { objs, obj };
}

function yourOffice(obj, labels) {
  const reviews = H.state.reviews || [];
  const toReview = reviews.filter((b) => b.needs_you).length;
  const prs = reviews.filter((b) => b.pr && !b.merged);
  const ready = reviews.filter((b) => b.state === "done" && !b.pr);
  const y0 = D - 210;
  let g = `<g transform="${FLOOR()}"><rect x="880" y="${y0}" width="${W - 880}" height="210" fill="#e3eee9" opacity=".55"/></g>`;
  g += box(960, y0 + 28, 0, 120, 44, 36, "#8a6240", "#6e4c31", "#5e4029", `filter="url(#o-sh)"`);
  g += box(992, y0 + 44, 36, 56, 5, 30, "#4a504c", "#3a3f3c", "#2e3330");
  g += `<g class="o-click" data-href="#/reviews"><title>Reviews waiting for you</title>${box(1052, y0 + 32, 36, 24, 20, 10, "#cfc4ae", "#bcaf96", "#ad9f85")}
    ${toReview ? at(1064, y0 + 42, 50, `<circle r="10" fill="#d04a6a"/><text y="4" font-size="11" text-anchor="middle" fill="#fff" font-weight="700">${toReview}</text>`) : ""}</g>`;
  const notes = [...prs.map((b) => ({ b, top: `PR #${(b.pr.match(/(\d+)\/?$/) || [, ""])[1]}`, sub: "open, merge it" })), ...ready.map((b) => ({ b, top: b.task, sub: "ready for a PR" }))].slice(0, 2);
  notes.forEach((n, i) => {
    g += `<g class="o-click" data-href="#/tasks/${encodeURIComponent(n.b.task)}/pr"><title>${H.esc(n.b.title || n.b.task)}</title>${at(976 + i * 6, y0 + 42 + i * 4, 46 + i * 34, `<g transform="translate(-34,-34)" filter="url(#o-sh)"><rect width="68" height="30" rx="4" fill="#fff"/>
      <text x="34" y="13" font-size="9" text-anchor="middle" fill="#3f7a5f" font-weight="700">${H.esc(n.top)}</text><text x="34" y="24" font-size="8" text-anchor="middle" fill="#6f7c75">${n.sub}</text></g>`)}</g>`;
  });
  g += poly([[880, y0, 0], [W, y0, 0], [W, y0, 90], [880, y0, 90]], "#cfe6dd", `opacity=".35" stroke="#8fb3a4" stroke-width="2"`);
  g += poly([[880, y0, 0], [880, D, 0], [880, D, 90], [880, y0, 90]], "#cfe6dd", `opacity=".35" stroke="#8fb3a4" stroke-width="2"`);
  obj(4000, g);
  const [x, y] = P(880, y0 + 110, 104);
  labels.push(`<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})"><g class="o-ls"><text font-size="12" fill="#4d6a5d" font-weight="700">Your office</text></g></g>`);
  const [tx, ty] = P(1020, D, 0);
  const parts = [`${toReview} review${toReview === 1 ? "" : "s"}`, `${prs.length} pull request${prs.length === 1 ? "" : "s"}`];
  labels.push(tag(tx, ty, `Your tray: ${parts.join(" · ")}`, "#/reviews", 22));
}

// ---- labels -------------------------------------------------------------------------------------------------------
const DOT = { attention: "#d04a6a", working: "#3fa06a", away: "#d9a441", idle: "#9aa39e", off: "#c3c9c6" };
function nameTag(x, y, id, role, dot) {
  const name = H.personOf(id);
  const w = Math.max(name.length * 8 + 16, role.length * 5.6) + 24;
  return `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})" class="o-click o-tag" data-href="#/agents/${id}" data-agent="${id}"><g class="o-ls"><rect x="${-w / 2}" y="-15" width="${w}" height="31" rx="8" fill="#fffdf8" opacity=".95" filter="url(#o-sh)"/>
    <circle cx="${-name.length * 3.6 - 9}" cy="-5" r="4" fill="${dot}"/><text x="4" y="-1" font-size="12" text-anchor="middle" font-weight="700" fill="#22302a">${H.esc(name)}</text>
    <text y="11" font-size="9.5" text-anchor="middle" fill="#6f7c75">${H.esc(role)}</text></g></g>`;
}
function pill(x, y, b) {
  const w = (b.text.length + b.cta.length) * 6.2 + 52;
  return `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})" class="o-click o-pill" data-href="${b.href}"><g class="o-ls"><g transform="translate(${-w / 2},-50)" filter="url(#o-sh)">
    <rect width="${w}" height="26" rx="13" fill="#fff" stroke="#d04a6a" stroke-width="2"/><path d="M${w / 2 - 6} 25 l6 8 l6 -8z" fill="#fff" stroke="#d04a6a" stroke-width="2"/><path d="M${w / 2 - 6} 24 h12" stroke="#fff" stroke-width="3"/>
    <circle cx="14" cy="13" r="9" fill="#d04a6a"/><text x="14" y="17" font-size="11" text-anchor="middle" fill="#fff" font-weight="700">${b.count}</text>
    <text x="29" y="17" font-size="11.5" font-weight="700" fill="#22302a">${H.esc(b.text)}</text><text x="${w - 12}" y="17" font-size="11" text-anchor="end" fill="#3f7a5f" font-weight="700">${b.cta}</text></g></g></g>`;
}
function tag(x, y, text, href = "", dy = 0) {
  const w = text.length * 6.1 + 20;
  return `<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})" ${href ? `class="o-click" data-href="${href}"` : ""}><g class="o-ls"><g transform="translate(${-w / 2},${dy - 11})" filter="url(#o-sh)"><rect width="${w}" height="22" rx="11" fill="#fffdf8"/><text x="10" y="15" font-size="10.5" fill="#6f7c75">${H.esc(text)}</text></g></g></g>`;
}

// ---- drawing --------------------------------------------------------------------------------------------------------
const roleWords = (id) => (H.roleOf(id) === "orchestrator" ? "Orchestrator" : H.OWNER_LABEL[H.roleOf(id)] || H.roleOf(id));
function statusWords(id, w) {
  const a = H.state.agents[id] || {};
  const task = H.busyWith(id);
  if (w.pose === "off") return [`${roleWords(id)} · not started`, "off"];
  if (w.place === "door") return [`${roleWords(id)} · coming in`, "working"];
  if (bubbleOf(id) || a.status === "waiting") return [`${roleWords(id)} · waiting for you`, "attention"];
  if (a.status === "working") {
    const mins = H.state.since[id] ? Math.max(1, Math.round((Date.now() - H.state.since[id]) / 60000)) : 0;
    return [`${roleWords(id)} · working${mins ? ` · ${mins} min` : ""}`, "working"];
  }
  if (w.pose === "cup") return [`${roleWords(id)} · coffee break`, "away"];
  if (w.pose === "relax") return [`${roleWords(id)} · on the sofa`, "away"];
  if (w.pose === "nap") return [`${roleWords(id)} · napping`, "idle"];
  return [`${roleWords(id)} · ${task ? task.id : "nothing to do"}`, "idle"];
}

function scene() {
  const ids = H.agentIds();
  const team = ids.filter((id) => id !== "orchestrator" && H.roleOf(id) !== "orchestrator")
    .sort((a, b) => (TEAM_ORDER[H.roleOf(a)] ?? 9) - (TEAM_ORDER[H.roleOf(b)] ?? 9) || a.localeCompare(b, undefined, { numeric: true }));
  const seats = [...team, "+hire"];
  const size = sizeRoom(Math.ceil(seats.length / 3));
  desks = seats.map((id, i) => ({ id, x: 280 + (i % 3) * 250, y: 220 + Math.floor(i / 3) * 260 }));
  const ph = phase();
  const where = whereabouts(ids);
  const { objs, obj } = room();
  const labels = [], lights = [];

  for (const d of desks) {
    const seat = seatOf(d);
    if (d.id === "+hire") {
      obj(d.x + d.y + 60, `<g class="o-click o-hire" data-hire="1"><g transform="${FLOOR()}"><rect x="${d.x - 22}" y="${d.y - 46}" width="174" height="140" rx="10" fill="#fffdf8" opacity=".25" stroke="#3f7a5f" stroke-width="3" stroke-dasharray="12 9"/></g>${deskSvg(d, { hire: true })}</g>`);
      const [x, y] = P(...seat, 80);
      labels.push(`<g transform="translate(${x.toFixed(1)},${y.toFixed(1)})" class="o-click o-hire" data-hire="1"><g class="o-ls" filter="url(#o-sh)"><rect x="-78" y="-18" width="156" height="40" rx="10" fill="#3f7a5f"/>
        <text y="-1" font-size="13" text-anchor="middle" font-weight="700" fill="#fff">+ Hire</text><text y="13" font-size="9.5" text-anchor="middle" fill="#d8eee3">Tech Lead · Dev · Reviewer</text></g></g>`);
      continue;
    }
    const id = d.id, w = where[id], a = H.state.agents[id] || {};
    const here = w.place === "desk" && !walking.has(id);
    const working = here && a.status === "working";
    const screen = !here ? "off" : working ? (H.roleOf(id) === "dev" ? "code" : "doc") : w.pose === "look" ? "doc" : "off";
    const lamp = here && (working || ph !== "day");
    obj(d.x + d.y + 60, `<g class="o-click o-station" data-href="#/agents/${id}" data-agent="${id}">${deskSvg(d, {
      person: here ? looks(id) : null, pose: here ? w.pose : "", screen, lamp,
      mug: hash(id + "m") % 4 ? pick(MUGS, id) : "", plant: hash(id + "p") % 3 === 0, papers: hash(id + "q") % 2 === 0 })}</g>`);
    if (ph !== "day" && here) lights.push(at(d.x + 30, d.y + 20, 36, `<ellipse rx="90" ry="44" fill="url(#o-night-lamp)"/>`));
  }

  // the front desk: the Orchestrator, by the door
  const orch = ids.find((id) => H.roleOf(id) === "orchestrator");
  {
    const [sx, sy] = receptionSeat(), y = D - 290;
    const w = orch ? where[orch] : { place: "off", pose: "off" };
    const here = orch && w.place === "desk" && !walking.has(orch);
    let g = at(sx, sy, 0, chair(!here) + (here ? (w.pose === "nap" ? napper(looks(orch)) : sitter(looks(orch), w.pose === "typing" ? "typing" : w.pose)) : ""));
    g += box(40, y, 0, 130, 40, 48, "#8a6240", "#6e4c31", "#5e4029", `filter="url(#o-sh)"`);
    g += box(40, y, 48, 130, 40, 3, "#efe8dc", "#d5c9b5", "#c3b6a0");
    g += box(70, y + 12, 51, 56, 5, 30, "#4a504c", "#3a3f3c", "#2e3330");
    g += at(150, y + 20, 51, `<rect x="-6" y="-12" width="12" height="12" fill="#3f7a5f"/><ellipse rx="6" ry="3" fill="#3f7a5f"/><ellipse cy="-12" rx="6" ry="3" fill="#5a3418" stroke="#3f7a5f" stroke-width="1.5"/>`);
    g += at(54, y + 10, 51, `<path d="M-6 0 L-5 -10 H5 L6 0Z" fill="#b8784a"/><circle cx="-4" cy="-15" r="6" fill="#4e8a5c"/><circle cx="4" cy="-17" r="6" fill="#5f9e6b"/>`);
    obj(y + 100, orch ? `<g class="o-click o-station" data-href="#/agents/${orch}" data-agent="${orch}">${g}</g>` : g);
    if (here && ph !== "day") lights.push(at(100, y + 10, 48, `<ellipse rx="80" ry="40" fill="url(#o-night-lamp)"/>`));
  }

  // people away from their desk: at the coffee machine, on the sofa, at the door
  for (const id of ids) {
    const w = where[id];
    if (walking.has(id) || w.place === "desk" || w.place === "off") continue;
    const [x, y] = spotXY(id, w.place);
    const sprite = w.place.startsWith("sofa") ? `<g transform="scale(-1,1)">${sitter(looks(id), "relax")}</g>` : stander(looks(id), w.pose === "cup");
    obj(x + y + 5, `<g class="o-click o-station" data-href="#/agents/${id}" data-agent="${id}">${at(x, y, 0, sprite)}</g>`);
  }

  // name tags, bubbles and what they're on, above everyone
  for (const id of ids) {
    if (walking.has(id)) continue;
    const w = where[id];
    const [x, y] = w.place === "desk" || w.place === "off" ? spotXY(id, "desk") : spotXY(id, w.place);
    const z = w.place === "off" ? 70 : w.pose === "nap" ? 92 : w.place.startsWith("coffee") || w.place === "door" ? 128 : 112;
    const [nx, ny] = P(x, y, z);
    const [words, dot] = statusWords(id, w);
    labels.push(nameTag(nx, ny, id, words, DOT[dot]));
    const b = bubbleOf(id);
    if (b) labels.push(pill(nx, ny, b));
    else if (H.state.agents[id]?.status === "working") {
      const t = H.busyWith(id);
      const text = clip(t ? `${t.id} · ${t.title}` : H.doing(id), 38);
      labels.push(tag(nx, ny, text, `#/agents/${id}`, -33));
    }
  }

  yourOffice(obj, labels);
  objs.sort((a, b) => a.key - b.key);
  const outline = pts([[0, D, 0], [0, D, WALL], [0, 0, WALL], [W, 0, WALL], [W, 0, 0], [W, D, 0]]);
  const shadeOver = ph === "night" ? `<polygon points="${outline}" fill="#16224a" opacity=".3"/>` : ph === "dusk" ? `<polygon points="${outline}" fill="#f09a50" opacity=".12"/>` : "";
  return { size, where, html: shell(ph) + objs.map((o) => o.svg).join("") + shadeOver + `<g style="mix-blend-mode:screen">${lights.join("")}</g>`, labels: labels.join("") };
}

// ---- the page -------------------------------------------------------------------------------------------------------
const DEFS = `<defs>
  <pattern id="o-planks" width="200" height="30" patternUnits="userSpaceOnUse"><rect width="200" height="30" fill="#d9b88c"/>
    <rect width="120" height="15" fill="#d4b083"/><rect x="120" width="80" height="15" fill="#dfc096"/><rect y="15" width="50" height="15" fill="#dfc096"/><rect x="50" y="15" width="150" height="15" fill="#cfab7e"/>
    <path d="M0 15H200M0 30H200M120 0V15M50 15V30" stroke="#bf9b6d" stroke-width="1"/></pattern>
  <pattern id="o-rug" width="10" height="10" patternUnits="userSpaceOnUse"><rect width="10" height="10" fill="#b98f86"/><circle cx="3" cy="3" r="1.4" fill="#ad8279"/><circle cx="8" cy="8" r="1.4" fill="#c49d94"/></pattern>
  <radialGradient id="o-glow-code"><stop offset="0" stop-color="#8ff0c4" stop-opacity=".75"/><stop offset="1" stop-color="#8ff0c4" stop-opacity="0"/></radialGradient>
  <radialGradient id="o-glow-doc"><stop offset="0" stop-color="#fffbe8" stop-opacity=".9"/><stop offset="1" stop-color="#fffbe8" stop-opacity="0"/></radialGradient>
  <radialGradient id="o-lamp"><stop offset="0" stop-color="#ffe9a0" stop-opacity=".7"/><stop offset="1" stop-color="#ffe9a0" stop-opacity="0"/></radialGradient>
  <radialGradient id="o-night-lamp"><stop offset="0" stop-color="#ffd98a" stop-opacity=".55"/><stop offset="1" stop-color="#ffd98a" stop-opacity="0"/></radialGradient>
  <linearGradient id="o-sun-day" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#fff7da" stop-opacity=".55"/><stop offset="1" stop-color="#fff7da" stop-opacity="0"/></linearGradient>
  <linearGradient id="o-sun-dusk" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffc98a" stop-opacity=".5"/><stop offset="1" stop-color="#ffc98a" stop-opacity="0"/></linearGradient>
  <filter id="o-sh" x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="0" dy="3" stdDeviation="3" flood-color="#3b2a18" flood-opacity=".25"/></filter>
</defs>`;

export async function OfficePage() {
  const [tasks, reviews] = await Promise.all([H.api("/api/tasks"), H.api("/api/reviews").catch(() => H.state.reviews || [])]);
  H.state.tasks = tasks;
  H.state.reviews = reviews;
  return `<div class="office-page">
    <div class="page-head office-head"><div><h1>Office</h1><p>Click someone to chat. A red bubble from a computer means they have something for you.</p></div>
      <div class="office-zoom" role="group" aria-label="Zoom"><button class="btn small" data-office-zoom="out" aria-label="Zoom out">−</button>
        <button class="btn small" data-office-zoom="fit">Fit</button><button class="btn small" data-office-zoom="in" aria-label="Zoom in">+</button></div></div>
    <div class="office-stage" id="office-stage">
      <svg id="office-svg" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet" role="img" aria-label="The team in an office">${DEFS}
        <g id="o-scene"></g><g id="o-walkers"></g><g id="o-labels"></g></svg>
      <div class="office-tip" id="office-tip" hidden></div>
      <div class="office-hire-menu" id="office-hire" hidden><b>Hire</b>
        <button class="btn small" data-hire-role="techlead">Tech Lead</button><button class="btn small" data-hire-role="dev">Dev</button><button class="btn small" data-hire-role="reviewer">Reviewer</button></div>
    </div></div>`;
}

let vb = null, fit = null, ticker = 0, lastSize = "";
const svgEl = () => document.getElementById("office-svg");
// Labels keep the same size on screen at any zoom: they're scaled by how many room units one pixel is.
function applyVB() {
  const svg = svgEl();
  if (!svg) return;
  svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
  const r = svg.getBoundingClientRect();
  if (r.width) svg.style.setProperty("--ls", (Math.max(vb.w / r.width, vb.h / r.height) * Math.min(1, Math.max(0.78, r.width / 1000))).toFixed(3));
}

export function officeRefresh() {
  const svg = svgEl();
  if (!svg) { clearInterval(ticker); ticker = 0; return; }
  const before = prevPlaces;
  const s = scene();
  const now = Object.fromEntries(Object.entries(s.where).map(([id, w]) => [id, w.place]));
  const moves = before ? Object.keys(now).filter((id) => before[id] && before[id] !== now[id] && !walking.has(id)) : [];
  if (moves.length) {
    for (const id of moves) walking.set(id, 0);
    const again = scene();   // draw again without the walkers in their old or new spot
    draw(again);
    for (const id of moves) walk(id, before[id], now[id]);
  } else draw(s);
  prevPlaces = now;
}

function draw(s) {
  document.getElementById("o-scene").innerHTML = s.html;
  document.getElementById("o-labels").innerHTML = s.labels;
  const key = `${s.size.w}x${s.size.h}`;
  fit = { x: 0, y: 0, w: s.size.w, h: s.size.h };
  if (!vb || key !== lastSize) { vb = startView(); applyVB(); }
  lastSize = key;
}

// Someone walks from one place to the other (the door when they arrive or leave), then sits down.
function walk(id, from, to) {
  const layer = document.getElementById("o-walkers");
  const [x0, y0] = P(...spotXY(id, from === "off" ? "door" : from));
  const [x1, y1] = P(...spotXY(id, to === "off" ? "door" : to));
  const secs = Math.min(5, Math.max(1.2, Math.hypot(x1 - x0, y1 - y0) / 120));
  const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
  g.setAttribute("class", "o-walker");
  g.style.transform = `translate(${x0}px, ${y0}px)`;
  g.style.transition = `transform ${secs}s linear`;
  g.innerHTML = `<g transform="scale(${(x1 < x0 ? -1 : 1) * K}, ${K})"><g class="o-bob">${stander(looks(id))}</g></g>`;
  layer.appendChild(g);
  requestAnimationFrame(() => requestAnimationFrame(() => { g.style.transform = `translate(${x1}px, ${y1}px)`; }));
  walking.set(id, setTimeout(() => { g.remove(); walking.delete(id); officeRefresh(); }, secs * 1000 + 60));
}

// The whole room on a wide screen; on a phone, closer in on the desks (drag to look around).
function startView() {
  const r = svgEl()?.getBoundingClientRect();
  if (!r?.width || r.width >= 700) return { ...fit };
  const w = Math.max(fit.w * 0.38, Math.min(fit.w * 0.6, fit.h * 0.85 * r.width / r.height)), h = w * (r.height / r.width);
  return { x: (fit.w - w) / 2, y: fit.h * 0.5 - h / 2, w, h };
}

export function mountOffice() {
  const stage = document.getElementById("office-stage");
  if (!stage) return;
  for (const t of walking.values()) clearTimeout(t);
  walking.clear();
  prevPlaces = null;
  vb = null;
  lastSize = "";
  officeRefresh();
  clearInterval(ticker);
  ticker = setInterval(officeRefresh, 30000);   // the clock, the light and idle people moving around

  const svg = svgEl(), tip = document.getElementById("office-tip"), hire = document.getElementById("office-hire");
  const toWorld = (cx, cy) => { const r = svg.getBoundingClientRect(); const s = Math.max(vb.w / r.width, vb.h / r.height);
    return [vb.x + (cx - r.left - (r.width - vb.w / s) / 2) * s, vb.y + (cy - r.top - (r.height - vb.h / s) / 2) * s, s]; };
  const zoom = (f, cx, cy) => {
    const r = svg.getBoundingClientRect();
    const [wx, wy] = cx === undefined ? [vb.x + vb.w / 2, vb.y + vb.h / 2] : toWorld(cx, cy);
    const w = Math.min(fit.w * 1.4, Math.max(fit.w / 4, vb.w * f)), h = w * (vb.h / vb.w);
    const k = w / vb.w;
    vb = { x: wx - (wx - vb.x) * k, y: wy - (wy - vb.y) * k, w, h };
    if (r.width) applyVB();
  };
  stage.addEventListener("wheel", (e) => { e.preventDefault(); zoom(e.deltaY > 0 ? 1.12 : 1 / 1.12, e.clientX, e.clientY); }, { passive: false });
  document.querySelector(".office-zoom").addEventListener("click", (e) => {
    const z = e.target.closest("[data-office-zoom]")?.dataset.officeZoom;
    if (z === "fit") { vb = startView(); applyVB(); } else if (z) zoom(z === "in" ? 1 / 1.25 : 1.25);
  });
  let drag = null;
  stage.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || e.target.closest(".office-hire-menu")) return;
    drag = { x: e.clientX, y: e.clientY, vx: vb.x, vy: vb.y, moved: false, id: e.pointerId };
  });
  stage.addEventListener("pointermove", (e) => {
    if (drag && e.pointerId === drag.id) {
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (!drag.moved && Math.hypot(dx, dy) > 5) { drag.moved = true; stage.setPointerCapture(e.pointerId); stage.classList.add("dragging"); tip.hidden = true; }
      if (drag.moved) { const s = toWorld(0, 0)[2]; vb.x = drag.vx - dx * s; vb.y = drag.vy - dy * s; applyVB(); }
      return;
    }
    const el = e.target.closest("[data-agent]");
    stage.querySelectorAll(".o-hover").forEach((x) => x !== el && x.classList.remove("o-hover"));
    if (!el) { tip.hidden = true; return; }
    const id = el.dataset.agent;
    stage.querySelectorAll(`[data-agent="${CSS.escape(id)}"]`).forEach((x) => x.classList.add("o-hover"));
    tip.innerHTML = tipHtml(id);
    tip.hidden = false;
    const r = stage.getBoundingClientRect();
    tip.style.left = `${Math.min(e.clientX - r.left + 16, r.width - tip.offsetWidth - 8)}px`;
    tip.style.top = `${Math.min(e.clientY - r.top + 16, r.height - tip.offsetHeight - 8)}px`;
  });
  stage.addEventListener("pointerleave", () => { tip.hidden = true; stage.querySelectorAll(".o-hover").forEach((x) => x.classList.remove("o-hover")); });
  const endDrag = () => { stage.classList.remove("dragging"); setTimeout(() => { drag = null; }, 0); };
  stage.addEventListener("pointerup", endDrag);
  stage.addEventListener("pointercancel", endDrag);
  stage.addEventListener("click", (e) => {
    if (drag?.moved) return;
    const role = e.target.closest("[data-hire-role]")?.dataset.hireRole;
    if (role) { hire.hidden = true; H.actions["add-agent"]({ dataset: { role } }); return; }
    if (e.target.closest(".office-hire-menu")) return;
    if (e.target.closest("[data-hire]")) {
      const r = stage.getBoundingClientRect();
      hire.hidden = false;
      hire.style.left = `${Math.min(e.clientX - r.left, r.width - hire.offsetWidth - 8)}px`;
      hire.style.top = `${Math.min(e.clientY - r.top + 10, r.height - hire.offsetHeight - 8)}px`;
      return;
    }
    hire.hidden = true;
    const href = e.target.closest("[data-href]")?.dataset.href;
    if (href) location.hash = href;
  });
  new ResizeObserver(() => applyVB()).observe(stage);
  stage.addEventListener("dblclick", (e) => { if (!e.target.closest("[data-href],[data-hire]")) { vb = startView(); applyVB(); } });
}

function tipHtml(id) {
  const a = H.state.agents[id] || {};
  const t = H.busyWith(id);
  const b = bubbleOf(id);
  return `<b>${H.esc(H.nameOf(id))}</b><span class="muted">${H.esc(H.STATUS_TEXT[a.status] || a.status || "")}</span>
    ${t ? `<span>On <b>${H.esc(t.id)}</b> ${H.esc(clip(t.title, 60))}</span>` : ""}
    ${b ? `<span class="attn">${H.esc(b.text)}</span>` : ""}
    ${a.status && a.status !== "stopped" ? `<span class="muted">${H.esc(clip(H.doing(id), 110))}</span>` : `<span class="muted">Open the chat to start it.</span>`}`;
}
