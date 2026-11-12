// Team Console: talks to the local console server (server/main.py).
// In the Office's chat panel the console shows just the chat: no menu, and other pages open in the main window.
const EMBED = new URLSearchParams(location.search).has("embed");
if (EMBED) {
  document.documentElement.classList.add("embed");
  addEventListener("hashchange", () => { if (!location.hash.startsWith("#/agents/")) { const to = location.hash; history.back(); window.top.location.hash = to; } });
}
// The Office is 3D: its code and its people load the first time you open it.
let officeMod = null;
async function office() {
  if (!officeMod) {
    officeMod = await import("./office3d.js");
    officeMod.setupOffice({ state, api, esc, personOf, nameOf, roleOf, agentIds, OWNER_LABEL, STATUS_TEXT, doing, busyWith, parseQuestions, actions, openRail, avatarHtml: (id) => avatar(id) });
  }
  return officeMod;
}
const OfficePage = async () => (await office()).OfficePage();
const officeRefresh = () => officeMod?.officeRefresh();

// The page's key, new each time Hive starts. A tab opened before a restart fetches the new one by itself
// (reading it from the page, as only this site can) instead of failing with "Reload the page." until you do.
let TOKEN = window.CONSOLE_TOKEN;
let tokenRefresh = null;
function refreshToken() {
  tokenRefresh ??= fetch("/", { cache: "no-store", credentials: "same-origin" })
    .then((r) => r.text())
    .then((html) => { const m = html.match(/CONSOLE_TOKEN = "([^"]+)"/); const changed = !!m && m[1] !== TOKEN; if (m) TOKEN = m[1]; return changed; })
    .catch(() => false)
    .finally(() => setTimeout(() => { tokenRefresh = null; }, 2000));
  return tokenRefresh;
}
const view = document.getElementById("view");

const ROLES = {
  orchestrator: { name: "Orchestrator", role: "Your assistant for the team", blurb: "Tells you where things stand, with links, and starts agents, hands tasks on or passes messages, each after you approve. Also in Slack.", quick: ["Where are we?", "What's waiting on me?"] },
  techlead: { name: "Tech Lead", role: "Tech lead / staff engineer", blurb: "Designs the change against the codebase and turns it into a complete, approved task spec.", quick: ["Show me the board", "What's still in draft?"] },
  dev: { name: "Dev", role: "Developer", blurb: "Builds exactly what the spec asks, in the project's style.", quick: ["Check your inbox"] },
  reviewer: { name: "Reviewer", role: "Reviewer", blurb: "Checks the requirements are met and the code is consistent with what exists.", quick: ["Check your inbox"] },
  coach: { name: "Coach", role: "Coach", blurb: "Reviews how finished tasks went and proposes improvements to the team's instructions, for your approval.", quick: ["Review everything since your last review", "What did you propose last time?"] },
};
const OWNER_LABEL = { orchestrator: "Orchestrator", techlead: "Tech Lead", dev: "Dev", reviewer: "Reviewer", coach: "Coach", lead: "You" };
// Agents are identified by id: the role, then -2, -3… for extra agents of the same role.
const roleOf = (id) => state.agents[id]?.role || String(id).split("-")[0];
// Each agent has a display name (Kareem), given at random and renamed in Settings; shown as "Kareem (Tech Lead)".
const personOf = (id) => { const given = state.settings?.agents?.[id]?.name; if (given) return given;
  const r = ROLES[roleOf(id)]; const n = String(id).split("-")[1]; return r ? (n ? `${r.name} ${n}` : r.name) : String(id); };
const nameOf = (id) => { const r = ROLES[roleOf(id)]; const p = personOf(id); return r && p !== r.name && !p.startsWith(`${r.name} `) ? `${p} (${r.name})` : p; };
const agentIds = () => Object.keys(state.agents);
// Who has the task right now, in words: "Salma (Dev)", "You, blocked by Salma (Dev)", "the next free Dev".
const holderText = (t) => {
  if (t.status === "blocked") return t.assignee ? `You, blocked by ${nameOf(t.assignee)}` : "You";
  if (t.assignee) return nameOf(t.assignee);
  if (t.owner === "lead") return "You";
  return `the next free ${OWNER_LABEL[t.owner] || t.owner}`;
};
const STAGES = [
  { status: "draft", label: "Draft", owner: "techlead" },
  { status: "ready-for-dev", label: "Ready for dev", owner: "dev" },
  { status: "in-dev", label: "In development", owner: "dev" },
  { status: "changes-requested", label: "Changes requested", owner: "dev" },
  { status: "ready-for-review", label: "Ready for review", owner: "reviewer" },
  { status: "in-review", label: "In review", owner: "reviewer" },
  { status: "done", label: "Done", owner: "lead" },
];
const STATUS_TEXT = { stopped: "Stopped", starting: "Starting…", idle: "Ready", working: "Working…", waiting: "Needs your approval" };

const state = {
  agents: {},         // name -> {status, session_id, pending, error}
  settings: null,
  kit: "",
  live: {},           // name -> events of the current session
  drafts: {},         // name -> unsent composer text
  land: {},           // task -> the landing page's plan and the lead's choices (kept across refreshes)
  openTools: new Set(),
  openProposals: new Set(),
  inboxUnread: 0,
  stream: {},         // name -> {thinking, text, tool}: what the agent is writing right now
  since: {},          // name -> when it started working (ms)
  codeTask: {},       // dev/reviewer name -> the task whose code it's on, for "Review the code"
  reviewNote: {},     // task id -> the general comment you're writing for your review
  reviewSent: null,   // the review you just submitted, for the banner on top of the review page
};
const emptyStream = () => ({ thinking: "", text: "", tool: "" });

// ---- helpers ------------------------------------------------------------------

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Agents often start a list right under a sentence ("Backend\n3. Searcher…"). Standard Markdown then glues the
// items onto that sentence (only a list starting at 1 may follow one directly): give each list a blank line above.
function listsOnTheirOwn(text) {
  let fenced = false, prev = "";
  const item = /^ {0,3}(?:\d{1,3}[.)]|[-*+])\s+\S/;
  return (text || "").split("\n").map((line) => {
    if (/^ {0,3}(```|~~~)/.test(line)) fenced = !fenced;
    const out = !fenced && item.test(line) && prev.trim() && !item.test(prev) && !/^\s/.test(prev) && !/^ {0,3}(#|>|\|)/.test(prev)
      ? `\n${line}` : line;
    prev = line;
    return out;
  }).join("\n");
}
const md = (text) => DOMPurify.sanitize(marked.parse(listsOnTheirOwn(text), { gfm: true, breaks: false }));

async function api(path, { method = "GET", body } = {}, retried = false) {
  const res = await fetch(path, {
    method,
    headers: { "x-token": TOKEN, ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && data.detail === "Reload the page." && !retried && await refreshToken()) {
    return api(path, { method, body }, true);   // Hive restarted since this page loaded: same request, new key
  }
  if (!res.ok) throw Object.assign(new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status}).`), { data });
  return data;
}

function toast(text, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.className = "toast" + (isError ? " error" : "");
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), isError ? 6000 : 2800);
}

async function act(fn, done) {
  try {
    const result = await fn();
    if (done) toast(done);
    return result;
  } catch (err) {
    toast(err.message, true);
  }
}

function ago(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

const money = (x) => (x > 0 && x < 0.01 ? "under $0.01" : `$${(x || 0).toFixed(2)}`);
const tokens = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n || 0}`);
function costText(c) {
  if (!c || (!c.cost_usd && !c.unpriced_tokens)) return "";
  if (!c.unpriced_tokens) return money(c.cost_usd);
  return c.cost_usd ? `${money(c.cost_usd)} + ${tokens(c.unpriced_tokens)} tokens unpriced` : `${tokens(c.unpriced_tokens)} tokens, no price set`;
}

const providerOf = (id) => (state.settings?.providers || []).find((p) => p.id === id) || { id, label: id, models: [] };
function choiceOf(name) {
  const ag = state.agents[name] || {};
  if (ag.status && ag.status !== "stopped" && ag.provider) return { provider: ag.provider, model: ag.model };
  return state.settings?.agents?.[name] || { provider: "claude", model: "" };
}
const modelLabel = (name) => { const c = choiceOf(name); return `${providerOf(c.provider).label}, ${c.model || "default model"}`; };

const ownerOf = (status) => (STAGES.find((s) => s.status === status) || { owner: "lead" }).owner;
const stageLabel = (status) => (STAGES.find((s) => s.status === status) || { label: status === "blocked" ? "Blocked" : status }).label;
const statusPill = (status) => `<span class="pill ${status === "blocked" ? "lead" : ownerOf(status)}">${esc(stageLabel(status))}</span>`;

function toolArg(name, input = {}) {
  if (name === "Team action") return input.summary || "";
  if (input.command) return input.command;
  if (input.file_path) return input.file_path;
  if (input.pattern) return input.path ? `${input.pattern}  in ${input.path}` : input.pattern;
  if (input.url) return input.url;
  if (input.query) return input.query;
  if (input.description) return input.description;
  if (name === "TodoWrite") return "update the to-do list";
  return JSON.stringify(input).slice(0, 140);
}

function toolDetail(name, input = {}) {
  if (name === "Team action") return input.summary || "";
  if (input.command) return input.command;
  if (name === "Edit" || name === "MultiEdit") {
    const edits = input.edits || [input];
    return `${input.file_path}\n\n` + edits.map((e) => `- ${e.old_string ?? ""}\n+ ${e.new_string ?? ""}`).join("\n\n");
  }
  if (name === "Write") return `${input.file_path}\n\n${(input.content || "").slice(0, 3000)}`;
  return JSON.stringify(input, null, 2);
}

// ---- live state ---------------------------------------------------------------

async function loadState() {
  const data = await api("/api/state");
  state.settings = data.settings;
  state.kit = data.kit;
  state.terminal = data.terminal;
  state.editorBrowser = !!data.editor_browser;
  const improvements = document.getElementById("improvements-badge");
  improvements.textContent = data.improvements;
  improvements.hidden = !data.improvements;
  document.getElementById("nav-terminal").hidden = !data.terminal;
  state.improvements = data.improvements;
  state.agents = Object.fromEntries(data.agents.map((a) => [a.name, a]));
  renderRail();
}

async function loadLive(name) {
  const sid = state.agents[name]?.session_id;
  state.live[name] = sid ? (await api(`/api/sessions/${sid}`)).events : [];
}

function connect() {
  const conn = document.getElementById("conn");
  const source = new EventSource(`/api/events?token=${encodeURIComponent(TOKEN)}`);
  source.onopen = () => { conn.textContent = "Live"; conn.classList.add("live"); resync(); };
  source.onerror = () => {
    conn.textContent = "Reconnecting…";
    conn.classList.remove("live");
    // The browser retries by itself, but gives up for good when Hive answers with an error (a restart: new key).
    if (source.readyState === EventSource.CLOSED) setTimeout(() => refreshToken().then(connect), 2000);
  };
  source.onmessage = (msg) => onEvent(JSON.parse(msg.data));
}

let boardTimer;
function onEvent(event) {
  if (event.kind === "agent") {
    const before = state.agents[event.agent.name]?.session_id;
    const wasBusy = ["working", "waiting"].includes(state.agents[event.agent.name]?.status);
    state.agents[event.agent.name] = event.agent;
    if (event.agent.status === "working" && !wasBusy) state.since[event.agent.name] = Date.now();
    if (!["working", "waiting"].includes(event.agent.status)) state.stream[event.agent.name] = emptyStream();
    if (before !== event.agent.session_id) {
      state.live[event.agent.name] = [];
      if (event.agent.session_id && route().page === "agent" && route().id === event.agent.name) resync();
    }
    renderRail();
    refreshIf(["overview"]);
    if (route().page === "agent" && route().id === event.agent.name) renderAgentChrome(event.agent.name);
    if (event.agent.name === "orchestrator") renderDrawer();
    if (route().page === "office") officeRefresh();
    return;
  }
  if (event.kind === "team") {
    loadState().then(() => render(true)).catch(() => {});
    return;
  }
  if (event.kind === "board") {
    clearTimeout(boardTimer);
    boardTimer = setTimeout(() => { refreshIf(["overview", "tasks", "task"]); refreshCounts().then(() => { if (route().page === "office") officeRefresh(); }); }, 300);
    return;
  }
  if (event.kind === "delta") {
    if (event.session !== state.agents[event.agent]?.session_id) return;
    const s = (state.stream[event.agent] ||= emptyStream());
    if (event.block === "tool") s.tool = event.text;
    else s[event.block] += event.text;
    if (route().page === "agent" && route().id === event.agent) renderLive(event.agent);
    return;
  }
  if (event.agent && event.session && event.session === state.agents[event.agent]?.session_id) {
    if (["text", "thinking", "tool", "permission", "result", "error"].includes(event.kind)) state.stream[event.agent] = emptyStream();
    (state.live[event.agent] ||= []).push(event);
    const r = route();
    if (r.page === "agent" && r.id === event.agent) renderTranscriptInto(event.agent);
    if (event.agent === "orchestrator") renderDrawer();
    if (r.page === "overview") refreshIf(["overview"]);
  }
}

function refreshIf(pages) {
  if (pages.includes(route().page)) render(true);
}

// The first line of an agent's message, without Markdown marks, for a one-line preview.
const plainLine = (text) => (text.split("\n").find((l) => l.trim()) || "").replace(/[*_`#>]+/g, "").trim();

// Agents that stopped on work handed to them without moving the task: they're waiting for your answer.
const stoppedForYou = () => Object.entries(state.agents).filter(([, a]) => a.waiting_for_lead && a.status === "idle");
const stoppedOn = (taskId) => stoppedForYou().some(([, a]) => a.waiting_for_lead.task === taskId);

// What needs you (Home's badge): approvals, agents waiting for you, blocked tasks, tasks waiting for a hand-off,
// the Coach's proposals.
function needsCount() {
  const approvals = Object.values(state.agents).reduce((n, a) => n + (a.pending?.length || 0), 0);
  const tasks = (state.tasks || []).filter((t) => !stoppedOn(t.id) && (["blocked", "ready-for-review", "ready-for-dev"].includes(t.status)
    || (t.status === "changes-requested" && !["working", "waiting"].includes(state.agents[t.dev]?.status)))).length;
  return approvals + stoppedForYou().length + tasks + (state.improvements ? 1 : 0);
}

function showCounts() {
  const toReview = (state.reviews || []).filter((b) => b.needs_you).length;
  const rb = document.getElementById("reviews-badge");
  rb.textContent = toReview;
  rb.hidden = toReview === 0;
  rb.title = `${toReview} ${toReview === 1 ? "branch" : "branches"} waiting for your review`;
  const n = needsCount();
  for (const id of ["home-badge", "home-badge-tab"]) {
    const badge = document.getElementById(id);
    badge.textContent = n;
    badge.hidden = n === 0;
  }
}

async function refreshCounts() {
  try {
    [state.tasks, state.reviews] = await Promise.all([api("/api/tasks"), api("/api/reviews").catch(() => state.reviews || [])]);
  } catch { return; }
  renderRail();
}
const refreshBadge = refreshCounts;

// ---- routing ------------------------------------------------------------------

function route() {
  const [, page = "", id = "", sub = "", name = ""] = location.hash.replace(/^#/, "").split("?")[0].split("/");
  if (page === "tasks" && id && sub === "review") return { page: "review", id: decodeURIComponent(id), sub };
  if (page === "tasks" && id && ["pr", "land"].includes(sub)) return { page: "land", id: decodeURIComponent(id), sub };
  if (page === "tasks" && sub === "chats" && name) return { page: "task-chat", id: decodeURIComponent(id), sub, name: decodeURIComponent(name) };
  const map = { improvements: "improvements", team: id ? (sub === "files" ? "team-files" : "team-change") : "team",
    "": "overview", office: "office", finance: "finance", tasks: id ? "task" : "tasks", reviews: "reviews", agents: "agent", history: id ? "session" : "history", settings: "settings", terminal: "terminal", knowledge: id ? "knowledge-file" : "knowledge" };
  return { page: map[page] || "overview", id: decodeURIComponent(id), sub };
}

let renderSeq = 0;
async function render(quiet = false) {
  const r = route();
  const seq = ++renderSeq;
  const pages = { overview: Overview, office: OfficePage, finance: Finance, tasks: Tasks, task: TaskDetail, agent: AgentChat, history: History, session: SessionView, settings: Settings, terminal: TerminalPage, "task-chat": TaskChat, improvements: Improvements, team: TeamHistory, "team-change": TeamChange, "team-files": TeamFiles, knowledge: KnowledgeList, "knowledge-file": KnowledgeView, review: CodeReview, reviews: Reviews, land: Land };
  try {
    const html = await pages[r.page](r, quiet);
    if (seq !== renderSeq || html === null) return;
    const scrollY = window.scrollY;
    parkTerminal();   // keep the shell alive while other pages are shown
    view.innerHTML = html;
    document.body.classList.toggle("office-full", r.page === "office");
    if (r.page !== "office") document.body.classList.remove("office-rail");
    window.scrollTo(0, quiet ? scrollY : 0);   // a new page opens at the top; a refresh keeps your place
    afterRender[r.page]?.(r);
  } catch (err) {
    if (seq === renderSeq) view.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
  }
  highlightNav(r);
  renderCrumb(r);
  const pill = document.getElementById("ask-pill");
  pill.hidden = r.page === "agent" || !state.agents.orchestrator;   // in a chat, the composer is right there
  if (!pill.hidden) pill.querySelector(".avatar").outerHTML = avatar("orchestrator");
  closeRail();
}

// Where you are, at the top of every page.
function renderCrumb(r) {
  const link = (href, text) => `<a href="${href}">${esc(text)}</a>`;
  const parts = {
    overview: ["Home"], office: ["Office"], finance: ["Finance"], tasks: ["Board"], history: ["Activity"], session: [link("#/history", "Activity"), "Conversation"],
    task: [link("#/tasks", "Board"), r.id], review: [link("#/reviews", "Reviews"), link(`#/tasks/${r.id}`, r.id), "Code review"], reviews: ["Reviews"],
    land: [link("#/reviews", "Reviews"), link(`#/tasks/${r.id}`, r.id), "Pull request"],
    "task-chat": [link("#/tasks", "Board"), link(`#/tasks/${r.id}`, r.id), "Conversations"],
    agent: [state.agents[r.id] ? ({ orchestrator: "Orchestrator", coach: "Coach" }[roleOf(r.id)] || "Team") : "Agents", state.agents[r.id] ? nameOf(r.id) : r.id],
    settings: r.id ? [link("#/settings", "Settings"), ...(r.sub ? [link(`#/settings/${r.id}`, (SETTINGS_SECTIONS.find(([k]) => k === r.id) || [, r.id])[1]), r.sub[0].toUpperCase() + r.sub.slice(1)] : [(SETTINGS_SECTIONS.find(([k]) => k === r.id) || [, r.id])[1]])] : ["Settings"], terminal: ["Terminal"], improvements: ["Coach", "Improvements"], team: ["Coach", "Team history"],
    "team-change": ["Coach", link("#/team", "Team history"), "Change"], "team-files": ["Coach", link("#/team", "Team history"), "Files"],
    knowledge: ["Library", "Knowledge"], "knowledge-file": ["Library", link("#/knowledge", "Knowledge"), r.id],
  }[r.page] || [];
  document.getElementById("crumb").innerHTML = parts.map((p, i) => i === parts.length - 1 && !p.startsWith("<a") ? `<b>${esc(p)}</b>` : p.startsWith("<a") ? p : esc(p)).join('<span class="sep">›</span>');
}

function highlightNav(r) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const nav = a.dataset.nav;
    const on = nav === r.page || (nav === "orchestrator-tab" && r.page === "agent" && r.id === "orchestrator") || (nav === "tasks" && ["task", "task-chat"].includes(r.page)) || (nav === "reviews" && ["review", "land"].includes(r.page)) || (nav === "history" && r.page === "session") || (nav === "knowledge" && r.page === "knowledge-file") || (nav === "team" && r.page.startsWith("team-"));
    on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
  });
  document.querySelectorAll(".rail-agent").forEach((a) => {
    r.page === "agent" && a.dataset.agent === r.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
  });
}

// The task each agent is on right now (from the board), shown under its name.
function busyWith(name) {
  return (state.tasks || []).find((t) => ["in-dev", "in-review", "draft", "blocked"].includes(t.status) && t.assignee === name);
}

// An agent's face (one of the Office's people, given in settings) in a ring of its role's colour; the initial
// if there's no face or it doesn't load.
function avatar(name, cls = "") {
  const face = state.settings?.agents?.[name]?.face;
  return `<span class="avatar ${roleOf(name)} ${face ? "face" : ""} ${cls}" aria-hidden="true">${esc((personOf(name) || "?").slice(0, 1).toUpperCase())}${
    face ? `<img src="/static/office/faces/${esc(face)}.webp" alt="" decoding="async">` : ""}</span>`;
}
document.addEventListener("error", (e) => {
  if (e.target.matches?.(".avatar.face > img")) { e.target.parentElement.classList.remove("face"); e.target.remove(); }
}, true);

function railAgent(name) {
  const st = state.agents[name]?.status || "stopped";
  const task = busyWith(name);
  const sub = (roleOf(name) === "orchestrator" ? "Your assistant, also in Slack" : OWNER_LABEL[roleOf(name)]) + (task ? ` · ${task.id}` : "");
  const stopped = st === "idle" && state.agents[name]?.waiting_for_lead;
  const marker = st === "waiting" ? `<span class="pill attention">Approve</span>`
    : stopped ? `<span class="pill attention" title="Stopped and waiting for your answer">Needs you</span>`
    : `<span class="dot ${st}" title="${STATUS_TEXT[st]}"></span>`;
  return `<a class="rail-agent ${roleOf(name)}" data-agent="${name}" href="#/agents/${name}" title="${esc(nameOf(name))}: ${STATUS_TEXT[st]}">
    ${avatar(name)}<span class="who">${esc(personOf(name))}<small>${esc(sub)}</small></span>${marker}</a>`;
}

function renderRail() {
  const ids = agentIds();
  const of = (roles) => ids.filter((n) => roles.includes(roleOf(n))).map(railAgent).join("");
  document.getElementById("rail-orchestrator").innerHTML = of(["orchestrator"]);
  document.getElementById("rail-team").innerHTML = of(["techlead", "dev", "reviewer"]);
  document.getElementById("rail-coach").innerHTML = of(["coach"]);
  let collapsed = [];
  try { collapsed = JSON.parse(localStorage.getItem("railCollapsed") || "[]"); } catch { /* not remembered */ }
  document.querySelectorAll(".rail-section").forEach((sec) => {
    const closed = collapsed.includes(sec.dataset.section);
    sec.classList.toggle("collapsed", closed);
    sec.querySelector(".rail-toggle").setAttribute("aria-expanded", String(!closed));
  });
  showCounts();
  highlightNav(route());
}

// The sidebar folded down to icons, remembered in this browser. On a phone the sidebar is a menu instead.
const wideScreen = () => matchMedia("(min-width: 721px)").matches;
function setRailMini(mini) {
  document.body.classList.toggle("rail-mini", mini);
  const button = document.querySelector(".rail-collapse");
  const label = mini ? "Expand the sidebar ([)" : "Collapse the sidebar ([)";
  button.setAttribute("aria-label", label.replace(" ([)", ""));
  button.title = label;
  try { localStorage.setItem("railMini", mini ? "1" : ""); } catch { /* this page only */ }
}
function toggleRail() {
  if (wideScreen()) setRailMini(!document.body.classList.contains("rail-mini"));
  else closeRail();
}
try { if (localStorage.getItem("railMini")) setRailMini(true); } catch { /* expanded */ }

function openRail() { document.body.classList.add("rail-open"); document.querySelector(".scrim").hidden = false; }
function closeRail() { document.body.classList.remove("rail-open"); const s = document.querySelector(".scrim"); if (s) s.hidden = true; }

// ---- jump anywhere (⌘K) ----------------------------------------------------------

const PAGES_TO_JUMP = [["Home", "#/"], ["Office", "#/office"], ["Finance", "#/finance"], ["Board", "#/tasks"], ["Reviews", "#/reviews"], ["Activity", "#/history"], ["Improvements", "#/improvements"],
  ["Team history", "#/team"], ["Knowledge", "#/knowledge"], ["Settings", "#/settings"], ["Terminal", "#/terminal"]];

async function openJump() {
  const dialog = document.getElementById("jump-dialog");
  if (dialog.open) return;
  dialog.showModal();
  const input = document.getElementById("jump-input");
  input.value = "";
  input.focus();
  if (!state.tasks) await refreshCounts();
  showJump("");
}

function jumpItems(q) {
  q = q.trim().toLowerCase();
  const items = [
    ...agentIds().map((n) => ({ label: nameOf(n), hint: "Agent", href: `#/agents/${n}`, key: `${n} ${nameOf(n)}` })),
    ...(state.tasks || []).map((t) => ({ label: `${t.id} ${t.title}`, hint: `${t.project_name} · ${stageLabel(t.status)}`, href: `#/tasks/${t.id}`, key: `${t.id} ${t.title} ${t.project_name}` })),
    ...PAGES_TO_JUMP.filter(([l]) => l !== "Terminal" || state.terminal).map(([label, href]) => ({ label, hint: "Page", href, key: label })),
  ];
  if (!q) return [...items.filter((i) => i.hint === "Page"), ...items.filter((i) => i.hint === "Agent")].slice(0, 12);
  return items.filter((i) => i.key.toLowerCase().includes(q)).slice(0, 12);
}

function showJump(q) {
  const list = document.getElementById("jump-list");
  list.innerHTML = jumpItems(q).map((i, n) => `<li role="option" ${n === 0 ? 'aria-selected="true"' : ""}><a href="${i.href}" data-action="jump-go">${esc(i.label)}<small>${esc(i.hint)}</small></a></li>`).join("")
    || `<li class="none">Nothing matches.</li>`;
}

document.getElementById("jump-input").addEventListener("input", (e) => showJump(e.target.value));
document.getElementById("jump-input").addEventListener("keydown", (e) => {
  const options = [...document.querySelectorAll("#jump-list li[role=option]")];
  const at = options.findIndex((o) => o.getAttribute("aria-selected") === "true");
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    const next = options[(at + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length];
    options.forEach((o) => o.removeAttribute("aria-selected"));
    next?.setAttribute("aria-selected", "true");
    next?.scrollIntoView({ block: "nearest" });
  } else if (e.key === "Enter" && options[at]) {
    e.preventDefault();
    location.hash = options[at].querySelector("a").getAttribute("href");
    document.getElementById("jump-dialog").close();
  }
});
document.getElementById("jump-dialog").addEventListener("click", (e) => { if (e.target.id === "jump-dialog") e.target.close(); });
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) || document.activeElement?.isContentEditable;
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openJump(); }
  else if (e.key === "/" && !typing && !document.getElementById("ask-pill").hidden) { e.preventDefault(); openDrawer(); }
  else if (e.key === "Escape" && !document.getElementById("drawer").hidden) closeDrawer();
  else if (e.key === "[" && !typing && !e.metaKey && !e.ctrlKey && !document.querySelector("dialog[open]")) toggleRail();
  else if (e.key === "." && !typing && !e.metaKey && !e.ctrlKey && route().page === "review" && document.querySelector(".open-editor")) holdToOpen(e);
});
document.addEventListener("keyup", (e) => { if (e.key === ".") releaseHold(true); });
window.addEventListener("blur", () => releaseHold(false));

// Hold . for a moment to open the editor (a single press is too easy to hit by accident); the button fills meanwhile.
const HOLD_MS = 2000;
let hold = null;
function holdToOpen(e) {
  e.preventDefault();
  if (hold || e.repeat) return;
  const button = document.querySelector(".open-editor");
  button.style.setProperty("--hold", `${HOLD_MS}ms`);
  button.classList.add("holding");
  hold = { button, timer: setTimeout(() => { releaseHold(false); reviewOpen(); }, HOLD_MS) };
}
function releaseHold(early) {
  if (!hold) return;
  clearTimeout(hold.timer);
  hold.button.classList.remove("holding");
  hold = null;
  if (early) toast("Keep holding . to open the editor.");
}

// ---- ask the Orchestrator from any page -------------------------------------------

async function openDrawer() {
  const drawer = document.getElementById("drawer");
  drawer.hidden = false;
  document.body.classList.add("drawer-open");
  if (state.agents.orchestrator?.session_id && !state.live.orchestrator?.length) await loadLive("orchestrator").catch(() => {});
  renderDrawer();
  drawer.querySelector("textarea")?.focus();
}

function closeDrawer() {
  document.getElementById("drawer").hidden = true;
  document.body.classList.remove("drawer-open");
}

function renderDrawer() {
  const drawer = document.getElementById("drawer");
  if (!drawer || drawer.hidden) return;
  const a = state.agents.orchestrator || { status: "stopped", pending: [] };
  const draft = drawer.querySelector("textarea")?.value || "";
  const events = (state.live.orchestrator || []).filter((e) => ["user", "text", "permission", "decision", "error"].includes(e.kind)).slice(-30);
  drawer.innerHTML = `<header>${avatar("orchestrator")}<div><b>${esc(nameOf("orchestrator"))}</b><small><span class="dot ${a.status}"></span>${STATUS_TEXT[a.status]}</small></div>
      <a class="btn small" href="#/agents/orchestrator">Full chat</a><button class="icon-btn" data-action="close-drawer" aria-label="Close">✕</button></header>
    <div class="drawer-msgs transcript">${events.length ? transcriptHTML(events, { pending: a.pending || [], agent: "orchestrator" })
      : `<p class="muted">Ask where things stand, or ask it to start an agent, hand a task on or pass a message. It asks you before it acts.</p>`}</div>
    <form class="drawer-form" data-form="drawer">
      <div class="chips">${["Where are we?", "What's waiting on me?"].map((q) => `<button type="button" class="chip-btn" data-action="drawer-quick">${q}</button>`).join("")}</div>
      <textarea rows="2" placeholder="Message the Orchestrator (Enter to send)" aria-label="Message the Orchestrator">${esc(draft)}</textarea></form>`;
  const msgs = drawer.querySelector(".drawer-msgs");
  msgs.scrollTop = msgs.scrollHeight;
  const text = drawer.querySelector("textarea");
  text.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendToOrchestrator(text.value); }
  });
}

async function sendToOrchestrator(text) {
  if (!text.trim()) return;
  const ok = await act(() => api("/api/agents/orchestrator/message", { method: "POST", body: { text } }));
  if (ok) { const t = document.querySelector("#drawer textarea"); if (t) t.value = ""; }
}

// ---- overview ----------------------------------------------------------------

