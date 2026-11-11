// Polls /api/state and renders strip + list + per-session timelines. No framework.
"use strict";

const POLL_MS = 3000;
const TIMELINE_S = 20 * 60;
const LABEL = { approval: "needs approval", your_turn: "your turn", waiting: "waiting",
                working: "working", parked: "parked" };
const GLYPH = { approval: "⏸", your_turn: "?", waiting: "⧗", working: "▶", parked: "·" };

// Per-viewer UI memory; storage can be unavailable (private window), so never rely on it.
const store = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ } },
};
let open = new Set(store.get("open", []));
let last = null;

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;  // textContent only: descriptions are untrusted
  return e;
}

function dur(s) {
  if (s < 60) return "now";
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s >= 86400) return `${Math.floor(s / 86400)}d${Math.floor((s % 86400) / 3600)}h`;
  return `${Math.floor(s / 3600)}h${String(Math.round((s % 3600) / 60)).padStart(2, "0")}`;
}

function kilo(n) { return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : `${Math.round(n / 1e3)}k`; }

function stateText(r) {
  return r.state === "waiting" ? `waiting · ${r.outstanding}/${r.total_subagents}` : LABEL[r.state];
}

// Weekly pace: the server works out today's yellow threshold from the reset time (week_yellow
// in usage.py). Orange is 5 points above it, red 8 above.
function limitLevel(pct, yellow, orange, red) {
  return pct >= red ? "lim-red" : pct >= orange ? "lim-orange" : pct >= yellow ? "lim-yellow" : "";
}

// [text, class, tooltip] per window.
function limitParts(L, now) {
  const text = (w, name) => `${name}: ${Math.round(w.used_percentage)}% · resets ${dur(w.resets_at - now)}`;
  const f = L.five_hour, w = L.seven_day;
  const parts = [f ? [text(f, "5h"), limitLevel(f.used_percentage, 80, 80, 90), "orange at 80%, red at 90%"] : ["5h: –"]];
  if (w) {
    const y = w.yellow;
    parts.push([text(w, "wk"), limitLevel(w.used_percentage, y, y + 5, y + 8),
                `today: yellow at ${y}%, orange at ${y + 5}%, red at ${y + 8}%`]);
  } else parts.push(["wk: –"]);
  return parts;
}

// Strip content as [text, class, tooltip] parts, joined with " · ".
function usageParts(u, now) {
  const L = !u.error && u.limits;
  if (!L) return [[usageText(u, now)]];
  const age = now - L.ts;  // real numbers from the status line; usageText's estimate is the fallback
  return [...limitParts(L, now), [`${kilo(u.burn_per_min)}/min`], [`as of ${dur(age)}${age < 60 ? "" : " ago"}`]];
}

// Anthropic's weekday peak window (05:00-11:00 Pacific), when 5-hour limits drain faster.
function peakPart(p) {
  if (!p) return [];
  const tip = "Weekdays 05:00-11:00 Pacific: 5-hour limits drain faster";
  return [p.on ? [`peak · ends ${dur(p.change_s)}`, "lim-orange", tip] : [`off-peak · peak in ${dur(p.change_s)}`, "", tip]];
}

function usageText(u, now) {
  if (u.error) return `5h: unavailable (${u.error})`;
  const burn = `${kilo(u.burn_per_min)}/min`;
  if (u.block_start === null) return `5h: idle window · ${burn}`;
  const tail = `${burn} · resets ${dur(u.block_end - now)} · ${u.label}`;
  if (!u.samples) return `5h: ${kilo(u.used)} used · no past limit on record · ${tail}`;
  const pct = Math.round((100 * u.used) / u.ceiling_median);
  if (u.above_samples) return `5h: ${pct}% · above all ${u.samples} past limits · ${tail}`;
  let left = "";
  if (u.minutes_left_hi !== null) {
    const lo = u.minutes_left_lo === null ? 0 : u.minutes_left_lo * 60;
    left = ` · ≈${dur(lo)}–${dur(u.minutes_left_hi * 60)} left`;
  }
  return `5h: ~${pct}% (${u.samples} samples)${left} · ${tail}`;
}

function toggleRow(id) {
  open.has(id) ? open.delete(id) : open.add(id);
  store.set("open", [...open]);
  if (last) render(last);
}

function renderStrip(s) {
  const pills = document.getElementById("pills");
  pills.replaceChildren(...s.sessions.map(r => {
    const p = el("span", `pill s-${r.state}`, `${r.name} ${GLYPH[r.state]}`);
    p.title = `${stateText(r)} — ${r.last_action}`;
    p.onclick = () => { document.body.classList.remove("mini"); store.set("mini", false); toggleRow(r.session_id); };
    return p;
  }));
  document.getElementById("usage").replaceChildren(...[...peakPart(s.peak), ...usageParts(s.usage, s.now)].flatMap(([text, cls, tip], i) => {
    const span = el("span", cls, text);
    if (tip) span.title = tip;
    return i ? [" · ", span] : [span];
  }));
}

function seg(track, t0, t1, now, cls) {
  const lo = now - TIMELINE_S;
  if (t1 < lo) return;
  const a = Math.max(t0, lo);
  const d = el("div", `seg ${cls}`);
  d.style.left = `${(100 * (a - lo)) / TIMELINE_S}%`;
  d.style.width = `${(100 * (Math.min(t1, now) - a)) / TIMELINE_S}%`;
  track.append(d);
}

