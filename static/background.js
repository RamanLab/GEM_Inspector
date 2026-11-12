// ---------------------------------------------------------------------------
// Background analyses (dead ends, FVA, FROG, MEMOTE): checkboxes at upload, a
// status panel with time estimates, and the results merged into the Reactions
// and Metabolites tables as they finish. The server does the work
// (overview/background.py); this file only starts it, polls, and merges.
// Loaded before app.js code runs; app.js calls startBackground/resetBackground.
// ---------------------------------------------------------------------------
const BG = { state: null, timer: null, merged: "", estimates: {} };
const BG_ORDER = ["dead_ends", "fva", "frog", "memote"];
const BG_BOX = { fva: "bgFva", dead_ends: "bgDead", frog: "bgFrog", memote: "bgMemote" };

function selectedBackgroundTasks() {
  return BG_ORDER.filter(t => $(BG_BOX[t]) && $(BG_BOX[t]).checked);
}

function resetBackground() {
  if (BG.timer) clearInterval(BG.timer);
  BG.timer = null; BG.state = null; BG.merged = "";
  const panel = $("bgPanel");
  if (panel) { panel.classList.add("hidden"); panel.innerHTML = ""; }
}

async function startBackground(tasks) {
  if (!MODEL_ID) return;
  try {
    const res = await fetch(`/api/background/${MODEL_ID}/start`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tasks }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    BG.state = data;
  } catch (err) { return; }
  bgEnsurePolling();
  bgSyncMemote();
  loadBgEstimates().then(renderBgPanel);
  renderBgPanel();
}

function bgEnsurePolling() {
  if (BG.timer) return;
  const forModel = MODEL_ID;
  BG.timer = setInterval(async () => {
    if (forModel !== MODEL_ID) { resetBackground(); return; }
    try {
      const res = await fetch(`/api/background/${forModel}/status`);
      if (!res.ok) return;
      BG.state = await res.json();
    } catch (err) { return; }
    bgSyncMemote();
    renderBgPanel();
    if (!BG.state.running) { clearInterval(BG.timer); BG.timer = null; }
    bgMergeResults();
  }, 2500);
}

// MEMOTE started here is the same job the MEMOTE tab shows, so hand it over to that tab's own polling.
function bgSyncMemote() {
  const m = BG.state && BG.state.tasks.memote;
  if (m && (m.status === "running" || m.status === "done") && !MEMOTE_TIMER && !(MEMOTE_STATE && MEMOTE_STATE.status === "done")) {
    MEMOTE_STATE = { status: "running", percent: 0 };
    renderMemoteBox();
    pollMemote();
  }
}

async function bgMergeResults() {
  const t = BG.state ? BG.state.tasks : {};
  const key = ["dead_ends", "fva"].map(n => (t[n] && t[n].status) || "-").join();
  if (key === BG.merged || !(t.fva?.status === "done" || t.dead_ends?.status === "done")) return;
  BG.merged = key;
  let r;
  try { r = await (await fetch(`/api/background/${MODEL_ID}/results`)).json(); } catch (err) { return; }
  if (r.fva) {
    const blocked = new Set(r.fva.blocked);
    DATA.reactions.forEach(x => {
      const range = r.fva.ranges[x.id];
      if (range) { x.fva_min = range[0]; x.fva_max = range[1]; x.fva_blocked = blocked.has(x.id); }
    });
    keepControls("reactions", renderReactions);
  }
  if (r.dead_ends) {
    DATA.metabolites.forEach(x => { x.dead_end = r.dead_ends[x.id] || null; });
    keepControls("metabolites", renderMetabolites);
  }
}

// Re-render a tab after new data arrived without losing the user's search and filters.
function keepControls(panelId, render) {
  const panel = $(panelId);
  const saved = [...panel.querySelectorAll("input[id], select[id]")].map(e => [e.id, e.type === "checkbox" ? e.checked : e.value]);
  render();
  let first = null;
  saved.forEach(([id, v]) => {
    const e = $(id);
    if (!e) return;
    if (e.type === "checkbox") e.checked = v; else e.value = v;
    first = first || e;
  });
  if (first) first.dispatchEvent(new Event("input"));
}

function bgFmtSeconds(s) {
  if (s == null) return "";
  return s < 90 ? `${Math.max(1, Math.round(s))} s` : `${Math.round(s / 60)} min`;
}