function doing(name) {
  const a = state.agents[name] || {};
  if (a.status === "stopped") return a.error ? `Couldn't start: ${a.error}` : "Not running. Start it to talk to it.";
  if (a.status === "waiting") return `Waiting for you to approve ${a.pending.map((p) => p.tool).join(", ")}.`;
  const last = [...(state.live[name] || [])].reverse().find((e) => ["text", "tool", "user"].includes(e.kind));
  if (!last) return "Ready for instructions.";
  if (last.kind === "tool") return `${last.name}: ${toolArg(last.name, last.input)}`;
  if (last.kind === "user") return `You: ${last.text}`;
  return last.text.replace(/[#*`_>]/g, "").slice(0, 200);
}

// Who can take a task now (free agents first). Rework goes back to the dev who built it, a re-review to the same reviewer.
function handCandidates(t) {
  const of = (role) => agentIds().filter((n) => roleOf(n) === role);
  const free = (n) => !busyWith(n) && !["working", "waiting"].includes(state.agents[n]?.status);
  const byFree = (list) => list.sort((a, b) => free(b) - free(a));
  if (t.status === "changes-requested") return t.dev && state.agents[t.dev] ? [t.dev] : [];
  if (t.status === "ready-for-review") return t.reviewer && state.agents[t.reviewer] ? [t.reviewer] : byFree(of("reviewer"));
  if (t.status === "ready-for-dev") return byFree(of("dev"));
  if (t.status === "draft") return t.techlead && state.agents[t.techlead] ? [t.techlead] : [];
  return [];
}

function handButtons(t, max = 2, firstPrimary = true) {
  return handCandidates(t).slice(0, max).map((n, i) =>
    `<button class="btn small ${firstPrimary && i === 0 ? "primary" : ""}" data-action="hand" data-task="${esc(t.id)}" data-agent="${n}">Hand ${t.status === "changes-requested" ? "back " : ""}to ${esc(personOf(n))}</button>`).join("");
}

const reviewLink = (t, primary = false) => t.from_commit ? `<a class="btn small ${primary ? "primary" : ""}" href="${reviewHref(t.id)}">Review the diff</a>` : "";

function greeting() {
  const h = new Date().getHours();
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
}

async function Overview() {
  const tasks = await api("/api/tasks");
  state.tasks = tasks;
  const cards = [];
  for (const [name, ag] of Object.entries(state.agents)) {
    for (const p of ag.pending || []) {
      cards.push(`<article class="need approval">
        <div class="k">${avatar(name)} Approval · ${esc(nameOf(name))}</div>
        <div class="t"><code>${esc(toolArg(p.tool, p.input).slice(0, 140))}</code></div>
        <div class="btn-row"><button class="btn small primary" data-action="allow" data-decision="allow" data-agent="${name}" data-pid="${esc(p.id)}">Allow</button>
          <button class="btn small" data-action="allow" data-decision="deny" data-agent="${name}" data-pid="${esc(p.id)}">Deny</button>
          <a class="btn small" href="#/agents/${name}">Open chat</a></div></article>`);
    }
  }
  const tasksById = Object.fromEntries(tasks.map((t) => [t.id, t]));
  for (const [name, ag] of stoppedForYou()) {
    const w = ag.waiting_for_lead, t = tasksById[w.task];
    cards.push(`<article class="need blocked">
      <div class="k">${avatar(name)} Waiting for you · ${esc(nameOf(name))} stopped ${ago(w.since)}</div>
      <div class="t">${t ? `<a href="#/tasks/${esc(t.id)}">${esc(t.id)}</a> ${esc(t.title)} <span class="muted">· ${esc(t.project_name)}</span>` : ""}</div>
      <div class="said">${esc(plainLine(w.text) || "It stopped without saying why.").slice(0, 280)}</div>
      <div class="btn-row"><a class="btn small primary" href="#/agents/${name}">Answer</a>
        ${t ? `<a class="btn small" href="#/tasks/${esc(t.id)}">Open task</a>` : ""}</div></article>`);
  }
  const card = (t, kind, label, who, buttons) => `<article class="need ${kind}">
      <div class="k">${who ? avatar(who) : ""} ${esc(label)}</div>
      <div class="t"><a href="#/tasks/${esc(t.id)}">${esc(t.id)}</a> ${esc(t.title)} <span class="muted">· ${esc(t.project_name)}</span></div>
      <div class="btn-row">${buttons}</div></article>`;
  for (const t of tasks.filter((x) => x.status === "blocked" && !stoppedOn(x.id))) {
    const who = t.blocked_by || t.assignee;
    cards.push(card(t, "blocked", `Blocked · ${who ? nameOf(who) : "needs you"}`, who,
      `${who ? `<a class="btn small primary" href="#/agents/${who}">Answer</a>` : ""}<a class="btn small" href="#/tasks/${esc(t.id)}">Open task</a>`));
  }
  for (const t of tasks.filter((x) => x.status === "ready-for-review")) {
    cards.push(card(t, "review", `Ready for review${t.dev ? ` · ${nameOf(t.dev)} finished it` : ""}`, t.dev, reviewLink(t, true) + handButtons(t, 2, false)));
  }
  for (const t of tasks.filter((x) => x.status === "changes-requested" && !stoppedOn(x.id) && !state.agents[x.dev]?.status?.match(/working|waiting/))) {
    cards.push(card(t, "rework", "Sent back for changes", t.dev, handButtons(t, 1) + reviewLink(t)));
  }
  for (const t of tasks.filter((x) => x.status === "ready-for-dev")) {
    cards.push(card(t, "dev", "Ready for a dev: who builds it?", "", handButtons(t, 3)));
  }
  if (state.improvements) {
    cards.push(`<article class="need coach"><div class="k">${state.agents.coach ? avatar("coach") : ""} The Coach</div>
      <div class="t">${state.improvements} proposed improvement${state.improvements > 1 ? "s" : ""} to the team's instructions</div>
      <div class="btn-row"><a class="btn small primary" href="#/improvements">See proposals</a></div></article>`);
  }
  const working = Object.values(state.agents).filter((a) => ["working", "waiting"].includes(a.status)).length;
  const moving = tasks.filter((t) => ["draft", "in-dev", "in-review"].includes(t.status));
  const done = tasks.filter((t) => t.status === "done").sort((a, b) => b.updated.localeCompare(a.updated)).slice(0, 5);
  const row = (t) => `<tr><td><a href="#/tasks/${esc(t.id)}"><b>${esc(t.id)}</b> ${esc(t.title)}</a> <span class="muted">· ${esc(t.project_name)}</span></td>
    <td class="right">${statusPill(t.status)}${t.assignee ? ` <span class="muted">${esc(personOf(t.assignee))}</span>` : ""}</td></tr>`;
  return `<div class="page-head"><div><h1>${greeting()}</h1>
      <p>${cards.length ? `${cards.length} thing${cards.length > 1 ? "s" : ""} need${cards.length > 1 ? "" : "s"} you.` : "Nothing needs you right now."}
        ${working ? `${working} agent${working > 1 ? "s are" : " is"} working.` : "No agent is working."}</p></div>
      <a class="btn primary" href="#/agents/${agentIds().find((n) => roleOf(n) === "techlead") || "techlead"}">New task</a></div>
    ${cards.length ? `<div class="needs-grid">${cards.join("")}</div>` : ""}
    <div class="home-cols">
      <section class="card-box"><h2>In progress</h2>${moving.length ? `<table class="plain">${moving.map(row).join("")}</table>` : `<p class="muted">Nothing is being worked on. <a href="#/tasks">Open the board</a>.</p>`}</section>
      <section class="card-box"><h2>Recently done</h2>${done.length ? `<table class="plain">${done.map((t) => `<tr><td><a href="#/tasks/${esc(t.id)}"><b>${esc(t.id)}</b> ${esc(t.title)}</a></td><td class="right">${reviewLink(t)}</td></tr>`).join("")}</table>` : `<p class="muted">Finished tasks show up here.</p>`}</section>
    </div>
    ${tasks.length ? "" : `<div class="empty">Tell the Tech Lead what you need, for example "In ~/code/my-api, users need to reset their password by email." The task will show up here.</div>`}`;
}

// ---- tasks -----------------------------------------------------------------

const taskFilter = { project: "", status: "open", q: "", agent: "" };
const boardView = () => { try { return localStorage.getItem("boardView") || "board"; } catch { return "board"; } };

const COLUMNS = [
  { key: "blocked", label: "Blocked", sub: "needs you", statuses: ["blocked"] },
  { key: "draft", label: "Draft", sub: "Tech Lead", statuses: ["draft"] },
  { key: "ready-for-dev", label: "Ready for dev", sub: "waiting for you", statuses: ["ready-for-dev"] },
  { key: "in-dev", label: "In dev", sub: "Dev", statuses: ["in-dev", "changes-requested"] },
  { key: "ready-for-review", label: "Ready for review", sub: "waiting for you", statuses: ["ready-for-review"] },
  { key: "in-review", label: "In review", sub: "Reviewer", statuses: ["in-review"] },
  { key: "done", label: "Done", sub: "newest first", statuses: ["done"] },
];

function boardCard(t) {
  const who = t.status === "blocked" ? (t.blocked_by || t.assignee) : t.assignee || (t.status === "done" ? t.dev : "");
  const tag = t.status === "blocked" ? `<span class="tag bad">Blocked</span>` : t.status === "changes-requested" ? `<span class="tag warn">Rework</span>` : "";
  const devBusy = ["working", "waiting"].includes(state.agents[t.dev]?.status);
  const actions = t.status === "blocked" ? (who ? `<a class="btn small primary" href="#/agents/${who}">Answer</a>` : "")
    : t.status === "ready-for-review" ? reviewLink(t, true) + handButtons(t, 1, false)
    : t.status === "ready-for-dev" ? handButtons(t, 1)
    : t.status === "changes-requested" && !devBusy ? handButtons(t, 1)
    : t.status === "done" ? reviewLink(t) : "";
  return `<article class="bcard ${t.status === "blocked" ? "blocked" : ""}">
    <a class="cover" href="#/tasks/${esc(t.id)}" aria-label="${esc(t.id)} ${esc(t.title)}"></a>
    <div class="meta"><span>${esc(t.id)}</span>${tag}</div>
    <div class="title">${esc(t.title)}<small>${esc(t.project_name)}</small></div>
    ${who || costText(t.cost) ? `<div class="foot">${who && state.agents[who] ? `${avatar(who)}<span>${esc(personOf(who))}</span>` : ""}<span class="cost">${esc(costText(t.cost))}</span></div>` : ""}
    ${actions ? `<div class="btn-row">${actions}</div>` : ""}</article>`;
}

async function Tasks() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  if (params.get("status")) taskFilter.status = params.get("status");
  const tasks = await api("/api/tasks");
  state.tasks = tasks;
  const view = boardView();
  const projects = [...new Set(tasks.map((t) => t.project_name))].sort();
  const involves = (t, n) => [t.assignee, t.dev, t.reviewer, t.techlead, t.blocked_by].includes(n);
  const matching = tasks.filter((t) =>
    (!taskFilter.project || t.project_name === taskFilter.project) && (!taskFilter.agent || involves(t, taskFilter.agent)) &&
    (!taskFilter.q || `${t.id} ${t.title}`.toLowerCase().includes(taskFilter.q.toLowerCase())));
  const option = (value, label, current) => `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(label)}</option>`;
  const techlead = agentIds().find((n) => roleOf(n) === "techlead") || "techlead";
  const head = `<div class="board-bar"><h1>Board</h1>
      <select id="task-project" aria-label="Project">${option("", "All projects", taskFilter.project)}${projects.map((p) => option(p, p, taskFilter.project)).join("")}</select>
      <select id="task-agent" aria-label="Agent">${option("", "Anyone", taskFilter.agent)}${agentIds().filter((n) => ["techlead", "dev", "reviewer"].includes(roleOf(n))).map((n) => option(n, nameOf(n), taskFilter.agent)).join("")}</select>
      <input type="text" id="task-q" placeholder="Search tasks" value="${esc(taskFilter.q)}" aria-label="Search tasks">
      ${view === "list" ? `<select id="task-status" aria-label="Status">${option("open", "Open tasks", taskFilter.status)}${option("all", "All tasks", taskFilter.status)}${option("blocked", "Blocked", taskFilter.status)}${STAGES.map((s) => option(s.status, s.label, taskFilter.status)).join("")}</select>` : ""}
      <span class="segmented" role="group" aria-label="View">${[["board", "Board"], ["list", "List"]].map(([v, l]) =>
        `<button class="btn small" data-action="board-view" data-view="${v}" aria-pressed="${v === view}">${l}</button>`).join("")}</span>
      <a class="btn primary" href="#/agents/${techlead}">New task</a></div>`;
  if (!tasks.length) return head + `<div class="empty">No tasks yet. Open the Tech Lead and describe what you need.</div>`;

  if (view === "board") {
    const cols = COLUMNS.map((c) => {
      const items = matching.filter((t) => c.statuses.includes(t.status)).sort((a, b) => b.updated.localeCompare(a.updated));
      return `<section class="bcol ${c.key}"><h2>${c.label} <span class="count">${items.length}</span></h2><small>${c.sub}</small>
        <div class="bcards">${items.map(boardCard).join("") || `<p class="none">None</p>`}</div></section>`;
    }).join("");
    return head + `<div class="board">${cols}</div>`;
  }

  const shown = matching.filter((t) => taskFilter.status === "all" || (taskFilter.status === "open" ? t.status !== "done" : t.status === taskFilter.status));
  const unlinked = (await api("/api/costs")).unlinked;
  return head + `${costText(unlinked) ? `<p class="muted">Conversations not linked to any task: ${esc(costText(unlinked))}. <a href="#/history">See Activity</a></p>` : ""}
    ${shown.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Task</th><th>Project</th><th>Stage</th><th>With</th><th>Spec ready</th><th>Cost so far</th><th>Updated</th></tr></thead>
      <tbody>${shown.map((t) => `<tr data-href="#/tasks/${esc(t.id)}">
        <td><a href="#/tasks/${esc(t.id)}"><b>${esc(t.id)}</b></a> ${esc(t.title)}</td>
        <td>${esc(t.project_name)}</td><td>${statusPill(t.status)}</td><td>${esc(holderText(t))}</td>
        <td><span class="ready"><span class="bar" aria-hidden="true"><i style="width:${t.ready.total ? Math.round(100 * t.ready.done / t.ready.total) : 0}%"></i></span>${t.ready.done}/${t.ready.total}</span></td>
        <td class="num">${esc(costText(t.cost)) || '<span class="muted">None yet</span>'}</td>
        <td class="num">${ago(t.updated)}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No tasks match these filters.</div>`}`;
}

const PROMPTS = {
  techlead: (t) => `Let's continue on ${t.id} (${t.title}).`,
  dev: (t) => `Work on ${t.id} per your instructions.`,
  reviewer: (t) => `Review ${t.id} per your instructions.`,
};

// When and how long, in words: "28 Oct, 10:02 → 10:41 (39 min)".
function span(from, to) {
  const a = new Date(from), b = to ? new Date(to) : null;
  const day = a.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  const time = (d) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (!b) return `${day}, ${time(a)}`;
  const mins = Math.max(1, Math.round((b - a) / 60000));
  return `${day}, ${time(a)} → ${time(b)} (${mins < 90 ? `${mins} min` : `${(mins / 60).toFixed(1)} h`})`;
}

function chatsSection(t, list) {
  const rows = list.map((c) => `<li><a href="#/tasks/${esc(t.id)}/chats/${esc(c.name)}"><span class="pill ${roleOf(c.agent)}">${esc(nameOf(c.agent))}</span></a>
      <span class="muted">${span(c.started, c.live ? null : c.finished)}</span>
      ${c.live ? `<span class="pill lead">in progress</span>` : c.outcome ? statusPill(c.outcome) : `<span class="muted">no hand-off</span>`}
      <span class="muted">${c.turns} turn${c.turns === 1 ? "" : "s"}${c.cost_usd ? `, $${c.cost_usd.toFixed(2)}` : ""}</span></li>`).join("");
  return `<section><h2>Who worked on it</h2>
    ${list.length ? `<ul class="chat-list">${rows}</ul>` : `<p class="muted">No conversations recorded yet.</p>`}
    <p class="hint">Each agent's conversation on this task, for debugging. Agents never read these; they work from the task file. Saved in <code>data/tasks/chats/${esc(t.id)}/</code>.</p></section>`;
}

async function TaskChat(r) {
  const c = await api(`/api/tasks/${encodeURIComponent(r.id)}/chats/${encodeURIComponent(r.name)}`);
  return `<p><a href="#/tasks/${esc(r.id)}" class="muted">${esc(r.id)}</a></p>
    <div class="page-head ${roleOf(c.agent)}"><div><h1>${esc(r.id)}: ${esc(nameOf(c.agent))}</h1>
      <p><span class="pill ${roleOf(c.agent)}">${esc(nameOf(c.agent))}</span> ${span(c.started, c.live ? null : c.finished)},
        ${c.live ? "still working on it" : c.outcome ? `handed off as ${statusPill(c.outcome)}` : "no hand-off in this conversation"},
        ${c.turns} turn${c.turns === 1 ? "" : "s"}${c.cost_usd ? `, about $${c.cost_usd.toFixed(2)}` : ""}${c.model ? `, ${esc(c.model)}` : ""}</p></div>
      ${c.live && state.agents[c.agent] ? `<a class="btn role ${roleOf(c.agent)}" href="#/agents/${c.agent}">Open live chat</a>` : ""}</div>
    <div class="transcript ${roleOf(c.agent)}" style="overflow:visible">${transcriptHTML(c.events, { agent: c.agent })}</div>`;
}

const PROGRESS = [["draft", "Draft"], ["ready-for-dev", "Ready for dev"], ["in-dev", "In dev"], ["ready-for-review", "Ready for review"], ["in-review", "In review"], ["done", "Done"]];

function progressLine(t) {
  const where = t.status === "changes-requested" ? "in-dev" : t.status === "blocked" ? (t.activity.find((a) => a.to !== "blocked")?.to || "draft") : t.status;
  const at = PROGRESS.findIndex(([k]) => k === where);
  return `<ol class="progress ${t.status === "blocked" ? "is-blocked" : ""}" aria-label="Progress">${PROGRESS.map(([k, label], i) =>
    `<li class="${i < at ? "done" : i === at ? "now" : ""}" ${i === at ? 'aria-current="step"' : ""}>${i === at && t.status === "changes-requested" ? "Rework" : i === at && t.status === "blocked" ? `${label} · blocked` : label}</li>`).join("")}</ol>`;
}

async function TaskDetail(r) {
  const tab = new URLSearchParams(location.hash.split("?")[1] || "").get("tab") || "spec";
  const [t, chatList] = await Promise.all([api(`/api/tasks/${encodeURIComponent(r.id)}`), api(`/api/tasks/${encodeURIComponent(r.id)}/chats`)]);
  const lr = t.lead_review || {};
  const holder = t.assignee && state.agents[t.assignee];
  const who = (id) => state.agents[id] ? `<a href="#/agents/${id}">${avatar(id)} ${esc(personOf(id))}</a>` : esc(nameOf(id));
  const tabs = [["spec", "Spec"], ["chats", `Conversations${chatList.length ? ` · ${chatList.length}` : ""}`], ...(t.from_commit ? [["reviews", `Your reviews${lr.rounds ? ` · ${lr.rounds}` : ""}`]] : []),
    ["activity", "Activity"], ["cost", `Cost${costText(t.cost) ? ` · ${costText(t.cost)}` : ""}`]];
  let body = "";
  if (tab === "chats") body = chatsSection(t, chatList);
  else if (tab === "activity") {
    const items = t.activity.slice().reverse().map((a) => `<li>${statusPill(a.to)} <span class="muted">${ago(a.ts)}${a.from ? `, from ${esc(stageLabel(a.from))}` : ""}${a.by ? `, ${a.to === "blocked" ? "by" : "with"} ${esc(nameOf(a.by))}` : ""}${a.actor === "lead" ? ", by you" : ""}</span></li>`).join("");
    body = items ? `<ul class="timeline">${items}</ul>` : `<p class="muted">No status changes recorded yet.</p>`;
  } else if (tab === "cost") body = costSection(t.cost);
  else if (tab === "reviews") {
    const rev = await api(`/api/tasks/${encodeURIComponent(t.id)}/review?mode=since`).catch(() => ({ rounds: [] }));
    body = (rev.rounds.length ? rev.rounds.slice().reverse().map((x) => roundCard(x, rev.dev)).join("") : `<p class="muted">You haven't reviewed this code yet.</p>`)
      + `<p><a class="btn primary" href="${reviewHref(t.id)}">Open the code review${lr.drafts ? ` (${lr.drafts} draft${lr.drafts === 1 ? "" : "s"})` : ""}</a></p>`;
  } else body = `<article class="prose">${md(t.markdown)}</article>`;
  return `<div class="task-head"><div class="title"><small>${esc(t.id)} · ${esc(t.project_name)}</small><h1>${esc(t.title)}</h1>
      <p class="muted">${statusPill(t.status)} with ${esc(holderText(t).replace(/^You/, "you"))}</p></div>
      <div class="btn-row">
        ${t.from_commit ? `<a class="btn primary" href="${reviewHref(t.id)}">Review the code${lr.drafts ? ` (${lr.drafts})` : ""}</a>` : ""}
        ${handButtons(t, 2, !t.from_commit)}
        ${holder && !handCandidates(t).includes(t.assignee) ? `<a class="btn" href="#/agents/${t.assignee}">${t.status === "blocked" ? "Answer" : "Open chat with"} ${esc(personOf(t.assignee))}</a>` : ""}
        <details class="menu"><summary class="btn" aria-label="More">⋯</summary><div class="menu-list">
          <button data-action="follow-up" data-task="${esc(t.id)}" data-title="${esc(t.title)}" data-project="${esc(t.project)}">Ask the Tech Lead for a follow-up</button>
          ${agentIds().filter((n) => ["techlead", "dev", "reviewer"].includes(roleOf(n))).map((n) => `<button data-action="handoff" data-agent="${n}" data-task="${esc(t.id)}" data-title="${esc(t.title)}">Draft a message to ${esc(nameOf(n))}</button>`).join("")}
        </div></details></div></div>
    ${progressLine(t)}
    <div class="task-layout">
      <div><nav class="tabs" aria-label="Task">${tabs.map(([k, label]) => `<a href="#/tasks/${esc(t.id)}${k === "spec" ? "" : `?tab=${k}`}" ${k === tab ? 'aria-current="page"' : ""}>${esc(label)}</a>`).join("")}</nav>${body}</div>
      <aside class="task-side">
        <section class="side-box"><h3>People</h3><dl class="kv people">
          <dt>Spec</dt><dd>${t.techlead ? who(t.techlead) : "—"}</dd><dt>Built</dt><dd>${t.dev ? who(t.dev) : "Not yet"}</dd><dt>Review</dt><dd>${t.reviewer ? who(t.reviewer) : "Not yet"}</dd></dl></section>
        <section class="side-box"><h3>Code</h3><dl class="kv">
          ${t.branch ? `<dt>Branch</dt><dd><code>${esc(t.branch)}</code></dd>` : ""}<dt>Base</dt><dd><code>${esc(t.base || "main")}</code></dd>
          ${t.worktree ? `<dt>Worktree</dt><dd><code title="${esc(t.worktree)}">…/${esc(t.worktree.split("/").slice(-2).join("/"))}</code></dd>` : ""}
          ${t.from_commit ? `<dt>Your reviews</dt><dd>${lr.rounds ? `${lr.rounds}, last at <code>${esc(lr.last.slice(0, 7))}</code>` : "None yet"}</dd>` : ""}</dl></section>
        ${t.same_branch.length || t.follows ? `<section class="side-box"><h3>Same feature</h3><ul class="side-list">
          ${t.follows ? `<li>Follows <a href="#/tasks/${esc(t.follows)}">${esc(t.follows)}</a></li>` : ""}
          ${t.same_branch.map((o) => `<li><a href="#/tasks/${esc(o.id)}">${esc(o.id)} ${esc(o.title)}</a> ${statusPill(o.status)}</li>`).join("")}</ul></section>` : ""}
        <section class="side-box"><h3>Details</h3><dl class="kv">
          <dt>Project</dt><dd><code title="${esc(t.project)}">${esc(t.project_name)}</code></dd><dt>Priority</dt><dd>${esc(t.priority || "—")}</dd>
          <dt>Created</dt><dd>${esc(t.created || "—")}</dd><dt>Approved</dt><dd>${esc(t.approved || "Not yet")}</dd>
          <dt>Spec ready</dt><dd>${t.ready.done} of ${t.ready.total} checks</dd><dt>File</dt><dd><code>${esc(t.path.split("/").pop())}</code></dd></dl></section>
      </aside>
    </div>`;
}

function costSection(c) {
  if (!c || !c.rows.length) return `<p class="muted">Nothing spent on this task yet.</p>`;
  const rows = c.rows.map((r) => `<tr><td>${esc(r.model)}<br><small class="muted">${esc(providerOf(r.provider).label)}</small></td>
      <td><span class="pill ${roleOf(r.agent)}">${esc(nameOf(r.agent))}</span></td>
      <td class="num">${tokens(r.tokens_in + r.tokens_out)}</td>
      <td class="num">${r.unpriced_tokens && !r.cost_usd ? '<a href="#/settings">Set price</a>' : money(r.cost_usd)}</td></tr>`).join("");
  return `<p class="cost-total">${esc(costText(c) || money(0))}</p>
    <div class="table-wrap"><table class="cost-table"><thead><tr><th>Model</th><th>Agent</th><th>Tokens</th><th>Cost</th></tr></thead>
    <tbody>${rows}</tbody></table></div>
    <p class="hint">From the Tech Lead's spec to the review, every agent turn on this task. Claude costs are Claude Code's own figures; other models use the prices in Settings.</p>`;
}

// ---- agent chat ----------------------------------------------------------------

// The task whose code a dev or reviewer is on (or last worked on), for the "Review the code" button.
async function codeTaskOf(name) {
  if (!["dev", "reviewer"].includes(roleOf(name))) return null;
  const tasks = (await api("/api/tasks")).filter((t) => t.from_commit && t[roleOf(name)] === name);
  return tasks.find((t) => t.assignee === name) || tasks.sort((a, b) => b.updated.localeCompare(a.updated))[0] || null;
}

async function AgentChat(r) {
  const name = r.id;
  if (!state.agents[name]) throw new Error("There's no agent with that name. It may have been removed in Settings.");
  reportWatching();
  const [, task] = await Promise.all([loadLive(name), codeTaskOf(name).catch(() => null)]);
  state.codeTask[name] = task;
  const a = ROLES[roleOf(name)];
  if (!state.tasks) await refreshCounts();
  return `<div class="chat-layout ${roleOf(name)}">
   <div class="chat-page">
    <header class="agent-head" id="agent-head"></header>
    <div class="transcript" id="transcript"><div id="tx-events"></div><div id="tx-live" aria-live="polite"></div></div>
    <div id="pinned-asks"></div>
    <form class="composer" id="composer">
      <div class="quick">${a.quick.map((q) => `<button type="button" class="chip-btn" data-action="quick" data-text="${esc(q)}">${esc(q)}</button>`).join("")}</div>
      <div class="compose-box"><textarea id="composer-text" rows="2" aria-label="Message ${esc(nameOf(name))}"
        placeholder="${roleOf(name) === "techlead" ? "Describe what you need, and in which project folder." : `Message ${esc(personOf(name))}… (Enter to send, Shift+Enter for a new line, # for a task)`}">${esc(state.drafts[name] || "")}</textarea>
        <button class="btn primary" type="submit" id="send">Send</button></div>
      <ul class="suggest" id="task-suggest" hidden></ul>
    </form>
   </div>
   <aside class="chat-side" id="chat-side"></aside></div>`;
}

// The panel next to a chat: the task it's on, this conversation, what it did before (or, for the Orchestrator
// and the Coach, what's waiting on you).
// It can be folded away to a thin strip (remembered in this browser, for every agent).
const PANEL_ICON = (arrow) => `<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1.5"/><path d="M10 2.8v10.4M${arrow}"/></svg>`;
const SIDE_HEAD = `<div class="side-head"><button class="icon-btn" data-action="chat-side" aria-label="Hide the details" title="Hide the details">${PANEL_ICON("5.5 6.2 7.3 8 5.5 9.8")}</button></div>`;
function chatSideShown() {
  try { return localStorage.getItem("chatSide") !== "hidden"; } catch { return true; }
}
function renderChatSide(name) {
  const side = document.getElementById("chat-side");
  if (!side) return;
  side.closest(".chat-layout")?.classList.toggle("side-closed", !chatSideShown());
  if (!chatSideShown()) {
    side.innerHTML = `<button class="tree-strip side-strip" data-action="chat-side" aria-label="Show the details" title="Show the details">${PANEL_ICON("7.3 6.2 5.5 8 7.3 9.8")}<span>Details</span></button>`;
    return;
  }
  const role = roleOf(name);
  const events = state.live[name] || [];
  const cost = events.filter((e) => e.kind === "result").reduce((n, e) => n + (e.cost_usd || 0), 0);
  const started = events.find((e) => e.ts)?.ts;
  const convo = `<section class="side-box"><h3>This conversation</h3>
      <dl class="kv"><dt>Started</dt><dd>${started ? esc(ago(started)) : "Not yet"}</dd><dt>Cost</dt><dd>${cost ? money(cost) : "Nothing yet"}</dd></dl>
      ${state.agents[name]?.status !== "stopped" ? `<button class="btn small" data-action="new" data-agent="${name}">New conversation</button>` : ""}</section>`;
  if (role === "orchestrator" || role === "coach") {
    const asks = Object.entries(state.agents).flatMap(([n, a]) => (a.pending || []).map((p) => ({ n, p })));
    const extra = role === "coach"
      ? `<section class="side-box"><h3>Improvements</h3><p>${state.improvements ? `${state.improvements} proposal${state.improvements > 1 ? "s" : ""} waiting for you.` : "No proposals waiting."}</p>
          <a class="btn small primary" href="#/improvements">${state.improvements ? "Review them" : "Start a review"}</a></section>`
      : `<section class="side-box"><h3>Waiting for you</h3>${asks.length ? `<ul class="side-list">${asks.map(({ n, p }) =>
          `<li><a href="#/agents/${n}">${esc(personOf(n))}</a>: ${esc(toolArg(p.tool, p.input).slice(0, 70))}</li>`).join("")}</ul>` : `<p class="muted">No approvals waiting.</p>`}
          <p class="muted">${needsCount()} thing${needsCount() === 1 ? "" : "s"} on <a href="#/">Home</a>.</p></section>`;
    side.innerHTML = SIDE_HEAD + extra + convo;
    return;
  }
  const t = busyWith(name) || state.codeTask[name];
  const field = role === "techlead" ? "techlead" : role;
  const earlier = (state.tasks || []).filter((x) => x[field] === name && x.id !== t?.id).sort((a, b) => b.updated.localeCompare(a.updated)).slice(0, 5);
  side.innerHTML = SIDE_HEAD + `${t ? `<section class="side-box"><h3>Task</h3><a class="side-title" href="#/tasks/${esc(t.id)}"><b>${esc(t.id)}</b> ${esc(t.title)}</a>
      <dl class="kv"><dt>Status</dt><dd>${statusPill(t.status)}</dd>${t.branch ? `<dt>Branch</dt><dd><code>${esc(t.branch)}</code></dd>` : ""}${t.base ? `<dt>Base</dt><dd><code>${esc(t.base)}</code></dd>` : ""}</dl>
      <div class="btn-row"><a class="btn small" href="#/tasks/${esc(t.id)}">Open task</a>${t.from_commit ? `<a class="btn small" href="${reviewHref(t.id)}">Diff</a>` : ""}</div></section>`
      : `<section class="side-box"><h3>Task</h3><p class="muted">Not on a task right now.</p></section>`}
    ${convo}
    ${earlier.length ? `<section class="side-box"><h3>Earlier tasks</h3><ul class="side-list">${earlier.map((x) =>
      `<li><a href="#/tasks/${esc(x.id)}">${esc(x.id)} ${esc(x.title)}</a> <span class="muted">${esc(stageLabel(x.status).toLowerCase())}</span></li>`).join("")}</ul></section>` : ""}`;
}

function renderAgentChrome(name) {
  const head = document.getElementById("agent-head");
  if (!head) return;
  const ag = state.agents[name] || { status: "stopped" };
  const running = ag.status !== "stopped";
  const busy = ag.status === "working" || ag.status === "waiting";
  const prov = providerOf(choiceOf(name).provider);
  const needsKey = prov.engine !== "claude" && !prov.has_key;
  const now = busyWith(name);
  const task = state.codeTask[name];
  const role = roleOf(name);
  const pill = { stopped: "Stopped", starting: "Starting", idle: "Ready", working: "Working", waiting: "Needs you" }[ag.status];
  head.innerHTML = `${avatar(name, "big")}
    <div class="title"><h1>${esc(personOf(name))} <span class="state-pill ${ag.status}">${pill}</span></h1>
      <p>${esc(OWNER_LABEL[role])}${now ? ` · on <a href="#/tasks/${esc(now.id)}"><b>${esc(now.id)}</b> ${esc(now.title)}</a>` : role === "orchestrator" ? " · your assistant, also in Slack" : ""}
        · <a class="model-tag" href="#/settings/team" title="Change it in Settings → Team">${esc(modelLabel(name).replace(", ", " · "))} ↗</a>
        ${needsKey ? ` · <span class="warn">no ${esc(prov.label)} key: <a href="#/settings/models">add it</a></span>` : ""}</p></div>
    <div class="btn-row head-actions">
      ${task && ["dev", "reviewer"].includes(role) ? `<a class="btn primary" href="${reviewHref(task.id)}" title="${esc(task.title)}">Review the code</a>` : ""}
      ${busy ? `<button class="btn" data-action="interrupt" data-agent="${name}">Interrupt</button>` : ""}
      ${running ? `<button class="btn" data-action="stop" data-agent="${name}">Stop</button>` : `<button class="btn primary" data-action="start" data-agent="${name}">Start</button>`}
      <details class="menu"><summary class="btn" aria-label="More">⋯</summary><div class="menu-list">
        <button data-action="rename" data-agent="${name}">Rename</button>
        ${running ? `<button data-action="new" data-agent="${name}">New conversation (like /clear)</button>` : ""}
        <a href="#/settings/team">Model and approvals</a>
        ${["techlead", "dev", "reviewer"].includes(role) ? `<button data-action="show-inbox" data-agent="${name}">Its inbox (for debugging)</button>` : ""}
      </div></details>
    </div>`;
  const send = document.getElementById("send");
  if (send) send.disabled = busy;
  renderTranscriptInto(name);
  renderChatSide(name);
}

function renderTranscriptInto(name) {
  const box = document.getElementById("transcript");
  if (!box) return;
  const atBottom = nearBottom(box);
  const ag = state.agents[name] || {};
  document.getElementById("tx-events").innerHTML = transcriptHTML(state.live[name] || [], { pending: ag.pending || [], agent: name, pinned: true })
    || `<div class="msg system">${ag.status === "stopped" ? "This agent isn't running. Press Start, or just send a message and it will start." : "No messages yet."}</div>`;
  const pinned = document.getElementById("pinned-asks");
  if (pinned) {
    const reqs = (state.live[name] || []).filter((e) => e.kind === "permission" && (ag.pending || []).some((p) => p.id === e.id));
    pinned.innerHTML = reqs.map((e, i) => askCard(e, name, i === 0)).join("");
  }
  renderLive(name, atBottom);
}

const nearBottom = (box) => box.scrollHeight - box.scrollTop - box.clientHeight < 120;

// What the agent is doing right now: streamed thinking, the reply being written, the next tool.
function renderLive(name, stick) {
  const box = document.getElementById("transcript");
  const live = document.getElementById("tx-live");
  if (!box || !live) return;
  const atBottom = stick ?? nearBottom(box);
  const ag = state.agents[name] || {};
  const s = state.stream[name] || emptyStream();
  let html = "";
  if (ag.status === "working" || ag.status === "starting") {
    if (s.thinking) html += `<details class="thinking live" open><summary>Thinking</summary><div class="thought">${esc(s.thinking.slice(-1500))}</div></details>`;
    if (s.text) html += `<div class="msg agent prose">${md(s.text)}</div>`;
    if (s.tool) html += `<div class="hint step">Preparing ${esc(s.tool)}</div>`;
    html += `<div class="working"><span class="status working"></span><span>${s.text ? "Writing" : s.thinking ? "Thinking" : s.tool ? "About to run a tool" : "Working"}<span class="elapsed" data-agent="${name}"></span></span>
      <button class="btn small" data-action="interrupt" data-agent="${name}">Interrupt</button></div>`;
  }
  live.innerHTML = html;
  tick();
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function tick() {
  document.querySelectorAll(".elapsed").forEach((el) => {
    const since = state.since[el.dataset.agent];
    if (!since) { el.textContent = ""; return; }
    const secs = Math.max(0, Math.round((Date.now() - since) / 1000));
    el.textContent = secs < 60 ? ` for ${secs} s` : ` for ${Math.floor(secs / 60)} min ${secs % 60} s`;
  });
}
setInterval(tick, 1000);

// Catch up after a dropped connection, a sleeping laptop or a background tab.
async function resync() {
  try {
    await loadState();
    const r = route();
    if (r.page === "agent") {
      await loadLive(r.id);
      const ag = state.agents[r.id];
      if (["working", "waiting"].includes(ag?.status) && !state.since[r.id]) {
        const lastUser = [...(state.live[r.id] || [])].reverse().find((e) => e.kind === "user");
        state.since[r.id] = lastUser ? new Date(lastUser.ts).getTime() : Date.now();
      }
      renderAgentChrome(r.id);
    } else {
      refreshIf(["overview", "tasks", "task"]);
    }
  } catch { /* the connection indicator shows the problem */ }
}

// Safety net: if the live feed missed something, notice within a few seconds.
setInterval(async () => {
  const r = route();
  if (document.hidden || r.page !== "agent") return;
  try {
    const data = await api("/api/state");
    const fresh = data.agents.find((a) => a.name === r.id);
    const known = state.agents[r.id];
    const sid = fresh?.session_id;
    const count = sid ? (await api(`/api/sessions/${sid}`)).events.length : 0;
    if (JSON.stringify(fresh) !== JSON.stringify(known) || count !== (state.live[r.id] || []).length) resync();
  } catch { /* ignore */ }
}, 6000);
document.addEventListener("visibilitychange", () => { if (!document.hidden) { resync(); reportWatching(); } });

// While an agent's chat is on screen, tell the server, so it doesn't notify you (Slack, Home) when that agent
// stops to ask you something: you're already looking at it.
function reportWatching() {
  const r = route();
  if (r.page === "agent" && !document.hidden && state.agents[r.id]) {
    api(`/api/agents/${r.id}/watching`, { method: "POST" }).catch(() => { /* next time */ });
  }
}
setInterval(reportWatching, 10000);
addEventListener("hashchange", reportWatching);

function askCard(e, agent, first = false) {
  return `<div class="ask" data-pid="${esc(e.id)}"><h3>${esc(nameOf(agent))} wants to ${e.tool === "Team action" ? "do this" : e.tool === "Bash" ? "run a command" : `use ${esc(e.tool)}`}</h3>
    <pre>${esc(toolDetail(e.tool, e.input))}</pre>
    <input type="text" class="reason" placeholder="Optional: tell the agent why you deny it" aria-label="Reason">
    <div class="btn-row">
      <button class="btn primary" data-action="allow" data-decision="allow" data-agent="${agent}" data-pid="${esc(e.id)}">Allow${first ? " <kbd>⏎</kbd>" : ""}</button>
      <button class="btn" data-action="allow" data-decision="always" data-agent="${agent}" data-pid="${esc(e.id)}">${e.tool === "Team action" ? "Allow all team actions for this session" : `Allow ${esc(e.tool)} for this session`}</button>
      <button class="btn danger" data-action="allow" data-decision="deny" data-agent="${agent}" data-pid="${esc(e.id)}">Deny${first ? " <kbd>Esc</kbd>" : ""}</button>
    </div></div>`;
}

// A run of tool calls in one line: "Read 4 files, ran 2 commands · 12 s". Click to see each one.
const TOOL_WORDS = { Read: ["read", "file"], Grep: ["searched", "time"], Glob: ["searched", "time"], Edit: ["edited", "file"], MultiEdit: ["edited", "file"],
  Write: ["wrote", "file"], Bash: ["ran", "command"], WebFetch: ["fetched", "page"], WebSearch: ["searched the web", "time"], TodoWrite: ["updated the plan", "time"] };
function toolRunSummary(tools, results) {
  const counts = new Map();
  for (const t of tools) {
    const [verb, noun] = TOOL_WORDS[t.name] || [`used ${t.name}`, "time"];
    const key = `${verb}|${noun}`;
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const parts = [...counts].map(([key, n]) => {
    const [verb, noun] = key.split("|");
    return noun === "time" && n === 1 ? verb : `${verb} ${n} ${noun}${n > 1 ? "s" : ""}`;
  });
  const text = parts.join(", ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function toolItem(e, results) {
  const res = results[e.id];
  const open = state.openTools.has(e.id) ? "open" : "";
  return `<details class="tool ${res?.is_error ? "failed" : ""}" data-tool="${esc(e.id)}" ${open}>
    <summary><span class="name">${esc(e.name)}</span><span class="arg">${esc(toolArg(e.name, e.input))}</span><span class="state">${res ? (res.is_error ? "Failed" : "Done") : "Running"}</span></summary>
    <pre>${esc(res ? res.text || "(no output)" : toolDetail(e.name, e.input))}</pre></details>`;
}

// ---- A round of the Tech Lead's questions, as cards (or as the text it wrote) ----------------
// The Tech Lead writes its round as text, between <!-- hive-questions {json} --> and <!-- /hive-questions -->; the
// JSON holds the same questions for the cards. Text outside the round is shown as it is, and each question opens to
// everything written about it, so the cards lose nothing; the switch shows the message exactly as written.
const QUESTIONS = /<!--\s*hive-questions\s+([\s\S]*?)-->([\s\S]*?)<!--\s*\/hive-questions\s*-->/;
const questionsView = () => { try { return localStorage.getItem("questionsView") || "cards"; } catch { return "cards"; } };

function parseQuestions(text) {
  const m = text.match(QUESTIONS);
  if (!m) return null;
  try {
    const q = JSON.parse(m[1]);
    if (!Array.isArray(q.questions)) return null;
    return { ...q, decisions: q.decisions || [], before: text.slice(0, m.index), after: text.slice(m.index + m[0].length) };
  } catch { return null; }
}

function questionsState(key, q) {
  state.questions ??= {};
  return (state.questions[key] ??= {
    pick: Object.fromEntries(q.questions.map((x) => [x.id, x.suggested ?? x.options?.[0]?.key ?? ""])),
    notes: {}, disagree: {}, open: new Set(["preview"]), sent: false });   // the reply shows until folded
}

// The reply the lead sends: self-contained (each question named), so it reads well in the chat and in Clarifications.
// An option as the lead reads it: "B: keep a read-only GET" (a label that already starts with its letter isn't doubled).
function optionText(o) {
  const label = o.label.replace(new RegExp(`^\\s*${o.key.replace(/[^\w]/g, "")}\\s*[.):\\-–]\\s*`, "i"), "").trim();
  return o.key.length === 1 ? `${o.key.toUpperCase()}: ${label}` : label;
}

// A note that starts with another option's letter ("B. keep it") was meant as that answer: say so before sending.
function noteNamesOtherOption(x, s) {
  const m = (s.notes[x.id] || "").match(/^\s*([a-z])(?:\s*[.):\-–]|\s+|$)/i);
  const other = m && (x.options || []).find((o) => o.key.toLowerCase() === m[1].toLowerCase());
  return other && other.key !== s.pick[x.id] ? other : null;
}

// The reply: one block per question, the answer on its own line, a note apart (it adds to the answer, never changes it).
function questionsReply(q, s) {
  const lines = [`Answers to ${q.round != null ? `round ${q.round}` : "your questions"} (each "Answer:" is my choice; a "Note:" adds to it, it doesn't change it):`];
  q.questions.forEach((x, i) => {
    const pick = s.pick[x.id], opt = (x.options || []).find((o) => o.key === pick);
    const note = (s.notes[x.id] || "").trim();
    lines.push("", `${i + 1}. ${x.title}`);
    if (pick === "own") lines.push(`   Answer (in my words): ${note || "(none yet)"}`);
    else {
      lines.push(`   Answer: ${opt ? optionText(opt) : pick}`);
      if (note) lines.push(`   Note: ${note}`);
    }
  });
  if (q.decisions.length) lines.push("");
  const against = q.decisions.map((d, i) => [d, s.disagree[i]]).filter(([, v]) => v !== undefined);
  if (q.decisions.length) {
    const ok = q.decisions.length - against.length;
    lines.push(against.length === 0 ? `Decisions: ${q.decisions.length === 1 ? "accepted" : `all ${q.decisions.length} accepted`}.`
      : `Decisions: ${ok ? `${ok} accepted, ` : ""}${against.length === 1 && !ok ? "not accepted" : `${against.length} not`}:`);
    for (const [d, v] of against) lines.push(`- ${d} → instead: ${v.trim() || "(say what)"}`);
  }
  return lines.join("\n");
}

// One line of an agent's Markdown with only its `code` kept (titles and their first line of context).
const inlineCode = (text) => esc(text.replace(/\*\*|__/g, "")).replace(/`([^`]+)`/g, "<code>$1</code>");

function questionsMessage(e, agent, answered) {
  const q = parseQuestions(e.text);
  const cards = questionsView() === "cards";
  const toggle = `<button class="link q-view" data-action="questions-view">${cards ? "Show as text" : "Show as cards"}</button>`;
  if (!q || !cards) return `<div class="msg agent prose">${md(e.text)}</div>${q ? `<p class="q-switch">${toggle}</p>` : ""}`;
  const key = `${agent}|${e.ts}`, s = questionsState(key, q), done = answered || s.sent;
  const rows = q.questions.map((x, i) => {
    const first = (x.details || "").split("\n").find((l) => l.trim()) || "";
    const opts = [...(x.options || []), { key: "own", label: "…", title: "Answer in your own words" }];
    const seg = done ? "" : `<span class="seg">${opts.map((o) => `<button type="button" class="${s.pick[x.id] === o.key ? "on" : ""} ${x.suggested === o.key ? "sug" : ""}"
        data-action="question-pick" data-q="${esc(key)}" data-id="${esc(x.id)}" data-key="${esc(o.key)}" title="${esc(o.title || o.label)}${x.suggested === o.key ? " (suggested)" : ""}">${esc(o.key === "own" ? "…" : o.label.length <= 12 ? o.label : o.key.toUpperCase())}</button>`).join("")}</span>`;
    return `<details class="qrow" data-q="${esc(key)}" data-id="${esc(x.id)}" ${s.open.has(x.id) || s.pick[x.id] === "own" ? "open" : ""}>
      <summary><span class="n">${i + 1}</span><span class="t">${inlineCode(x.title)}<small>${inlineCode(first)}</small></span>${seg}</summary>
      <div class="qbody">${x.details ? `<div class="prose">${md(x.details)}</div>` : ""}
        ${(x.options || []).length ? `<ul class="q-options">${x.options.map((o) => `<li>${esc(optionText(o))}${x.suggested === o.key ? ` <span class="muted">(suggested)</span>` : ""}</li>`).join("")}</ul>` : ""}
        ${done ? "" : `<input class="q-note" data-q="${esc(key)}" data-id="${esc(x.id)}" value="${esc(s.notes[x.id] || "")}"
          placeholder="${s.pick[x.id] === "own" ? "Your answer, in your own words" : "A note that goes with your answer (optional; to answer differently, pick another option)"}">
          <p class="q-mismatch" data-q="${esc(key)}" data-id="${esc(x.id)}">${mismatchHtml(x, s, key)}</p>`}</div></details>`;
  }).join("");
  const decisions = q.decisions.length ? `<details class="q-decisions" ${s.open.has("decisions") ? "open" : ""} data-q="${esc(key)}" data-id="decisions">
      <summary>${plural(q.decisions.length, "decision")}, accepted unless you say otherwise</summary>
      <ul>${q.decisions.map((d, i) => `<li><span class="prose">${md(d)}</span>${done ? "" : s.disagree[i] === undefined
        ? `<button type="button" class="link" data-action="question-disagree" data-q="${esc(key)}" data-i="${i}">Disagree</button>`
        : `<input class="q-against" data-q="${esc(key)}" data-i="${i}" value="${esc(s.disagree[i])}" placeholder="What should it be?"><button type="button" class="link" data-action="question-disagree" data-q="${esc(key)}" data-i="${i}">Keep it</button>`}</li>`).join("")}</ul></details>` : "";
  return `${q.before.trim() ? `<div class="msg agent prose">${md(q.before)}</div>` : ""}
    <div class="qcard ${done ? "done" : ""}" data-q="${esc(key)}">
      <div class="q-head"><b>Round ${esc(String(q.round ?? ""))}</b><span class="muted">${plural(q.questions.length, "question")}${done ? " · answered" : ""}</span>${toggle}</div>
      ${rows}${decisions}
      ${done ? "" : `<details class="q-preview" ${s.open.has("preview") ? "open" : ""} data-q="${esc(key)}" data-id="preview"><summary>Message to ${esc(personOf(agent))}</summary><pre class="q-reply" data-q="${esc(key)}">${esc(questionsReply(q, s))}</pre></details>
      <div class="q-foot"><span class="muted">Suggested answers are preselected.</span><button type="button" class="btn primary small" data-action="question-send" data-q="${esc(key)}" data-agent="${esc(agent)}">Send</button></div>`}
    </div>
    ${q.after.trim() ? `<div class="msg agent prose">${md(q.after)}</div>` : ""}`;
}

// The card's question, from the transcript on screen (the message's text is in the page's state).
function questionsOf(key) {
  const [agent, ts] = key.split("|");
  const e = (state.questionEvents ?? new Map()).get(key);
  return e ? parseQuestions(e.text) : null;
}

function mismatchHtml(x, s, key) {
  const other = noteNamesOtherOption(x, s);
  if (!other) return "";
  const picked = (x.options || []).find((o) => o.key === s.pick[x.id]);
  return `Your note starts with ${esc(other.key.toUpperCase())}, but the answer selected is ${esc(picked ? picked.key.toUpperCase() : "your own")}.
    <button type="button" class="link" data-action="question-pick" data-q="${esc(key)}" data-id="${esc(x.id)}" data-key="${esc(other.key)}">Answer ${esc(other.key.toUpperCase())}</button>`;
}

function refreshReply(key) {
  const q = questionsOf(key), pre = document.querySelector(`.q-reply[data-q="${CSS.escape(key)}"]`);
  if (q && pre) pre.textContent = questionsReply(q, state.questions[key]);
}

function transcriptHTML(events, { pending = [], agent = "", pinned = false } = {}) {
  const results = {}, decisions = {};
  for (const e of events) {
    if (e.kind === "tool_result") results[e.id] = e;
    if (e.kind === "decision") decisions[e.id] = e;
  }
  const pendingIds = new Set(pending.map((p) => p.id));
  // fold each run of consecutive tool calls into one line
  const items = [];
  for (const e of events) {
    if (e.kind === "tool_result" || e.kind === "decision") continue;
    if (e.kind === "tool" && items.at(-1)?.kind === "tool-run") items.at(-1).tools.push(e);
    else if (e.kind === "tool") items.push({ kind: "tool-run", tools: [e] });
    else items.push(e);
  }
  return items.map((e, i) => {
    if (e.kind === "text" && agent && QUESTIONS.test(e.text)) {
      (state.questionEvents ??= new Map()).set(`${agent}|${e.ts}`, e);
      const answered = items.slice(i + 1).some((x) => x.kind === "user");
      return questionsMessage(e, agent, answered);
    }
    if (e.kind === "tool-run") {
      const failed = e.tools.filter((t) => results[t.id]?.is_error).length;
      const running = e.tools.find((t) => !results[t.id]);
      const secs = e.tools.length && e.tools[0].ts && results[e.tools.at(-1).id]?.ts
        ? Math.round((new Date(results[e.tools.at(-1).id].ts) - new Date(e.tools[0].ts)) / 1000) : null;
      const key = `run-${e.tools[0].id}`;
      return `<details class="tool-run ${failed ? "failed" : ""}" data-tool="${esc(key)}" ${state.openTools.has(key) ? "open" : ""}>
        <summary><span>${esc(toolRunSummary(e.tools, results))}${failed ? `, <b>${failed} failed</b>` : ""}${running ? ` · <span class="muted">running ${esc(running.name)}…</span>` : ""}</span>
          <span class="state">${secs !== null && secs >= 1 ? `${secs} s` : ""}</span></summary>
        <div class="run-items">${e.tools.map((t) => toolItem(t, results)).join("")}</div></details>`;
    }
    switch (e.kind) {
      case "user": return `<div class="msg user">${esc(e.text)}</div>`;
      case "text": return `<div class="msg agent prose">${md(e.text)}</div>`;
      case "thinking": return `<details class="thinking"><summary>Thought process</summary><div class="thought">${esc(e.text)}</div></details>`;
      case "system": return `<div class="msg system">${esc(e.text.replace(/\.$/, ""))}, ${ago(e.ts)}</div>`;
      case "error": return `<div class="msg error">Something went wrong: ${esc(e.text)}</div>`;
      case "result": return `<div class="msg result">Finished in ${(e.duration_ms / 1000).toFixed(1)} s${e.cost_usd ? `, about $${e.cost_usd.toFixed(3)}` : ""}${e.tokens_in ? `, ${(e.tokens_in + e.tokens_out).toLocaleString()} tokens` : ""}${e.is_error ? ", with an error" : ""}</div>`;
      case "tool": {   // not reached (tools are folded into runs), kept for safety
        const res = results[e.id];
        const open = state.openTools.has(e.id) ? "open" : "";
        return `<details class="tool ${res?.is_error ? "failed" : ""}" data-tool="${esc(e.id)}" ${open}>
          <summary><span class="name">${esc(e.name)}</span><span class="arg">${esc(toolArg(e.name, e.input))}</span><span class="state">${res ? (res.is_error ? "Failed" : "Done") : "Running"}</span></summary>
          <pre>${esc(res ? res.text || "(no output)" : toolDetail(e.name, e.input))}</pre></details>`;
      }
      case "permission": {
        const d = decisions[e.id];
        if (d) return `<div class="answered">${d.decision === "deny" ? "You denied" : d.decision === "always" ? "You allowed (for the rest of this session)" : "You allowed"} ${esc(e.tool)}${d.message ? `: ${esc(d.message)}` : ""}</div>`;
        if (!pendingIds.has(e.id)) return `<div class="answered">Request for ${esc(e.tool)} expired.</div>`;
        return pinned ? `<div class="answered">Waiting for your answer below.</div>` : askCard(e, agent);
      }
      default: return "";
    }
  }).join("");
}

// ---- history ------------------------------------------------------------------

const activityFilter = { project: "", agent: "", status: "" };

// ---- Finance: where the money went, per task, per day or month, with filters ------------------------
const financeFilter = { range: "30d", from: "", to: "", by: "day", agent: "", model: "", project: "", q: "" };
const dayKey = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const RANGES = [["7d", "Last 7 days"], ["30d", "Last 30 days"], ["90d", "Last 90 days"], ["month", "This month"], ["lastmonth", "Last month"], ["year", "This year"], ["all", "All time"], ["custom", "Custom…"]];

// The first and last day (YYYY-MM-DD) the range covers; "" means open.
function financeSpan(f, lines) {
  const today = new Date(), t = dayKey(today);
  const back = (n) => { const d = new Date(today); d.setDate(d.getDate() - (n - 1)); return dayKey(d); };
  if (f.range === "7d") return [back(7), t];
  if (f.range === "30d") return [back(30), t];
  if (f.range === "90d") return [back(90), t];
  if (f.range === "month") return [`${t.slice(0, 7)}-01`, t];
  if (f.range === "lastmonth") { const d = new Date(today.getFullYear(), today.getMonth() - 1, 1), e = new Date(today.getFullYear(), today.getMonth(), 0); return [dayKey(d), dayKey(e)]; }
  if (f.range === "year") return [`${t.slice(0, 4)}-01-01`, t];
  if (f.range === "custom") return [f.from || (lines[0]?.ts.slice(0, 10) ?? t), f.to || t];
  return [lines[0]?.ts.slice(0, 10) ?? t, t];
}
const usd = (x) => (x > 0 && x < 0.01 ? "<$0.01" : `$${(x || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`);
const niceMax = (v) => { if (v <= 0) return 1; const p = 10 ** Math.floor(Math.log10(v)); const n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p; };

async function Finance() {
  const [{ lines: all }, tasks] = await Promise.all([api("/api/finance"), api("/api/tasks")]);
  const f = financeFilter;
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const projectOfTask = (id) => byId[id]?.project_name || byId[id]?.project?.split("/").pop() || "";
  const [from, to] = financeSpan(f, all);
  const q = f.q.trim().toLowerCase();
  const lines = all.filter((l) => { const d = l.ts.slice(0, 10);
    return d >= from && d <= to && (!f.agent || l.agent === f.agent) && (!f.model || l.model === f.model)
      && (!f.project || (l.task && projectOfTask(l.task) === f.project))
      && (!q || (l.task && (l.task.toLowerCase().includes(q) || (byId[l.task]?.title || "").toLowerCase().includes(q)))); });
  state.financeLines = lines;
  const sum = (ls) => ls.reduce((a, l) => a + (l.cost_usd || 0), 0);
  const total = sum(lines);
  const unpriced = lines.filter((l) => l.cost_usd === null).reduce((a, l) => a + l.tokens, 0);
  const unlinked = sum(lines.filter((l) => !l.task));

  // buckets for the chart and the period table: every day (or month) in the range, empty ones too
  const by = f.by;
  const buckets = new Map();
  for (let d = new Date(`${from}T00:00`); dayKey(d) <= to; d.setDate(d.getDate() + 1)) {
    const k = by === "month" ? dayKey(d).slice(0, 7) : dayKey(d);
    if (!buckets.has(k)) buckets.set(k, { key: k, cost: 0, tasks: new Map() });
    if (buckets.size > 1500) break;
  }
  for (const l of lines) { const k = by === "month" ? l.ts.slice(0, 7) : l.ts.slice(0, 10); const b = buckets.get(k); if (!b) continue;
    b.cost += l.cost_usd || 0; const t = l.task || "—"; b.tasks.set(t, (b.tasks.get(t) || 0) + (l.cost_usd || 0)); }
  const series = [...buckets.values()];
  const days = series.length * (by === "month" ? 30.4 : 1);
  const label = (k) => (by === "month" ? new Date(`${k}-01T00:00`).toLocaleDateString(undefined, { month: "short", year: "numeric" })
    : new Date(`${k}T00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }));
  const top = niceMax(Math.max(0, ...series.map((b) => b.cost)));
  const every = Math.max(1, Math.ceil(series.length / (innerWidth < 720 ? 5 : 12)));
  const chart = series.length ? `<div class="fin-chart" role="img" aria-label="Spending per ${by}">
      <div class="fin-y"><span>${usd(top)}</span><span>${usd(top / 2)}</span><span>$0</span></div>
      <div class="fin-plot"><div class="fin-grid"><i></i><i></i><i></i></div>
        <div class="fin-bars">${series.map((b, i) => `<button type="button" class="fin-bar" data-fin-bucket="${b.key}" style="--h:${(b.cost / top) * 100}%"
          aria-label="${esc(label(b.key))}: ${usd(b.cost)}"><span></span>${i % every === 0 ? `<em>${esc(label(b.key))}</em>` : ""}</button>`).join("")}</div></div>
      <div class="fin-tip" id="fin-tip" hidden></div></div>` : "";

  const group = (keyOf) => { const m = new Map(); for (const l of lines) { const k = keyOf(l); const g = m.get(k) || { key: k, cost: 0, tokens: 0, turns: 0, agents: new Set(), models: new Set() };
    g.cost += l.cost_usd || 0; g.tokens += l.tokens; g.turns += 1; g.agents.add(l.agent); g.models.add(l.model); m.set(k, g); } return [...m.values()].sort((a, b) => b.cost - a.cost || b.tokens - a.tokens); };
  const share = (c) => (total ? `<span class="fin-share"><i style="width:${Math.max(1, (c / total) * 100)}%"></i></span><span class="muted">${Math.round((c / total) * 100)}%</span>` : "");
  const byTask = group((l) => l.task || "");
  const taskRows = byTask.map((g) => { const t = byId[g.key];
    return `<tr><td>${g.key ? `<a href="#/tasks/${esc(g.key)}"><b>${esc(g.key)}</b> ${esc(t?.title || "")}</a>` : `<span class="muted">Not linked to a task</span>`}</td>
      <td class="muted wide-only">${esc(g.key ? projectOfTask(g.key) : "")}</td><td class="wide-only">${t ? statusPill(t.status) : ""}</td>
      <td class="wide-only">${[...g.agents].map((a) => esc(personOf(a))).join(", ")}</td><td class="num wide-only">${g.tokens.toLocaleString()}</td><td class="num"><b>${usd(g.cost)}</b></td><td class="fin-share-cell">${share(g.cost)}</td></tr>`; }).join("");
  const agentRows = group((l) => l.agent).map((g) => `<tr><td>${avatar(g.key)} ${esc(personOf(g.key))} <span class="muted">${esc(OWNER_LABEL[roleOf(g.key)] || "")}</span></td>
      <td class="num">${g.turns}</td><td class="num">${g.tokens.toLocaleString()}</td><td class="num"><b>${usd(g.cost)}</b></td><td class="fin-share-cell">${share(g.cost)}</td></tr>`).join("");
  const modelRows = group((l) => l.model).map((g) => `<tr><td>${esc(g.key)}</td><td class="num">${g.tokens.toLocaleString()}</td><td class="num"><b>${usd(g.cost)}</b></td><td class="fin-share-cell">${share(g.cost)}</td></tr>`).join("");
  const periodRows = [...series].reverse().filter((b) => b.cost > 0).map((b) => { const t = [...b.tasks.entries()].sort((x, y) => y[1] - x[1]).slice(0, 3);
    return `<tr><td>${esc(by === "month" ? label(b.key) : new Date(`${b.key}T00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }))}</td>
      <td class="muted">${t.map(([id, c]) => `${esc(id === "—" ? "not linked" : id)} ${usd(c)}`).join(" · ")}</td><td class="num"><b>${usd(b.cost)}</b></td></tr>`; }).join("");

  const option = (value, text, cur) => `<option value="${esc(value)}" ${value === cur ? "selected" : ""}>${esc(text)}</option>`;
  const projects = [...new Set(tasks.map((t) => projectOfTask(t.id)).filter(Boolean))].sort();
  const models = [...new Set(all.map((l) => l.model))].sort();
  const agents = [...new Set(all.map((l) => l.agent))].sort((a, b) => personOf(a).localeCompare(personOf(b)));
  const tasksWorked = byTask.filter((g) => g.key).length;
  return `<div class="page-head"><div><h1>Finance</h1><p>What the team spent, per task and over time. Costs come from every agent turn; a turn that worked on several tasks is split between them.</p></div>
      <button class="btn" data-action="finance-csv" ${lines.length ? "" : "disabled"}>Export CSV</button></div>
    <div class="filters fin-filters">
      <select id="fin-range" aria-label="Period">${RANGES.map(([v, l]) => option(v, l, f.range)).join("")}</select>
      ${f.range === "custom" ? `<input type="date" id="fin-from" aria-label="From" value="${esc(f.from)}"><input type="date" id="fin-to" aria-label="To" value="${esc(f.to)}">` : ""}
      <select id="fin-agent" aria-label="Agent">${option("", "Everyone", f.agent)}${agents.map((a) => option(a, nameOf(a), f.agent)).join("")}</select>
      <select id="fin-project" aria-label="Project">${option("", "All projects", f.project)}${projects.map((p) => option(p, p, f.project)).join("")}</select>
      <select id="fin-model" aria-label="Model">${option("", "All models", f.model)}${models.map((m) => option(m, m, f.model)).join("")}</select>
      <input type="text" id="fin-q" placeholder="Task ID or title" aria-label="Task" value="${esc(f.q)}">
      <span class="segmented" role="group" aria-label="Group by">${[["day", "Per day"], ["month", "Per month"]].map(([v, l]) =>
        `<button type="button" class="btn small" data-fin-by="${v}" aria-pressed="${f.by === v}">${l}</button>`).join("")}</span>
    </div>
    <div class="fin-stats">
      <div class="fin-stat"><span>Spent</span><b>${usd(total)}</b><small>${esc(new Date(`${from}T00:00`).toLocaleDateString())} – ${esc(new Date(`${to}T00:00`).toLocaleDateString())}</small></div>
      <div class="fin-stat"><span>Per day, on average</span><b>${usd(total / Math.max(1, Math.round(days)))}</b><small>over ${Math.round(days)} day${Math.round(days) === 1 ? "" : "s"}</small></div>
      <div class="fin-stat"><span>Tasks worked on</span><b>${tasksWorked}</b><small>${tasksWorked ? `${usd((total - unlinked) / tasksWorked)} per task` : "none in this period"}</small></div>
      <div class="fin-stat"><span>Not linked to a task</span><b>${usd(unlinked)}</b><small>questions, planning, chats</small></div>
    </div>
    ${unpriced ? `<p class="notice">${unpriced.toLocaleString()} tokens are from models without a price, so they aren't in these totals. <a href="#/settings">Set prices in Settings</a>.</p>` : ""}
    ${lines.length ? `<section class="card-box fin-card"><h2>Spending per ${by}</h2>${chart}</section>
    <section class="fin-section"><h2>By task</h2><div class="table-wrap"><table class="fin-table"><thead><tr><th>Task</th><th class="wide-only">Project</th><th class="wide-only">Status</th><th class="wide-only">Who</th><th class="num wide-only">Tokens</th><th class="num">Spent</th><th>Share</th></tr></thead><tbody>${taskRows}</tbody></table></div></section>
    <div class="fin-two">
      <section class="fin-section"><h2>By agent</h2><div class="table-wrap"><table class="fin-table"><thead><tr><th>Agent</th><th class="num">Turns</th><th class="num">Tokens</th><th class="num">Spent</th><th>Share</th></tr></thead><tbody>${agentRows}</tbody></table></div></section>
      <section class="fin-section"><h2>By model</h2><div class="table-wrap"><table class="fin-table"><thead><tr><th>Model</th><th class="num">Tokens</th><th class="num">Spent</th><th>Share</th></tr></thead><tbody>${modelRows}</tbody></table></div></section>
    </div>
    <section class="fin-section"><h2>Per ${by}</h2><div class="table-wrap"><table class="fin-table"><thead><tr><th>${by === "month" ? "Month" : "Day"}</th><th>Biggest tasks</th><th class="num">Spent</th></tr></thead><tbody>${periodRows || `<tr><td colspan="3" class="muted">Nothing spent in this period.</td></tr>`}</tbody></table></div></section>`
    : `<div class="empty">${all.length ? "Nothing was spent in this period with these filters." : "Spending shows up here once the agents have worked."}</div>`}`;
}

async function History() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const view = params.get("view") || "tasks";
  const tabs = `<nav class="tabs"><a href="#/history" ${view === "tasks" ? 'aria-current="page"' : ""}>Task updates</a><a href="#/history?view=conversations" ${view === "conversations" ? 'aria-current="page"' : ""}>Conversations</a></nav>`;
  const head = `<div class="page-head"><div><h1>Activity</h1><p>${view === "tasks" ? "Every time a task moved, and who moved it." : "Every conversation with your agents. Open one to read it, or continue where it left off."}</p></div></div>`;
  if (view === "conversations") {
    const agent = params.get("role") || "";
    const sessions = (await api("/api/sessions")).filter((s) => s.title && (!agent || (s.role || roleOf(s.agent)) === agent));
    return head + tabs + `<div class="filters">${["", ...Object.keys(ROLES)].map((k) => `<a class="chip-btn ${agent === k ? "on" : ""}" href="#/history?view=conversations${k ? `&role=${k}` : ""}">${k ? ROLES[k].name : "Everyone"}</a>`).join("")}</div>
      ${sessions.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Agent</th><th>Conversation</th><th>Model</th><th>Started</th><th>Last activity</th><th>Turns</th><th>Usage</th></tr></thead>
      <tbody>${sessions.map((s) => `<tr data-href="#/history/${s.id}"><td><span class="pill ${roleOf(s.agent)}">${esc(nameOf(s.agent))}</span></td>
        <td><a href="#/history/${s.id}">${esc(s.title)}</a></td><td>${esc(providerOf(s.provider || "claude").label)}${s.model ? `<br><small class="muted">${esc(s.model)}</small>` : ""}</td>
        <td class="num">${esc(new Date(s.started).toLocaleString())}</td>
        <td class="num">${ago(s.updated)}</td><td class="num">${s.turns}</td><td class="num">${s.cost_usd ? `$${s.cost_usd.toFixed(2)}` : s.tokens ? `${s.tokens.toLocaleString()} tokens` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No conversations yet.</div>`}`;
  }
  const [feed, tasks] = await Promise.all([api("/api/activity?limit=600"), api("/api/tasks")]);
  const byId = Object.fromEntries(tasks.map((t) => [t.id, t]));
  const projectOf = (a) => byId[a.id]?.project_name || a.project?.split("/").pop() || "";
  const projects = [...new Set(feed.map(projectOf).filter(Boolean))].sort();
  const option = (value, label, current) => `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(label)}</option>`;
  const f = activityFilter;
  const shown = feed.filter((a) => (!f.project || projectOf(a) === f.project) && (!f.status || a.to === f.status)
    && (!f.agent || [a.by, a.actor].includes(f.agent)));
  const days = new Map();
  for (const a of shown) {
    const d = new Date(a.ts);
    const key = d.toDateString();
    if (!days.has(key)) days.set(key, { label: d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" }), items: [] });
    days.get(key).items.push(a);
  }
  const today = new Date().toDateString(), yesterday = new Date(Date.now() - 864e5).toDateString();
  const groups = [...days].map(([key, g]) => `<section class="day"><h2>${key === today ? "Today" : key === yesterday ? "Yesterday" : esc(g.label)}</h2><ul class="feed">${g.items.map((a) => {
    const who = a.actor === "lead" ? "You" : a.actor && state.agents[a.actor] ? personOf(a.actor) : a.by && state.agents[a.by] ? personOf(a.by) : "";
    return `<li><time>${new Date(a.ts).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}</time>
      ${a.actor === "lead" ? `<span class="avatar you" title="You">You</span>` : a.actor && state.agents[a.actor] ? avatar(a.actor) : a.by && state.agents[a.by] ? avatar(a.by) : `<span class="avatar lead">·</span>`}
      <span class="what"><a href="#/tasks/${esc(a.id)}"><b>${esc(a.id)}</b> ${esc(byId[a.id]?.title || a.title || "")}</a> <span class="muted">· ${esc(projectOf(a))}</span><br>
        ${who ? `${esc(who)} moved it ` : "Moved "}${a.from ? `from ${esc(stageLabel(a.from))} ` : ""}to ${statusPill(a.to)}</span></li>`;
  }).join("")}</ul></section>`).join("");
  return head + tabs + `<div class="filters">
      <select id="act-project" aria-label="Project">${option("", "All projects", f.project)}${projects.map((p) => option(p, p, f.project)).join("")}</select>
      <select id="act-agent" aria-label="Agent">${option("", "Anyone", f.agent)}${option("lead", "You", f.agent)}${agentIds().map((n) => option(n, nameOf(n), f.agent)).join("")}</select>
      <select id="act-status" aria-label="Moved to">${option("", "Any status", f.status)}${option("blocked", "Blocked", f.status)}${STAGES.map((s) => option(s.status, s.label, f.status)).join("")}</select></div>
    ${groups || `<div class="empty">${feed.length ? "Nothing matches these filters." : "Status changes will appear here."}</div>`}`;
}

async function SessionView(r) {
  const s = await api(`/api/sessions/${encodeURIComponent(r.id)}`);
  const current = state.agents[s.agent]?.session_id === s.id && state.agents[s.agent]?.status !== "stopped";
  return `<p><a href="#/history" class="muted">All conversations</a></p>
    <div class="page-head ${roleOf(s.agent)}"><div><h1>${esc(s.title || "Conversation")}</h1>
      <p><span class="pill ${roleOf(s.agent)}">${esc(nameOf(s.agent))}</span> started ${esc(new Date(s.started).toLocaleString())}, ${s.turns} turns${s.cost_usd ? `, about $${s.cost_usd.toFixed(2)}` : ""}</p></div>
      ${current ? `<a class="btn" href="#/agents/${s.agent}">Open live chat</a>`
                : !state.agents[s.agent] ? `<span class="muted">${esc(nameOf(s.agent))} was removed from the team.</span>`
                : `<button class="btn role ${roleOf(s.agent)}" data-action="resume" data-agent="${s.agent}" data-session="${s.id}">Continue this conversation</button>`}</div>
    <div class="transcript ${roleOf(s.agent)}" style="overflow:visible">${transcriptHTML(s.events, { agent: s.agent })}</div>`;
}

// ---- settings -----------------------------------------------------------------

const SETTINGS_SECTIONS = [["team", "Team"], ["models", "Models & keys"], ["integrations", "Integrations"], ["access", "Access & links"],
  ["workspace", "Workspace"], ["backup", "Backup"], ["appearance", "Appearance"], ["about", "About"]];

async function Settings(r) {
  await loadState();
  if (r.id === "slack") { location.replace("#/settings/integrations/slack"); return null; }   // old link
  const section = SETTINGS_SECTIONS.some(([k]) => k === r.id) ? r.id : "team";
  const [live, bk] = await Promise.all([api("/api/slack").catch(() => ({})), api("/api/backup").catch(() => null)]);
  state.backup = bk;
  const keys = state.settings.providers.filter((p) => p.engine !== "claude" && p.has_key).length;
  const hint = { team: `${agentIds().length} agents`, models: keys ? `${keys} key${keys > 1 ? "s" : ""}` : "",
    integrations: integrationsDot(live), backup: backupHint(bk) };
  const nav = SETTINGS_SECTIONS.map(([k, label]) => `<a href="#/settings/${k}" ${k === section ? 'aria-current="page"' : ""}>${label}<small>${hint[k] || ""}</small></a>`).join("");
  const body = section === "integrations" && r.sub === "slack" ? await slackSection(live)
    : section === "integrations" && r.sub === "editor" ? await editorSection()
    : await { team: teamSection, models: modelsSection, integrations: integrationsSection, access: accessSection, workspace: workspaceSection,
      backup: backupSection, appearance: appearanceSection, about: aboutSection }[section](live);
  return `<div class="settings-grid"><nav class="settings-nav" aria-label="Settings">${nav}</nav><div class="settings-body">${body}</div></div>`;
}

const settingsHead = (title, text) => `<div class="page-head"><div><h1>${title}</h1>${text ? `<p>${text}</p>` : ""}</div></div>`;

// The apps Hive connects to. Slack today; each new one gets a card here and its own page.
const INTEGRATIONS = [
  { id: "slack", name: "Slack", icon: "slack", text: "Talk to the Orchestrator or any agent, approve requests with buttons, and follow each task in a thread." },
  { id: "editor", name: "Editor", icon: "editor", text: "Open the branch you're reviewing in VS Code, in the browser like GitHub's . key, or in your desktop editor." },
];

function integrationsSection(live) {
  const status = (id) => id === "slack"
    ? (live.connected ? `<span class="slack-status on"><span class="dot"></span>Connected</span>` : live.error ? `<span class="slack-status bad"><span class="dot"></span>Error</span>` : `<span class="slack-status"><span class="dot"></span>Not connected</span>`)
    : id === "editor" ? (editorOn() ? `<span class="slack-status on"><span class="dot"></span>${editorPrefs().app === "browser" ? "In the browser" : esc(editorName()) + (editorPrefs().where === "ssh" ? ` over SSH (${esc(editorPrefs().host)})` : "")}</span>` : `<span class="slack-status"><span class="dot"></span>Off</span>`)
    : "";
  return settingsHead("Integrations", "The apps Hive works with. More will appear here.")
    + `<div class="integrations">${INTEGRATIONS.map((i) => `<a class="integration" href="#/settings/integrations/${i.id}">
        <span class="int-icon ${i.icon}" aria-hidden="true">${i.id === "editor" ? VSCODE_ICON : i.name.slice(0, 1)}</span>
        <span class="int-body"><b>${esc(i.name)}</b>${status(i.id)}<small>${esc(i.text)}</small></span>
        <span class="btn small">${(i.id === "slack" && live.connected) || (i.id === "editor" && editorOn()) ? "Manage" : "Set up"}</span></a>`).join("")}</div>`;
}

async function modelsSection() {
  const seen = (await api("/api/costs")).models.filter((m) => m.provider !== "claude").map((m) => m.model);
  const configured = Object.values(state.settings.agents).filter((a) => a.provider !== "claude" && a.model).map((a) => a.model);
  const priced = Object.keys(state.settings.prices || {});
  const models = [...new Set([...seen, ...configured, ...priced])].sort();
  return settingsHead("Models & keys", "API keys for the providers your agents can run on, and model prices for the cost numbers. Keys are kept on this server in <code>data/console/settings.json</code> and never shown again in the browser.")
    + `<div class="providers">${state.settings.providers.map(providerCard).join("")}</div>
    <section class="section"><h2>Model prices</h2>
      <p class="muted" style="max-width:68ch">OpenAI, DeepSeek, Qwen and Kimi report tokens, not money. Enter each model's price from your provider's pricing page, in US$ per 1 million tokens, to see task costs. Changes apply to past conversations too. Claude Code reports its own cost.</p>
      ${models.length ? `<div class="table-wrap prices"><table><thead><tr><th>Model</th><th>Input, $ per 1M</th><th>Output, $ per 1M</th><th></th></tr></thead><tbody>
        ${models.map((m) => { const p = state.settings.prices?.[m] || {}; return `<tr><td><code>${esc(m)}</code></td>
          <td><input type="text" inputmode="decimal" data-price="input" data-model="${esc(m)}" value="${p.input ?? ""}" placeholder="0.00" aria-label="${esc(m)} input price"></td>
          <td><input type="text" inputmode="decimal" data-price="output" data-model="${esc(m)}" value="${p.output ?? ""}" placeholder="0.00" aria-label="${esc(m)} output price"></td>
          <td><button class="btn small" data-action="save-price" data-model="${esc(m)}">Save</button></td></tr>`; }).join("")}
      </tbody></table></div>` : `<p class="muted">Models appear here once an agent is set to a non-Claude model.</p>`}</section>
    <section class="section"><h2>How approvals work</h2>
      <p class="muted" style="max-width:68ch">When an agent wants to edit a file or run a command, it pauses and asks you (in its chat, on Home and in Slack). On Claude, anything your Claude Code settings already allow runs without asking. On the other providers, reading and searching inside the agents' home folder and the Hive folder, editing task files and running the team's own tools don't ask; everything else does. Set an agent's Edits to "Allow automatically" in <a href="#/settings/team">Team</a> to skip edit prompts for it.</p></section>`;
}

async function accessSection() {
  const a = await api("/api/about");
  const remote = a.hosts.length;
  return settingsHead("Access & links", "") + (await linksSection())
    + `<section class="section"><h2>Who can open the console</h2>
      <dl class="facts"><dt>Reached at</dt><dd>${remote ? `This machine, and ${a.hosts.map((h) => `<code>${esc(h)}</code>`).join(", ")} with a password` : "This machine only (<code>localhost</code>)"}</dd>
        <dt>Password</dt><dd>${remote ? (a.password ? "Set: each browser signs in once (30 days)" : "Missing") : "Not needed"}</dd>
        <dt>Terminal page</dt><dd>${a.terminal ? "On: anyone who can open the console gets a shell on this machine" : "Off"}</dd></dl>
      <p class="hint">These are server settings: <code>HOST</code>, <code>CONSOLE_HOSTS</code>, <code>CONSOLE_PASSWORD</code> and <code>ENABLE_TERMINAL</code> when you start the console. See <code>docs/INSTALL.md</code>, "Run on a server".</p></section>`;
}

function workspaceSection() {
  return settingsHead("Workspace", "") + `<form class="form" id="settings-form">
      <label for="workspace">Agents' home folder</label>
      <p class="muted" style="margin:0">Agents start here and can work in any project under it without extra permission prompts. Pick the folder that holds your projects. Takes effect the next time an agent starts.</p>
      <div class="row"><input type="text" id="workspace" value="${esc(state.settings.workspace)}"><button class="btn primary">Save</button></div>
    </form>
    <section class="section"><h2>Where things live</h2><dl class="facts">
      <dt>Hive</dt><dd><code>${esc(state.kit)}</code></dd><dt>The team</dt><dd><code>${esc(state.kit)}/team</code></dd>
      <dt>Your data</dt><dd><code>${esc(state.kit)}/data</code>: tasks, knowledge, the Coach's proposals, conversations and settings</dd></dl></section>`;
}

// ---- Backup: everything Hive needs to start again, nightly to S3 or a folder ------------------

function backupHint(b) {
  const last = b?.history?.[0];
  if (!last) return b?.destination ? "" : "";
  return last.ok ? `<span title="Last backup ${esc(ago(last.at))}">${esc(ago(last.at))}</span>` : `<span class="bad" title="The last backup failed">●</span>`;
}

function backupSection() {
  const b = state.backup || { history: [], destination: "", schedule: "off", hour: 3, keep: 14 };
  const last = b.history[0];
  const size = (n) => n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`;
  const lastLine = b.running ? `<p class="bk-status"><span class="spinner" aria-hidden="true"></span> Backing up now…</p>`
    : !last ? `<p class="bk-status muted">No backup yet.</p>`
    : last.ok ? `<p class="bk-status"><span class="ok">●</span> Last backup ${esc(ago(last.at))}: <code>${esc(last.name)}</code>, ${size(last.size)}, to <code>${esc(last.destination)}</code>.</p>`
    : `<p class="bk-status"><span class="bad">●</span> The last backup, ${esc(ago(last.at))}, failed: ${esc(last.error)}</p>`;
  const s3 = b.destination.startsWith("s3://");
  const [bucket, ...prefix] = s3 ? b.destination.slice(5).split("/") : ["", ""];
  const kind = b.destination && !s3 ? "folder" : "s3";
  const options = (n, from, label, selected) => Array.from({ length: n }, (_, k) => k + from)
    .map((v) => `<option value="${v}" ${v === selected ? "selected" : ""}>${label(v)}</option>`).join("");
  const hours = options(24, 0, (h) => `${String(h).padStart(2, "0")}:00`, b.hour);
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const ordinal = (n) => n + (n % 10 === 1 && n !== 11 ? "st" : n % 10 === 2 && n !== 12 ? "nd" : n % 10 === 3 && n !== 13 ? "rd" : "th");
  const rows = b.history.map((h) => `<tr><td>${esc(new Date(h.at).toLocaleString())}</td><td>${h.trigger === "scheduled" ? "Scheduled" : "By you"}</td>
      <td>${h.ok ? `<span class="ok">●</span> ${size(h.size)}${h.pruned?.length ? `, removed ${plural(h.pruned.length, "old one")}` : ""}` : `<span class="bad">●</span> ${esc(h.error || "failed")}`}</td></tr>`).join("");
  const up = state.backupUpload;
  return settingsHead("Backup", "Everything Hive needs to start again as if nothing happened, as one archive.") + `
    <section class="section bk-top">${lastLine}
      <div class="btn-row"><button class="btn" data-action="backup-now" ${b.running || !b.destination ? "disabled" : ""}>Back up now</button></div></section>
    <form class="form bk-form" id="backup-form">
      <fieldset><legend>Where</legend><div class="radios bk-col">
        <label class="radio"><input type="radio" name="kind" value="s3" ${kind === "s3" ? "checked" : ""}> <span>Amazon S3</span></label>
        <div class="bk-sub bk-s3">
          <label for="bk-bucket">Bucket</label><input type="text" id="bk-bucket" value="${esc(bucket)}" placeholder="almentor-hive-backups" spellcheck="false" autocapitalize="off">
          <label for="bk-prefix">Folder in the bucket <span class="muted">(optional)</span></label><input type="text" id="bk-prefix" value="${esc(prefix.join("/"))}" placeholder="hive" spellcheck="false" autocapitalize="off">
          <p class="hint">Uses this machine's own AWS access: the instance's role, through the <code>aws</code> command${b.aws ? "" : ` (<span class="warn">not installed here</span>)`}. The role needs to read, write and delete in that folder; keep the bucket private.</p></div>
        <label class="radio"><input type="radio" name="kind" value="folder" ${kind === "folder" ? "checked" : ""}> <span>A folder on this machine</span></label>
        <div class="bk-sub bk-folder"><input type="text" id="bk-folder" value="${esc(kind === "folder" ? b.destination : "")}" placeholder="/backups/hive" aria-label="Folder" spellcheck="false" autocapitalize="off"></div>
      </div></fieldset>
      <fieldset><legend>How often</legend><div class="radios bk-col bk-when">
        ${[["daily", "Every day"], ["weekly", "Every week"], ["monthly", "Every month"], ["off", "Only when I press Back up now"]].map(([v, l]) =>
          `<label class="radio"><input type="radio" name="schedule" value="${v}" ${b.schedule === v ? "checked" : ""}> <span>${l}</span></label>`).join("")}
        <div class="bk-sub bk-at">
          <span class="bk-weekly">on <select id="bk-weekday" aria-label="Day of the week">${days.map((d, k) => `<option value="${k}" ${k === b.weekday ? "selected" : ""}>${d}</option>`).join("")}</select></span>
          <span class="bk-monthly">on the <select id="bk-day" aria-label="Day of the month">${options(28, 1, ordinal, b.day)}</select></span>
          at <select id="bk-hour" aria-label="Hour">${hours}</select> <span class="muted">(this machine's time)</span></div>
      </div></fieldset>
      <label for="bk-keep">Keep the last</label>
      <div class="row bk-keep"><input type="number" id="bk-keep" min="1" max="365" value="${b.keep}"> <span>backups; older ones are deleted.</span></div>
      <div class="btn-row"><button class="btn primary">Save</button></div>
      ${b.next ? `<p class="hint">Next: ${esc(new Date(b.next).toLocaleString())}. One missed while the machine was off is made when Hive starts.</p>` : ""}
    </form>
    <section class="section"><h2>What's in a backup</h2><ul class="bk-list">
      <li><b>All of <code>data/</code></b>: tasks, reviews, knowledge, the Coach's work, conversations, and these settings with their API keys and Slack tokens.</li>
      <li><b>Branches only this machine has</b>: anything not on GitHub yet (agents' work in progress, and the commits kept when you tidied a branch for its pull request), as git bundles.</li>
      <li><b>Claude Code's conversations and sign-in</b>, so agents can resume and you don't sign in again.</li>
      <li>Not included: VS Code's extensions and caches (they download again), and the environment you start Hive with (<code>CONSOLE_PASSWORD</code>, <code>CONSOLE_HOSTS</code>, …).</li></ul></section>
    <section class="section"><h2>Restore</h2>
      ${up?.restarting ? `<p class="bk-status"><span class="spinner" aria-hidden="true"></span> Restoring and restarting Hive… This page reloads when it's back.</p>`
      : up ? `<div class="bk-found"><p><b>${esc(up.file)}</b> · ${size(up.size)}</p><dl class="facts">
          <dt>Made</dt><dd>${esc(up.made ? new Date(up.made).toLocaleString() : "unknown")}${up.from ? ` from <code>${esc(up.from)}</code>` : ""}${up.hive_version ? `, Hive <code>${esc(up.hive_version)}</code>` : ""}</dd>
          <dt>Inside</dt><dd>${plural(up.tasks, "task")}, ${plural(up.files, "file")} of data${up.conversations ? ", Claude Code's conversations" : ""}</dd>
          ${up.projects.length ? `<dt>Projects</dt><dd>${up.projects.map((x) => `<code>${esc(x.path)}</code>${x.branches ? ` (${x.branches} unpushed branch${x.branches > 1 ? "es" : ""})` : ""}`).join("<br>")}</dd>` : ""}</dl>
          ${up.restart ? `<p class="notice warn">${esc(up.restart)}<code>${esc(state.kit)}/data/backup/uploads/${esc(up.file)}</code></p>`
            : `<p class="hint">Hive stops, puts this backup back and starts again (about a minute). The data here now is moved aside to <code>data.before-restore-…</code>, never deleted; a branch that's newer here is left alone. Running agents are stopped.</p>
          <div class="btn-row"><button class="btn danger" data-action="backup-restore">Restore this backup</button><button class="btn" data-action="backup-forget">Cancel</button></div>`}</div>`
      : `<p>Upload a backup (<code>hive-backup-….tar.gz</code>) to put Hive back as it was then.</p>
        <label class="btn bk-upload"><input type="file" id="bk-file" accept=".gz,.tgz,application/gzip" hidden> Choose a backup…</label>
        <p class="hint">Or, with Hive stopped, from the Hive folder: <code>bash scripts/restore.sh ${esc(b.destination || "s3://bucket/folder")}</code> (the newest one there).</p>`}</section>
    ${rows ? `<section class="section"><h2>History</h2><div class="table-wrap"><table class="bk-history"><thead><tr><th>When</th><th>Started</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table></div></section>` : ""}`;
}

// Hive stops, restores and starts again: wait until it's gone, then until it's back, then reload (new key).
function waitForRestart() {
  let gone = false;
  const started = Date.now();
  const timer = setInterval(async () => {
    const up = await fetch("/api/about", { cache: "no-store" }).then((r) => r.ok || r.status === 401).catch(() => false);
    if (!up) gone = true;
    if ((gone && up) || Date.now() - started > 300000) {
      clearInterval(timer);
      location.reload();
    }
  }, 2000);
}

async function uploadBackup(file) {
  state.backupUpload = null;
  toast(`Uploading ${file.name}…`);
  try {
    const res = await fetch("/api/backup/upload", { method: "POST", body: file,
      headers: { "x-token": TOKEN, "x-filename": file.name, "content-type": "application/octet-stream" } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Upload failed (${res.status}).`);
    state.backupUpload = data;
    toast("Uploaded. Check it's the right one, then restore.");
  } catch (err) {
    toast(err.message, true);
  }
  render(true);
}

function followBackup() {
  clearInterval(followBackup.timer);
  followBackup.timer = setInterval(async () => {
    const b = await api("/api/backup").catch(() => null);
    if (!b || b.running) return;
    clearInterval(followBackup.timer);
    state.backup = b;
    const last = b.history[0];
    if (last) toast(last.ok ? `Backed up: ${last.name}` : `The backup failed: ${last.error}`, !last.ok);
    if (route().page === "settings") render(true);
  }, 2000);
}

function appearanceSection() {
  let theme = "system";
  try { theme = localStorage.getItem("theme") || "system"; } catch { /* default */ }
  return settingsHead("Appearance", "Saved in this browser.") + `<fieldset class="theme-pick"><legend>Theme</legend>
      ${[["system", "Follow my system"], ["light", "Light"], ["dark", "Dark"]].map(([v, l]) =>
        `<label class="${v}"><input type="radio" name="theme" value="${v}" data-theme-pick ${v === theme ? "checked" : ""}><span class="swatch" aria-hidden="true"></span>${l}</label>`).join("")}</fieldset>`;
}

async function aboutSection() {
  const a = await api("/api/about");
  return settingsHead("About", "") + `<div class="about-card"><img src="/assets/hive-logo.svg" alt="" width="56" height="56">
      <div><h2>Hive</h2><p class="muted">Your agent team: a Tech Lead, Devs, Reviewers, a Coach and an Orchestrator, run from this console and Slack.</p></div></div>
    <dl class="facts">
      <dt>Version</dt><dd>${a.commit ? `<code>${esc(a.commit)}</code> on <code>${esc(a.branch)}</code>, ${esc(ago(a.date))}: ${esc(a.subject)}` : "Not a git repository"}</dd>
      ${a.commit ? `<dt>Not pushed</dt><dd>${a.ahead === null ? "No upstream branch" : a.ahead ? `${a.ahead} commit${a.ahead > 1 ? "s" : ""}` : "Nothing: up to date with the remote"}${a.dirty ? ", plus uncommitted changes" : ""}</dd>` : ""}
      <dt>Hive folder</dt><dd><code>${esc(a.kit)}</code></dd>
      <dt>Documentation</dt><dd><code>README.md</code>, and in <code>docs/</code>: <code>INSTALL.md</code>, <code>USAGE.md</code>, <code>CONSOLE.md</code>, <code>DEVELOPMENT.md</code>. The team's process: <code>team/TEAM.md</code> and <code>team/PREFERENCES.md</code></dd></dl>`;
}

async function linksSection() {
  const s = state.settings;
  return `<section class="section"><h2>Console address</h2>
    <form class="form" id="console-url-form">
      <label for="console-url">The address you open the console at</label>
      <p class="muted" style="margin:0;max-width:68ch">Used in links the Orchestrator and Slack give you (a task, its code review, an agent's chat). On a server behind your VPN, use the name you open it with there, so links work from your laptop and your phone. Empty: <code>http://localhost:8420</code>, or <code>CONSOLE_URL</code> from the server's environment.</p>
      <div class="row"><input type="text" id="console-url" value="${esc(s.console_url || "")}" placeholder="${esc(s.console_url_effective)}" spellcheck="false"><button class="btn primary">Save</button></div>
      <p class="hint">Links use <code>${esc(s.console_url_effective)}</code>${s.console_url ? "" : " (set CONSOLE_URL on the server, or type an address above)"}.</p>
    </form></section>`;
}

async function slackSection(live) {
  const sl = state.settings.slack;
  live = live || await api("/api/slack").catch(() => ({}));
  const token = (k, label, prefix) => {
    const t = sl[k];
    const note = t.from_env ? `Using <code>${k === "bot_token" ? "SLACK_BOT_TOKEN" : "SLACK_APP_TOKEN"}</code> from the server's environment.` : t.set ? `Saved, ends in ${esc(t.hint)}.` : "Not set.";
    return `<label for="slack-${k}">${label}</label>
      <input type="password" id="slack-${k}" autocomplete="off" placeholder="${t.set ? "Paste a new token to replace it" : `${prefix}…`}" ${t.from_env ? "disabled" : ""}>
      <p class="hint">${note}</p>`;
  };
  const state_ = live.connected ? `<span class="slack-status on"><span class="dot"></span>Connected</span>`
    : live.error ? `<span class="slack-status bad"><span class="dot"></span>${esc(live.error)}</span>`
    : `<span class="slack-status"><span class="dot"></span>Not connected</span>`;
  return `<p class="sub-crumb"><a href="#/settings/integrations">Integrations</a> › Slack</p>` + settingsHead("Slack", "") + `<section>
    <p style="max-width:68ch">${state_} ${live.connected ? `<button class="btn small" data-action="slack-test">Send a test message</button>` : ""}</p>
    <p class="muted" style="max-width:68ch">Talk to the Orchestrator (or any agent: start with its name, "Nabil: …") by messaging the app, approve agents' requests with buttons, and follow each task in a thread with buttons for what's next. The console connects out to Slack, so it works from your laptop or a server behind a VPN, with nothing exposed. One Slack app per running console.</p>
    <details ${live.connected ? "" : "open"}><summary>How to set it up (5 minutes)</summary><ol class="setup-steps">
      <li>Go to <a href="https://api.slack.com/apps" target="_blank" rel="noopener">api.slack.com/apps</a> → <b>Create New App</b> → <b>From a manifest</b>, pick the workspace, and paste <code>integrations/slack/slack-app.yml</code> from the Hive folder. (In a company workspace, an admin may need to approve the app.)</li>
      <li><b>Basic Information</b> → <b>App-Level Tokens</b> → <b>Generate</b>, with the scope <code>connections:write</code>: that's the <code>xapp-…</code> token.</li>
      <li><b>Install App</b> → <b>Install to Workspace</b>: that's the <code>xoxb-…</code> bot token.</li>
      <li>Your Slack member ID: in Slack, your profile → ⋮ → <b>Copy member ID</b> (<code>U…</code>). Add everyone who may talk to the team and approve requests.</li>
      <li>Paste them below and save. Then message the app in Slack.</li></ol></details>
    <form class="form" id="slack-form">
      ${token("bot_token", "Bot token", "xoxb-")}
      ${token("app_token", "App-level token", "xapp-")}
      <label for="slack-users">Who can use it (Slack member IDs)</label>
      <input type="text" id="slack-users" value="${esc(sl.users.value)}" placeholder="U01234ABCD, U05678EFGH" spellcheck="false" ${sl.users.from_env ? "disabled" : ""}>
      <p class="hint">Only these people can message the agents and press Allow. Anyone else is turned away.</p>
      <label for="slack-channel">Where task updates go <span class="muted">(optional)</span></label>
      <input type="text" id="slack-channel" value="${esc(sl.channel.value)}" placeholder="A channel ID like C0123ABCD; empty = a direct message to the first person above" spellcheck="false" ${sl.channel.from_env ? "disabled" : ""}>
      <p class="hint">For a channel, invite the app to it first (<code>/invite @Team Console</code>).</p>
      <div class="btn-row"><button class="btn primary">Save and connect</button>
        ${sl.bot_token.set && !sl.bot_token.from_env ? `<button type="button" class="btn danger" data-action="slack-disconnect">Disconnect</button>` : ""}</div>
    </form></section>${slackNotifications()}`;
}

// When Slack tells you, and how a reply in a task's thread reaches you.
const SLACK_EVENTS = [
  ["Waiting on you", [["waiting", "An agent stopped and is waiting for your answer"],
    ["approval", "An agent asks for approval", "Requests in a conversation you started in Slack always come there."],
    ["blocked", "A task is blocked"]]],
  ["Tasks", [["ready-for-dev", "A spec is approved: ready for a dev"], ["ready-for-review", "A dev finished: ready for review"],
    ["changes-requested", "A task is sent back for changes"], ["done", "A reviewer approved a task: done"],
    ["draft", "A new task (still a draft)"], ["in-dev", "A dev started building"], ["in-review", "A reviewer started reviewing"]]],
  ["The Coach", [["proposals", "New proposals to improve the team"]]],
];
function slackNotifications() {
  const prefs = state.settings.slack_prefs || { notify: {}, replies: "thread" };
  const where = state.settings.slack.channel.value ? "to the channel" : "as a direct message";
  const level = (event, label, hint) => `<div class="notify-row"><div><span>${esc(label)}</span>${hint ? `<small class="muted">${esc(hint)}</small>` : ""}</div>
    <select name="${event}" aria-label="${esc(label)}">${[["notify", "Notify me"], ["quiet", "Quietly"], ["off", "Off"]].map(([v, l]) =>
      `<option value="${v}" ${prefs.notify[event] === v ? "selected" : ""}>${l}</option>`).join("")}</select></div>`;
  return `<section class="section"><h2>Notifications</h2>
    <form class="form" id="slack-notify-form">
      <p class="muted" style="margin:0;max-width:68ch"><b>Notify me</b> posts it with a mention, so Slack notifies you. <b>Quietly</b> posts it in the task's thread without notifying you. <b>Off</b> doesn't post it.</p>
      ${SLACK_EVENTS.map(([group, rows]) => `<fieldset class="notify-group"><legend>${esc(group)}</legend>${rows.map((r) => level(...r)).join("")}</fieldset>`).join("")}
      <fieldset class="notify-group"><legend>Replies in a thread</legend>
        <label class="radio"><input type="radio" name="replies" value="thread" ${prefs.replies !== "thread_and_dm" ? "checked" : ""}> Only in the thread <small class="muted">(you're mentioned, so it still notifies you)</small></label>
        <label class="radio"><input type="radio" name="replies" value="thread_and_dm" ${prefs.replies === "thread_and_dm" ? "checked" : ""}> In the thread, and also ${where} <small class="muted">(Slack's "Also send ${where}")</small></label>
      </fieldset>
      <div class="btn-row"><button class="btn primary">Save notifications</button></div>
    </form></section>`;
}

// One dot beside Integrations, whatever is set up: red when one needs attention, green when they're all fine.
function integrationsDot(live) {
  const on = [live.connected && "Slack", editorOn() && "Editor"].filter(Boolean);
  if (live.error) return `<span class="bad" title="Slack: ${esc(live.error)}">●</span>`;
  return on.length ? `<span class="ok" title="On: ${on.join(", ")}">●</span>` : "";
}

async function editorSection() {
  const e = editorPrefs(), cs = await api("/api/editor").catch(() => ({}));
  const radio = (name, value, label, checked, extra = "") => `<label class="radio"><input type="radio" name="${name}" value="${value}" ${checked ? "checked" : ""} ${extra}> <span>${label}</span></label>`;
  const found = cs.installed
    ? `<p class="hint"><span class="ok">●</span> code-server ${esc(cs.version)} found at <code>${esc(cs.path)}</code>.</p>`
    : `<p class="hint"><span class="bad">●</span> code-server isn't installed on the Hive machine. Install it there once, then reload this page:<br>
        Linux: <code>curl -fsSL https://code-server.dev/install.sh | sh</code> &nbsp; macOS: <code>brew install code-server</code></p>`;
  const browserBlocked = !cs.allowed ? "disabled" : "";
  return `<p class="sub-crumb"><a href="#/settings/integrations">Integrations</a> › Editor</p>` + settingsHead("Editor", "")
    + `<section><p class="muted" style="max-width:68ch">Open the code you're reviewing in VS Code: <b>Open in editor</b> (or holding <b>.</b>) in a code review opens the branch's worktree folder, indexed (go to definition, references, search).</p>
    <form class="form editor-form" id="editor-form">
      <fieldset><legend>Open code in</legend><div class="radios editor-apps">
        ${radio("app", "browser", "<b>In the browser</b>: VS Code in a new tab, running on the Hive machine (like GitHub's <b>.</b>)", e.app === "browser", browserBlocked)}
        ${radio("app", "vscode", "VS Code on this computer", e.app === "vscode")}
        ${radio("app", "cursor", "Cursor on this computer", e.app === "cursor")}
        ${radio("app", "off", "Off", e.app === "off")}</div></fieldset>
      <div class="editor-browser">
        ${!cs.allowed ? `<p class="hint"><span class="bad">●</span> Turned off on this server (<code>ENABLE_EDITOR=0</code>).</p>` : found}
        <p class="hint">Anyone who can open this console can edit files and run commands with it, like the Terminal page. Extensions come from Open VSX (most are there; Microsoft's own, like Pylance, aren't). <code>ENABLE_EDITOR=0</code> turns it off for good.</p>
      </div>
      <fieldset class="editor-desktop"><legend>Where the code is</legend>
        ${radio("where", "local", "On this computer: Hive runs here", e.where !== "ssh")}
        ${radio("where", "ssh", "On a server I reach over SSH", e.where === "ssh")}
        <div class="ssh-host"><label for="editor-host">SSH host</label>
          <input type="text" id="editor-host" value="${esc(e.host)}" placeholder="hive-ec2" spellcheck="false" autocapitalize="off">
          <p class="hint">A <code>Host</code> from your <code>~/.ssh/config</code> (or <code>user@address</code>). Needs the <b>Remote - SSH</b> extension; the first time, your editor sets itself up on the server and installs your extensions there.</p></div>
        <p class="hint">Saved in this browser, so each computer can have its own. The first time, your browser asks whether to open the app: tick <b>Always allow</b>.</p>
      </fieldset>
      <div class="btn-row"><button class="btn primary">Save</button></div>
    </form></section>`;
}

function teamSection() {
  const row = (id) => {
    const ag = state.agents[id];
    const choice = state.settings.agents[id] || {};
    const prov = providerOf(choice.provider || "claude");
    const running = ag.status !== "stopped";
    const mode = state.settings?.permission_mode?.[id] || "default";
    const role = roleOf(id);
    const removable = ["techlead", "dev", "reviewer"].includes(role) && agentIds().filter((x) => roleOf(x) === role).length > 1;
    return `<div class="agent-row">${avatar(id)}
      <div class="who"><input type="text" class="agent-name" data-action="name" data-agent="${id}" value="${esc(personOf(id))}" maxlength="30" aria-label="Name of ${esc(id)}">
        <small>${esc(OWNER_LABEL[role])} · <a href="#/agents/${id}">chat</a> · <code>${esc(id)}</code></small></div>
      <div class="model-cell"><select data-action="provider" data-agent="${id}" aria-label="Provider for ${esc(personOf(id))}" ${running ? "disabled" : ""}>${(state.settings?.providers || []).map((p) =>
          `<option value="${p.id}" ${p.id === (choice.provider || "claude") ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select>
        <input type="text" list="models-${id}" data-action="model" data-agent="${id}" value="${esc(choice.model || "")}" ${running ? "disabled" : ""}
          placeholder="${prov.engine === "claude" ? "Default from the agent file" : `For example ${esc(prov.models?.[0] || "")}`}" spellcheck="false" aria-label="Model for ${esc(personOf(id))}">
        <datalist id="models-${id}">${(prov.models || []).map((m) => `<option value="${esc(m)}">`).join("")}</datalist>
        ${running ? `<small class="muted">Stop ${esc(personOf(id))} to change it.</small>` : prov.engine !== "claude" && !prov.has_key ? `<small class="warn">No ${esc(prov.label)} key yet: <a href="#/settings/models">add it</a></small>` : ""}</div>
      <select data-action="mode" data-agent="${id}" aria-label="File edit approvals for ${esc(personOf(id))}">
        <option value="default" ${mode === "default" ? "selected" : ""}>Ask me first</option>
        <option value="acceptEdits" ${mode === "acceptEdits" ? "selected" : ""}>Allow automatically</option></select>
      <span>${removable ? `<button class="btn small danger" data-action="remove-agent" data-agent="${id}" ${running ? 'disabled title="Stop it first"' : ""}>Remove</button>` : ""}</span></div>`;
  };
  const group = (title, note, roles, extra = "") => `<section class="agent-group"><header><h2>${title}</h2><span class="muted">${note}</span>${extra}</header>
    ${agentIds().filter((id) => roles.includes(roleOf(id))).map(row).join("")}</section>`;
  return settingsHead("Team", "Who's on the team, the model each one runs on, and whether it asks before editing files. Model changes apply the next time an agent starts.")
    + `<div class="agent-cols muted"><span></span><span>Agent</span><span>Model</span><span>Edits</span><span></span></div>`
    + group("Orchestrator", "your assistant, here and in Slack", ["orchestrator"])
    + group("Team", "several of each role can work in parallel, each on its own tasks", ["techlead", "dev", "reviewer"],
      `<span class="add-agent"><select id="add-role" aria-label="Role to add"><option value="dev">Dev</option><option value="reviewer">Reviewer</option><option value="techlead">Tech Lead</option></select>
        <button class="btn small" data-action="add-agent-picked">Add</button></span>`)
    + group("Coach", "reviews how tasks went and proposes improvements", ["coach"]);
}

function providerCard(p) {
  if (p.engine === "claude") {
    return `<div class="provider"><h3>${esc(p.label)}</h3><p class="muted">${esc(p.note)}</p></div>`;
  }
  const keyText = p.key_from_env ? `Using <code>${esc(p.key_env)}</code> from the server's environment.`
    : p.has_key ? `Saved key ends in ${esc(p.key_hint)}.` : "No key yet.";
  return `<form class="provider form" data-provider="${p.id}">
      <h3>${esc(p.label)}</h3>
      ${p.note ? `<p class="muted">${esc(p.note)}</p>` : ""}
      <label for="key-${p.id}">API key</label>
      <input type="password" id="key-${p.id}" name="api_key" autocomplete="off" placeholder="${p.has_key ? "Paste a new key to replace it" : `Paste your ${esc(p.label)} API key`}">
      <p class="hint">${keyText}</p>
      <label for="url-${p.id}">API address</label>
      <input type="text" id="url-${p.id}" name="base_url" value="${esc(p.base_url)}" spellcheck="false">
      <div class="btn-row"><button class="btn primary">Save</button>
        ${p.has_key && !p.key_from_env ? `<button type="button" class="btn danger" data-action="remove-key" data-provider="${p.id}">Remove key</button>` : ""}</div>
    </form>`;
}

async function renameAgent(name, value) {
  const saved = await act(() => api(`/api/agents/${name}/name`, { method: "PUT", body: { name: value } }), `Renamed to ${value.trim()}.`);
  if (saved) state.settings = saved;
  render(true);
  renderRail();
}

async function saveConfig(name, provider, model) {
  const saved = await act(() => api(`/api/agents/${name}/config`, { method: "PUT", body: { provider, model } }));
  if (saved) state.settings = saved;
  renderAgentChrome(name);
  if (["overview", "settings"].includes(route().page)) render(true);
}

// ---- your code review (a pull request inside the console) ------------------------------------

const REVIEW_VIEWS = [["feature", "Whole branch"], ["since", "Since your last review"]];
const reviewView = () => {
  const view = new URLSearchParams(location.hash.split("?")[1] || "").get("view");
  return ["since", "earlier"].includes(view) ? view : "feature";
};
const reviewHref = (id, view) => `#/tasks/${encodeURIComponent(id)}/review${view && view !== "feature" ? `?view=${view}` : ""}`;
const lineKey = (file, side, line) => `${file}\u0000${side}\u0000${line}`;
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

function commentWhere(c) {
  if (!c.file) return "General comment";
  if (!c.line) return `<code>${esc(c.file)}</code>`;
  return c.side === "old" ? `<code>${esc(c.file)}</code> <span class="muted">removed line ${c.line}</span>` : `<code>${esc(c.file)}:${c.line}</code>`;
}

function draftCard(c, { where = false } = {}) {
  return `<div class="review-comment draft" data-comment="${esc(c.id)}">
    <div class="who"><span class="pill lead">Draft</span>${where ? ` ${commentWhere(c)}` : ""}</div>
    ${where && c.code ? `<pre class="snippet">${esc(c.code)}</pre>` : ""}
    <div class="prose body">${md(c.body)}</div>
    <div class="btn-row"><button class="btn small" data-action="edit-comment" data-id="${esc(c.id)}">Edit</button>
      <button class="btn small" data-action="delete-comment" data-id="${esc(c.id)}">Delete</button></div></div>`;
}

// A submitted comment, shown back on its line, with the dev's reply.
function postedCard(c, r, dev) {
  const asked = r.verdict === "changes";
  return `<div class="review-comment posted ${asked ? "" : "approved"}">
    <div class="who"><span class="pill ${asked ? "lead" : "dev"}">Round ${r.n}</span> <span class="muted">${esc(ago(r.at))}</span></div>
    <div class="prose body">${md(c.body)}</div>
    ${asked ? `<div class="reply ${c.reply ? "" : "none"}"><span class="pill dev">${esc(dev ? nameOf(dev) : "Dev")}</span> ${c.reply ? esc(c.reply) : "No reply yet."}</div>` : ""}</div>`;
}

// Where each submitted comment sits in this view: the line in the same file and side whose code is still the line
// it was made on (the last line of its snippet), nearest to its old position. If that code changed or isn't in this
// view, it stays only under "Your earlier reviews" (like an outdated comment on a pull request).
function placePosted(files, rounds, head) {
  const placed = new Map();
  for (const r of rounds) {
    for (const c of r.comments) {
      if (!c.file || !c.line) continue;
      const f = files.find((x) => x.path === c.file);
      if (!f) continue;
      const lines = f.hunks.flatMap((h) => h.lines).map((l) => ({ side: l.t === "-" ? "old" : "new", n: l.t === "-" ? l.o : l.n, s: l.s }))
        .filter((l) => l.side === c.side);
      const text = c.code ? c.code.split("\n").pop() : null;
      const matches = text !== null ? lines.filter((l) => l.s === text) : r.commit === head ? lines.filter((l) => l.n === c.line) : [];
      if (!matches.length) continue;
      const best = matches.reduce((a, b) => (Math.abs(b.n - c.line) < Math.abs(a.n - c.line) ? b : a));
      const key = lineKey(c.file, c.side, best.n);
      placed.set(key, [...(placed.get(key) || []), { c, r }]);
    }
  }
  return placed;
}

// How you read diffs: "unified" (one column) or "split" (side by side), remembered in this browser.
function reviewLayout() {
  try { return localStorage.getItem("reviewLayout") || (innerWidth < 900 ? "unified" : "split"); } catch { return "unified"; }
}

// Word-level changes inside a modified line, like GitHub: the removed line and the line that replaced it each get
// the words that differ highlighted. Lines that share too little are left plain (they were rewritten, not edited).
const inline = new WeakMap();   // diff line -> its HTML with the changed words marked
const wordsOf = (text) => text.match(/\w+|\s+|[^\w\s]/g) || [];

function markChanges(del, add) {
  const a = wordsOf(del.s), b = wordsOf(add.s);
  if (!a.length || !b.length || a.length * b.length > 60000) return;
  const dp = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1));
  for (let i = a.length - 1; i >= 0; i--) for (let j = b.length - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const same = [...a].filter((t, i) => t.trim()).length ? dp[0][0] : 0;
  if (same < 0.3 * Math.max(a.length, b.length)) return;
  const outA = [], outB = [];
  let i = 0, j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) { outA.push([a[i++], false]); outB.push([b[j++], false]); }
    else if (j < b.length && (i >= a.length || dp[i][j + 1] >= dp[i + 1][j])) outB.push([b[j++], true]);
    else outA.push([a[i++], true]);
  }
  const html = (parts) => {
    // a lone unchanged character between two changes (a quote, a comma) reads better inside the highlight
    for (let k = 1; k < parts.length - 1; k++) if (!parts[k][1] && parts[k][0].length === 1 && parts[k - 1][1] && parts[k + 1][1]) parts[k][1] = true;
    let out = "", open = false;
    for (const [t, changed] of parts) {
      const mark = changed && t.trim() !== "" || (changed && open);
      if (mark && !open) { out += '<span class="chg">'; open = true; }
      if (!mark && open) { out += "</span>"; open = false; }
      out += esc(t);
    }
    return out + (open ? "</span>" : "");
  };
  inline.set(del, html(outA));
  inline.set(add, html(outB));
}