function lane(who, small, what, fill) {
  const row = el("div", "lane");
  const w = el("span", "who", who);
  if (small) { w.append(" "); w.append(el("small", null, small)); }
  const track = el("div", "track");
  fill(track);
  track.append(el("div", "nowline"));
  row.append(w, track, el("span", "what", what));
  return row;
}

function flatten(nodes, out = []) {
  for (const n of nodes) { out.push(n); flatten(n.children, out); }
  return out;
}

function renderTimeline(r, now) {
  const box = el("div", "exp");
  box.append(lane(`${r.name} (parent)`, r.model || "", `ctx ${Math.round(100 * r.context_pct)}%`, track => {
    if (r.outstanding) seg(track, now - TIMELINE_S, now, now, "wait");
    for (const [a, b] of r.parent_busy_segments) seg(track, a, b + 5, now, "run");
  }));
  const all = flatten(r.subagents);
  const shown = all.filter(n => n.running || n.last_activity >= now - TIMELINE_S);
  for (const n of shown) {
    const indent = "  ".repeat(n.depth - 1) + "└ ";
    const kind = `${n.specialist ? "specialist" : "general"}${n.depth > 1 ? ` · depth ${n.depth}` : ""}${n.background ? " · bg" : ""}`;
    const what = `${n.running ? "●" : "✓"} ${n.description} · ${dur(n.last_activity - n.started)}`;
    box.append(lane(indent + n.agent_type, kind, what, track =>
      seg(track, n.started, n.running ? now : n.last_activity, now, n.running ? "run" : "fin")));
  }
  const hidden = all.length - shown.length;
  box.append(el("div", "foot",
    `← 20 min ··· now → · depth ${r.max_depth} · ${r.specialists} specialist / ${r.generals} general` +
    ` · ${kilo(r.tokens_last_hour)} weighted tokens last hour` +
    (hidden ? ` · ${hidden} older subagent${hidden > 1 ? "s" : ""} not shown` : "") +
    ` · ${r.cwd}`));
  return box;
}

function renderList(s) {
  const list = document.getElementById("list");
  if (!s.sessions.length) {
    list.replaceChildren(el("div", "empty", s.error ? "" : "No live Claude Code sessions."));
    return;
  }
  const live = new Set(s.sessions.map(r => r.session_id));
  open = new Set([...open].filter(id => live.has(id)));  // ended sessions close their rows
  store.set("open", [...open]);
  const rows = [];
  for (const r of s.sessions) {
    const row = el("div", "row");
    row.onclick = () => toggleRow(r.session_id);
    const bar = el("div", r.context_pct > 0.8 ? "bar hot" : "bar");
    const fill = el("i");
    fill.style.width = `${Math.min(100, 100 * r.context_pct)}%`;
    bar.append(fill);
    bar.title = `context ${Math.round(100 * r.context_pct)}% of ${kilo(s.context_limit)}`;
    const name = el("b", null, r.name);
    name.title = r.cwd;
    row.append(el("span", null, open.has(r.session_id) ? "▾" : "▸"), name,
               el("span", `badge s-${r.state}`, stateText(r)), el("span", "action", r.last_action),
               bar, el("span", "idle", r.busy ? "now" : dur(r.idle_s)));
    rows.push(row);
    if (open.has(r.session_id)) rows.push(renderTimeline(r, s.now));
  }
  list.replaceChildren(...rows);
}

function renderJobs(s) {
  const box = document.getElementById("jobs");
  const jobs = s.jobs || [];
  box.hidden = !jobs.length;
  box.replaceChildren(el("div", "head", "Background jobs"), ...jobs.map(j => {
    const row = el("div", "job");
    const bar = el("div", "bar");
    if (j.pct !== null) {
      const fill = el("i");
      fill.style.width = `${j.pct}%`;
      bar.append(fill);
    }
    const name = el("b", null, j.name);
    name.title = j.path;
    row.append(name, bar, el("span", "action", j.pct === null ? "no tqdm progress" : `${j.pct}% · ${j.detail}`),
               el("span", "idle", dur(j.quiet_s)));
    row.title = `last written ${dur(j.quiet_s)} ago`;
    return row;
  }));
}

function render(s) {
  const banner = document.getElementById("banner");
  banner.hidden = !s.error;
  banner.textContent = s.error ? `Can't list sessions: ${s.error}` : "";
  renderStrip(s);
  renderList(s);
  renderJobs(s);
  document.getElementById("note").textContent = s.hook_installed ? "" :
    "Permission prompts (🟥) aren't detected yet: install the hook with `python -m dashboard.install`.";
  const waiting = s.sessions.filter(r => r.state === "approval" || r.state === "your_turn").length;
  document.title = waiting ? `(${waiting}) Claude Sessions` : "Claude Sessions";
}

async function poll() {
  try {
    const res = await fetch("/api/state", { cache: "no-store" });
    if (res.status === 500) {
      const banner = document.getElementById("banner");
      banner.hidden = false;
      banner.textContent = `Dashboard error: ${(await res.json()).error}. Retrying…`;
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    last = await res.json();
    render(last);
  } catch (e) {
    const banner = document.getElementById("banner");
    banner.hidden = false;
    banner.textContent = `Dashboard server unreachable (${e.message}). Retrying…`;
  }
}

document.body.classList.toggle("mini", store.get("mini", false));
document.getElementById("toggle").onclick = () => {
  const mini = document.body.classList.toggle("mini");
  store.set("mini", mini);
};
poll();
setInterval(poll, POLL_MS);
