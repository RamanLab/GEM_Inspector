// ---------------------------------------------------------------------------
// Pathway Explorer (sub-tab of the Pathway Tracer): draw your own graph.
// Start from any metabolite or reaction, then grow it one step at a time —
// upstream (what makes it), downstream (what uses it) or both — and read the
// diagnostics on the nodes: flux, blocked (FVA), dead end, essential, and
// whether the network can make or use each metabolite at all. "Trace the break"
// expands unmakeable metabolites upstream until the chain reaches metabolites
// that can be made, which leaves the first unmakeable ones — the real break.
// The server does the work (debugging/explore.py); drawing helpers come from
// network_map.js. renderExplorer() is called by renderTracer().
// ---------------------------------------------------------------------------
const EXP = { cy: null, busy: false };

function renderExplorer() {
  EXP.cy = null;
  $("trcExploreView").innerHTML = `
    <div class="note">
      Draw your own graph. Pick a <strong>metabolite or reaction</strong> to start, then click a node and expand it
      <strong>upstream</strong> (what can make it), <strong>downstream</strong> (what can use it) or both. Double-click a node to expand it both ways.
      <strong>Test metabolites</strong> checks, for every metabolite drawn, whether the network can make it and use it at all under the
      current bounds (green/red); <strong>Trace the break</strong> keeps expanding unmakeable metabolites upstream and stops where things can be made again,
      so the red nodes left are where the real gap is. Cofactors are hidden unless you pick them.
    </div>
    <div class="tracer-form">
      <div class="tracer-field tracer-field-wide"><label>Add a metabolite or reaction</label>
        <input id="expSeed" type="text" list="trcList" placeholder="Search ID or name…" autocomplete="off">
        <span class="stoich" id="expSeedKind"></span></div>
      <div class="tracer-field"><label>&nbsp;</label><button id="expAddExpand" type="button">Add and expand</button></div>
      <div class="tracer-field"><label>&nbsp;</label><button id="expAddOnly" type="button" class="secondary">Add only</button></div>
      <div class="tracer-field"><label>&nbsp;</label>
        <label class="debug-toggle tracer-inline-toggle"><input type="checkbox" id="expHide" checked> Hide cofactors</label></div>
      <div class="tracer-field"><label>&nbsp;</label>${currencyEditButton()}</div>
    </div>
    <div class="tracer-network-toolbar">
      <button type="button" id="expTest" class="secondary" title="Can the network make and use each metabolite drawn?">Test metabolites</button>
      <select id="expBreakDir"><option value="up">Trace the break: upstream (unmakeable)</option><option value="down">Trace the break: downstream (unusable)</option></select>
      <label>Rounds <select id="expRounds"><option>1</option><option>2</option><option selected>3</option><option>4</option><option>5</option></select></label>
      <button type="button" id="expBreak">Trace the break</button>
      <label class="debug-toggle"><input type="checkbox" id="expFrontier"> Show only the problem area</label>
      <select id="expColour"><option value="make">Colour metabolites: can be made</option><option value="use">Colour metabolites: can be used</option><option value="role">Colour metabolites: plain</option></select>
    </div>
    <div class="tracer-network-toolbar">
      <select id="expLayout"><option value="cose">Tidy: clustered</option><option value="breadthfirst">Tidy: tree</option></select>
      <input type="text" id="expFind" placeholder="Find a node…" class="map-find">
      <span class="map-zoom">
        <button type="button" class="secondary" data-act="in" title="Zoom in">+</button>
        <button type="button" class="secondary" data-act="out" title="Zoom out">−</button>
        <button type="button" class="secondary" data-act="fit">Fit</button>
        <button type="button" class="secondary" data-act="png">PNG</button>
        <button type="button" class="secondary" data-act="csv" title="Download the nodes drawn, with their diagnostics">CSV</button>
        <button type="button" class="secondary" data-act="clear">Clear</button>
      </span>
      <span id="expCount" class="stoich"></span>
    </div>
    <div id="expStatus" class="debug-status"></div>
    ${progressBarHtml("expProgress")}
    <div class="exp-layout">
      <div class="tracer-cy-wrap"><div id="expCy" class="tracer-cy-container"></div></div>
      <div id="expSide" class="exp-side"><div class="stoich">Click a node to see its details and expand it.</div></div>
    </div>
    <div class="tracer-legend xmap-legend">
      <span><i class="tracer-dot tracer-dot-start"></i> Start</span>
      <span><i class="tracer-dot" style="background:#bbf7d0"></i> Can be made / used</span>
      <span><i class="tracer-dot" style="background:#fecaca;border:1px solid #dc2626"></i> Cannot</span>
      <span><i class="tracer-dot tracer-dot-dead"></i> Dead end (needs the dead-end analysis)</span>
      <span><i class="xmap-sq xmap-sq-active"></i> Active</span>
      <span><i class="xmap-sq xmap-sq-inactive"></i> Inactive</span>
      <span><i class="xmap-sq xmap-sq-blocked"></i> Blocked (bounds, or FVA when run)</span>
      <span>🔒 Essential reaction</span>
      <span class="stoich">Arrows follow the flux, or the direction the bounds allow; two heads = reversible. Hover for details.</span>
    </div>`;
  $("expSeed").addEventListener("input", () => {
    const hit = tracerLookup($("expSeed").value);
    $("expSeedKind").textContent = hit ? hit.type : $("expSeed").value.trim() ? "not found in this model" : "";
  });
  $("expSeed").addEventListener("keydown", ev => { if (ev.key === "Enter") expAdd(true); });
  $("expAddExpand").addEventListener("click", () => expAdd(true));
  $("expAddOnly").addEventListener("click", () => expAdd(false));
  $("expTest").addEventListener("click", () => expBusy(expTestAll));
  $("expBreak").addEventListener("click", () => expBusy(expTraceBreak));
  $("expFrontier").addEventListener("change", expApplyView);
  $("expColour").addEventListener("change", expApplyView);
  $("expLayout").addEventListener("change", expTidy);
  $("expFind").addEventListener("input", expFind);
  $("trcExploreView").querySelectorAll(".map-zoom button").forEach(b => b.addEventListener("click", () => expAction(b.dataset.act)));
}