function renderBgPanel() {
  const panel = $("bgPanel"), st = BG.state;
  if (!panel || !st) return;
  const tasks = st.tasks, names = BG_ORDER;
  const chip = s => ({ queued: "waiting", running: "running…", done: "done", error: "failed", stopped: "stopped" }[s] || s);
  const rows = names.map(n => {
    const t = tasks[n];
    const label = { dead_ends: "Dead-end metabolites", fva: "FVA (blocked reactions, flux ranges)", frog: "FROG report", memote: "MEMOTE" }[n];
    if (!t) return `<div class="bg-row"><span>${label}</span><span class="stoich">not run</span>
      <button type="button" class="secondary" data-bg-run="${n}">Run${BG.estimates[n] ? ` (~${bgFmtSeconds(BG.estimates[n])})` : ""}</button></div>`;
    const timing = t.status === "running" ? `${bgFmtSeconds(t.elapsed)} of ~${bgFmtSeconds(t.estimate) || "?"}`
      : t.status === "done" ? `${bgFmtSeconds(t.elapsed)}` : t.status === "queued" && t.estimate ? `~${bgFmtSeconds(t.estimate)}` : "";
    return `<div class="bg-row"><span>${label}</span><span class="bg-chip bg-${t.status}">${chip(t.status)}</span>
      <span class="stoich">${escapeHtml(timing)}</span>${t.error ? `<span class="error">${escapeHtml(t.error)}</span>` : ""}</div>`;
  }).join("");
  const done = names.filter(n => tasks[n] && tasks[n].status === "done").length, total = names.filter(n => tasks[n]).length;
  panel.classList.remove("hidden");
  panel.innerHTML = `<summary>Background analyses${st.running ? ` — running (${done}/${total} done)` : total ? ` — ${done}/${total} done` : ""}</summary>
    <div class="bg-body">${rows}
      <div class="stoich">${st.cores} core(s) available; flux variability and deletions use ${st.processes} process(es). Estimates are rough, from the time of one LP on this model.
        You can keep exploring; the Network Gaps and FROG tabs open once the analyses they need have finished.</div>
      ${st.running ? '<div class="stoich">A running step cannot be interrupted midway; stopping takes effect when it finishes.</div><button type="button" class="secondary" data-bg-stop="1">Stop after the current step</button>' : ""}
    </div>`;
  applyTabLocks();
  panel.querySelectorAll("[data-bg-run]").forEach(b => b.addEventListener("click", () => startBackground([b.dataset.bgRun])));
  const stop = panel.querySelector("[data-bg-stop]");
  if (stop) stop.addEventListener("click", async () => { BG.state = await (await fetch(`/api/background/${MODEL_ID}/stop`, { method: "POST" })).json(); renderBgPanel(); });
}

async function loadBgEstimates() {
  try { BG.estimates = (await (await fetch(`/api/background/${MODEL_ID}/estimates`)).json()).estimates || {}; } catch (err) { /* optional */ }
}

// Tabs that would repeat what a background task is computing are locked until it finishes.
const BG_TAB_LOCKS = { gaps: ["dead_ends", "fva"], frog: ["fva", "frog"] };

function bgLockedBy(tab) {
  const tasks = BG.state ? BG.state.tasks : {};
  return (BG_TAB_LOCKS[tab] || []).filter(n => tasks[n] && (tasks[n].status === "queued" || tasks[n].status === "running"));
}

function applyTabLocks() {
  Object.keys(BG_TAB_LOCKS).forEach(tab => {
    const btn = document.querySelector(`.tab[data-tab="${tab}"]`);
    if (!btn) return;
    const busy = bgLockedBy(tab).length > 0;
    btn.classList.toggle("tab-locked", busy);
    btn.title = busy ? "Still being computed in the background — check again in a little while." : "";
  });
}

function bgToast(text) {
  let el = $("bgToast");
  if (!el) { el = document.createElement("div"); el.id = "bgToast"; el.className = "bg-toast"; document.body.appendChild(el); }
  el.textContent = text; el.classList.add("show");
  clearTimeout(bgToast.t);
  bgToast.t = setTimeout(() => el.classList.remove("show"), 5000);
}

document.addEventListener("click", ev => {
  const btn = ev.target.closest && ev.target.closest(".tab");
  if (!btn || !bgLockedBy(btn.dataset.tab).length) return;
  ev.stopImmediatePropagation(); ev.preventDefault();
  const names = bgLockedBy(btn.dataset.tab).map(n => ({ dead_ends: "dead-end", fva: "FVA", frog: "FROG" }[n])).join(" and ");
  bgToast(`The ${names} analysis is still running in the background. This tab opens once it finishes — check again in a little while.`);
  const panel = $("bgPanel"); if (panel) panel.open = true;
}, true);
