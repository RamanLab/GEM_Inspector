// ---------------------------------------------------------------------------
// Exchange Debugging tab: pick one exchange (essential ones first, the rest on
// request) and see where its metabolite goes. The map shows the active-flux
// route to biomass plus every reaction within N hops of that route, active or
// not, so missing or blocked links around an essential exchange stand out.
// Drawing is done by network_map.js. Loaded after app.js; app.js calls renderDebugDefault().
// ---------------------------------------------------------------------------
const XMAP = { exchanges: [], selected: null, data: null };
const XMAP_VIEW = createNetworkMap("xmap");

function showDebugModal() { $("debugTab").click(); }

function renderDebugDefault(exchanges) {
  XMAP.exchanges = exchanges || [];
  if (!XMAP.exchanges.length) {
    $("debug").innerHTML = `<div class="note">Exchange debugging starts from the exchange essentiality analysis. That analysis is still running (or hasn't started) — this page fills in automatically when it finishes.</div>`;
    return;
  }
  const row = e => `
    <label class="debug-check-row" data-search="${escapeHtml((e.id + " " + join(e.metabolite_names)).toLowerCase())}">
      <input type="radio" name="xmapEx" value="${escapeHtml(e.id)}">
      <span class="debug-check-id">${escapeHtml(e.id)}</span>
      <span class="debug-check-name">${escapeHtml(join(e.metabolite_names) || join(e.metabolites))}</span>
    </label>`;
  const essential = XMAP.exchanges.filter(e => e.essential), other = XMAP.exchanges.filter(e => !e.essential);
  $("debug").innerHTML = `
    <div class="note">
      Choose an exchange to see how its metabolite feeds biomass. The <strong>primary route</strong> follows the
      active flux of the current FBA solution; <strong>hops</strong> adds every reaction around that route, including
      reactions that carry no flux, so you can check whether a link is missing or blocked. Cofactors are left out.
    </div>
    <h4>Essential exchanges (${essential.length})</h4>
    <div class="debug-select-list">${essential.map(row).join("") || '<div class="note">No essential exchanges were found.</div>'}</div>
    <details class="xmap-other">
      <summary>Show non-essential exchanges (${other.length})</summary>
      <input type="text" id="xmapSearch" placeholder="Search exchange ID or metabolite…">
      <div class="debug-select-list">${other.map(row).join("")}</div>
    </details>
    <div class="toolbar xmap-controls">
      <label>Hops <select id="xmapHops">
        <option value="0">0 – route only</option><option value="1" selected>1</option>
        <option value="2">2</option><option value="3">3</option></select></label>
      <label class="debug-toggle"><input type="checkbox" id="xmapHideTrivial" checked> Hide cofactors (H, H2O, ATP/ADP, NAD(H), Pi…)</label>
      ${currencyEditButton()}
      <button id="xmapRun" type="button" style="margin-left:auto;" disabled>Visualize</button>
    </div>
    <div id="xmapStatus" class="debug-status"></div>
    ${progressBarHtml("xmapProgress")}
    <div id="xmapResult"></div>`;

  document.querySelectorAll('input[name="xmapEx"]').forEach(r => r.addEventListener("change", () => {
    XMAP.selected = r.value; $("xmapRun").disabled = false;
  }));
  $("xmapSearch").addEventListener("input", ev => {
    const q = ev.target.value.trim().toLowerCase();
    document.querySelectorAll(".xmap-other .debug-check-row").forEach(l => l.classList.toggle("hidden", q && !l.dataset.search.includes(q)));
  });
  $("xmapRun").addEventListener("click", runExchangeMap);
  if (XMAP.selected) {
    const keep = document.querySelector(`input[name="xmapEx"][value="${CSS.escape(XMAP.selected)}"]`);
    if (keep) { keep.checked = true; $("xmapRun").disabled = false; }
  }
}

async function runExchangeMap() {
  if (!XMAP.selected) return;
  const btn = $("xmapRun");
  btn.disabled = true;
  $("xmapStatus").textContent = `Mapping ${XMAP.selected}…`;
  progressStart("xmapProgress");
  try {
    if (!MODEL_ID) throw new Error("Model session expired — please re-run the initial analysis.");
    const res = await fetch("/api/debug-exchange-map", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: MODEL_ID, exchange_id: XMAP.selected, hops: Number($("xmapHops").value),
        exclude_trivial_metabolites: $("xmapHideTrivial").checked, currency_metabolites: currencyPayload(),
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Mapping failed");
    XMAP.data = data;
    $("xmapStatus").textContent = "";
    renderXmapResult();
  } catch (err) {
    $("xmapStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
  } finally {
    progressDone("xmapProgress");
    btn.disabled = false;
  }
}

function renderXmapResult() {
  const d = XMAP.data, gi = d.growth_impact;
  const lost = gi.ko_growth_fraction !== null && gi.ko_growth_fraction < 1e-6;
  $("xmapResult").innerHTML = `
    <div class="debug-card">
      <h3>${escapeHtml(d.exchange_id)} <span class="stoich">${escapeHtml(d.exchange_name || "")}</span></h3>
      <dl class="kv">
        <dt>Exchanged metabolite</dt><dd>${escapeHtml(d.internal_metabolite.name)} <span class="badge">${escapeHtml(d.internal_metabolite.id)}</span></dd>
        <dt>Biomass reaction</dt><dd>${escapeHtml(d.biomass_reaction)}</dd>
        <dt>Growth after knockout</dt><dd>${fmt(gi.ko_growth)} of ${fmt(gi.wt_growth)}${gi.ko_growth_fraction == null ? "" : ` (${fmt(gi.ko_growth_fraction * 100, 2)}%)`}</dd>
      </dl>
      ${d.paths.length ? "" : `<div class="note">No active-flux route from this exchange to biomass in the current solution — the map shows the surrounding reactions only. (If the metabolite is itself a cofactor, untick “Hide cofactors”.)</div>`}
      <div id="xmapMap"></div>
      <details class="xmap-text"><summary>Active-flux route as text (${d.paths.length} path${d.paths.length === 1 ? "" : "s"})</summary>${mapPathsHtml(d.paths, "Path")}</details>
    </div>`;
  XMAP_VIEW.render($("xmapMap"), {
    map: d.map, hasKo: true, knocked: [d.exchange_id], csvName: d.exchange_id,
    koNote: lost ? "Growth is lost, so no flux distribution is shown after the knockout." : "",
    legendHtml: `<span><i class="tracer-dot tracer-dot-start"></i> Exchanged metabolite</span>
      <span><i class="tracer-dot tracer-dot-mid"></i> On the route</span>
      <span><i class="tracer-dot tracer-dot-side"></i> Neighbour</span>`,
  });
}