// ---- graph building -------------------------------------------------------
function expEnsureCy() {
  if (EXP.cy) return EXP.cy;
  if (typeof cytoscape === "undefined") {
    $("expCy").innerHTML = `<div class="note error">The network library did not load (static/vendor/cytoscape.min.js). Reload with Ctrl+F5.</div>`;
    return null;
  }
  EXP.cy = cytoscape({ container: $("expCy"), wheelSensitivity: 0.25, maxZoom: 2.5, style: MAP_STYLE, boxSelectionEnabled: false });
  EXP.cy.on("tap", "node", ev => expSelect(ev.target));
  EXP.cy.on("tap", ev => { if (ev.target === EXP.cy) $("expSide").innerHTML = '<div class="stoich">Click a node to see its details and expand it.</div>'; });
  EXP.cy.on("dbltap", "node", ev => expBusy(() => expExpand(ev.target, "both")));
  mapAttachTooltips(EXP.cy);
  return EXP.cy;
}

async function expAdd(expandToo) {
  const hit = tracerLookup($("expSeed").value);
  if (!hit) { $("expStatus").innerHTML = '<span class="error">Pick a metabolite or reaction that exists in this model.</span>'; return; }
  $("expSeed").value = ""; $("expSeedKind").textContent = "";
  await expBusy(async () => {
    const node = await expFetchAndMerge(hit.type, hit.id, expandToo ? "both" : "none", null);
    if (node && expandToo === false) { /* a lone node */ }
    const cy = EXP.cy;
    if (cy && cy.getElementById(hit.id).nonempty()) { cy.getElementById(hit.id).addClass("seed"); expSelect(cy.getElementById(hit.id)); cy.fit(undefined, 40); }
  });
}

async function expFetchAndMerge(kind, id, direction, srcNode) {
  const cy = expEnsureCy();
  if (!cy) return null;
  const res = await fetch("/api/explore-expand", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model_id: MODEL_ID, type: kind, id, direction: direction === "none" ? "both" : direction,
      exclude_trivial_metabolites: $("expHide").checked, currency_metabolites: currencyPayload() }),
  });
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.error || "Expansion failed");
  const source = srcNode || (cy.getElementById(id).nonempty() ? cy.getElementById(id) : null);
  const mode = direction;
  // The node itself is always added; its neighbours only when expanding.
  const reactions = direction === "none" ? data.reactions.filter(r => r.id === id) : data.reactions;
  const metIds = new Set(reactions.flatMap(r => r.mets.map(m => m[0])));
  if (kind === "metabolite") metIds.add(id);
  const mets = data.metabolites.filter(m => metIds.has(m.id));
  expMerge(mets, reactions, source, mode);
  if (srcNode && direction !== "none") {
    srcNode.data(direction === "up" ? "upDone" : direction === "down" ? "downDone" : "upDone", true);
    if (direction === "both") srcNode.data("downDone", true);
    srcNode.data(direction === "down" ? "downFound" : "upFound", data.found);
  }
  if (data.truncated) $("expStatus").innerHTML = `<span class="note">Only the ${reactions.length} most relevant of ${data.found} reactions were added (active first). Expand again from a specific node to see others.</span>`;
  return source;
}