// Pair each run of removed lines with the added lines right after it, in order (what GitHub compares word by word).
function markHunk(lines) {
  for (let k = 0; k < lines.length;) {
    if (lines[k].t !== "-") { k++; continue; }
    const dels = [];
    while (k < lines.length && lines[k].t === "-") dels.push(lines[k++]);
    const adds = [];
    while (k < lines.length && lines[k].t === "+") adds.push(lines[k++]);
    dels.forEach((d, n) => adds[n] && markChanges(d, adds[n]));
  }
}

// ---- opening the code in your editor (Settings → Integrations → Editor, kept in this browser) ----

// browser: VS Code in a new tab, run by Hive on its own machine (code-server); vscode/cursor: the desktop app.
const EDITORS = { browser: { name: "VS Code" }, vscode: { name: "VS Code", scheme: "vscode" }, cursor: { name: "Cursor", scheme: "cursor" } };
const VSCODE_ICON = '<svg class="ico-vscode" viewBox="0 0 24 24" aria-hidden="true"><path d="M17.6 2 8.4 10.4 3.7 6.8 2 7.7v8.6l1.7.9 4.7-3.6 9.2 8.4L22 20.2V3.8zM4 14.4V9.6L6.6 12zm13.6 2.3L12.1 12l5.5-4.7z"/></svg>';

