// ---------------------------------------------------------------------------
// Pathway Tracer tab. Pick a start and a target (each a metabolite or a
// reaction) and see the routes between them drawn with their neighbourhood:
// "active" follows only reactions carrying flux in the current FBA solution,
// "all" follows every reaction whose bounds allow it, so alternatives show up.
// Optional extras (metabolites/reactions to always show) and a knockout for a
// before/after comparison. Drawing is done by network_map.js.
// Nothing runs until "Run trace" is clicked; renderTracer() is called by app.js.
// ---------------------------------------------------------------------------
let TRACER_RESULT = null;   // shape used by the generated report (see reportTracerSectionHtml)
const TRACER_VIEW = createNetworkMap("trc");
const TRACER_PICKS = { extra: [], knockout: [] };   // chip lists: ids of metabolites and reactions

function resetTracer() {
  TRACER_RESULT = null;
  TRACER_PICKS.extra = []; TRACER_PICKS.knockout = [];
  TRACER_VIEW.destroy();
  if (typeof EXP !== "undefined" && EXP.cy) { EXP.cy.destroy(); EXP.cy = null; }
}

// "metabolite" | "reaction" | null for a typed id (case-insensitive; returns the exact id).
function tracerLookup(text) {
  const t = (text || "").trim().toLowerCase();
  if (!t) return null;
  const met = (DATA.metabolites || []).find(m => m.id.toLowerCase() === t);
  if (met) return { type: "metabolite", id: met.id };
  const rxn = (DATA.reactions || []).find(r => r.id.toLowerCase() === t);
  return rxn ? { type: "reaction", id: rxn.id } : null;
}

function renderTracer() {
  const opt = (kind, x) => `<option value="${escapeHtml(x.id)}" label="${kind}: ${escapeHtml(x.name || "")}"></option>`;
  const options = (DATA.metabolites || []).map(m => opt("metabolite", m)).join("")
    + (DATA.reactions || []).map(r => opt("reaction", r)).join("");
  const field = (id, label, hint) => `
    <div class="tracer-field tracer-field-wide"><label>${label}</label>
      <input id="${id}" type="text" list="trcList" placeholder="${hint}" autocomplete="off">
      <span class="stoich" id="${id}Kind"></span></div>`;
  const picker = (key, label, hint) => `
    <div class="tracer-field tracer-field-wide"><label>${label}</label>
      <div class="trc-chips" id="trc${key}Chips"></div>
      <input id="trc${key}" type="text" list="trcList" placeholder="${hint}" autocomplete="off"></div>`;
  $("tracer").innerHTML = `
    <div class="trc-subtabs">
      <button type="button" class="trc-subtab active" data-sub="Route">Route: start → target</button>
      <button type="button" class="trc-subtab" data-sub="Explore">Explore: draw your own graph</button>
    </div>
    <div id="trcRouteView">
    <div class="note">
      Trace routes between any two points of the model. Start and target can each be a <strong>metabolite or a
      reaction</strong> (pick from the list or type to search). <strong>Active flux only</strong> follows reactions
      carrying flux in the current FBA solution; <strong>all possible routes</strong> follows every reaction whose bounds
      allow it, so you can see alternatives and where a route is blocked. <strong>Hops</strong> adds the reactions around
      the routes, active or not. Cofactors are hidden unless you add them under “Also show”.
    </div>
    <datalist id="trcList">${options}</datalist>
    <div class="tracer-form">
      ${field("trcStart", "Start (metabolite or reaction)", "Search ID or name…")}
      ${field("trcTarget", "Target (metabolite or reaction)", "Search ID or name…")}
      <div class="tracer-field"><label>Routes</label>
        <select id="trcMode"><option value="active">Active flux only</option><option value="all">All possible routes</option></select></div>
      <div class="tracer-field"><label>Hops</label>
        <select id="trcHops"><option value="0">0 – routes only</option><option value="1" selected>1</option><option value="2">2</option><option value="3">3</option></select></div>
      <div class="tracer-field"><label>Max levels</label><input id="trcLevels" type="number" min="1" max="100" value="15"></div>
      <div class="tracer-field"><label>Max paths</label><input id="trcPaths" type="number" min="1" max="100" value="10"></div>
      <div class="tracer-field"><label>&nbsp;</label>
        <label class="debug-toggle tracer-inline-toggle"><input type="checkbox" id="trcHide" checked> Hide cofactors</label></div>
      <div class="tracer-field"><label>&nbsp;</label>${currencyEditButton()}</div>
      ${picker("Extra", "Also show (metabolites or reactions)", "Add a metabolite or reaction…")}
      ${picker("Knockout", "Knock out (optional, for before/after)", "Reaction, or metabolite to block…")}
      <div class="tracer-field"><label>&nbsp;</label><button id="trcRun" type="button">Run trace</button></div>
    </div>
    <div id="trcStatus" class="debug-status"></div>
    ${progressBarHtml("trcProgress")}
    <div id="trcResult"></div>
    </div>
    <div id="trcExploreView" class="hidden"></div>`;
  document.querySelectorAll(".trc-subtab").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll(".trc-subtab").forEach(x => x.classList.toggle("active", x === b));
    $("trcRouteView").classList.toggle("hidden", b.dataset.sub !== "Route");
    $("trcExploreView").classList.toggle("hidden", b.dataset.sub !== "Explore");
  }));
  renderExplorer();

  ["trcStart", "trcTarget"].forEach(id => $(id).addEventListener("input", () => {
    const hit = tracerLookup($(id).value);
    $(id + "Kind").textContent = hit ? hit.type : $(id).value.trim() ? "not found in this model" : "";
  }));
  [["Extra", "extra"], ["Knockout", "knockout"]].forEach(([key, list]) => {
    const input = $("trc" + key);
    const add = () => {
      const hit = tracerLookup(input.value);
      if (!hit) return;
      if (!TRACER_PICKS[list].includes(hit.id)) TRACER_PICKS[list].push(hit.id);
      input.value = ""; drawChips(key, list);
    };
    input.addEventListener("change", add);
    input.addEventListener("keydown", ev => { if (ev.key === "Enter") { ev.preventDefault(); add(); } });
    drawChips(key, list);
  });
  $("trcRun").addEventListener("click", runTracer);
}