function expMerge(mets, reactions, source, direction) {
  const cy = EXP.cy;
  const sx = source ? source.position("x") : (Math.random() - 0.5) * 400, sy = source ? source.position("y") : (Math.random() - 0.5) * 300;
  const side = direction === "up" ? -1 : direction === "down" ? 1 : 0;
  const comps = [...new Set(cy.nodes("[kind='met']").map(n => n.data("compartment")).concat(mets.map(m => m.compartment)))];
  const color = c => LANE_COLORS[comps.indexOf(c) % LANE_COLORS.length];
  const fresh = reactions.filter(r => cy.getElementById(r.id).empty());
  fresh.forEach((r, i) => {
    const dx = (side || (i % 2 ? 1 : -1)) * 190, dy = (i - (fresh.length - 1) / 2) * 56;
    const { state, flux } = mapReactionState(r, "before");
    cy.add({ data: Object.assign({}, r, { label: (r.essential ? "🔒 " : "") + r.id, kind: "rxn", state, flux }),
      classes: state + (r.essential ? " essential" : ""), position: { x: sx + dx, y: sy + dy } });
  });
  const placed = new Map();
  mets.forEach(m => {
    if (cy.getElementById(m.id).nonempty()) return;
    const home = fresh.find(r => r.mets.some(([id]) => id === m.id));
    const base = home ? cy.getElementById(home.id).position() : { x: sx, y: sy };
    const k = placed.get(home && home.id) || 0; placed.set(home && home.id, k + 1);
    cy.add({ data: Object.assign({}, m, { label: m.name || m.id, kind: "met", laneColor: color(m.compartment) }),
      classes: m.role + (m.dead_end ? " deadend" : ""),
      position: { x: base.x + (side || (base.x >= sx ? 1 : -1)) * 170, y: base.y + (k - 0.5) * 46 } });
  });
  reactions.forEach(r => {
    const { state, flux } = mapReactionState(r, "before");
    mapReactionEdges(r, state, flux).forEach(e => {
      if (cy.getElementById(e.data.id).empty() && cy.getElementById(e.data.source).nonempty() && cy.getElementById(e.data.target).nonempty()) cy.add(e);
    });
  });
  expApplyView();
}

async function expExpand(node, direction) {
  await expFetchAndMerge(node.data("kind") === "rxn" ? "reaction" : "metabolite", node.id(), direction, node);
  expSelect(node);
}

// ---- tests and the break trace ---------------------------------------------
async function expTestMetabolites(nodes) {
  if (!nodes.length) return;
  for (let i = 0; i < nodes.length; i += 100) {
    const chunk = nodes.slice(i, i + 100);
    const res = await fetch("/api/explore-test", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: MODEL_ID, metabolites: chunk.map(n => n.id()) }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Test failed");
    chunk.forEach(n => { const r = data.results[n.id()]; if (r) { n.data("make", r.make); n.data("use", r.use); } });
  }
  expApplyView();
}

const expUntested = () => EXP.cy ? EXP.cy.nodes("[kind='met']").filter(n => n.data("make") === undefined).toArray() : [];

async function expTestAll() {
  if (!EXP.cy) return;
  $("expStatus").textContent = "Testing metabolites…";
  await expTestMetabolites(expUntested());
  const bad = EXP.cy.nodes("[kind='met']").filter(n => n.data("make") === false).length;
  $("expStatus").textContent = `${bad} metabolite(s) cannot be made by the network.`;
}

async function expTraceBreak() {
  if (!EXP.cy) return;
  const dir = $("expBreakDir").value, prop = dir === "up" ? "make" : "use", done = dir === "up" ? "upDone" : "downDone";
  const rounds = Number($("expRounds").value);
  $("expStatus").textContent = "Testing metabolites…";
  await expTestMetabolites(expUntested());
  let round = 0;
  for (; round < rounds; round++) {
    const bad = EXP.cy.nodes("[kind='met']").filter(n => n.data(prop) === false && !n.data(done)).toArray().slice(0, 25);
    if (!bad.length) break;
    for (let i = 0; i < bad.length; i++) {
      $("expStatus").textContent = `Round ${round + 1}/${rounds}: expanding ${bad[i].id()} (${i + 1}/${bad.length})…`;
      await expFetchAndMerge("metabolite", bad[i].id(), dir, bad[i]);
    }
    await expTestMetabolites(expUntested());
    if (EXP.cy.nodes().length > 400) { $("expStatus").textContent = "Stopped: the graph reached 400 nodes."; break; }
  }
  const left = EXP.cy.nodes("[kind='met']").filter(n => n.data(prop) === false);
  $("expFrontier").checked = true; expApplyView();
  $("expStatus").textContent = left.length
    ? `Done after ${round} round(s): ${left.length} metabolite(s) still ${dir === "up" ? "cannot be made" : "cannot be used"} — shown as the problem area. Click one for the diagnosis.`
    : "Everything drawn can be " + (dir === "up" ? "made." : "used.");
  EXP.cy.fit(EXP.cy.elements().not(".xmap-hidden"), 40);
}