// In the browser once the lead turns it on for the server; a browser can pick a desktop editor instead (or Off).
function editorPrefs() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem("editor") || "{}"); } catch { /* private window */ }
  const prefs = { where: "local", host: "", ...saved };
  if (!saved.app || saved.app === "browser") prefs.app = state.editorBrowser ? "browser" : "off";
  return prefs;
}
const editorOn = () => {
  const e = editorPrefs();
  return e.app === "browser" ? state.editorBrowser : !!EDITORS[e.app] && (e.where !== "ssh" || !!e.host);
};
const editorName = () => (EDITORS[editorPrefs().app] || EDITORS.vscode).name;

// vscode://file/<folder> on this computer; over SSH, vscode://vscode-remote/ssh-remote+<host>/<folder>
function editorUrl(path) {
  const e = editorPrefs(), scheme = EDITORS[e.app].scheme;
  const where = e.where === "ssh" ? `vscode-remote/ssh-remote+${encodeURIComponent(e.host)}` : "file";
  return `${scheme}://${where}${encodeURI(path)}`;
}

// One line of code as a cell you can comment on: the anchor holds where it is and its text.
function codeCell(f, l, side, kind) {
  const line = side === "old" ? l.o : l.n;
  return `<td class="code ${kind}" data-file="${esc(f.path)}" data-side="${side}" data-line="${line}" data-s="${esc(l.s)}"><button class="add-comment" data-action="comment-line" aria-label="Comment on line ${line} of ${esc(f.path)}" title="Comment on this line">+</button><span class="mark">${l.t === " " ? " " : l.t}</span>${inline.get(l) ?? esc(l.s)}</td>`;
}

