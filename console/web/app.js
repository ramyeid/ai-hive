// Team Console: talks to the local console server (server/main.py).

const TOKEN = window.CONSOLE_TOKEN;
const view = document.getElementById("view");

const ROLES = {
  techlead: { name: "Tech Lead", role: "Tech lead / staff engineer", blurb: "Designs the change against the codebase and turns it into a complete, approved task spec.", quick: ["Show me the board", "What's still in draft?"] },
  dev: { name: "Dev", role: "Developer", blurb: "Builds exactly what the spec asks, in the project's style.", quick: ["Check your inbox"] },
  reviewer: { name: "Reviewer", role: "Reviewer", blurb: "Checks business need, consistency and simplicity.", quick: ["Check your inbox"] },
};
const OWNER_LABEL = { techlead: "Tech Lead", dev: "Dev", reviewer: "Reviewer", lead: "You" };
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
  openTools: new Set(),
  inboxUnread: 0,
  stream: {},         // name -> {thinking, text, tool}: what the agent is writing right now
  since: {},          // name -> when it started working (ms)
};
const emptyStream = () => ({ thinking: "", text: "", tool: "" });

// ---- helpers ------------------------------------------------------------------

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const md = (text) => DOMPurify.sanitize(marked.parse(text || "", { gfm: true, breaks: false }));

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: { "x-token": TOKEN, ...(body ? { "content-type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Request failed (${res.status}).`);
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
  document.getElementById("nav-terminal").hidden = !data.terminal;
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
  source.onerror = () => { conn.textContent = "Reconnecting…"; conn.classList.remove("live"); };
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
    return;
  }
  if (event.kind === "team") {
    loadState().then(() => render(true)).catch(() => {});
    return;
  }
  if (event.kind === "board") {
    clearTimeout(boardTimer);
    boardTimer = setTimeout(() => { refreshIf(["overview", "tasks", "task", "inbox"]); refreshBadge(); }, 300);
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
    if (r.page === "overview") refreshIf(["overview"]);
  }
}

function refreshIf(pages) {
  if (pages.includes(route().page)) render(true);
}

async function refreshBadge() {
  try {
    const inbox = await api("/api/inbox/lead");
    const badge = document.getElementById("inbox-badge");
    badge.textContent = inbox.notifications.length;
    badge.hidden = inbox.notifications.length === 0;
  } catch { /* shown elsewhere */ }
}

// ---- routing ------------------------------------------------------------------

function route() {
  const [, page = "", id = "", sub = ""] = location.hash.replace(/^#/, "").split("?")[0].split("/");
  const map = { "": "overview", tasks: id ? "task" : "tasks", agents: "agent", inbox: "inbox", history: id ? "session" : "history", settings: "settings", terminal: "terminal", knowledge: id ? "knowledge-file" : "knowledge" };
  return { page: map[page] || "overview", id: decodeURIComponent(id), sub };
}

let renderSeq = 0;
async function render(quiet = false) {
  const r = route();
  const seq = ++renderSeq;
  const pages = { overview: Overview, tasks: Tasks, task: TaskDetail, agent: AgentChat, inbox: Inbox, history: History, session: SessionView, settings: Settings, terminal: TerminalPage, knowledge: KnowledgeList, "knowledge-file": KnowledgeView };
  try {
    const html = await pages[r.page](r, quiet);
    if (seq !== renderSeq || html === null) return;
    const scrollY = window.scrollY;
    parkTerminal();   // keep the shell alive while other pages are shown
    view.innerHTML = html;
    if (quiet) window.scrollTo(0, scrollY);
    afterRender[r.page]?.(r);
  } catch (err) {
    if (seq === renderSeq) view.innerHTML = `<div class="empty">${esc(err.message)}</div>`;
  }
  highlightNav(r);
}

function highlightNav(r) {
  document.querySelectorAll("[data-nav]").forEach((a) => {
    const nav = a.dataset.nav;
    const on = nav === r.page || (nav === "tasks" && r.page === "task") || (nav === "history" && r.page === "session") || (nav === "knowledge" && r.page === "knowledge-file");
    on ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
  });
  document.querySelectorAll(".rail-agent").forEach((a) => {
    r.page === "agent" && a.dataset.agent === r.id ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current");
  });
}

function renderRail() {
  document.getElementById("rail-agents").innerHTML = agentIds().map((name) => {
    const st = state.agents[name]?.status || "stopped";
    return `<a class="rail-agent ${roleOf(name)}" data-agent="${name}" href="#/agents/${name}">
      <span class="who">${esc(personOf(name))}<small>${ROLES[roleOf(name)].role}</small></span>
      <span class="status ${st}" title="${STATUS_TEXT[st]}">${st === "waiting" ? "Approve" : ""}</span></a>`;
  }).join("");
  highlightNav(route());
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

async function Overview() {
  const data = await api("/api/dashboard");
  await Promise.all(agentIds().filter((n) => state.agents[n]?.session_id && !state.live[n]?.length).map(loadLive));

  const stations = agentIds().map((name) => {
    const ag = state.agents[name] || { status: "stopped" };
    const running = ag.status !== "stopped";
    return `<section class="station ${roleOf(name)} ${ag.status === "waiting" ? "waiting" : ""}">
      <header><h2><a href="#/agents/${name}">${esc(nameOf(name))}</a></h2><span class="status ${ag.status}">${STATUS_TEXT[ag.status]}</span></header>
      <p class="model">${esc(modelLabel(name))}</p>
      <p class="doing">${esc(doing(name))}</p>
      <div class="btn-row">
        <a class="btn small ${ag.status === "waiting" ? "role" : ""}" href="#/agents/${name}">${ag.status === "waiting" ? "Review request" : "Open chat"}</a>
        ${running ? `<button class="btn small" data-action="stop" data-agent="${name}">Stop</button>`
                  : `<button class="btn small" data-action="start" data-agent="${name}">Start</button>`}
      </div></section>`;
  }).join("");

  const tasks = data.tasks;
  const lane = (s) => {
    const items = tasks.filter((t) => t.status === s.status);
    return `<div class="stage ${s.owner}">
      <div class="stage-head"><h3>${s.label}<span class="count">${items.length}</span></h3><small>${s.owner === "lead" ? "Accepted" : `With ${OWNER_LABEL[s.owner]}`}</small></div>
      ${items.slice(0, 6).map((t) => `<a class="chip" href="#/tasks/${esc(t.id)}"><b>${esc(t.title)}</b><small>${esc(t.id)}, ${esc(t.project_name)}${t.assignee ? `, ${t.status === "blocked" ? "blocked by " : ""}${esc(nameOf(t.assignee))}` : ""}</small></a>`).join("")}
      ${items.length > 6 ? `<a class="muted" href="#/tasks?status=${s.status}">${items.length - 6} more</a>` : ""}
    </div>`;
  };
  const blocked = tasks.filter((t) => t.status === "blocked");

  const needs = [];
  for (const [name, ag] of Object.entries(state.agents)) {
    for (const p of ag.pending || []) needs.push(`<li><span class="what"><a href="#/agents/${name}">${esc(nameOf(name))} wants to run ${esc(p.tool)}</a>: <code>${esc(toolArg(p.tool, p.input).slice(0, 80))}</code></span></li>`);
  }
  for (const t of blocked) needs.push(`<li><span class="what"><a href="#/tasks/${esc(t.id)}">${esc(t.id)} is blocked${t.assignee ? ` by ${esc(nameOf(t.assignee))}` : ""}</a>: ${esc(t.title)}</span><span class="when">${ago(t.updated)}</span></li>`);
  if (data.unread.lead) needs.push(`<li><span class="what"><a href="#/inbox/lead">${data.unread.lead} new notification${data.unread.lead > 1 ? "s" : ""} for you</a></span></li>`);

  const activity = data.activity.slice(0, 10).map((a) => `<li><span class="what"><a href="#/tasks/${esc(a.id)}">${esc(a.id)}</a> ${esc(a.title)} <span class="muted">(${esc(a.project)})</span><br>${statusPill(a.to)}</span><span class="when">${ago(a.ts)}</span></li>`).join("");

  return `<div class="page-head"><div><h1>Overview</h1>
      <p>${tasks.length ? `${tasks.length} task${tasks.length > 1 ? "s" : ""} across ${data.projects.length} project${data.projects.length > 1 ? "s" : ""}.` : "No tasks yet."} Agents work from <code>${esc(state.settings?.workspace)}</code>.</p></div>
      <a class="btn" href="#/agents/techlead">Start a new task with the Tech Lead</a></div>
    <div class="stations">${stations}</div>
    <p class="team-link"><a href="#/settings">Add or remove agents</a></p>
    <section class="section"><h2>Who has each task</h2>
      ${tasks.length ? `<div class="pipeline">${blocked.length ? `<div class="stage stage-blocked lead"><div class="stage-head"><h3>Blocked<span class="count">${blocked.length}</span></h3><small>Needs your decision</small></div>${blocked.map((t) => `<a class="chip" href="#/tasks/${esc(t.id)}"><b>${esc(t.title)}</b><small>${esc(t.id)}, ${esc(t.project_name)}${t.assignee ? `, blocked by ${esc(nameOf(t.assignee))}` : ""}</small></a>`).join("")}</div>` : ""}${STAGES.map(lane).join("")}</div>`
                     : `<div class="empty">Tell the Tech Lead what you need, for example "In ~/code/my-api, users need to reset their password by email." The task will show up here.</div>`}
    </section>
    <div class="two-col section">
      <section><h2>Needs you</h2>${needs.length ? `<ul class="list needs">${needs.join("")}</ul>` : `<p class="muted">Nothing is waiting on you.</p>`}</section>
      <section><h2>Recent activity</h2>${activity ? `<ul class="list">${activity}</ul>` : `<p class="muted">Status changes will appear here.</p>`}</section>
    </div>`;
}

// ---- tasks -----------------------------------------------------------------

const taskFilter = { project: "", status: "open", q: "" };

async function Tasks() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  if (params.get("status")) taskFilter.status = params.get("status");
  const tasks = await api("/api/tasks");
  const projects = [...new Set(tasks.map((t) => t.project_name))].sort();
  const shown = tasks.filter((t) =>
    (!taskFilter.project || t.project_name === taskFilter.project) &&
    (taskFilter.status === "all" || (taskFilter.status === "open" ? t.status !== "done" : t.status === taskFilter.status)) &&
    (!taskFilter.q || `${t.id} ${t.title}`.toLowerCase().includes(taskFilter.q.toLowerCase())));
  const option = (value, label, current) => `<option value="${esc(value)}" ${value === current ? "selected" : ""}>${esc(label)}</option>`;

  const unlinked = (await api("/api/costs")).unlinked;
  return `<div class="page-head"><div><h1>Tasks</h1><p>Every task across your projects. Task files live in <code>${esc(state.kit)}/tasks</code>.</p>
      ${costText(unlinked) ? `<p>Conversations not linked to any task: ${esc(costText(unlinked))}. <a href="#/history">See History</a></p>` : ""}</div></div>
    <div class="filters">
      <input type="text" id="task-q" placeholder="Search by ID or title" value="${esc(taskFilter.q)}" aria-label="Search tasks">
      <select id="task-project" aria-label="Project">${option("", "All projects", taskFilter.project)}${projects.map((p) => option(p, p, taskFilter.project)).join("")}</select>
      <select id="task-status" aria-label="Status">${option("open", "Open tasks", taskFilter.status)}${option("all", "All tasks", taskFilter.status)}${option("blocked", "Blocked", taskFilter.status)}${STAGES.map((s) => option(s.status, s.label, taskFilter.status)).join("")}</select>
    </div>
    ${shown.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Task</th><th>Project</th><th>Stage</th><th>With</th><th>Spec ready</th><th>Cost so far</th><th>Updated</th></tr></thead>
      <tbody>${shown.map((t) => `<tr data-href="#/tasks/${esc(t.id)}">
        <td><a href="#/tasks/${esc(t.id)}"><b>${esc(t.id)}</b></a> ${esc(t.title)}</td>
        <td>${esc(t.project_name)}</td><td>${statusPill(t.status)}</td><td>${esc(holderText(t))}</td>
        <td><span class="ready"><span class="bar" aria-hidden="true"><i style="width:${t.ready.total ? Math.round(100 * t.ready.done / t.ready.total) : 0}%"></i></span>${t.ready.done}/${t.ready.total}</span></td>
        <td class="num">${esc(costText(t.cost)) || '<span class="muted">None yet</span>'}</td>
        <td class="num">${ago(t.updated)}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">${tasks.length ? "No tasks match these filters." : "No tasks yet. Open the Tech Lead and describe what you need."}</div>`}`;
}

const PROMPTS = {
  techlead: (t) => `Let's continue on ${t.id} (${t.title}).`,
  dev: (t) => `Work on ${t.id} per your instructions.`,
  reviewer: (t) => `Review ${t.id} per your instructions.`,
};

async function TaskDetail(r) {
  const t = await api(`/api/tasks/${encodeURIComponent(r.id)}`);
  const timeline = t.activity.slice().reverse().map((a) => `<li class="${ownerOf(a.to)}">${statusPill(a.to)}<br><span class="muted">${ago(a.ts)}${a.from ? `, from ${esc(stageLabel(a.from))}` : ""}${a.by ? `, ${a.to === "blocked" ? "by" : "with"} ${esc(nameOf(a.by))}` : ""}</span></li>`).join("");
  const holder = t.assignee && state.agents[t.assignee];
  const chatButton = holder ? `<a class="btn role ${roleOf(t.assignee)}" href="#/agents/${t.assignee}">Open chat with ${esc(nameOf(t.assignee))}${t.status === "blocked" ? ", who blocked it" : ""}</a>` : "";
  // Names in Details link to that agent's chat (plain text if the agent was removed).
  const who = (id) => state.agents[id] ? `<a href="#/agents/${id}">${esc(nameOf(id))}</a>` : esc(nameOf(id));
  return `<p><a href="#/tasks" class="muted">All tasks</a></p>
    <div class="page-head"><div><h1>${esc(t.title)}</h1><p>${esc(t.id)} in ${esc(t.project_name)}, ${statusPill(t.status)} with ${esc(holderText(t).replace(/^You/, "you"))}</p></div>${chatButton}</div>
    <div class="task-layout">
      <article class="prose">${md(t.markdown)}</article>
      <aside class="task-side">
        <section><h2>Hand it to an agent</h2><p class="muted">Opens the chat with a message ready to send.</p>
          <div class="btn-row">${agentIds().map((n) => `<button class="btn small" data-action="handoff" data-agent="${n}" data-task="${esc(t.id)}" data-title="${esc(t.title)}">${esc(nameOf(n))}</button>`).join("")}</div></section>
        <section><h2>Cost so far</h2>${costSection(t.cost)}</section>
        <section><h2>Details</h2><dl class="facts">
          <dt>Project</dt><dd><code>${esc(t.project)}</code></dd>
          ${t.techlead ? `<dt>Tech Lead</dt><dd>${who(t.techlead)}</dd>` : ""}
          ${t.dev ? `<dt>Dev</dt><dd>${who(t.dev)}</dd>` : ""}
          ${t.reviewer ? `<dt>Reviewer</dt><dd>${who(t.reviewer)}</dd>` : ""}
          ${t.worktree ? `<dt>Worktree</dt><dd><code>${esc(t.worktree)}</code></dd>` : ""}
          <dt>Branch</dt><dd><code>${esc(t.branch)}</code></dd>
          <dt>Base</dt><dd><code>${esc(t.base)}</code></dd>
          <dt>Priority</dt><dd>${esc(t.priority)}</dd>
          <dt>Created</dt><dd>${esc(t.created)}</dd>
          <dt>Approved</dt><dd>${esc(t.approved || "Not yet")}</dd>
          <dt>Spec ready</dt><dd>${t.ready.done} of ${t.ready.total} checks</dd>
          <dt>File</dt><dd><code>${esc(t.path)}</code></dd></dl></section>
        <section><h2>History</h2>${timeline ? `<ul class="timeline">${timeline}</ul>` : `<p class="muted">No status changes recorded yet.</p>`}</section>
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

async function AgentChat(r) {
  const name = r.id;
  if (!state.agents[name]) throw new Error("There's no agent with that name. It may have been removed in Settings.");
  await loadLive(name);
  const a = ROLES[roleOf(name)];
  return `<div class="chat-page ${roleOf(name)}">
    <header class="agent-head" id="agent-head"></header>
    <div class="transcript" id="transcript"><div id="tx-events"></div><div id="tx-live" aria-live="polite"></div></div>
    <form class="composer" id="composer">
      <label class="hint" for="composer-text">Message ${esc(nameOf(name))}. Enter sends, Shift+Enter adds a line.</label>
      <textarea id="composer-text" rows="3" placeholder="${roleOf(name) === "techlead" ? "Describe what you need, and in which project folder." : "Tell the agent what to do."}">${esc(state.drafts[name] || "")}</textarea>
      <div class="row"><div class="quick">${a.quick.map((q) => `<button type="button" class="btn small" data-action="quick" data-text="${esc(q)}">${esc(q)}</button>`).join("")}</div>
        <button class="btn role" type="submit" id="send">Send</button></div>
    </form></div>`;
}

function renderAgentChrome(name) {
  const head = document.getElementById("agent-head");
  if (!head) return;
  const a = ROLES[roleOf(name)];
  const ag = state.agents[name] || { status: "stopped" };
  const mode = state.settings?.permission_mode?.[name] || "default";
  const running = ag.status !== "stopped";
  const busy = ag.status === "working" || ag.status === "waiting";
  const choice = choiceOf(name);
  const prov = providerOf(choice.provider);
  const needsKey = prov.engine !== "claude" && !prov.has_key;
  const picker = running
    ? `<p class="model">Running on ${esc(modelLabel(name))}</p>`
    : `<div class="model-pick">
        <label>Provider <select data-action="provider" data-agent="${name}">${(state.settings?.providers || []).map((p) =>
          `<option value="${p.id}" ${p.id === choice.provider ? "selected" : ""}>${esc(p.label)}</option>`).join("")}</select></label>
        <label>Model <input type="text" list="models-${name}" data-action="model" data-agent="${name}" value="${esc(choice.model)}"
          placeholder="${prov.engine === "claude" ? "Default from the agent file" : `For example ${esc(prov.models?.[0] || "")}`}" spellcheck="false"></label>
        <datalist id="models-${name}">${(prov.models || []).map((m) => `<option value="${esc(m)}">`).join("")}</datalist>
        ${needsKey ? `<span class="warn">No ${esc(prov.label)} API key yet. <a href="#/settings">Add it in Settings</a></span>` : ""}
      </div>`;
  head.innerHTML = `<div class="title"><h1>${esc(nameOf(name))} <button class="btn small" data-action="rename" data-agent="${name}">Rename</button></h1><p>${a.blurb}</p>${picker}</div>
    <div class="btn-row" style="align-items:center">
      <span class="status ${ag.status}">${STATUS_TEXT[ag.status]}</span>
      <label class="mode">Edits <select data-action="mode" data-agent="${name}" aria-label="File edit approvals">
        <option value="default" ${mode === "default" ? "selected" : ""}>Ask me first</option>
        <option value="acceptEdits" ${mode === "acceptEdits" ? "selected" : ""}>Allow automatically</option></select></label>
      ${busy ? `<button class="btn" data-action="interrupt" data-agent="${name}">Interrupt</button>` : ""}
      ${running ? `<button class="btn" data-action="new" data-agent="${name}" title="Start over with a clean context (like /clear)">New session</button>
                   <button class="btn danger" data-action="stop" data-agent="${name}">Stop</button>`
                : `<button class="btn role" data-action="start" data-agent="${name}">Start</button>`}
    </div>`;
  const send = document.getElementById("send");
  if (send) send.disabled = busy;
  renderTranscriptInto(name);
}

function renderTranscriptInto(name) {
  const box = document.getElementById("transcript");
  if (!box) return;
  const atBottom = nearBottom(box);
  const ag = state.agents[name] || {};
  document.getElementById("tx-events").innerHTML = transcriptHTML(state.live[name] || [], { pending: ag.pending || [], agent: name })
    || `<div class="msg system">${ag.status === "stopped" ? "This agent isn't running. Press Start, or just send a message and it will start." : "No messages yet."}</div>`;
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
      refreshIf(["overview", "tasks", "task", "inbox"]);
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
document.addEventListener("visibilitychange", () => { if (!document.hidden) resync(); });

function transcriptHTML(events, { pending = [], agent = "" } = {}) {
  const results = {}, decisions = {};
  for (const e of events) {
    if (e.kind === "tool_result") results[e.id] = e;
    if (e.kind === "decision") decisions[e.id] = e;
  }
  const pendingIds = new Set(pending.map((p) => p.id));
  return events.map((e) => {
    switch (e.kind) {
      case "user": return `<div class="msg user">${esc(e.text)}</div>`;
      case "text": return `<div class="msg agent prose">${md(e.text)}</div>`;
      case "thinking": return `<details class="thinking"><summary>Thought process</summary><div class="thought">${esc(e.text)}</div></details>`;
      case "system": return `<div class="msg system">${esc(e.text.replace(/\.$/, ""))}, ${ago(e.ts)}</div>`;
      case "error": return `<div class="msg error">Something went wrong: ${esc(e.text)}</div>`;
      case "result": return `<div class="msg result">Finished in ${(e.duration_ms / 1000).toFixed(1)} s${e.cost_usd ? `, about $${e.cost_usd.toFixed(3)}` : ""}${e.tokens_in ? `, ${(e.tokens_in + e.tokens_out).toLocaleString()} tokens` : ""}${e.is_error ? ", with an error" : ""}</div>`;
      case "tool": {
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
        return `<div class="ask" data-pid="${esc(e.id)}"><h3>${esc(nameOf(agent))} wants to use ${esc(e.tool)}</h3>
          <pre>${esc(toolDetail(e.tool, e.input))}</pre>
          <input type="text" class="reason" placeholder="Optional: tell the agent why you deny it" aria-label="Reason">
          <div class="btn-row">
            <button class="btn role" data-action="allow" data-decision="allow" data-agent="${agent}" data-pid="${esc(e.id)}">Allow once</button>
            <button class="btn" data-action="allow" data-decision="always" data-agent="${agent}" data-pid="${esc(e.id)}">Allow ${esc(e.tool)} for this session</button>
            <button class="btn danger" data-action="allow" data-decision="deny" data-agent="${agent}" data-pid="${esc(e.id)}">Deny</button>
          </div></div>`;
      }
      default: return "";
    }
  }).join("");
}

// ---- inbox ------------------------------------------------------------------

async function Inbox(r) {
  const role = ["lead", "techlead", "dev", "reviewer"].includes(r.id) ? r.id : "lead";
  const data = await api(`/api/inbox/${role}`);
  const label = { lead: "You", techlead: "Tech Lead", dev: "Dev", reviewer: "Reviewer" };
  const notes = data.notifications.map((n) => `<li><span class="what"><a href="#/tasks/${esc(n.id)}">${esc(n.id)}</a> ${esc(n.title)} <span class="muted">(${esc(n.project)})</span><br>${statusPill(n.to)} <span class="muted">from ${esc(stageLabel(n.frm))}${n.by ? `, blocked by ${esc(nameOf(n.by))}` : n.who ? `, ${esc(nameOf(n.who))}` : ""}${n.recipient !== role ? `, for ${esc(nameOf(n.recipient))}` : ""}</span></span><span class="when">${esc(n.ts)}</span></li>`).join("");
  const waiting = data.waiting.map((t) => `<li><span class="what"><a href="#/tasks/${esc(t.id)}">${esc(t.id)}</a> ${esc(t.title)} <span class="muted">(${esc(t.project_name)}, ${esc(holderText(t))})</span></span>${statusPill(t.status)}</li>`).join("");
  const askButtons = role === "lead" ? "" : agentIds().filter((n) => roleOf(n) === role).map((n) =>
    `<button class="btn small" data-action="check-inbox" data-agent="${n}">Ask ${esc(nameOf(n))} to check its inbox</button>`).join("");
  return `<div class="page-head"><div><h1>Inbox</h1><p>Hand-offs land here when a task changes stage. Agents read their own inbox when you tell them to check it.</p></div></div>
    <nav class="tabs">${Object.entries(label).map(([k, v]) => `<a class="${k}" href="#/inbox/${k}" ${k === role ? 'aria-current="page"' : ""}>${v}</a>`).join("")}</nav>
    <div class="two-col">
      <section><h2>New notifications</h2>${notes ? `<ul class="list">${notes}</ul>` : `<p class="muted">Nothing new.</p>`}
        <div class="btn-row" style="margin-top:12px">
          ${notes ? `<button class="btn small" data-action="clear-inbox" data-role="${role}">Mark all as read</button>` : ""}
          ${askButtons}
        </div></section>
      <section><h2>Waiting on ${label[role] === "You" ? "you" : label[role]}</h2>${waiting ? `<ul class="list">${waiting}</ul>` : `<p class="muted">No tasks are waiting here.</p>`}</section>
    </div>`;
}

// ---- history ------------------------------------------------------------------

async function History() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const agent = params.get("role") || "";
  const sessions = (await api("/api/sessions")).filter((s) => s.title && (!agent || (s.role || roleOf(s.agent)) === agent));
  return `<div class="page-head"><div><h1>History</h1><p>Every conversation with your agents. Open one to read it, or continue where it left off.</p></div></div>
    <nav class="tabs"><a href="#/history" ${!agent ? 'aria-current="page"' : ""}>All</a>${Object.entries(ROLES).map(([k, a]) => `<a class="${k}" href="#/history?role=${k}" ${agent === k ? 'aria-current="page"' : ""}>${a.name}</a>`).join("")}</nav>
    ${sessions.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Agent</th><th>Conversation</th><th>Model</th><th>Started</th><th>Last activity</th><th>Turns</th><th>Usage</th></tr></thead>
      <tbody>${sessions.map((s) => `<tr data-href="#/history/${s.id}"><td><span class="pill ${roleOf(s.agent)}">${esc(nameOf(s.agent))}</span></td>
        <td><a href="#/history/${s.id}">${esc(s.title)}</a></td><td>${esc(providerOf(s.provider || "claude").label)}${s.model ? `<br><small class="muted">${esc(s.model)}</small>` : ""}</td>
        <td class="num">${esc(new Date(s.started).toLocaleString())}</td>
        <td class="num">${ago(s.updated)}</td><td class="num">${s.turns}</td><td class="num">${s.cost_usd ? `$${s.cost_usd.toFixed(2)}` : s.tokens ? `${s.tokens.toLocaleString()} tokens` : ""}</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">No conversations yet.</div>`}`;
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

async function Settings() {
  await loadState();
  const seen = (await api("/api/costs")).models.filter((m) => m.provider !== "claude").map((m) => m.model);
  const configured = Object.values(state.settings.agents).filter((a) => a.provider !== "claude" && a.model).map((a) => a.model);
  const priced = Object.keys(state.settings.prices || {});
  const models = [...new Set([...seen, ...configured, ...priced])].sort();
  return `<div class="page-head"><div><h1>Settings</h1></div></div>
    ${teamSection()}
    <form class="form" id="settings-form">
      <label for="workspace">Agents' home folder</label>
      <p class="muted" style="margin:0">Agents start here and can work in any project under it without extra permission prompts. Pick the folder that holds your projects. Takes effect the next time an agent starts.</p>
      <div class="row"><input type="text" id="workspace" value="${esc(state.settings.workspace)}"><button class="btn primary">Save</button></div>
    </form>
    <section class="section"><h2>AI providers</h2>
      <p class="muted" style="max-width:68ch">Choose the provider and model for each agent in its chat header, while the agent is stopped. Keys are kept on this server in <code>console/data/settings.json</code> and are never shown again in the browser.</p>
      <div class="providers">${state.settings.providers.map(providerCard).join("")}</div></section>
    <section class="section"><h2>Model prices</h2>
      <p class="muted" style="max-width:68ch">OpenAI, DeepSeek, Qwen and Kimi report tokens, not money. Enter each model's price from your provider's pricing page, in US$ per 1 million tokens, to see task costs. Changes apply to past conversations too. Claude Code reports its own cost.</p>
      ${models.length ? `<div class="table-wrap prices"><table><thead><tr><th>Model</th><th>Input, $ per 1M</th><th>Output, $ per 1M</th><th></th></tr></thead><tbody>
        ${models.map((m) => { const p = state.settings.prices?.[m] || {}; return `<tr><td><code>${esc(m)}</code></td>
          <td><input type="text" inputmode="decimal" data-price="input" data-model="${esc(m)}" value="${p.input ?? ""}" placeholder="0.00" aria-label="${esc(m)} input price"></td>
          <td><input type="text" inputmode="decimal" data-price="output" data-model="${esc(m)}" value="${p.output ?? ""}" placeholder="0.00" aria-label="${esc(m)} output price"></td>
          <td><button class="btn small" data-action="save-price" data-model="${esc(m)}">Save</button></td></tr>`; }).join("")}
      </tbody></table></div>` : `<p class="muted">Models appear here once an agent is set to a non-Claude model.</p>`}</section>
    <section class="section"><h2>How approvals work</h2>
      <p class="muted" style="max-width:68ch">When an agent wants to edit a file or run a command, it pauses and asks you in its chat. On Claude, anything your Claude Code settings already allow runs without asking. On the other providers, reading and searching inside the agents' home folder and the kit, editing task files and running the kit's own scripts don't ask; everything else does. Choose "Allow automatically" for edits in an agent's chat header to skip edit prompts for that agent.</p></section>
    <section class="section"><h2>Agent kit</h2><dl class="facts"><dt>Kit folder</dt><dd><code>${esc(state.kit)}</code></dd><dt>Task board</dt><dd><code>${esc(state.kit)}/tasks</code></dd></dl></section>`;
}

function teamSection() {
  const rows = Object.entries(ROLES).map(([role, r]) => {
    const ids = agentIds().filter((id) => roleOf(id) === role);
    return `<div class="team-role ${role}"><h3>${r.name}s <small class="muted">${ids.length}</small></h3>
      <ul>${ids.map((id) => {
        const ag = state.agents[id];
        const choice = state.settings.agents[id] || {};
        return `<li><input type="text" class="agent-name" data-action="name" data-agent="${id}" value="${esc(personOf(id))}" maxlength="30" aria-label="Name of ${esc(id)}">
          <a href="#/agents/${id}" class="muted">chat</a> <code class="muted">${esc(id)}</code>
          <span class="muted">${esc(providerOf(choice.provider || "claude").label)}${choice.model ? `, ${esc(choice.model)}` : ""}</span>
          ${ids.length > 1 ? `<button class="btn small danger" data-action="remove-agent" data-agent="${id}" ${ag.status !== "stopped" ? 'disabled title="Stop it first"' : ""}>Remove</button>` : ""}</li>`;
      }).join("")}</ul>
      <button class="btn small" data-action="add-agent" data-role="${role}">Add a ${r.name}</button></div>`;
  }).join("");
  return `<section class="section"><h2>Team</h2>
    <p class="muted" style="max-width:68ch">Run several agents of the same role in parallel. Each claims its own tasks, so two never work on the same one, and each dev works in its own git worktree next to the project (<code>&lt;project&gt;.worktrees/TASK-NNN</code>). Rework goes back to the dev who built it, re-reviews to the same reviewer. Each agent gets a random name; type over it to rename. Choose each agent's provider and model in its chat header.</p>
    <div class="team">${rows}</div></section>`;
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
  if (route().page === "overview") render(true);
}

// ---- knowledge ------------------------------------------------------------------
// The Tech Lead's memory of each service (knowledge/<service>.md), read-only here.

function freshness(k) {
  if (!k.commit) return `<span class="pill lead">Never stamped</span>`;
  if (k.changed === null) return `<span class="pill lead" title="The recorded commit isn't in the repo anymore">Unverified</span>`;
  if (k.changed === 0) return `<span class="pill dev">Up to date</span>`;
  return `<span class="pill reviewer">${k.changed} file${k.changed > 1 ? "s" : ""} changed since</span>`;
}

async function KnowledgeList() {
  const items = await api("/api/knowledge");
  return `<div class="page-head"><div><h1>Knowledge</h1>
      <p>The Tech Lead's memory of each service: what it learned while writing specs, so the next task starts here instead of re-reading the code. Each file records the commit it describes; "changed since" counts the files changed in the project after that, which the Tech Lead re-checks before relying on it.</p></div></div>
    ${items.length ? `<div class="table-wrap"><table>
      <thead><tr><th>Service</th><th>Freshness</th><th>Commit</th><th>Updated</th><th>By</th><th>Size</th></tr></thead>
      <tbody>${items.map((k) => `<tr data-href="#/knowledge/${encodeURIComponent(k.file.replace(/\.md$/, ""))}">
        <td><a href="#/knowledge/${encodeURIComponent(k.file.replace(/\.md$/, ""))}">${esc(k.service)}</a><br><small class="muted"><code>${esc(k.path)}</code></small></td>
        <td>${freshness(k)}</td><td><code>${esc(k.commit || "")}</code>${k.branch ? ` <small class="muted">${esc(k.branch)}</small>` : ""}</td>
        <td class="num">${esc(k.updated || "")}</td><td>${k.updated_by ? esc(nameOf(k.updated_by)) : ""}</td><td class="num">${k.lines} lines</td></tr>`).join("")}</tbody></table></div>`
      : `<div class="empty">Nothing yet. The Tech Lead writes a file for a service the first time it specs a task there.</div>`}`;
}

async function KnowledgeView(r) {
  const k = await api(`/api/knowledge/${encodeURIComponent(r.id)}`);
  const linked = k.markdown.replace(/(^|[^\w`\[\/-])(TASK-\d{3,})(?![\w-])/g, "$1[$2](#/tasks/$2)");
  const changes = k.changed_files.length ? `<details class="changed"><summary>${k.changed} file${k.changed > 1 ? "s" : ""} changed since ${esc(k.commit)}${k.stale_sections.length ? `, touching: ${esc(k.stale_sections.join(", "))}` : ""}</summary>
      <ul>${k.changed_files.map((f) => `<li><code>${esc(f)}</code></li>`).join("")}</ul></details>` : "";
  return `<p><a href="#/knowledge" class="muted">All services</a></p>
    <div class="page-head"><div><h1>${esc(k.service)}</h1>
      <p>${freshness(k)} <code>${esc(k.path)}</code>${k.commit ? `, describes <code>${esc(k.commit)}</code>${k.branch ? ` on ${esc(k.branch)}` : ""}` : ""}${k.updated ? `, updated ${esc(k.updated)}` : ""}${k.updated_by ? ` by ${esc(nameOf(k.updated_by))}` : ""}</p></div></div>
    ${changes}
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

  const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/terminal`);
  socket.binaryType = "arraybuffer";
  shell.socket = socket;
  socket.onopen = () => { shell.fit.fit(); socket.send(JSON.stringify({ token: TOKEN, cols: shell.xterm.cols, rows: shell.xterm.rows })); };
  socket.onmessage = (e) => shell.xterm.write(new Uint8Array(e.data));
  socket.onclose = (e) => {
    shell.ended = true;
    shell.pane.classList.add("ended");
    shell.pane.querySelector(".term-state").textContent = "ended";
    shell.xterm.write(`\r\n\x1b[2m[${e.reason || "Disconnected."}]\x1b[0m\r\n`);
  };
  shell.xterm.onData((data) => socket.readyState === 1 && socket.send(JSON.stringify({ type: "input", data })));
  shell.xterm.onResize(({ cols, rows }) => socket.readyState === 1 && socket.send(JSON.stringify({ type: "resize", cols, rows })));
  shell.xterm.focus();
  return shell;
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
  tasks() {
    const rerender = () => render(true);
    document.getElementById("task-q").addEventListener("input", (e) => { taskFilter.q = e.target.value; clearTimeout(afterRender.t); afterRender.t = setTimeout(rerender, 200); });
    document.getElementById("task-project").addEventListener("change", (e) => { taskFilter.project = e.target.value; rerender(); });
    document.getElementById("task-status").addEventListener("change", (e) => { taskFilter.status = e.target.value; history.replaceState(null, "", "#/tasks"); rerender(); });
  },
  settings() {
    document.querySelectorAll("form.provider").forEach((form) => form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const key = form.api_key.value.trim();
      const saved = await act(() => api(`/api/providers/${form.dataset.provider}`, { method: "PUT",
        body: { api_key: key || null, base_url: form.base_url.value.trim() } }), "Provider saved.");
      if (saved) { state.settings = saved; render(true); }
    }));
    document.getElementById("settings-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const saved = await act(() => api("/api/settings", { method: "PUT", body: { workspace: document.getElementById("workspace").value } }), "Settings saved.");
      if (saved) state.settings = saved;
    });
  },
};

// ---- actions (event delegation) -------------------------------------------------

const actions = {
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

document.addEventListener("change", async (e) => {
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

document.addEventListener("toggle", (e) => {
  const id = e.target.dataset?.tool;
  if (id) e.target.open ? state.openTools.add(id) : state.openTools.delete(id);
}, true);

window.addEventListener("hashchange", () => { render(); view.focus({ preventScroll: true }); });

// ---- boot ------------------------------------------------------------------------

(async () => {
  try {
    await loadState();
  } catch (err) {
    view.innerHTML = `<div class="empty">Can't reach the console server: ${esc(err.message)} Restart it with <code>./start.sh</code> and reload.</div>`;
    return;
  }
  connect();
  refreshBadge();
  render();
})();