async function expBusy(fn) {
  if (EXP.busy) return;
  EXP.busy = true;
  progressStart("expProgress");
  try { $("expStatus").textContent = ""; await fn(); }
  catch (err) { $("expStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`; }
  finally { EXP.busy = false; progressDone("expProgress"); }
}

// ---- view: colours, problem-area filter, layout, search --------------------
function expApplyView() {
  const cy = EXP.cy;
  if (!cy) return;
  const mode = $("expColour").value;
  cy.nodes("[kind='met']").forEach(n => {
    n.removeClass("mk-yes mk-no");
    const v = mode === "role" ? undefined : n.data(mode);
    if (v !== undefined) n.addClass(v ? "mk-yes" : "mk-no");
  });
  cy.elements().removeClass("xmap-hidden");
  if ($("expFrontier").checked) {
    const prop = $("expBreakDir").value === "up" ? "make" : "use";
    const bad = cy.nodes("[kind='met']").filter(n => n.data(prop) === false);
    if (bad.nonempty()) {
      const rxns = bad.neighborhood("node[kind='rxn']"), keep = bad.union(rxns).union(rxns.neighborhood("node[kind='met']"));
      cy.nodes().not(keep).addClass("xmap-hidden");
      cy.edges().filter(e => e.source().hasClass("xmap-hidden") || e.target().hasClass("xmap-hidden")).addClass("xmap-hidden");
    }
  }
  $("expCount").textContent = `${cy.nodes("[kind='met']").not(".xmap-hidden").length} metabolites · ${cy.nodes("[kind='rxn']").not(".xmap-hidden").length} reactions`;
  expFind();
}

function expTidy() {
  const cy = EXP.cy;
  if (!cy || !cy.nodes().length) return;
  const roots = cy.nodes(".seed").map(n => n.id());
  cy.layout($("expLayout").value === "cose"
    ? { name: "cose", animate: false, padding: 24, nodeRepulsion: 9000 }
    : { name: "breadthfirst", roots, directed: true, spacingFactor: 1.15, padding: 24 }).run();
  cy.fit(undefined, 30);
}

function expFind() {
  const cy = EXP.cy, q = $("expFind").value.trim().toLowerCase();
  if (!cy) return;
  cy.nodes().removeClass("hit");
  if (!q) return;
  const hits = cy.nodes().not(".xmap-hidden").filter(n => `${n.id()} ${n.data("name") || ""}`.toLowerCase().includes(q));
  hits.addClass("hit");
  if (hits.length) cy.animate({ fit: { eles: hits, padding: 80 }, duration: 150 });
}

function expAction(act) {
  const cy = EXP.cy;
  if (!cy) return;
  const mid = { x: cy.width() / 2, y: cy.height() / 2 };
  if (act === "in") cy.zoom({ level: cy.zoom() * 1.3, renderedPosition: mid });
  else if (act === "out") cy.zoom({ level: cy.zoom() / 1.3, renderedPosition: mid });
  else if (act === "fit") cy.fit(cy.elements().not(".xmap-hidden"), 30);
  else if (act === "png") { const a = document.createElement("a"); a.href = cy.png({ full: true, scale: 2, bg: "#ffffff" }); a.download = "explorer_graph.png"; a.click(); }
  else if (act === "csv") expCsv();
  else if (act === "clear") { cy.elements().remove(); expApplyView(); $("expSide").innerHTML = '<div class="stoich">Click a node to see its details and expand it.</div>'; $("expStatus").textContent = ""; }
}

function expCsv() {
  const cy = EXP.cy, q = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const head = ["Type", "ID", "Name", "Status / role", "Flux", "FVA min", "FVA max", "Can be made", "Can be used", "Dead end", "Essential", "Equation"];
  const rows = cy.nodes().map(n => { const d = n.data(), r = d.kind === "rxn";
    return [r ? "reaction" : "metabolite", d.id, d.name || "", r ? d.state : d.role, r ? d.flux : "", d.fva ? d.fva[0] : "", d.fva ? d.fva[1] : "",
      d.make ?? "", d.use ?? "", d.dead_end || "", r ? (d.essential ? "yes" : "no") : "", d.equation || ""]; });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([[head, ...rows].map(r => r.map(q).join(",")).join("\n")], { type: "text/csv" }));
  a.download = "explorer_nodes.csv"; a.click(); URL.revokeObjectURL(a.href);
}

// ---- side panel ------------------------------------------------------------
function expDiagnosis(n) {
  const d = n.data();
  if (d.kind === "rxn") {
    const bits = [];
    if (d.fva_blocked || d.state === "blocked") bits.push("This reaction cannot carry flux under the current bounds" + (d.fva_blocked ? " (FVA)" : "") + ". Check whether a substrate is unmakeable or the bounds/direction are too tight.");
    else if (d.state === "inactive") bits.push("Allowed by its bounds but carries no flux in the current solution.");
    if (d.essential) bits.push("Essential: knocking it out stops growth.");
    return bits.join(" ");
  }
  const bits = [];
  if (d.dead_end) bits.push(`Dead end: ${d.dead_end}.`);
  if (d.make === false) bits.push(d.upFound === 0
    ? "Nothing in the model can produce it: add a producing reaction (or a sink/exchange for it)."
    : d.upDone ? "Reactions exist that could produce it, but none can run: follow the red nodes upstream." : "The network cannot make it. Expand upstream to see why.");
  if (d.use === false) bits.push(d.downFound === 0
    ? "Nothing in the model can use it: add a consuming reaction or a demand."
    : d.downDone ? "Reactions exist that could use it, but none can run." : "The network cannot use it. Expand downstream to see why.");
  if (d.make === true && d.use === true) bits.push("The network can make and use it.");
  return bits.join(" ");
}

function expSelect(n) {
  const d = n.data(), isR = d.kind === "rxn";
  const row = (k, v) => v === undefined || v === null || v === "" ? "" : `<div class="exp-kv"><span>${k}</span><span>${v}</span></div>`;
  const yn = v => v === undefined ? "not tested" : v ? "yes" : "no";
  $("expSide").innerHTML = `
    <div class="ent-title">${escapeHtml(d.id)} <span class="stoich">${isR ? "reaction" : "metabolite"}</span></div>
    <div>${escapeHtml(d.name || "")}</div>
    ${isR ? `<div class="ent-eq">${equationHtml(d.equation)}</div>
      ${row("Status", escapeHtml(d.state) + (d.state === "active" ? ` (flux ${fmt(d.flux)})` : ""))}
      ${row("Bounds", `[${fmt(d.lower_bound, 2)}, ${fmt(d.upper_bound, 2)}]`)}
      ${row("FVA range", d.fva ? `[${fmt(d.fva[0], 4)}, ${fmt(d.fva[1], 4)}]` : "not computed")}
      ${row("Subsystem", escapeHtml(d.subsystem))}${row("GPR", escapeHtml(d.genes))}`
    : `${row("Compartment", escapeHtml(d.compartment_name || d.compartment))}${row("Formula", escapeHtml(d.formula))}
      ${row("Can be made", yn(d.make))}${row("Can be used", yn(d.use))}${row("Dead end", escapeHtml(d.dead_end || (d.dead_end === undefined ? "" : "no")))}`}
    <div class="exp-diag">${escapeHtml(expDiagnosis(n))}</div>
    <div class="exp-actions">
      <button type="button" data-d="up" title="${isR ? "What makes its substrates" : "Reactions that can make it"}">↑ Upstream</button>
      <button type="button" data-d="down" title="${isR ? "What uses its products" : "Reactions that can use it"}">↓ Downstream</button>
      <button type="button" data-d="both">↕ Both</button>
      ${isR ? "" : '<button type="button" class="secondary" data-t="1">Test this</button>'}
      <button type="button" class="secondary" data-r="1">Remove</button>
    </div>`;
  const side = $("expSide");
  side.querySelectorAll("[data-d]").forEach(b => b.addEventListener("click", () => expBusy(() => expExpand(n, b.dataset.d))));
  const t = side.querySelector("[data-t]");
  if (t) t.addEventListener("click", () => expBusy(async () => { await expTestMetabolites([n]); expSelect(n); }));
  side.querySelector("[data-r]").addEventListener("click", () => {
    const cy = EXP.cy;
    n.remove();
    cy.nodes().filter(x => x.connectedEdges().empty() && !x.hasClass("seed")).remove();  // orphans left behind
    expApplyView();
    side.innerHTML = '<div class="stoich">Node removed.</div>';
  });
}