// Lines of a hunk side by side: unchanged lines on both sides, removed lines next to the lines that replaced them.
function pairUp(lines) {
  const rows = [];
  let dels = [], adds = [];
  const flush = () => {
    for (let i = 0; i < Math.max(dels.length, adds.length); i++) rows.push({ o: dels[i] || null, n: adds[i] || null });
    dels = []; adds = [];
  };
  for (const l of lines) {
    if (l.t === "-") dels.push(l);
    else if (l.t === "+") adds.push(l);
    else { flush(); rows.push({ o: l, n: l, ctx: true }); }
  }
  flush();
  return rows;
}

// ---- Unchanged lines around the changes, hidden until you expand them (like GitHub) ----
// A file's lines at the diff's head are fetched once, the first time you expand something in it; what you expanded
// is kept per file (by the lines it opened above and below each gap), so it survives a refresh of the page.
const EXPAND_STEP = 20;
let reviewCtx = null;                        // what the review page drew with, to draw one file again
const reviewSource = new Map();              // "head:path" -> the file's lines
const reviewExpanded = new Map();            // "head:path" -> { gap start line: { down, up } }

// The gaps of unchanged lines in a file's new version: before each hunk, and after the last one.
function diffGaps(f) {
  const total = reviewSource.get(`${reviewCtx?.head}:${f.path}`)?.length;
  const gaps = [];
  let after = 0, delta = 0;   // the last new line shown so far; old line = new line + delta in unchanged code
  for (const h of f.hunks) {
    const m = h.header.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)/);
    const oldStart = +m[1], newStart = +m[2];
    const first = h.lines.find((l) => l.n != null)?.n ?? newStart;
    gaps.push({ from: after + 1, to: first - 1, delta: oldStart - newStart, before: h });
    const ns = h.lines.filter((l) => l.n != null).map((l) => l.n);
    after = ns.length ? Math.max(...ns) : newStart - 1;
    const os = h.lines.filter((l) => l.o != null).map((l) => l.o);
    delta = (os.length ? Math.max(...os) : oldStart - 1) - after;
  }
  gaps.push({ from: after + 1, to: total ?? Infinity, delta, before: null });   // the end isn't known until fetched
  return gaps;
}

function gapRows(f, gap, layout, cols) {
  const key = `${reviewCtx?.head}:${f.path}`, src = reviewSource.get(key);
  const open = reviewExpanded.get(key)?.[gap.from] || { down: 0, up: 0 };
  const size = gap.to - gap.from + 1;   // Infinity until the file is fetched (after the last hunk)
  if (size <= 0 || f.status === "deleted" || f.binary) return gap.before ? [`<tr class="hunk"><td colspan="${cols}">${esc(gap.before.header)}</td></tr>`] : [];
  const down = Math.min(open.down, size), up = Math.min(open.up, size - down), hidden = size - down - up;
  const line = (n) => {
    const l = { t: " ", o: n + gap.delta, n, s: src?.[n - 1] ?? "" };
    return layout === "split"
      ? `<tr class="ctx expanded"><td class="ln">${l.o}</td>${codeCell(f, l, "new", "ctx")}<td class="ln">${l.n}</td>${codeCell(f, l, "new", "ctx")}</tr>`
      : `<tr class="ctx expanded"><td class="ln">${l.o}</td><td class="ln">${l.n}</td>${codeCell(f, l, "new", "ctx")}</tr>`;
  };
  const rows = [];
  for (let n = gap.from; n < gap.from + down; n++) rows.push(line(n));
  if (hidden > 0) {
    const btn = (dir, label, title) => `<button class="expand" data-action="expand-gap" data-path="${esc(f.path)}" data-from="${gap.from}" data-dir="${dir}" title="${title}">${label}</button>`;
    const first = gap.from === 1, last = !gap.before, small = hidden <= EXPAND_STEP;
    const buttons = small && Number.isFinite(hidden) ? btn("all", "↕", `Show ${plural(hidden, "hidden line")}`)
      : [first ? "" : btn("down", "↓", `Show ${EXPAND_STEP} more lines below`), last ? "" : btn("up", "↑", `Show ${EXPAND_STEP} more lines above`)].join("");
    const what = gap.before ? esc(gap.before.header) : Number.isFinite(hidden) ? `${plural(hidden, "more line")} to the end of the file` : "";
    rows.push(`<tr class="hunk gap"><td colspan="${cols}"><span class="expanders">${buttons}</span>${what}</td></tr>`);
  }
  for (let n = gap.from + size - up; n <= gap.to && n < gap.from + size; n++) rows.push(line(n));
  return rows;
}

async function expandGap(el) {
  const ctx = reviewCtx, f = ctx?.files.find((x) => x.path === el.dataset.path);
  if (!f) return;
  const key = `${ctx.head}:${f.path}`;
  if (!reviewSource.has(key)) {
    el.disabled = true;
    try {
      const got = await api(`/api/tasks/${encodeURIComponent(ctx.task)}/review/source?rev=${ctx.head}&path=${encodeURIComponent(f.path)}`);
      reviewSource.set(key, got.lines);
    } catch (err) {
      el.disabled = false;
      return toast(err.message, true);
    }
  }
  const from = +el.dataset.from, gap = diffGaps(f).find((g) => g.from === from);
  if (!gap) return;
  const all = reviewExpanded.get(key) || {}, open = all[from] || { down: 0, up: 0 };
  const size = gap.to - gap.from + 1;
  if (el.dataset.dir === "all") open.down = size;
  else open[el.dataset.dir] += EXPAND_STEP;
  all[from] = open;
  reviewExpanded.set(key, all);
  redrawDiffFile(f);
}

// Draw one file of the review again, in place (the rest of the page stays as it is).
function redrawDiffFile(f) {
  const ctx = reviewCtx, index = ctx.files.indexOf(f), old = document.getElementById(`file-${index}`);
  if (!old) return;
  const tmp = document.createElement("div");
  tmp.innerHTML = diffFile(f, ctx.drafts, new Set(), ctx.posted, ctx.dev, ctx.layout, index);
  const fresh = tmp.firstElementChild;
  fresh.open = old.open;
  old.replaceWith(fresh);
}