function drawChips(key, list) {
  $(`trc${key}Chips`).innerHTML = TRACER_PICKS[list].map(id =>
    `<span class="trc-chip">${escapeHtml(id)}<button type="button" data-id="${escapeHtml(id)}" aria-label="Remove">×</button></span>`).join("");
  $(`trc${key}Chips`).querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    TRACER_PICKS[list] = TRACER_PICKS[list].filter(x => x !== b.dataset.id); drawChips(key, list);
  }));
}

async function runTracer() {
  const start = tracerLookup($("trcStart").value), target = tracerLookup($("trcTarget").value);
  const status = $("trcStatus"), btn = $("trcRun");
  if (!start || !target) { status.innerHTML = `<span class="error">Pick a start and a target that exist in this model.</span>`; return; }
  const split = ids => ids.map(i => tracerLookup(i));
  btn.disabled = true; status.textContent = "Tracing…"; progressStart("trcProgress");
  try {
    if (!MODEL_ID) throw new Error("Model session expired — please re-run the initial analysis.");
    const res = await fetch("/api/trace-map", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: MODEL_ID, start, target, mode: $("trcMode").value, hops: Number($("trcHops").value),
        max_levels: Number($("trcLevels").value), max_paths: Number($("trcPaths").value),
        exclude_trivial_metabolites: $("trcHide").checked, currency_metabolites: currencyPayload(),
        extra_metabolites: split(TRACER_PICKS.extra).filter(x => x && x.type === "metabolite").map(x => x.id),
        extra_reactions: split(TRACER_PICKS.extra).filter(x => x && x.type === "reaction").map(x => x.id),
        knockouts: TRACER_PICKS.knockout,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Trace failed");
    TRACER_RESULT = { start_id: start.id, target_metabolite: { id: target.id }, paths: data.paths, growth: data.growth };
    status.textContent = "";
    renderTracerResult(data);
  } catch (err) {
    status.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
  } finally {
    progressDone("trcProgress"); btn.disabled = false;
  }
}

function renderTracerResult(d) {
  const ko = d.knockout, koOk = ko && !ko.error, gi = koOk ? ko.growth_impact : null;
  const lost = gi && gi.ko_growth_fraction !== null && gi.ko_growth_fraction < 1e-6;
  const label = e => `${escapeHtml(e.id)} <span class="stoich">${e.type}</span>`;
  const notes = [];
  if (!d.paths.length) notes.push(`No ${d.mode === "all" ? "route allowed by the bounds" : "active-flux route"} from the start to the target
    ${d.mode === "active" ? "— try “All possible routes”, which also follows reactions with no flux" : "within the level limit — raise Max levels"}. The map shows the surrounding reactions.`);
  if (ko && ko.error) notes.push(ko.error);
  if (koOk && ko.not_found.length) notes.push(`Not found: ${ko.not_found.map(escapeHtml).join(", ")}.`);
  $("trcResult").innerHTML = `
    <div class="debug-card">
      <h3>${label(d.start)} → ${label(d.target)}</h3>
      <dl class="kv">
        <dt>Routes</dt><dd>${d.paths.length} ${d.mode === "all" ? "possible" : "active-flux"} (shortest first)</dd>
        <dt>Growth</dt><dd>${fmt(d.growth)}${koOk ? ` → ${fmt(gi.ko_growth)} after knocking out ${ko.blocked_reactions.length} reaction(s)` : ""}</dd>
      </dl>
      ${notes.map(n => `<div class="note">${n}</div>`).join("")}
      <div id="trcMap"></div>
      <details class="xmap-text"><summary>Routes as text (${d.paths.length})</summary>${mapPathsHtml(d.paths, "Route")}</details>
    </div>`;
  TRACER_VIEW.render($("trcMap"), {
    map: d.map, hasKo: koOk, knocked: koOk ? ko.blocked_reactions : [], csvName: `${d.start.id}_to_${d.target.id}`,
    koNote: lost ? "Growth is lost, so no flux distribution is shown after the knockout." : "",
    legendHtml: `<span><i class="tracer-dot tracer-dot-start"></i> Start</span>
      <span><i class="tracer-dot tracer-dot-target"></i> Target</span>
      <span><i class="tracer-dot tracer-dot-mid"></i> On a route</span>
      <span><i class="tracer-dot tracer-dot-side"></i> Neighbour</span>
      <span><i class="xmap-sq xmap-sq-extra"></i> Added by you</span>`,
  });
}