function diffFile(f, drafts, shown, posted = new Map(), dev = "", layout = "unified", index = 0) {
  const rows = [], cols = layout === "split" ? 4 : 3;
  const gaps = reviewCtx && !f.binary ? diffGaps(f) : [];
  const comments = (keys) => {
    for (const key of keys) {
      shown.add(key);
      for (const { c, r } of posted.get(key) || []) rows.push(`<tr class="comment-row"><td colspan="${cols}">${postedCard(c, r, dev)}</td></tr>`);
      for (const c of drafts.get(key) || []) rows.push(`<tr class="comment-row"><td colspan="${cols}">${draftCard(c)}</td></tr>`);
    }
  };
  f.hunks.forEach((h, k) => {
    markHunk(h.lines);
    rows.push(...(gaps[k] ? gapRows(f, gaps[k], layout, cols) : [`<tr class="hunk"><td colspan="${cols}">${esc(h.header)}</td></tr>`]));
    if (layout === "split") {
      for (const p of pairUp(h.lines)) {
        if (p.ctx) {   // an unchanged line is commented on as the new code, like in the unified view
          rows.push(`<tr class="ctx"><td class="ln">${p.o.o}</td>${codeCell(f, p.o, "new", "ctx")}<td class="ln">${p.n.n}</td>${codeCell(f, p.n, "new", "ctx")}</tr>`);
          comments([lineKey(f.path, "new", p.n.n)]);
          continue;
        }
        const left = p.o ? `<td class="ln del">${p.o.o}</td>${codeCell(f, p.o, "old", "del")}` : `<td class="ln blank"></td><td class="code blank"></td>`;
        const right = p.n ? `<td class="ln add">${p.n.n}</td>${codeCell(f, p.n, "new", "add")}` : `<td class="ln blank"></td><td class="code blank"></td>`;
        rows.push(`<tr>${left}${right}</tr>`);
        comments([...(p.o ? [lineKey(f.path, "old", p.o.o)] : []), ...(p.n ? [lineKey(f.path, "new", p.n.n)] : [])]);
      }
      return;
    }
    for (const l of h.lines) {
      const side = l.t === "-" ? "old" : "new", line = side === "old" ? l.o : l.n;
      const kind = l.t === "+" ? "add" : l.t === "-" ? "del" : "ctx";
      rows.push(`<tr class="${kind}"><td class="ln">${l.o ?? ""}</td><td class="ln">${l.n ?? ""}</td>${codeCell(f, l, side, kind)}</tr>`);
      comments([lineKey(f.path, side, line)]);
    }
  });
  if (f.hunks.length && gaps.length && f.status !== "added") rows.push(...gapRows(f, gaps[gaps.length - 1], layout, cols));
  const changed = f.additions + f.deletions;
  const label = { added: "new file", deleted: "deleted", renamed: `renamed from ${f.old_path}` }[f.status] || "";
  return `<details class="review-file ${f.viewed ? "is-viewed" : ""}" id="file-${index}" data-index="${index}" data-path="${esc(f.path)}" ${changed > 400 || f.viewed ? "" : "open"}>
    <summary><code class="path" title="${esc(f.path)}"><bdi>${esc(f.path)}</bdi></code>${label ? ` <span class="muted file-label">${esc(label)}</span>` : ""}
      ${f.changed_since_viewed ? `<span class="pill warn changed-since">Changed since you viewed it</span>` : ""}
      <span class="counts"><span class="plus">+${f.additions}</span> <span class="minus">−${f.deletions}</span></span>
      <button class="viewed-toggle" data-action="mark-viewed" aria-pressed="${!!f.viewed}" title="Mark as viewed: it folds away until the dev changes it"><span class="box" aria-hidden="true"></span>Viewed</button></summary>
    ${f.binary ? `<p class="muted pad">Binary file, not shown.</p>` : rows.length ? `<div class="table-wrap" style="contain-intrinsic-size: auto ${rows.length * 24}px"><table class="code-diff ${layout}">
      <colgroup>${layout === "split" ? `<col class="ln"><col class="half"><col class="ln"><col class="half">` : `<col class="ln"><col class="ln"><col>`}</colgroup>
      <tbody>${rows.join("")}</tbody></table></div>` : `<p class="muted pad">No line changes.</p>`}
  </details>`;
}

// The changed files under their folders, like GitHub's file tree. Folders with a single subfolder and no files of
// their own are shown on one line (backend/src/hive). Each folder can be folded; a file jumps to its diff.
function fileTree(files, drafts) {
  const root = { dirs: new Map(), files: [] };
  files.forEach((f, index) => {
    const parts = f.path.split("/");
    let node = root;
    for (const dir of parts.slice(0, -1)) {
      if (!node.dirs.has(dir)) node.dirs.set(dir, { dirs: new Map(), files: [] });
      node = node.dirs.get(dir);
    }
    node.files.push({ f, index, name: parts.at(-1) });
  });
  const notes = (path) => [...drafts.values()].flat().filter((c) => c.file === path).length;
  const STATUS = { added: ["A", "Added"], deleted: ["D", "Deleted"], renamed: ["R", "Renamed"] };
  const render = (node, prefix) => {
    const dirs = [...node.dirs].sort(([a], [b]) => a.localeCompare(b)).map(([name, sub]) => {
      let label = name, path = `${prefix}${name}/`;
      while (!sub.files.length && sub.dirs.size === 1) {   // a chain of single folders reads as one path
        const [[next, deeper]] = sub.dirs;
        label += `/${next}`; path += `${next}/`; sub = deeper;
      }
      return `<li><details open data-dir="${esc(path)}"><summary class="tree-dir" title="${esc(path)}">
        <svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 3.5h4.2l1.5 1.6h7.3v7.4H1.5z"/></svg><span>${esc(label)}</span></summary>
        <ul>${render(sub, path)}</ul></details></li>`;
    });
    const items = node.files.sort((a, b) => a.name.localeCompare(b.name)).map(({ f, index, name }) => {
      const [letter, word] = STATUS[f.status] || ["M", "Modified"];
      const n = notes(f.path);
      return `<li><button class="tree-file ${f.viewed ? "viewed" : ""}" data-action="jump-file" data-index="${index}" title="${esc(f.path)}${f.viewed ? " (viewed)" : ""}">
        <span class="st ${letter}" title="${word}">${letter}</span><span class="name">${esc(name)}</span>
        ${n ? `<span class="notes" title="${plural(n, "draft comment")}">${n}</span>` : ""}
        <span class="counts"><span class="plus">+${f.additions}</span> <span class="minus">−${f.deletions}</span></span><span class="seen" aria-hidden="true">✓</span></button></li>`;
    });
    return dirs.join("") + items.join("");
  };
  return `<aside class="review-tree" aria-label="Changed files">
    <div class="tree-head"><b>Files</b> <span class="muted viewed-count" title="Files you marked viewed">${files.filter((f) => f.viewed).length}/${files.length} viewed</span>
      <button class="icon-btn tree-fold" data-action="tree-fold" data-open="false" aria-label="Collapse all folders" title="Collapse all folders">${FOLD_ICON(false)}</button>
      <button class="icon-btn hide-viewed" data-action="hide-viewed" aria-pressed="${hideViewed()}" aria-label="Hide viewed files" title="${hideViewed() ? "Show" : "Hide"} the files you marked viewed">${eyeIcon(hideViewed())}</button>
      <button class="icon-btn tree-hide" data-action="review-tree" aria-label="Hide the files" title="Hide the files, show only the diff"><svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1.5"/><path d="M6 2.8v10.4M10.5 6.2 8.7 8l1.8 1.8"/></svg></button></div>
    <ul class="tree">${render(root, "")}</ul></aside>`;
}

const FOLD_ICON = (open) => `<svg class="ico" viewBox="0 0 16 16" aria-hidden="true">${open
  ? '<path d="M5 6.5 8 3.5l3 3M5 9.5l3 3 3-3"/>' : '<path d="M5 3.5 8 6.5l3-3M5 12.5l3-3 3 3"/>'}</svg>`;
const eyeIcon = (hidden) => `<svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 8s2.4-4.5 6.5-4.5S14.5 8 14.5 8 12.1 12.5 8 12.5 1.5 8 1.5 8z"/><circle cx="8" cy="8" r="2"/>${hidden ? '<path d="M2.5 13.5l11-11"/>' : ""}</svg>`;

// Whether files you marked viewed are hidden from the diff and the tree, remembered in this browser.
function hideViewed() {
  try { return localStorage.getItem("hideViewed") === "1"; } catch { return false; }
}
function viewedCount() {
  return `${document.querySelectorAll(".review-file.is-viewed").length}/${document.querySelectorAll(".review-file").length} viewed`;
}

// Whether the file tree is shown next to the diff, remembered in this browser.
function reviewTreeShown() {
  try { return localStorage.getItem("reviewTree") !== "hidden"; } catch { return true; }
}

// The file at the top of the screen is highlighted in the tree while you scroll the diff. A file you jumped to
// stays highlighted until you scroll yourself (the last files can't scroll up to the top).
let treeFrame = 0, jumpedTo = null;
addEventListener("scroll", () => {
  if (treeFrame || !document.querySelector(".review-tree")) return;
  treeFrame = requestAnimationFrame(() => {
    treeFrame = 0;
    const files = [...document.querySelectorAll(".review-file")];
    const current = (jumpedTo?.isConnected && jumpedTo) || files.filter((f) => f.getBoundingClientRect().top < 120).pop() || files[0];
    document.querySelectorAll(".tree-file").forEach((b) => b.classList.toggle("current", current && b.dataset.index === current.id.slice(5)));
  });
}, { passive: true });
for (const type of ["wheel", "touchmove", "keydown"]) addEventListener(type, () => { jumpedTo = null; }, { passive: true });

function roundCard(r, dev) {
  const asked = r.verdict === "changes";
  const items = r.comments.map((c) => `<li><div class="who">${commentWhere(c)}</div>
      ${c.code ? `<pre class="snippet">${esc(c.code)}</pre>` : ""}<div class="prose">${md(c.body)}</div>
      ${asked ? `<div class="reply ${c.reply ? "" : "none"}"><span class="pill dev">${esc(dev ? nameOf(dev) : "Dev")}</span> ${c.reply ? esc(c.reply) : "No reply yet."}</div>` : ""}</li>`).join("");
  return `<article class="review-round ${asked ? "changes" : "approved"}">
    <header><strong>Round ${r.shown || r.n}</strong>${r.onTask ? ` <a class="muted" href="#/tasks/${esc(r.onTask)}">${esc(r.onTask)}</a>` : ""} <span class="pill ${asked ? "lead" : "dev"}">${asked ? "Changes requested" : "Approved"}</span>
      <span class="muted">${esc(ago(r.at))}, at <code>${esc(r.commit.slice(0, 7))}</code>, ${esc(r.describes.replace(/`/g, ""))}</span></header>
    ${r.summary ? `<div class="prose">${md(r.summary)}</div>` : ""}
    ${items ? `<ol class="round-comments">${items}</ol>` : ""}</article>`;
}

async function CodeReview(r) {
  const view = reviewView();
  const earlier = view === "earlier";   // your earlier reviews, in their own tab (the diff tabs show their comments on the lines)
  const [t, d] = await Promise.all([api(`/api/tasks/${encodeURIComponent(r.id)}`),
    api(`/api/tasks/${encodeURIComponent(r.id)}/review?mode=${earlier ? "feature" : view}`)]);
  const drafts = new Map();
  for (const c of d.pending) {
    if (!c.file || !c.line) continue;
    const key = lineKey(c.file, c.side, c.line);
    drafts.set(key, [...(drafts.get(key) || []), c]);
  }
  const shown = new Set();
  const posted = placePosted(d.files, d.rounds, d.head);
  const layout = reviewLayout();
  reviewCtx = { task: d.task, head: d.head, files: d.files, drafts, posted, dev: d.dev, layout };
  const files = d.files.map((f, i) => diffFile(f, drafts, shown, posted, d.dev, layout, i)).join("");
  const treeOn = reviewTreeShown() && d.files.length > 0;
  const treeStrip = `<button class="tree-strip" data-action="review-tree" aria-label="Show the files" title="Show the files">
    <svg class="ico" viewBox="0 0 16 16" aria-hidden="true"><rect x="1.8" y="2.8" width="12.4" height="10.4" rx="1.5"/><path d="M6 2.8v10.4M8.7 6.2 10.5 8 8.7 9.8"/></svg>
    <span>Files ${d.files.length}</span></button>`;
  const elsewhere = d.pending.filter((c) => !c.file || !c.line || !shown.has(lineKey(c.file, c.side, c.line)));
  const adds = d.files.reduce((n, f) => n + f.additions, 0), dels = d.files.reduce((n, f) => n + f.deletions, 0);
  const tabs = REVIEW_VIEWS.map(([v, label]) => {
    const off = v === "since" && !d.last_reviewed;
    return off ? `<span class="tab off" title="After your first review">${label}</span>`
      : `<a class="tab" href="${reviewHref(t.id, v)}" ${v === d.mode && !earlier ? 'aria-current="page"' : ""}>${label}${v === "since" ? ` <code>${esc(d.last_reviewed.slice(0, 7))}</code>` : ""}</a>`;
  }).join("") + (d.rounds.length
    ? `<a class="tab" href="${reviewHref(t.id, "earlier")}" ${earlier ? 'aria-current="page"' : ""}>Earlier reviews <span class="count">${d.rounds.length}</span></a>`
    : `<span class="tab off" title="After your first review">Earlier reviews</span>`);
  // rounds are numbered along the branch; each names its task when the branch has had several
  const severalTasks = new Set(d.rounds.map((x) => x.task)).size > 1;
  const numbered = d.rounds.map((x, i) => ({ ...x, shown: i + 1, onTask: severalTasks ? x.task : "" }));
  const rounds = numbered.slice().reverse().map((x, i) => i === 0 ? roundCard(x, d.dev)
    : `<details class="older-round"><summary>Round ${x.shown}${x.onTask ? ` (${esc(x.onTask)})` : ""}, ${x.verdict === "changes" ? "changes requested" : "approved"} ${esc(ago(x.at))}</summary>${roundCard(x, d.dev)}</details>`).join("");
  const sent = state.reviewSent?.task === d.task ? sentBanner(state.reviewSent, d) : "";
  const elsewhereTask = d.opened && d.task !== d.opened
    ? `<p class="notice">This branch's current task is <a href="#/tasks/${esc(d.task)}">${esc(d.task)}</a>: your comments and reviews go there, to the dev working on it.</p>` : "";
  const dev = d.dev && nameOf(d.dev);
  state.reviewFolder = { folder: d.folder, onBranch: d.folder_on_branch, branch: d.branch };
  return `<p><a href="#/tasks/${esc(t.id)}" class="muted">${esc(t.id)}</a></p>
    <div class="page-head"><div><h1>Review: ${esc(t.title)}</h1>
      <p><code>${esc(d.branch)}</code> into <code>${esc(d.base)}</code>, ${statusPill(t.status)} with ${esc(holderText(t).replace(/^You/, "you"))}${d.head ? `, latest commit <code>${esc(d.head.slice(0, 7))}</code>` : ""}</p>${elsewhereTask}</div>
      <div class="btn-row">${d.status === "done" && d.head ? `<a class="btn ${d.pending.length ? "" : "primary"} land-link" href="#/tasks/${esc(t.id)}/pr">Prepare the pull request</a>` : ""}
        ${d.pending.length ? `<button class="btn primary" data-action="finish-review">Finish your review (${plural(d.pending.length, "draft")})</button>` : ""}</div></div>
    ${sent}
    <section class="section">
      <div class="review-bar"><nav class="tabs" aria-label="What to compare">${tabs}</nav>
        ${!earlier && d.head && editorOn() ? `<button class="btn small open-editor" data-action="open-folder" title="Open the branch in ${editorName()} (or hold .)">Open in editor <kbd>.</kbd></button>` : ""}
        ${d.files.length && !earlier ? `<button class="btn small tree-toggle" data-action="review-tree" aria-pressed="${treeOn}" title="Show or hide the file tree">Files</button>` : ""}
        ${earlier ? "" : `<div class="segmented" role="group" aria-label="Layout">${[["unified", "Unified"], ["split", "Side by side"]].map(([v, label]) =>
          `<button class="btn small" data-action="review-layout" data-layout="${v}" aria-pressed="${v === layout}">${label}</button>`).join("")}</div>`}</div>
      ${earlier ? `<p class="muted">Every review you've submitted on this branch, newest first, with ${esc(dev || "the dev")}'s replies. Your comments also show on their lines in the other tabs.</p>${rounds}` : `<p class="muted">Showing ${esc(d.describes.replace(/`/g, ""))}${d.files.length ? `: ${plural(d.files.length, "file")}, <span class="plus">+${adds}</span> <span class="minus">−${dels}</span>` : ""}. Hover a line and press <b>+</b> to comment on it.</p>

      ${files ? `<div class="review-body ${treeOn ? "with-tree" : "tree-folded"} ${hideViewed() ? "hide-viewed" : ""}">${fileTree(d.files, drafts)}${treeStrip}<div class="review-diffs">${files}</div></div>`
        : `<div class="empty">${d.head ? "No changes in this view." : esc(d.describes)}</div>`}`}
    </section>
    ${earlier ? "" : `<section class="section review-submit" id="review-submit"><h2>Your review</h2>
      ${elsewhere.length ? `<div class="drafts">${elsewhere.map((c) => draftCard(c, { where: true })).join("")}</div>` : ""}
      <label for="review-note">General comment <span class="muted">(optional, sent with your review)</span></label>
      <textarea id="review-note" rows="3" placeholder="Anything that isn't about one line. For example: errors here are always { code, message }.">${esc(state.reviewNote[t.id] || "")}</textarea>
      <div class="btn-row">
        <button class="btn primary" data-action="submit-review" data-verdict="changes" ${d.can_request_changes ? "disabled" : ""}>Request changes</button>
        <button class="btn" data-action="submit-review" data-verdict="approve" ${d.head ? "" : "disabled"}>Approve</button></div>
      <p class="hint">${d.can_request_changes ? esc(d.can_request_changes) + " " : ""}<b>Request changes</b> sends ${d.pending.length ? plural(d.pending.length, "draft comment") : "your comments"} (and the general comment) back to ${esc(dev || "the dev who built it")}, who answers each one, fixes the code on the same branch, then hands it to the reviewer again. <b>Approve</b> only records your approval: the reviewer still has the last word before done.</p>
    </section>`}`;
}

// ---- Reviews: every feature branch, like a list of pull requests --------------------------

const REVIEW_TABS = [["open", "Open"], ["draft", "Draft"], ["done", "Done"]];
const YOUR_REVIEW = { new: ["New commits since your review", "rv-waiting"], none: ["Not reviewed yet", "rv-waiting"],
  approved: ["You approved", "rv-approved"], changes: ["Changes requested", "rv-changes"] };

async function Reviews() {
  const all = await api("/api/reviews");
  state.reviews = all;
  showCounts();
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const tab = REVIEW_TABS.some(([k]) => k === params.get("tab")) ? params.get("tab") : "open";
  const projects = [...new Set(all.map((b) => b.project_name))].sort();
  const tabs = REVIEW_TABS.map(([k, label]) => `<a class="tab" href="#/reviews?tab=${k}" ${k === tab ? 'aria-current="page"' : ""}>${label} <span class="count">${all.filter((b) => b.state === k).length}</span></a>`).join("");
  const holder = (b) => b.state === "done" ? "done"
    : b.status === "in-review" ? `${b.reviewer ? nameOf(b.reviewer) : "the reviewer"} is reviewing`
    : b.status === "ready-for-review" ? `ready for review ${ago(b.updated)}`
    : b.status === "in-dev" || b.status === "changes-requested" ? `${b.dev ? nameOf(b.dev) : "a dev"} ${b.status === "in-dev" ? "is building" : "has your changes"}`
    : stageLabel(b.status).toLowerCase();
  const row = (b) => {
    // done branches show no review state: after you merge (and maybe delete) them, there's nothing left to review
    const [you, cls] = b.state === "done" ? (b.merged ? ["Merged", "rv-approved"] : b.pr ? ["Pull request open", "rv-waiting"] : b.head ? ["Not landed yet", "rv-quiet"] : ["", ""])
      : !b.head ? ["No code yet", "rv-quiet"] : YOUR_REVIEW[b.your_review];
    const ids = b.tasks.map((x) => x.id).join(" ");
    return `<a class="rv-row" href="${reviewHref(b.task)}" data-search="${esc(`${b.title} ${b.branch} ${ids} ${b.tasks.map((x) => x.title).join(" ")}`.toLowerCase())}" data-project="${esc(b.project_name)}">
      <span class="rv-ico ${b.state}" aria-label="${b.state}"></span>
      <span class="rv-main"><span class="rv-title">${esc(b.title)}</span>
        <span class="rv-meta"><code>${esc(b.branch)}</code> · ${esc(b.project_name)} · ${esc(ids.replaceAll(" ", ", "))} · ${esc(holder(b))}</span></span>
      ${you ? `<span class="rv-you ${cls}">${esc(you)}</span>` : "<span></span>"}
      <span class="rv-size">${b.size ? `${plural(b.size.files, "file")} · <span class="plus">+${b.size.additions}</span> <span class="minus">−${b.size.deletions}</span>` : ""}</span></a>`;
  };
  const rows = all.filter((b) => b.state === tab);
  const empty = { open: "Nothing to review: no branch is ready for review.", draft: "No branch is being built right now.", done: "No finished branches yet." }[tab];
  return `<div class="page-head"><div><h1>Reviews</h1><p class="muted">Every feature branch the team has worked on, and where your review stands. Open one to review it.</p></div></div>
    <nav class="tabs rv-tabs" aria-label="Branches">${tabs}</nav>
    <div class="rv-filters"><input type="search" id="rv-search" placeholder="Search by branch, title or task ID…" aria-label="Search reviews" autocomplete="off">
      ${projects.length > 1 ? `<select id="rv-project" aria-label="Project"><option value="">All projects</option>${projects.map((p) => `<option>${esc(p)}</option>`).join("")}</select>` : ""}</div>
    ${rows.length ? `<div class="rv-list">${rows.map(row).join("")}</div><p class="empty rv-none" hidden>No branch matches.</p>` : `<div class="empty">${empty}</div>`}
    ${tab === "done" ? `<p class="hint">Done means every task on the branch is done. Open one and press <b>Prepare the pull request</b> to tidy its commits, push it and open the pull request; merging stays yours, on GitHub.</p>` : ""}`;
}

// ---- Landing a finished branch: clean up its history (like git rebase -i), push it, open the pull request ----

const LAND_ACTIONS = [["pick", "Keep"], ["squash", "Squash into the one above"], ["fixup", "Fold into the one above, drop its message"], ["drop", "Drop"]];
const withoutAgentLine = (m) => m.split("\n").filter((l) => !/^Agent:\s*\S+/.test(l)).join("\n").replace(/\n{3,}/g, "\n\n").trim();

async function loadLand(id, fresh = true) {
  const plan = await api(`/api/tasks/${encodeURIComponent(id)}/land?fresh=${fresh}`);
  const old = state.land[id];
  const same = old && old.plan.commits.map((c) => c.sha).sort().join() === plan.commits.map((c) => c.sha).sort().join();
  state.land[id] = same ? { ...old, plan } : {
    plan, edited: {}, error: "", conflicts: [],
    steps: plan.commits.map((c, i) => ({ sha: c.sha, action: i === 0 ? "pick" : "fixup" })),   // one commit, by default
    title: old?.title ?? plan.pr_title, body: old?.body ?? plan.pr_body, draft: old?.draft ?? false,
  };
  return state.land[id];
}

// The commits the lead's choices make: each pick starts one, squash and fixup join the one before.
function landGroups(L) {
  const bySha = Object.fromEntries(L.plan.commits.map((c) => [c.sha, c]));
  const groups = [];
  for (const s of L.steps) {
    if (s.action === "drop") continue;
    if (s.action === "pick" || !groups.length) groups.push({ key: s.sha, commits: [], invalid: s.action !== "pick" });
    groups[groups.length - 1].commits.push({ ...bySha[s.sha], action: s.action });
  }
  return groups;
}

function landMessage(L, g) {
  if (g.key in L.edited) return L.edited[g.key];
  if (g.commits.length === L.plan.commits.length && g.commits.length > 1) return L.plan.draft_message;
  return g.commits.filter((c, i) => i === 0 || c.action === "squash").map((c) => withoutAgentLine(c.message)).join("\n\n");
}

async function Land(r, quiet) {
  // At once from what Hive knows, then again once it has asked GitHub (that takes a few seconds).
  const L = quiet && state.land[r.id] ? state.land[r.id] : await loadLand(r.id, false);
  if (!quiet) {
    loadLand(r.id, true).then(() => { if (route().page === "land" && route().id === r.id) render(true); })
      .catch((err) => { state.land[r.id].error = err.message; if (route().page === "land") render(true); });
  }
  const p = L.plan;
  const groups = landGroups(L);
  const blocked = p.not_ready || groups.some((g) => g.invalid);
  const many = p.commits.length > 1;
  const oneMessage = L.oneMessage ?? p.draft_message;
  const rows = L.steps.map((s, i) => {
    const c = p.commits.find((x) => x.sha === s.sha);
    return `<li class="land-commit act-${s.action}">
      <span class="moves"><button class="icon-btn" data-action="land-move" data-i="${i}" data-dir="-1" aria-label="Move up" ${i === 0 ? "disabled" : ""}>↑</button><button class="icon-btn" data-action="land-move" data-i="${i}" data-dir="1" aria-label="Move down" ${i === L.steps.length - 1 ? "disabled" : ""}>↓</button></span>
      <select data-land-step="${i}" aria-label="What to do with ${esc(c.short)}">${LAND_ACTIONS.map(([v, label]) => `<option value="${v}" ${v === s.action ? "selected" : ""}>${label}</option>`).join("")}</select>
      <code>${esc(c.short)}</code><span class="subject" title="${esc(c.message)}">${esc(c.subject)}</span>
      ${c.agent || p.can_undo ? "" : `<span class="land-yours" title="No Agent: line, so not made by an agent">yours</span>`}
      <span class="counts"><span class="plus">+${c.additions}</span> <span class="minus">−${c.deletions}</span></span></li>`;
  }).join("");
  const results = groups.map((g, i) => `<div class="land-result">
      <label for="land-msg-${i}">Commit ${i + 1} <span class="muted">from ${g.commits.map((c) => `<code>${esc(c.short)}</code>`).join(" ")}</span></label>
      ${g.invalid ? `<p class="warn">The first commit you keep has nothing above it to join: set it to <b>Keep</b>.</p>` : ""}
      <textarea id="land-msg-${i}" data-land-msg="${esc(g.key)}" rows="${Math.min(10, Math.max(3, landMessage(L, g).split("\n").length + 1))}">${esc(landMessage(L, g))}</textarea></div>`).join("");
  const pr = p.record.pr_url;
  const error = L.error ? `<div class="notice warn" role="alert"><p>${esc(L.error)}</p>
      ${L.conflicts.length && p.dev ? `<button class="btn small" data-action="land-ask-dev">Ask ${esc(personOf(p.dev))} to rebase it and resolve them</button>` : ""}</div>` : "";
  return `<p><a href="${reviewHref(r.id)}" class="muted">← Back to the review</a></p>
    <div class="page-head"><div><h1>Pull request: ${esc(p.tasks[0]?.title || p.branch)}</h1>
      <p><code>${esc(p.branch)}</code> onto <code>${esc(p.onto)}</code> · ${esc(p.tasks.map((x) => x.id).join(", "))}${p.fresh ? "" : ` · <span class="muted"><span class="spinner" aria-hidden="true"></span>checking GitHub…</span>`}</p></div></div>
    ${p.not_ready ? `<p class="notice">${esc(p.not_ready)}</p>` : ""}
    ${p.record.merged_at ? `<section class="sent-banner" role="status"><span class="tick" aria-hidden="true">✓</span><div><b>Merged on GitHub.</b> <span class="muted">Hive removed ${esc((p.record.removed || []).join(" and ") || "nothing")}.</span></div></section>` : ""}
    ${error}
    ${p.record.merged_at ? `<p>Pull request: <a href="${esc(pr)}" target="_blank" rel="noopener">${esc(pr)}</a></p>` : `<ol class="land-steps">
    <li class="section land-step"><h2>Commits</h2>
      <p class="muted">${plural(p.commits.length, "commit")} on the branch · ${p.behind ? `<b>${esc(p.onto)} has ${plural(p.behind, "new commit")}</b>, and the branch goes on top of ${p.behind > 1 ? "them" : "it"}` : `already on top of ${esc(p.onto)}`}.</p>
      ${many ? `<div class="land-one">Squashed, its message is <b>${esc(oneMessage.split("\n")[0])}</b>
        <button class="link" data-action="land-edit-one" aria-expanded="${!!L.editOne}">${L.editOne ? "Hide" : "Edit"}</button>
        ${L.editOne ? `<textarea data-land-msg="__one__" aria-label="The squashed commit's message" rows="${Math.min(12, oneMessage.split("\n").length + 2)}">${esc(oneMessage)}</textarea>` : ""}</div>` : ""}
      <div class="btn-row">
        ${many ? `<button class="btn primary" data-action="land-quick" data-preset="one" ${p.not_ready ? "disabled" : ""}>Squash into one commit${p.behind ? " and rebase" : ""}</button>` : ""}
        ${p.behind ? `<button class="btn ${many ? "" : "primary"}" data-action="land-quick" data-preset="keep" ${p.not_ready ? "disabled" : ""}>${many ? "Keep the commits and rebase" : `Rebase on ${esc(p.onto)}`}</button>` : ""}
        ${p.can_undo ? `<button class="btn" data-action="land-undo" title="Put back the commits as the team made them">Undo</button>` : ""}
        ${!many && !p.behind && !p.can_undo ? `<span class="muted">Nothing to tidy: one commit, on top of ${esc(p.onto)}.</span>` : ""}</div>
      <details class="land-more" ${L.more ? "open" : ""}><summary>More actions</summary>
        <p class="muted">Like <code>git rebase -i ${esc(p.onto)}</code>: choose, commit by commit, what to keep, squash or drop, and in which order.</p>
        <ol class="land-commits">${rows || `<li class="muted">No commits on the branch.</li>`}</ol>
        <h3>Result: ${plural(groups.length, "commit")} on ${esc(p.onto)}</h3>
        ${results}
        <div class="btn-row"><button class="btn primary" data-action="land-apply" ${blocked || !rows ? "disabled" : ""}>Apply${p.behind ? ` and rebase on ${esc(p.onto)}` : ""}</button></div>
      </details>
      <p class="hint">Nothing is lost: the commits as the team made them are kept${p.can_undo ? "" : " when you change them"}, for <b>Undo</b> and for the Coach. A conflict with ${esc(p.onto)} changes nothing.</p></li>
    <li class="section land-step"><h2>Push</h2>
      <p>${p.pushed ? "GitHub has this exact version of the branch." : p.on_origin ? "GitHub has an older version of the branch: pushing replaces it (safely: <code>--force-with-lease</code> stops if someone else pushed to it)." : "The branch isn't on GitHub yet."}</p>
      <div class="btn-row"><button class="btn ${p.pushed ? "" : "primary"}" data-action="land-push" ${p.pushed || p.not_ready ? "disabled" : ""}>Push to origin</button></div></li>
    <li class="section land-step"><h2>Pull request</h2>
      ${pr ? `<p>${p.record.pr_state === "closed" ? "Closed without merging: " : p.record.merged_at ? "Merged: " : "Open: "}<a href="${esc(pr)}" target="_blank" rel="noopener">${esc(pr)}</a></p>` : ""}
      ${p.gh ? `<form class="form land-pr" id="land-pr">
        <label for="land-title">Title</label><input type="text" id="land-title" value="${esc(L.title)}">
        <label for="land-body">Description <span class="muted">(written from the spec and the reviews)</span></label><textarea id="land-body" rows="10">${esc(L.body)}</textarea>
        ${pr ? "" : `<label class="check"><input type="checkbox" id="land-draft" ${L.draft ? "checked" : ""}> Open it as a draft</label>`}
        <div class="btn-row"><button class="btn ${p.pushed && !pr ? "primary" : ""}" ${p.on_origin && !p.record.merged_at ? "" : "disabled"}>${pr ? "Update the title and description" : "Open the pull request"}</button></div>
        ${p.on_origin ? "" : `<p class="hint">Push first.</p>`}</form>`
        : `<p class="muted">The GitHub CLI (<code>gh</code>) isn't installed on the Hive machine: open the pull request on GitHub.</p>`}</li>
    <li class="section land-step"><h2>Merge</h2>
      <p class="muted">Yours, on GitHub. Hive checks every 10 minutes; once it's merged, it removes the branch's worktree and local branch.</p></li>
    </ol>`}`;
}

async function landAct(fn) {
  const id = route().id, L = state.land[id];
  L.error = "";
  L.conflicts = [];
  try {
    const out = await fn(id, L);
    await loadLand(id);
    return out ?? true;
  } catch (err) {
    L.error = err.message;
    L.conflicts = err.data?.conflicts || [];
    return null;
  } finally {
    render(true);
  }
}

// Search and project filter on the Reviews page, in the page (no reload).
function filterReviews() {
  const q = (document.getElementById("rv-search")?.value || "").trim().toLowerCase();
  const project = document.getElementById("rv-project")?.value || "";
  let shown = 0;
  document.querySelectorAll(".rv-row").forEach((r) => {
    const on = (!q || q.split(/\s+/).every((w) => r.dataset.search.includes(w))) && (!project || r.dataset.project === project);
    r.hidden = !on;
    shown += on;
  });
  const none = document.querySelector(".rv-none");
  if (none) none.hidden = shown > 0;
}

// The banner after you submit a review: what happened, and the next step (request the final review, or back to the board).
function sentBanner(s, d) {
  const task = { id: d.task, status: d.status, reviewer: d.reviewer, dev: d.dev };
  const dev = d.dev ? nameOf(d.dev) : "the dev";
  const reviewer = handCandidates(task)[0];
  let title, next = "", button = "";
  // whoever has the branch now: the dev it went back to, or the reviewer you handed it to
  const chat = s.verdict === "changes" ? d.dev : s.handed || (d.status === "in-review" ? d.reviewer : "") || d.dev;
  if (s.verdict === "changes") {
    title = `Sent back to ${dev} with ${plural(s.comments, "comment")}`;
    next = s.told ? `${dev} is on it now.` : `It's in ${dev}'s inbox.`;
  } else {
    title = "You approved this branch";
    if (s.handed) next = `Final review requested: ${personOf(s.handed)} is on it now.`;
    else if (d.status === "ready-for-review" && reviewer) {
      next = "The reviewer has the last word before it's done.";
      button = `<button class="btn small primary" data-action="hand" data-task="${esc(d.task)}" data-agent="${reviewer}">Request final review from ${esc(personOf(reviewer))}</button>`;
    } else if (d.status === "in-review") next = `${d.reviewer ? nameOf(d.reviewer) : "The reviewer"} is reviewing it now.`;
    else if (d.status === "done") next = "It's done.";
    else next = `${dev} is still on it; it goes to the reviewer when ${dev} hands it on.`;
  }
  return `<section class="sent-banner" role="status"><span class="tick" aria-hidden="true">✓</span>
    <div><b>${esc(title)}.</b> <span class="muted">${esc(next)}</span></div>
    <div class="btn-row">${button}${chat ? `<a class="btn small ${button ? "" : "primary"}" href="#/agents/${esc(chat)}">Go to ${esc(personOf(chat))}'s chat</a>` : ""}<a class="btn small" href="#/tasks">Back to Board</a></div></section>`;
}

// Up to three lines ending at this one, on the same side, as the comment's code context.
function codeAbove(cell) {
  const side = cell.dataset.side, lines = [cell.dataset.s];
  let prev = cell.closest("tr").previousElementSibling;
  while (prev && lines.length < 3 && !prev.classList.contains("hunk")) {
    // the cell on the same side of that row (side by side), or that row's line if it's on this side (unified)
    const pick = [...prev.querySelectorAll("td.code[data-s]")].find((c) => c.dataset.side === side || c.classList.contains("ctx"));
    if (pick) lines.unshift(pick.dataset.s);
    prev = prev.previousElementSibling;
  }
  return lines.join("\n");
}

async function saveDraft(body) {
  const id = route().id;
  return act(() => api(`/api/tasks/${encodeURIComponent(id)}/review/comments`, { method: "POST", body }));
}

async function pingDev(dev, taskId) {
  if (!dev || !state.agents[dev]) return false;
  if (state.agents[dev].status === "stopped") {
    const started = await act(() => api(`/api/agents/${dev}/start`, { method: "POST", body: {} }));
    if (!started) return false;
  }
  return act(() => api(`/api/agents/${dev}/message`, { method: "POST",
    body: { text: `I reviewed the code of ${taskId} and requested changes. Work on it per your instructions.` } }));
}

// Open the branch's folder in your editor (that's what it indexes); once the worktree is gone (a done task), the
// project folder, which may be on another branch.
function reviewOpen() {
  const r = state.reviewFolder || {};
  if (!r.folder) return toast("This branch isn't checked out anywhere yet.", true);
  if (!r.onBranch) toast(`The branch's worktree was removed, so this opens your project folder, which may not be on ${r.branch}.`);
  if (editorPrefs().app !== "browser") { location.href = editorUrl(r.folder); return; }
  // Open the tab now, while the click still counts (later it would be blocked as a pop-up), then point it at VS Code.
  const tab = window.open("", "_blank");
  if (!tab) return toast("Your browser blocked the new tab: allow pop-ups for this site, or click Open in editor.", true);
  tab.document.title = "Opening VS Code…";
  api("/api/editor/open", { method: "POST", body: { folder: r.folder } })
    .then((d) => { tab.location.href = d.url; })
    .catch((err) => { tab.close(); toast(err.message, true); });
}

const reviewActions = {
  // Viewed, like GitHub: the file folds away and is ticked in the tree, until the dev changes it again.
  "mark-viewed": async (el) => {
    const file = el.closest(".review-file"), viewed = !file.classList.contains("is-viewed");
    const show = (on) => {
      file.classList.toggle("is-viewed", on);
      el.setAttribute("aria-pressed", String(on));
      document.querySelector(`.tree-file[data-index="${file.dataset.index}"]`)?.classList.toggle("viewed", on);
      const count = document.querySelector(".viewed-count");
      if (count) count.textContent = viewedCount();
    };
    show(viewed);
    if (viewed) {
      file.open = false;
      file.querySelector(".changed-since")?.remove();
      if (file.getBoundingClientRect().top < 64) file.scrollIntoView({ block: "start" });   // keep your place: the next file
    } else {
      file.open = true;
    }
    try {
      await api(`/api/tasks/${encodeURIComponent(route().id)}/review/viewed`, { method: "POST", body: { path: file.dataset.path, viewed, at: reviewCtx?.head || "" } });
    } catch (err) {
      show(!viewed);
      toast(err.message, true);
    }
  },
  "hide-viewed": (el) => {   // in the page only: no need to fetch the diff again
    const on = !hideViewed();
    try { localStorage.setItem("hideViewed", on ? "1" : ""); } catch { /* this page only */ }
    document.querySelector(".review-body")?.classList.toggle("hide-viewed", on);
    el.setAttribute("aria-pressed", String(on));
    el.title = `${on ? "Show" : "Hide"} the files you marked viewed`;
    el.innerHTML = eyeIcon(on);
  },
  "open-folder": () => reviewOpen(),
  "land-move": (el) => {
    const L = state.land[route().id], i = +el.dataset.i, j = i + +el.dataset.dir;
    if (j < 0 || j >= L.steps.length) return;
    [L.steps[i], L.steps[j]] = [L.steps[j], L.steps[i]];
    render(true);
  },
  "land-edit-one": () => {
    const L = state.land[route().id];
    L.editOne = !L.editOne;
    render(true);
  },
  "land-quick": (el) => {
    const L = state.land[route().id], commits = L.plan.commits, one = el.dataset.preset === "one";
    const steps = commits.map((c, i) => ({ sha: c.sha, action: one && i > 0 ? "fixup" : "pick" }));
    const messages = one ? [L.oneMessage ?? L.plan.draft_message] : commits.map((c) => c.message);
    landAct((id) => api(`/api/tasks/${encodeURIComponent(id)}/land/cleanup`, { method: "POST", body: { steps, messages } }))
      .then((out) => { if (out) { Object.assign(state.land[route().id], { edited: {}, oneMessage: undefined, editOne: false }); toast(`Done: ${plural(out.commits, "commit")} on ${out.onto}.`); } });
  },
  "land-apply": () => {
    const L = state.land[route().id];
    const messages = landGroups(L).map((g) => landMessage(L, g));
    landAct((id) => api(`/api/tasks/${encodeURIComponent(id)}/land/cleanup`, { method: "POST", body: { steps: L.steps, messages } }))
      .then((out) => { if (out) { state.land[route().id].edited = {}; toast(`Done: ${plural(out.commits, "commit")} on ${out.onto}.`); } });
  },
  "land-undo": () => {
    if (!confirm("Put the branch back as the team made it? Your clean-up is undone (you can do it again).")) return;
    landAct((id) => api(`/api/tasks/${encodeURIComponent(id)}/land/undo`, { method: "POST" })).then((out) => out && toast("The branch is back as the team made it."));
  },
  "land-push": () => {
    const p = state.land[route().id].plan;
    if (!confirm(`Push ${p.branch} to origin${p.on_origin ? ", replacing the version there" : ""}?`)) return;
    landAct((id) => api(`/api/tasks/${encodeURIComponent(id)}/land/push`, { method: "POST" })).then((out) => out && toast("Pushed."));
  },
  "land-ask-dev": () => {
    const L = state.land[route().id], p = L.plan;
    const text = `Please rebase ${p.branch} on ${p.onto} in ${p.folder} and resolve the conflicts in ${L.conflicts.join(", ")}. `
      + "Keep every commit as it is (no squashing: I'll clean up the history when I land it), run the tests, then tell me it's done.";
    act(() => api(`/api/agents/${p.dev}/message`, { method: "POST", body: { text } }))
      .then((ok) => ok && toast(`Sent to ${personOf(p.dev)}. Come back here once it's done.`));
  },
  "backup-now": async () => {
    const b = await act(() => api("/api/backup/run", { method: "POST" }));
    if (!b) return;
    state.backup = b;
    render(true);
    followBackup();
  },
  "backup-forget": () => { state.backupUpload = null; render(true); },
  "backup-restore": async () => {
    const up = state.backupUpload;
    if (!confirm(`Restore ${up.file}? Hive stops (with any running agents), puts this backup back and starts again.`)) return;
    const done = await act(() => api("/api/backup/restore", { method: "POST", body: { file: up.file } }));
    if (!done) return;
    state.backupUpload = { ...up, restarting: true };
    render(true);
    waitForRestart();
  },
  "expand-gap": (el) => expandGap(el),
  "questions-view": () => {
    try { localStorage.setItem("questionsView", questionsView() === "cards" ? "text" : "cards"); } catch { /* this page only */ }
    render(true);
  },
  "question-pick": (el) => {   // (the click handler's preventDefault keeps the question from opening or closing)
    const s = state.questions[el.dataset.q];
    s.pick[el.dataset.id] = el.dataset.key;
    if (el.closest(".q-mismatch")) {   // "B. keep it" was the answer itself: keep only what it adds
      s.notes[el.dataset.id] = (s.notes[el.dataset.id] || "").replace(/^\s*[a-z]\s*[.):\-–]?\s*/i, "");
    }
    if (el.dataset.key === "own") s.open.add(el.dataset.id);
    render(true);
  },
  "question-disagree": (el) => {
    const s = state.questions[el.dataset.q], i = +el.dataset.i;
    if (s.disagree[i] === undefined) s.disagree[i] = ""; else delete s.disagree[i];
    s.open.add("decisions");
    render(true);
  },
  "question-send": async (el) => {
    const key = el.dataset.q, q = questionsOf(key), s = state.questions[key];
    const missing = q.questions.findIndex((x) => s.pick[x.id] === "own" && !(s.notes[x.id] || "").trim());
    if (missing >= 0) return toast(`Write your answer to question ${missing + 1}, or pick one of its options.`, true);
    const unsure = q.questions.findIndex((x) => noteNamesOtherOption(x, s));
    if (unsure >= 0 && !confirm(`Question ${unsure + 1}: your note names another option than the one selected. Send anyway?`)) return;
    const ok = await act(() => api(`/api/agents/${el.dataset.agent}/message`, { method: "POST", body: { text: questionsReply(q, s) } }));
    if (ok) { s.sent = true; render(true); }
  },
  "chat-side": () => {
    try { localStorage.setItem("chatSide", chatSideShown() ? "hidden" : "shown"); } catch { /* this page only */ }
    renderChatSide(route().id);
  },
  "review-tree": () => {
    // Both the tree and its folded strip are on the page: only switch which one shows (no redraw of the diff).
    const show = !reviewTreeShown();
    try { localStorage.setItem("reviewTree", show ? "shown" : "hidden"); } catch { /* this page only */ }
    document.querySelector(".review-body")?.classList.toggle("with-tree", show);
    document.querySelector(".review-body")?.classList.toggle("tree-folded", !show);
    document.querySelector(".tree-toggle")?.setAttribute("aria-pressed", String(show));
  },
  "jump-file": (el) => {
    const file = document.getElementById(`file-${el.dataset.index}`);
    if (!file) return;
    file.open = true;
    jumpedTo = file;
    file.scrollIntoView({ block: "start", behavior: "smooth" });
  },
  "tree-fold": (el) => {
    // Only the top folders change; the ones inside keep their state but are hidden with them (one change, not hundreds).
    const open = el.dataset.open === "true";
    document.querySelectorAll(".review-tree .tree > li > details").forEach((d) => { d.open = open; });
    if (open) document.querySelectorAll(".review-tree details:not([open])").forEach((d) => { d.open = true; });
    el.dataset.open = String(!open);
    el.innerHTML = FOLD_ICON(!open);
    el.title = el.ariaLabel = open ? "Collapse all folders" : "Expand all folders";
  },
  "review-layout": (el) => {
    try { localStorage.setItem("reviewLayout", el.dataset.layout); } catch { /* remembered for this page only */ }
    render(true);
  },
  "comment-line": (el) => {
    const cell = el.closest("td");
    const row = el.closest("tr");
    let after = row;
    while (after.nextElementSibling?.classList.contains("comment-row")) after = after.nextElementSibling;
    if (after.nextElementSibling?.classList.contains("comment-form-row")) return after.nextElementSibling.querySelector("textarea").focus();
    after.insertAdjacentHTML("afterend", `<tr class="comment-form-row"><td colspan="${row.cells.length}"><form class="comment-form">
      <textarea rows="3" aria-label="Your comment on line ${cell.dataset.line}" placeholder="What should change here, and why?"></textarea>
      <div class="btn-row"><button class="btn small primary" type="submit">Add comment</button><button class="btn small" type="button" data-action="cancel-comment">Cancel</button></div></form></td></tr>`);
    const form = after.nextElementSibling.querySelector("form");
    const text = form.querySelector("textarea");
    text.focus();
    text.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) form.requestSubmit(); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (!text.value.trim()) return text.focus();
      const saved = await saveDraft({ body: text.value, file: cell.dataset.file, line: Number(cell.dataset.line), side: cell.dataset.side, code: codeAbove(cell) });
      if (saved) render(true);
    });
  },
  "cancel-comment": (el) => el.closest("tr").remove(),
  "edit-comment": (el) => {
    const card = el.closest(".review-comment");
    if (card.querySelector("textarea")) return;
    const body = card.querySelector(".body");
    api(`/api/tasks/${encodeURIComponent(route().id)}/review?mode=${reviewView()}`).then((d) => {
      const c = d.pending.find((x) => x.id === el.dataset.id);
      if (!c) return render(true);
      body.outerHTML = `<form class="comment-form"><textarea rows="3" aria-label="Edit your comment">${esc(c.body)}</textarea>
        <div class="btn-row"><button class="btn small primary" type="submit">Save</button></div></form>`;
      const form = card.querySelector("form");
      form.querySelector("textarea").focus();
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const ok = await act(() => api(`/api/tasks/${encodeURIComponent(route().id)}/review/comments/${el.dataset.id}`,
          { method: "PUT", body: { body: form.querySelector("textarea").value } }));
        if (ok) render(true);
      });
    });
  },
  "delete-comment": async (el) => {
    const ok = await act(() => api(`/api/tasks/${encodeURIComponent(route().id)}/review/comments/${el.dataset.id}`, { method: "DELETE" }));
    if (ok) render(true);
  },
  "finish-review": () => {
    const box = () => document.getElementById("review-submit");
    if (box()) return box().scrollIntoView({ behavior: "smooth" });
    location.hash = reviewHref(route().id);   // from Earlier reviews: your review is with the diff
    const wait = setInterval(() => { if (box()) { clearInterval(wait); box().scrollIntoView({ behavior: "smooth" }); } }, 100);
    setTimeout(() => clearInterval(wait), 5000);
  },
  "submit-review": async (el) => {
    const id = route().id, verdict = el.dataset.verdict;
    const comment = document.getElementById("review-note").value;
    const done = await act(() => api(`/api/tasks/${encodeURIComponent(id)}/review/submit`, { method: "POST", body: { verdict, comment, mode: reviewView() } }));
    if (!done) return;
    state.reviewNote[id] = "";
    const told = verdict === "changes" && await pingDev(done.dev, id);
    state.reviewSent = { task: done.task || id, verdict, comments: done.comments.length, told };
    location.hash = reviewHref(id, "feature");
    await render(true);
    scrollTo({ top: 0, behavior: "smooth" });   // the banner is at the top
  },
};

// ---- improvements (the Coach's proposals) and team history ---------------------------

// A change shown as a diff, line by line: unchanged lines plain, removed ones struck out, new ones added.
function diffLines(before, after) {
  const a = before ? before.split("\n") : [], b = after.split("\n");
  const lcs = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--)
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
  const out = [];
  let i = 0, j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) { out.push(`<span class="ctx">  ${esc(a[i])}</span>`); i++; j++; }
    else if (j < b.length && (i >= a.length || lcs[i][j + 1] >= lcs[i + 1][j])) out.push(`<span class="add">+ ${esc(b[j++])}</span>`);
    else out.push(`<span class="del">- ${esc(a[i++])}</span>`);
  }
  return `<pre class="diff">${out.join("")}</pre>`;
}

function unifiedDiff(text) {
  return `<pre class="diff">${text.split("\n").filter((l) => !/^(diff --git|index |--- |\+\+\+ |new file|deleted file)/.test(l)).map((l) =>
    `<span class="${l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "ctx"}">${esc(l)}</span>`).join("")}</pre>`;
}

const taskLinks = (ids) => ids.map((t) => `<a href="#/tasks/${esc(t)}">${esc(t)}</a>`).join(", ");

function proposalCard(p) {
  const pending = p.status === "pending";
  const changes = p.changes.map((c, i) => `<div class="change"><h4><code>${esc(c.file)}</code>${c.before ? "" : ` <span class="muted">added at the end</span>`}</h4>
      ${diffLines(c.before, c.after)}
      ${pending ? `<textarea class="edit-after" data-index="${i}" rows="${Math.min(18, c.after.split("\n").length + 2)}" hidden aria-label="New text for ${esc(c.file)}">${esc(c.after)}</textarea>` : ""}</div>`).join("");
  const decided = pending ? "" : `<p class="muted">${p.status === "approved" ? "Approved" : "Rejected"} ${esc(p.decided)}${p.note ? `: ${esc(p.note)}` : ""}${p.commit ? ` · <a href="#/team/${esc(p.commit)}">see the change</a>` : ""}</p>`;
  const head = `<header><h2><span class="muted">${esc(p.id)}</span> ${esc(p.title)}</h2>${pending ? "" : `<span class="muted proposal-when">${esc(p.decided)}</span>`}${statusWord(p.status)}</header>`;
  // a decided proposal is folded to its title line; click it to see the why, the evidence and the change
  return `${pending ? `<section class="proposal ${p.status}" id="${esc(p.id)}">${head}` : `<details class="proposal ${p.status}" id="${esc(p.id)}" data-proposal="${esc(p.id)}" ${state.openProposals.has(p.id) ? "open" : ""}><summary>${head}</summary>`}
    ${p.tasks.length ? `<p class="muted">Based on ${taskLinks(p.tasks)}</p>` : ""}
    <div class="prose"><h3>Why</h3>${md(p.why)}<h3>Evidence</h3>${md(p.evidence)}</div>
    <h3>Change</h3>${changes}
    ${p.problems.length ? `<p class="warn">Can't be applied as it is: ${esc(p.problems.join(" "))} Ask the Coach to fix it.</p>` : ""}
    ${decided}
    ${pending ? `<div class="btn-row">
      <button class="btn primary" data-action="approve" data-id="${esc(p.id)}" ${p.problems.length ? "disabled" : ""}>Approve</button>
      <button class="btn" data-action="edit-proposal" data-id="${esc(p.id)}">Edit before approving</button>
      <button class="btn" data-action="reject" data-id="${esc(p.id)}">Reject</button></div>` : ""}
  ${pending ? "</section>" : "</details>"}`;
}

const statusWord = (s) => `<span class="pill ${s === "approved" ? "dev" : s === "rejected" ? "lead" : "reviewer"}">${s}</span>`;

async function Improvements() {
  const list = await api("/api/improvements");
  const pending = list.filter((p) => p.status === "pending");
  const decided = list.filter((p) => p.status !== "pending");
  return `<div class="page-head"><div><h1>Improvements</h1>
      <p>The Coach reviews how finished tasks went (your corrections, reviews, follow-ups, your commits on the pull requests) and proposes changes to the team's instructions. Nothing changes until you approve; every approved change is committed and shows in <a href="#/team">Team history</a>, where you can undo it.</p></div></div>
    <section class="section review-form"><h2>Start a review</h2>
      <div class="form-row">
        <label>Review <select id="review-scope">
          <option value="last">everything since the last review</option>
          <option value="tasks">these tasks</option>
          <option value="project">one project</option>
          <option value="all">all tasks</option></select></label>
        <input id="review-target" placeholder="TASK-012, TASK-019  or  ~/code/my-api" aria-label="Tasks or project" hidden>
        <button class="btn role coach" data-action="start-review">Start the review</button>
      </div>
      <p class="hint">It runs on the Coach's model (Opus, thinking hard), so a review costs more than a normal task. It may ask you questions in its chat before proposing anything.</p></section>
    <section class="section"><h2>Waiting for you <span class="count">${pending.length}</span></h2>
      ${pending.length ? pending.map(proposalCard).join("") : `<p class="muted">No proposals waiting.</p>`}</section>
    ${decided.length ? `<section class="section"><h2>Decided <span class="count">${decided.length}</span></h2>${decided.map(proposalCard).join("")}</section>` : ""}`;
}

async function TeamHistory() {
  const data = await api("/api/team/history");
  if (!data.repo) return `<div class="page-head"><div><h1>Team history</h1></div></div><div class="empty">The Hive folder isn't a git repository, so there's no history to show.</div>`;
  const rows = data.changes.map((c) => `<tr data-href="#/team/${c.short}">
      <td class="num">${esc(new Date(c.date).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }))}</td>
      <td>${c.proposal ? `<span class="pill coach">Coach</span> <span class="muted">${esc(c.proposal)}</span>` : esc(c.by)}</td>
      <td><a href="#/team/${c.short}">${esc(c.subject)}</a>${c.tasks && c.tasks !== "-" ? `<br><small class="muted">from ${esc(c.tasks)}</small>` : ""}</td>
      <td>${c.files.map((f) => `<code>${esc(f)}</code>`).join(" ")}</td></tr>`).join("");
  return `<div class="page-head"><div><h1>Team history</h1>
      <p>Every change to the team's instructions (the agents' files, TEAM.md, PREFERENCES.md, templates), newest first: the Coach's approved proposals, your own edits and any other commit. Open one to see exactly what changed, read the team as it was then, or undo it.</p></div></div>
    ${rows ? `<div class="table-wrap"><table><thead><tr><th>When</th><th>Who</th><th>What</th><th>Files</th></tr></thead><tbody>${rows}</tbody></table></div>`
           : `<div class="empty">No changes yet.</div>`}`;
}

async function TeamChange(r) {
  const c = await api(`/api/team/history/${encodeURIComponent(r.id)}`);
  return `<p><a href="#/team" class="muted">Team history</a></p>
    <div class="page-head"><div><h1>${esc(c.subject)}</h1>
      <p>${c.proposal ? `<span class="pill coach">Coach</span> ${esc(c.proposal)}, approved by you` : `By ${esc(c.by)}`},
        ${esc(new Date(c.date).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }))}, <code>${esc(c.short)}</code>
        ${c.tasks && c.tasks !== "-" ? `· from ${taskLinks(c.tasks.split(",").map((t) => t.trim()))}` : ""}</p></div>
      <div class="btn-row"><a class="btn" href="#/team/${c.short}/files">See the team as of this change</a>
        ${c.undoable ? `<button class="btn" data-action="undo-team" data-sha="${c.short}">Undo this change</button>` : ""}</div></div>
    ${c.body ? `<div class="prose">${md(c.body)}</div>` : ""}
    ${!c.undoable && c.other_files.length ? `<p class="hint">This commit also changed other files (${c.other_files.slice(0, 4).map((f) => `<code>${esc(f)}</code>`).join(", ")}${c.other_files.length > 4 ? "…" : ""}), so it can't be undone from here.</p>` : ""}
    ${c.diffs.map((d) => `<section class="section"><h3><code>${esc(d.file)}</code></h3>${unifiedDiff(d.diff)}</section>`).join("")}`;
}

async function TeamFiles(r) {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const path = params.get("path") || "";
  const { files } = await api(`/api/team/at/${encodeURIComponent(r.id)}`);
  const shown = path ? await api(`/api/team/at/${encodeURIComponent(r.id)}?path=${encodeURIComponent(path)}`) : null;
  return `<p><a href="#/team/${esc(r.id)}" class="muted">Back to the change</a></p>
    <div class="page-head"><div><h1>The team as of <code>${esc(r.id)}</code></h1><p>The instructions exactly as they were after this change.</p></div></div>
    <div class="files-at"><nav class="file-list">${files.map((f) => `<a href="#/team/${esc(r.id)}/files?path=${encodeURIComponent(f)}" ${f === path ? 'aria-current="page"' : ""}>${esc(f)}</a>`).join("")}</nav>
      <div>${shown ? `<h2><code>${esc(shown.path)}</code></h2><pre class="file-view">${esc(shown.text)}</pre>` : `<p class="muted">Pick a file.</p>`}</div></div>`;
}

// ---- knowledge ------------------------------------------------------------------
// The Tech Lead's memory of each service (data/knowledge/<repo>/), read-only here.

function freshness(k) {
  if (!k.commit) return `<span class="pill lead">Never stamped</span>`;
  if (k.changed === null) return `<span class="pill lead" title="The recorded commit isn't in the repo anymore">Unverified</span>`;
  if (k.changed === 0) return `<span class="pill dev">Up to date</span>`;
  return `<span class="pill reviewer">${k.changed} file${k.changed > 1 ? "s" : ""} changed since</span>`;
}

const knowledgeHref = (repo, name) => `#/knowledge/${encodeURIComponent(repo)}${name && name !== "index" ? `/${encodeURIComponent(name)}` : ""}`;
const knowledgeLabel = (f) => f.kind === "index" ? "Index" : f.name;

async function KnowledgeList() {
  const repos = await api("/api/knowledge");
  const table = (repo) => `<div class="table-wrap"><table>
      <thead><tr><th>File</th><th>Covers</th><th>Freshness</th><th>Commit</th><th>Updated</th><th>By</th><th>Size</th></tr></thead>
      <tbody>${repo.files.map((f) => `<tr data-href="${knowledgeHref(repo.repo, f.name)}">
        <td><a href="${knowledgeHref(repo.repo, f.name)}">${esc(knowledgeLabel(f))}</a></td>
        <td>${f.scope.length ? f.scope.map((s) => `<code>${esc(s)}</code>`).join(" ") : `<span class="muted">${f.kind === "index" ? "whole repo" : "not set"}</span>`}</td>
        <td>${freshness(f)}</td><td><code>${esc(f.commit || "")}</code>${f.branch ? ` <small class="muted">${esc(f.branch)}</small>` : ""}</td>
        <td class="num">${esc(f.updated || "")}</td><td>${f.updated_by ? esc(nameOf(f.updated_by)) : ""}</td><td class="num">${f.lines} lines</td></tr>`).join("")}</tbody></table></div>`;
  return `<div class="page-head"><div><h1>Knowledge</h1>
      <p>The Tech Lead's memory of each repository: what it learned while writing specs, so the next task starts here instead of re-reading the code. A monorepo has an index plus one file per service; each file records the commit it describes, and "changed since" counts the files changed in its own folders after that.</p></div></div>
    ${repos.length ? repos.map((repo) => `<section class="section knowledge-repo"><h2>${esc(repo.repo)} <small class="muted"><code>${esc(repo.path)}</code></small></h2>${table(repo)}</section>`).join("")
      : `<div class="empty">Nothing yet. The Tech Lead writes a repository's knowledge the first time it specs a task there.</div>`}`;
}

async function KnowledgeView(r) {
  const name = r.sub || "index";
  const k = await api(`/api/knowledge/${encodeURIComponent(r.id)}/${encodeURIComponent(name)}`);
  const linked = k.markdown.replace(/(^|[^\w`\[\/-])(TASK-\d{3,})(?![\w-])/g, "$1[$2](#/tasks/$2)")
    .replace(/\|\s*([A-Za-z0-9._-]+)\.md\s*\|/g, (m, file) => k.siblings.some((s) => s.name === file) ? `| [${file}.md](${knowledgeHref(k.repo, file)}) |` : m);
  const tabs = k.siblings.length > 1 ? `<nav class="tabs">${k.siblings.map((s) => `<a href="${knowledgeHref(k.repo, s.name)}" ${s.name === name ? 'aria-current="page"' : ""}>${esc(s.kind === "index" ? "Index" : s.name)}</a>`).join("")}</nav>` : "";
  const changes = k.changed_files.length ? `<details class="changed"><summary>${k.changed} file${k.changed > 1 ? "s" : ""} changed since ${esc(k.commit)}${k.stale_sections.length ? `, touching: ${esc(k.stale_sections.join(", "))}` : ""}</summary>
      <ul>${k.changed_files.map((f) => `<li><code>${esc(f)}</code></li>`).join("")}</ul></details>` : "";
  return `<p><a href="#/knowledge" class="muted">All repositories</a></p>
    <div class="page-head"><div><h1>${esc(k.repo)}${k.kind === "service" ? ` <span class="muted">/</span> ${esc(k.name)}` : ""}</h1>
      <p>${freshness(k)} <code>${esc(k.path)}</code>${k.scope.length ? `, covers ${k.scope.map((s) => `<code>${esc(s)}</code>`).join(" ")}` : ""}${k.commit ? `, describes <code>${esc(k.commit)}</code>${k.branch ? ` on ${esc(k.branch)}` : ""}` : ""}${k.updated ? `, updated ${esc(k.updated)}` : ""}${k.updated_by ? ` by ${esc(nameOf(k.updated_by))}` : ""}</p></div></div>
    ${tabs}${changes}
    <article class="prose knowledge">${md(linked)}</article>
    <p class="hint">File: <code>${esc(k.file_path)}</code></p>`;
}

// ---- terminal -------------------------------------------------------------------
// Several shells per browser tab, laid out in a 2-column grid: 1 and 2 side by side, 3 under 1,
// 4 next to 3, 5 under 3… They keep running while you visit other pages and end when the tab closes.

const shells = [];              // { n, pane, xterm, fit, socket, ended }
let shellCount = 0;
const grid = Object.assign(document.createElement("div"), { className: "term-grid" });

function loadAsset(tag, attrs) {
  return new Promise((resolve, reject) => {
    const el = Object.assign(document.createElement(tag), attrs, { onload: resolve, onerror: reject });
    document.head.append(el);
  });
}

async function loadXterm() {
  if (window.Terminal) return;
  await Promise.all([loadAsset("link", { rel: "stylesheet", href: "/static/vendor/xterm/xterm.css" }),
                     loadAsset("script", { src: "/static/vendor/xterm/xterm.js" })]);
  await loadAsset("script", { src: "/static/vendor/xterm/addon-fit.js" });
}

function layoutShells() {
  grid.dataset.count = shells.length;
  grid.style.gridTemplateColumns = shells.length > 1 ? "repeat(2, minmax(0, 1fr))" : "minmax(0, 1fr)";
  grid.style.gridTemplateRows = `repeat(${Math.max(1, Math.ceil(shells.length / 2))}, minmax(220px, 1fr))`;
}

async function openShell() {
  await loadXterm();
  const shell = { n: ++shellCount, ended: false };
  shell.pane = Object.assign(document.createElement("section"), { className: "term-pane" });
  shell.pane.innerHTML = `<header><span class="term-title">Shell ${shell.n}</span><span class="term-state"></span>
    <button class="term-close" data-action="close-shell" data-shell="${shell.n}" title="Close this shell" aria-label="Close shell ${shell.n}">×</button></header>
    <div class="term-box"></div>`;
  const box = shell.pane.querySelector(".term-box");
  shell.xterm = new window.Terminal({ cursorBlink: true, fontFamily: "Plex Mono, ui-monospace, Menlo, monospace", fontSize: 13,
                                      theme: { background: "#16202a", foreground: "#e3e7eb" } });
  shell.fit = new window.FitAddon.FitAddon();
  shell.xterm.loadAddon(shell.fit);
  shells.push(shell);
  grid.append(shell.pane);
  layoutShells();
  shell.xterm.open(box);
  new ResizeObserver(() => { if (box.isConnected && box.clientWidth) shell.fit.fit(); }).observe(box);

  const send = (msg) => shell.socket?.readyState === 1 && shell.socket.send(JSON.stringify(msg));   // the current connection
  shell.xterm.onData((data) => send({ type: "input", data }));
  shell.xterm.onResize(({ cols, rows }) => send({ type: "resize", cols, rows }));
  attachShell(shell);
  shell.xterm.focus();
  return shell;
}

function attachShell(shell, retried = false) {
  const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/terminal`);
  socket.binaryType = "arraybuffer";
  shell.socket = socket;
  socket.onopen = () => { shell.fit.fit(); socket.send(JSON.stringify({ token: TOKEN, cols: shell.xterm.cols, rows: shell.xterm.rows })); };
  socket.onmessage = (e) => shell.xterm.write(new Uint8Array(e.data));
  socket.onclose = async (e) => {
    if (e.code === 4401 && !retried && await refreshToken()) return attachShell(shell, true);   // Hive restarted
    shell.ended = true;
    shell.pane.classList.add("ended");
    shell.pane.querySelector(".term-state").textContent = "ended";
    shell.xterm.write(`\r\n\x1b[2m[${e.reason || "Disconnected."}]\x1b[0m\r\n`);
  };
}

function closeShell(n) {
  const i = shells.findIndex((s) => s.n === n);
  if (i < 0) return;
  const [shell] = shells.splice(i, 1);
  shell.socket.close();   // the server ends the shell
  shell.xterm.dispose();
  shell.pane.remove();
  layoutShells();
  (shells[i] || shells[i - 1])?.xterm.focus();
}

function parkTerminal() {
  if (grid.isConnected) document.getElementById("term-parking").append(grid);
}

async function TerminalPage(r, quiet) {
  if (!state.terminal) {
    return `<div class="page-head"><div><h1>Terminal</h1></div></div>
      <div class="empty">The terminal was turned off when the console started (<code>ENABLE_TERMINAL=0</code>). Restart the console without it to use the terminal.</div>`;
  }
  if (quiet && document.getElementById("term-slot")) return null;   // don't disturb live shells
  return `<div class="page-head"><div><h1>Terminal</h1>
      <p>Shells on the machine running the console, starting in the agents' home folder. They keep running while you use other pages and end when you close this browser tab.</p></div>
      <button class="btn primary" data-action="new-shell">New shell</button></div>
    <div id="term-slot" class="term-slot"></div>`;
}

// ---- after-render wiring --------------------------------------------------------

const afterRender = {
  office: () => officeMod?.mountOffice(),
  reviews() {
    document.getElementById("rv-search")?.addEventListener("input", filterReviews);
    document.getElementById("rv-project")?.addEventListener("change", filterReviews);
  },
  async terminal() {
    const slot = document.getElementById("term-slot");
    if (!slot) return;
    slot.append(grid);
    if (!shells.length) await openShell();
    shells.find((s) => !s.ended)?.xterm.focus();
  },
  agent(r) {
    renderAgentChrome(r.id);
    const box = document.getElementById("transcript");
    if (box) box.scrollTop = box.scrollHeight;
    const text = document.getElementById("composer-text");
    text.focus();
    text.addEventListener("input", () => (state.drafts[r.id] = text.value));
    text.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); document.getElementById("composer").requestSubmit(); }
    });
    document.getElementById("composer").addEventListener("submit", async (e) => {
      e.preventDefault();
      const value = text.value.trim();
      if (!value) return;
      text.value = ""; state.drafts[r.id] = "";
      const ok = await act(() => api(`/api/agents/${r.id}/message`, { method: "POST", body: { text: value } }));
      if (!ok) { text.value = value; state.drafts[r.id] = value; resync(); }
    });
  },
  finance() {
    const f = financeFilter, again = () => render(true);
    for (const [id, key] of [["fin-range", "range"], ["fin-agent", "agent"], ["fin-project", "project"], ["fin-model", "model"], ["fin-from", "from"], ["fin-to", "to"]]) {
      document.getElementById(id)?.addEventListener("change", (e) => { f[key] = e.target.value; if (key === "range" && f.range === "custom" && !f.from) f.from = state.financeLines?.[0]?.ts.slice(0, 10) || ""; again(); });
    }
    document.getElementById("fin-q")?.addEventListener("input", (e) => { f.q = e.target.value; clearTimeout(afterRender.t); afterRender.t = setTimeout(() => { again().then?.(() => { const i = document.getElementById("fin-q"); i?.focus(); i?.setSelectionRange(i.value.length, i.value.length); }); }, 300); });
    document.querySelectorAll("[data-fin-by]").forEach((b) => b.addEventListener("click", () => { f.by = b.dataset.finBy; again(); }));
    const tip = document.getElementById("fin-tip");
    document.querySelectorAll(".fin-bar").forEach((bar) => {
      bar.addEventListener("mouseenter", () => {
        const k = bar.dataset.finBucket, ls = (state.financeLines || []).filter((l) => (f.by === "month" ? l.ts.slice(0, 7) : l.ts.slice(0, 10)) === k);
        const per = new Map(); for (const l of ls) per.set(l.task || "Not linked", (per.get(l.task || "Not linked") || 0) + (l.cost_usd || 0));
        const total = [...per.values()].reduce((a, b) => a + b, 0);
        tip.innerHTML = `<b>${esc(bar.getAttribute("aria-label").split(":")[0])}</b><span class="fin-tip-total">${usd(total)}</span>${[...per.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([t, c]) => `<span>${esc(t)} <i>${usd(c)}</i></span>`).join("")}${ls.length ? `<small>Click to see only this ${f.by}</small>` : ""}`;
        tip.hidden = false;
        const box = bar.closest(".fin-chart").getBoundingClientRect(), r = bar.getBoundingClientRect();
        tip.style.left = `${Math.min(box.width - tip.offsetWidth - 4, Math.max(0, r.left - box.left + r.width / 2 - tip.offsetWidth / 2))}px`;
      });
      bar.addEventListener("mouseleave", () => { tip.hidden = true; });
      bar.addEventListener("click", () => { const k = bar.dataset.finBucket;
        if (f.by === "month") { const [y, m] = k.split("-").map(Number); f.range = "custom"; f.from = `${k}-01`; f.to = dayKey(new Date(y, m, 0)); f.by = "day"; }
        else { f.range = "custom"; f.from = f.to = k; }
        again(); });
    });
  },
  history() {
    for (const [id, key] of [["act-project", "project"], ["act-agent", "agent"], ["act-status", "status"]]) {
      document.getElementById(id)?.addEventListener("change", (e) => { activityFilter[key] = e.target.value; render(true); });
    }
  },
  tasks() {
    const rerender = () => render(true);
    document.getElementById("task-q").addEventListener("input", (e) => { taskFilter.q = e.target.value; clearTimeout(afterRender.t); afterRender.t = setTimeout(rerender, 200); });
    document.getElementById("task-project").addEventListener("change", (e) => { taskFilter.project = e.target.value; rerender(); });
    document.getElementById("task-agent").addEventListener("change", (e) => { taskFilter.agent = e.target.value; rerender(); });
    document.getElementById("task-status")?.addEventListener("change", (e) => { taskFilter.status = e.target.value; history.replaceState(null, "", "#/tasks"); rerender(); });
  },
  settings() {
    document.querySelectorAll("form.provider").forEach((form) => form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const key = form.api_key.value.trim();
      const saved = await act(() => api(`/api/providers/${form.dataset.provider}`, { method: "PUT",
        body: { api_key: key || null, base_url: form.base_url.value.trim() } }), "Provider saved.");
      if (saved) { state.settings = saved; render(true); }
    }));
    document.getElementById("console-url-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const saved = await act(() => api("/api/settings/console-url", { method: "PUT", body: { console_url: document.getElementById("console-url").value } }), "Address saved.");
      if (saved) { state.settings = saved; render(true); }
    });
    document.getElementById("slack-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const value = (id) => document.getElementById(id);
      const body = {};
      for (const [k, id] of [["bot_token", "slack-bot_token"], ["app_token", "slack-app_token"]]) if (!value(id).disabled && value(id).value.trim()) body[k] = value(id).value.trim();
      for (const [k, id] of [["users", "slack-users"], ["channel", "slack-channel"]]) if (!value(id).disabled) body[k] = value(id).value;
      const saved = await act(() => api("/api/settings/slack", { method: "PUT", body }));
      if (saved) { state.settings = saved; render(true); const s = await api("/api/slack"); toast(s.connected ? "Connected to Slack." : s.error || "Saved. Add both tokens and at least one member ID to connect.", !s.connected && !!s.error); }
    });
    document.getElementById("editor-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target, pick = (n) => form.querySelector(`input[name=${n}]:checked`)?.value;
      const prefs = { app: pick("app") || "off", where: pick("where"), host: form.querySelector("#editor-host").value.trim() };
      const desktop = prefs.app === "vscode" || prefs.app === "cursor";
      if (desktop && prefs.where === "ssh" && !prefs.host) return toast("Enter the SSH host you connect to the server with.", true);
      // In the browser is on or off for the server (it runs there); a desktop editor is this browser's own choice.
      let warned = false;
      if (prefs.app === "browser" || (prefs.app === "off" && state.editorBrowser)) {
        const s = await act(() => api("/api/editor", { method: "PUT", body: { enabled: prefs.app === "browser" } }));
        if (!s) return;
        if (prefs.app === "browser" && !s.installed) { warned = true; toast("Saved. Install code-server on the Hive machine to use it.", true); }
        state.editorBrowser = s.enabled;
      }
      try { localStorage.setItem("editor", JSON.stringify(prefs)); } catch { if (desktop) return toast("This browser doesn't keep settings (private window?).", true); }
      if (!warned) toast("Editor saved.");
      render(true);
    });
    document.getElementById("slack-notify-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const form = e.target;
      const notify = Object.fromEntries([...form.querySelectorAll("select")].map((s) => [s.name, s.value]));
      const saved = await act(() => api("/api/settings/slack/notifications", { method: "PUT",
        body: { notify, replies: form.querySelector("input[name=replies]:checked").value } }), "Notifications saved.");
      if (saved) state.settings = saved;
    });
    document.getElementById("settings-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      const saved = await act(() => api("/api/settings", { method: "PUT", body: { workspace: document.getElementById("workspace").value } }), "Settings saved.");
      if (saved) state.settings = saved;
    });
  },
};

// ---- actions (event delegation) -------------------------------------------------

const actions = {
  "finance-csv"() {
    const rows = [["time", "task", "title", "agent", "provider", "model", "tokens", "cost_usd"],
      ...(state.financeLines || []).map((l) => [l.ts, l.task || "", state.tasks?.find?.((t) => t.id === l.task)?.title || "", personOf(l.agent), l.provider, l.model, l.tokens, l.cost_usd ?? ""])];
    const csv = rows.map((r) => r.map((v) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `hive-spending-${dayKey(new Date())}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  },
  ...reviewActions,
  "add-agent-picked": (el) => actions["add-agent"]({ dataset: { role: document.getElementById("add-role").value } }),
  "slack-test": () => act(() => api("/api/slack/test", { method: "POST" }), "Sent. Check Slack."),

  "show-inbox": async (el) => {
    const role = roleOf(el.dataset.agent);
    const data = await api(`/api/inbox/${role}`);
    const notes = data.notifications.map((n) => `• ${n.text || n.message || JSON.stringify(n)}`).join("\n");
    alertBox(`${nameOf(el.dataset.agent)}'s inbox`, notes || "Empty: nothing waiting for this agent.");
  },
  "board-view": (el) => { try { localStorage.setItem("boardView", el.dataset.view); } catch { /* this page only */ } render(true); },
  hand: async (el) => {
    const done = await act(() => api(`/api/tasks/${encodeURIComponent(el.dataset.task)}/hand/${el.dataset.agent}`, { method: "POST" }));
    if (!done) return;
    if (state.reviewSent?.task === el.dataset.task) state.reviewSent.handed = el.dataset.agent;   // the banner says who's on it
    else toast(done.message);
    refreshCounts(); render(true);
  },
  "toggle-section": (el) => {
    const sec = el.closest(".rail-section").dataset.section;
    let collapsed = [];
    try { collapsed = JSON.parse(localStorage.getItem("railCollapsed") || "[]"); } catch { /* not remembered */ }
    collapsed = collapsed.includes(sec) ? collapsed.filter((x) => x !== sec) : [...collapsed, sec];
    try { localStorage.setItem("railCollapsed", JSON.stringify(collapsed)); } catch { /* this page only */ }
    renderRail();
  },
  "open-rail": () => openRail(),
  "toggle-rail": () => toggleRail(),
  "close-rail": () => closeRail(),
  jump: () => openJump(),
  "jump-go": () => document.getElementById("jump-dialog").close(),
  "open-drawer": () => openDrawer(),
  "close-drawer": () => closeDrawer(),
  "drawer-quick": (el) => sendToOrchestrator(el.textContent),
  start: (el) => act(() => api(`/api/agents/${el.dataset.agent}/start`, { method: "POST", body: {} }), `${nameOf(el.dataset.agent)} started.`),
  stop: (el) => act(() => api(`/api/agents/${el.dataset.agent}/stop`, { method: "POST" }), `${nameOf(el.dataset.agent)} stopped.`),
  interrupt: (el) => act(() => api(`/api/agents/${el.dataset.agent}/interrupt`, { method: "POST" })),
  new: (el) => act(() => api(`/api/agents/${el.dataset.agent}/new`, { method: "POST" }), "Started a fresh session."),
  async allow(el) {
    const card = el.closest(".ask");
    const message = card?.querySelector(".reason")?.value || "";
    await act(() => api(`/api/agents/${el.dataset.agent}/permissions/${el.dataset.pid}`, { method: "POST", body: { decision: el.dataset.decision, message } }));
  },
  quick(el) {
    const text = document.getElementById("composer-text");
    text.value = el.dataset.text;
    document.getElementById("composer").requestSubmit();
  },
  "follow-up": (el) => {
    const lead = agentIds().find((n) => roleOf(n) === "techlead");
    state.drafts[lead] = `Follow-up to ${el.dataset.task} (${el.dataset.title}) in ${el.dataset.project}: `;
    location.hash = `#/agents/${lead}`;
  },
  handoff(el) {
    const name = el.dataset.agent;
    state.drafts[name] = PROMPTS[roleOf(name)]({ id: el.dataset.task, title: el.dataset.title });
    location.hash = `#/agents/${name}`;
  },
  "save-price": async (el) => {
    const m = el.dataset.model;
    const val = (k) => document.querySelector(`input[data-price="${k}"][data-model="${CSS.escape(m)}"]`).value.trim();
    const input = val("input"), output = val("output");
    const body = input === "" && output === "" ? { model: m } : { model: m, input: Number(input), output: Number(output) };
    if (body.input !== undefined && (Number.isNaN(body.input) || Number.isNaN(body.output))) return toast("Enter prices as numbers, like 0.27.", true);
    const ok = await act(() => api("/api/prices", { method: "PUT", body }), input === "" && output === "" ? "Price removed." : "Price saved.");
    if (ok) await loadState();
  },
  async rename(el) {
    const name = el.dataset.agent;
    const value = prompt(`New name for ${nameOf(name)}:`, personOf(name));
    if (value !== null && value.trim() && value.trim() !== personOf(name)) await renameAgent(name, value);
  },
  "new-shell": () => openShell(),
  "slack-disconnect": async () => {
    if (!confirm("Disconnect Slack and forget its tokens?")) return;
    const saved = await act(() => api("/api/settings/slack", { method: "PUT", body: { bot_token: "", app_token: "" } }), "Slack disconnected.");
    if (saved) { state.settings = saved; render(true); }
  },
  "start-review": async () => {
    const scope = document.getElementById("review-scope").value;
    const target = document.getElementById("review-target").value.trim();
    if ((scope === "tasks" || scope === "project") && !target) return toast("Say which tasks or which project.");
    const coach = agentIds().find((n) => roleOf(n) === "coach");
    const text = { last: "Review everything since your last review.", all: "Review all tasks.",
                   tasks: `Review these tasks: ${target}.`, project: `Review the tasks in ${target}.` }[scope];
    if (state.agents[coach].status === "stopped") {
      const started = await act(() => api(`/api/agents/${coach}/start`, { method: "POST", body: {} }));
      if (!started) return;
    }
    const sent = await act(() => api(`/api/agents/${coach}/message`, { method: "POST", body: { text } }));
    if (sent) location.hash = `#/agents/${coach}`;
  },
  "edit-proposal": (el) => {
    const card = document.getElementById(el.dataset.id);
    const editing = card.classList.toggle("editing");
    card.querySelectorAll(".edit-after").forEach((t) => { t.hidden = !editing; });
    el.textContent = editing ? "Cancel editing" : "Edit before approving";
  },
  approve: async (el) => {
    const card = document.getElementById(el.dataset.id);
    const afters = card.classList.contains("editing") ? [...card.querySelectorAll(".edit-after")].map((t) => t.value) : null;
    if (!confirm(`Apply ${el.dataset.id} to the team's instructions? It's committed, and you can undo it in Team history.`)) return;
    const done = await act(() => api(`/api/improvements/${el.dataset.id}/approve`, { method: "POST", body: { afters } }), `${el.dataset.id} applied.`);
    if (done) render(true);
  },
  reject: async (el) => {
    const note = prompt(`Why reject ${el.dataset.id}? The Coach reads this and won't propose it again without new evidence.`, "");
    if (note === null) return;
    const done = await act(() => api(`/api/improvements/${el.dataset.id}/reject`, { method: "POST", body: { note } }), `${el.dataset.id} rejected.`);
    if (done) render(true);
  },
  "undo-team": async (el) => {
    if (!confirm("Undo this change? A new commit reverses it, so the undo shows in the history too.")) return;
    const done = await act(() => api(`/api/team/undo/${el.dataset.sha}`, { method: "POST", body: {} }), "Change undone.");
    if (done) location.hash = "#/team";
  },
  "close-shell": (el) => closeShell(Number(el.dataset.shell)),
  "add-agent": async (el) => {
    const added = await act(() => api("/api/agents", { method: "POST", body: { role: el.dataset.role } }));
    if (!added) return;
    state.settings = added.settings;
    await loadState();
    toast(`${nameOf(added.id)} added. Start it from its page.`);
    render(true);
  },
  "remove-agent": async (el) => {
    const name = el.dataset.agent;
    if (!confirm(`Remove ${nameOf(name)}? Its past conversations stay in History. Tasks it claimed keep its name; another agent of the role can't take its rework until you reassign it in the task file.`)) return;
    const removed = await act(() => api(`/api/agents/${name}`, { method: "DELETE" }), `${nameOf(name)} removed.`);
    if (!removed) return;
    state.settings = removed.settings;
    await loadState();
    render(true);
  },
  "remove-key": async (el) => {
    const saved = await act(() => api(`/api/providers/${el.dataset.provider}`, { method: "PUT", body: { api_key: "" } }), "Key removed.");
    if (saved) { state.settings = saved; render(true); }
  },
  "clear-inbox": async (el) => { await act(() => api(`/api/inbox/${el.dataset.role}/clear`, { method: "POST" }), "Marked as read."); render(true); refreshBadge(); },
  "check-inbox": async (el) => {
    const ok = await act(() => api(`/api/agents/${el.dataset.agent}/message`, { method: "POST", body: { text: "Check your inbox." } }));
    if (ok) location.hash = `#/agents/${el.dataset.agent}`;
  },
  async resume(el) {
    const name = el.dataset.agent;
    if (state.agents[name]?.status !== "stopped") {
      if (!confirm(`${nameOf(name)} is running another conversation. Stop it and continue this one?`)) return;
      await act(() => api(`/api/agents/${name}/stop`, { method: "POST" }));
    }
    const ok = await act(() => api(`/api/agents/${name}/start`, { method: "POST", body: { resume: el.dataset.session } }));
    if (ok) location.hash = `#/agents/${name}`;
  },
};

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (el && actions[el.dataset.action] && el.tagName !== "SELECT") {
    e.preventDefault();
    actions[el.dataset.action](el);
    return;
  }
  const row = e.target.closest("tr[data-href]");
  if (row && !e.target.closest("a")) location.hash = row.dataset.href;
});

document.addEventListener("input", (e) => {
  if (e.target.id === "review-note") state.reviewNote[route().id] = e.target.value;
});

// The landing page keeps what you type and choose in state, so a refresh of the page doesn't lose it.
document.addEventListener("input", (e) => {
  const L = route().page === "land" && state.land[route().id];
  if (!L) return;
  if (e.target.dataset.landMsg === "__one__") L.oneMessage = e.target.value;
  else if (e.target.dataset.landMsg) L.edited[e.target.dataset.landMsg] = e.target.value;
  else if (e.target.id === "land-title") L.title = e.target.value;
  else if (e.target.id === "land-body") L.body = e.target.value;
  else if (e.target.id === "land-draft") L.draft = e.target.checked;
});
document.addEventListener("change", (e) => {
  if (e.target.id === "bk-file" && e.target.files[0]) uploadBackup(e.target.files[0]);
});
// The question cards keep what you type and open in state: the chat is drawn again when anything happens.
document.addEventListener("input", (e) => {
  const key = e.target.dataset?.q, s = key && state.questions?.[key];
  if (!s) return;
  if (e.target.classList.contains("q-note")) {
    s.notes[e.target.dataset.id] = e.target.value;
    const x = questionsOf(key)?.questions.find((y) => y.id === e.target.dataset.id);
    const hint = e.target.parentElement.querySelector(".q-mismatch");
    if (x && hint) hint.innerHTML = mismatchHtml(x, s, key);
  }
  else if (e.target.classList.contains("q-against")) s.disagree[+e.target.dataset.i] = e.target.value;
  else return;
  refreshReply(key);
});
document.addEventListener("toggle", (e) => {
  const key = e.target.dataset?.q, s = key && state.questions?.[key];
  if (s && e.target.dataset.id) (e.target.open ? s.open.add(e.target.dataset.id) : s.open.delete(e.target.dataset.id));
}, true);
document.addEventListener("toggle", (e) => {
  if (e.target.classList?.contains("land-more") && state.land[route().id]) state.land[route().id].more = e.target.open;
}, true);
document.addEventListener("submit", async (e) => {
  if (e.target.id === "backup-form") {
    e.preventDefault();
    const f = e.target;
    const kind = f.querySelector("input[name=kind]:checked").value;
    const bucket = f.querySelector("#bk-bucket").value.trim().replace(/^s3:\/\//, "").replace(/\/+$/, "");
    const prefix = f.querySelector("#bk-prefix").value.trim().replace(/^\/+|\/+$/g, "");
    const destination = kind === "s3" ? (bucket ? `s3://${bucket}${prefix ? `/${prefix}` : ""}` : "") : f.querySelector("#bk-folder").value.trim();
    const body = { destination, schedule: f.querySelector("input[name=schedule]:checked").value, hour: +f.querySelector("#bk-hour").value,
      weekday: +f.querySelector("#bk-weekday").value, day: +f.querySelector("#bk-day").value, keep: +f.querySelector("#bk-keep").value };
    const b = await act(() => api("/api/backup", { method: "PUT", body }));
    if (b) { state.backup = b; toast("Backup settings saved."); render(true); }
    return;
  }
  if (e.target.id !== "land-pr") return;
  e.preventDefault();
  const L = state.land[route().id];
  landAct((id) => api(`/api/tasks/${encodeURIComponent(id)}/land/pr`, { method: "POST", body: { title: L.title, body: L.body, draft: L.draft } }))
    .then((out) => out && toast(`Pull request ${out.number ? `#${out.number} ` : ""}ready: ${out.url}`));
});

document.addEventListener("change", async (e) => {
  if (e.target.dataset.landStep !== undefined && state.land[route().id]) {
    state.land[route().id].steps[+e.target.dataset.landStep].action = e.target.value;
    render(true);
    return;
  }
  if (e.target.matches("[data-theme-pick]")) {
    const v = e.target.value;
    try { localStorage.setItem("theme", v); } catch { /* this page only */ }
    if (v === "system") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v;
    return;
  }
  if (e.target.id === "review-scope") {
    document.getElementById("review-target").hidden = !["tasks", "project"].includes(e.target.value);
    return;
  }
  if (e.target.matches('[data-action="provider"]')) {
    saveConfig(e.target.dataset.agent, e.target.value, "");
    return;
  }
  if (e.target.matches('input[data-action="name"]')) {
    const name = e.target.dataset.agent;
    if (e.target.value.trim() && e.target.value.trim() !== personOf(name)) renameAgent(name, e.target.value);
    else e.target.value = personOf(name);
    return;
  }
  if (e.target.matches('[data-action="model"]')) {
    const name = e.target.dataset.agent;
    saveConfig(name, choiceOf(name).provider, e.target.value.trim());
    return;
  }
  if (e.target.matches('select[data-action="mode"]')) {
    const name = e.target.dataset.agent;
    const saved = await act(() => api(`/api/agents/${name}/mode`, { method: "PUT", body: { mode: e.target.value } }),
      e.target.value === "acceptEdits" ? "File edits will be allowed automatically." : "You'll be asked before each file edit.");
    if (saved) state.settings.permission_mode = saved.permission_mode;
  }
});

// decided proposals start folded and stay as you left them
document.addEventListener("toggle", (e) => {
  const id = e.target.dataset?.proposal;
  if (id) e.target.open ? state.openProposals.add(id) : state.openProposals.delete(id);
}, true);
document.addEventListener("toggle", (e) => {
  const id = e.target.dataset?.tool;
  if (id) e.target.open ? state.openTools.add(id) : state.openTools.delete(id);
}, true);

// A ⋯ menu opens towards whichever side has room, so it never runs under the sidebar or off the screen.
document.addEventListener("toggle", (e) => {
  const menu = e.target;
  if (!menu.matches?.("details.menu") || !menu.open) return;
  menu.classList.remove("open-left");
  const list = menu.querySelector(".menu-list");
  if (list && list.getBoundingClientRect().right > document.documentElement.clientWidth - 8) menu.classList.add("open-left");
}, true);

window.addEventListener("hashchange", () => {
  if (route().page !== "review") state.reviewSent = null;   // the banner is for the review you just sent
  render();
  view.focus({ preventScroll: true });
});

// ---- boot ------------------------------------------------------------------------


(async () => {
  try {
    await loadState();
  } catch (err) {
    view.innerHTML = `<div class="empty">Can't reach the console server: ${esc(err.message)} Restart it with <code>./start.sh</code> and reload.</div>`;
    return;
  }
  connect();
  await refreshCounts();
  render();
})();

// A small read-only box (the agents' inboxes, for debugging).
function alertBox(title, text) {
  let d = document.getElementById("info-dialog");
  if (!d) { d = document.createElement("dialog"); d.id = "info-dialog"; d.className = "info-dialog"; document.body.appendChild(d); }
  d.innerHTML = `<h2>${esc(title)}</h2><pre>${esc(text)}</pre><form method="dialog"><button class="btn">Close</button></form>`;
  d.showModal();
}

// Approvals pinned under a chat: Enter allows the first one, Escape denies it (when you're not typing).
document.addEventListener("keydown", (e) => {
  if (route().page !== "agent") return;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
  if (typing || e.metaKey || e.ctrlKey || document.querySelector("dialog[open]")) return;
  const first = document.querySelector("#pinned-asks .ask");
  if (!first) return;
  if (e.key === "Enter") { e.preventDefault(); first.querySelector('[data-decision="allow"]').click(); }
  if (e.key === "Escape" && document.getElementById("drawer").hidden) { e.preventDefault(); first.querySelector('[data-decision="deny"]').click(); }
});

// "#" in a message suggests task IDs.
document.addEventListener("input", (e) => {
  if (e.target.id !== "composer-text") return;
  const list = document.getElementById("task-suggest");
  const m = e.target.value.slice(0, e.target.selectionStart).match(/#([\w-]*)$/);
  if (!m || !list) { if (list) list.hidden = true; return; }
  const q = m[1].toLowerCase();
  const hits = (state.tasks || []).filter((t) => `${t.id} ${t.title}`.toLowerCase().includes(q) || t.id.toLowerCase().endsWith(q)).slice(0, 6);
  list.innerHTML = hits.map((t) => `<li><button type="button" data-action="pick-task" data-id="${esc(t.id)}">${esc(t.id)} <span class="muted">${esc(t.title)}</span></button></li>`).join("");
  list.hidden = !hits.length;
});
actions["pick-task"] = (el) => {
  const text = document.getElementById("composer-text");
  const at = text.selectionStart;
  const before = text.value.slice(0, at).replace(/#[\w-]*$/, el.dataset.id + " ");
  text.value = before + text.value.slice(at);
  text.focus();
  text.selectionStart = text.selectionEnd = before.length;
  document.getElementById("task-suggest").hidden = true;
};

// Close an open ⋯ menu when clicking anywhere else.
document.addEventListener("click", (e) => {
  document.querySelectorAll("details.menu[open]").forEach((m) => { if (!m.contains(e.target) || e.target.closest(".menu-list")) m.open = false; });
});
