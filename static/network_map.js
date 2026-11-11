// ---------------------------------------------------------------------------
// Shared network map (Cytoscape) used by Exchange Debugging and the Pathway
// Tracer. Metabolites are circles, reactions are rounded boxes; arrows follow
// the flux (or the written equation when there is none). It also draws the
// "reactions in the map" table with CSV download.
//
//   const map = createNetworkMap("xmap");
//   map.render(element, { map, hasKo, koNote, knocked: [ids], csvName, extraNote });
//
// `map` is the body built by debugging/map_graph.py. Loaded before the tabs
// that use it; needs cytoscape (static/vendor) at draw time only.
// ---------------------------------------------------------------------------
const FLUX_EPS = 1e-9;
const LANE_COLORS = ["#2563eb", "#16a34a", "#d97706", "#9333ea", "#dc2626", "#0891b2", "#be185d", "#4d7c0f"];
const LANE_RANK = { c: 0, p: 1, e: 2 };

// Status of a reaction in the displayed state ("before" or "after" the knockout).
function mapReactionState(r, mode) {
  const flux = mode === "after" ? (r.flux_after || 0) : r.flux_before;
  if (Math.abs(flux) > FLUX_EPS) return { state: "active", flux };
  return { state: r.blocked ? "blocked" : "inactive", flux: 0 };
}

function mapPathsHtml(paths, title) {
  return paths.map((p, i) => `<div class="debug-path"><div class="debug-path-title">${title} ${i + 1}</div>
    <div class="debug-met">${escapeHtml(p.metabolites[0].name || p.metabolites[0].id)} <span class="stoich">${escapeHtml(p.metabolites[0].id)}</span></div>
    ${p.reactions.map((rxn, idx) => { const met = p.metabolites[idx + 1]; return `<div class="debug-step">
      <span class="debug-arrow">↓</span> <span class="badge">${escapeHtml(rxn.id)}</span> flux=${fmt(rxn.flux)}
      <div class="debug-met">→ ${escapeHtml(met.name || met.id)} <span class="stoich">${escapeHtml(met.id)}</span></div></div>`; }).join("")}
  </div>`).join("");
}

const MAP_COLUMNS = [
  ["Reaction", r => r.id], ["Name", r => r.name], ["Equation", r => r.equation], ["Subsystem", r => r.subsystem],
  ["Hop", r => r.primary ? "route" : r.extra ? "added" : r.hop], ["Status", (r, s) => s.state], ["Flux", (r, s) => s.flux],
  ["Lower bound", r => r.lower_bound], ["Upper bound", r => r.upper_bound], ["Genes", r => r.genes],
];
const MAP_HOP_COL = 4, MAP_FLUX_COL = 6;

function createNetworkMap(p) {
  const S = { cy: null, mode: "before", data: null, opts: null, root: null };
  const el = id => S.root.querySelector(`#${p}${id}`);

  function render(root, opts) {
    S.root = root; S.opts = opts; S.data = opts.map; S.mode = "before";
    const m = S.data, lanes = new Set(m.metabolites.map(x => x.compartment)).size > 1;
    root.innerHTML = `
      ${m.truncated ? `<div class="note">The neighbourhood was cut at ${m.max_reactions} reactions (active ones kept first). Lower the hops or hide more cofactors to see all of it.</div>` : ""}
      ${opts.extraNote || ""}
      <div class="tracer-network-toolbar">
        ${opts.hasKo ? `<label class="debug-toggle"><input type="radio" name="${p}Mode" value="before" checked> Before knockout</label>
        <label class="debug-toggle"><input type="radio" name="${p}Mode" value="after"> After knockout</label>` : ""}
        <label class="debug-toggle"><input type="checkbox" id="${p}ShowInactive" checked> Show inactive reactions</label>
        <select id="${p}Layout"><option value="cose">Layout: clustered</option><option value="breadthfirst">Layout: tree</option>
          ${lanes ? '<option value="lanes">Layout: compartment lanes</option>' : ""}</select>
        <input type="text" id="${p}Find" placeholder="Find a node…" class="map-find">
        <span id="${p}Count" class="stoich"></span>
      </div>
      <div class="tracer-cy-wrap"><div id="${p}Cy" class="tracer-cy-container"></div></div>
      <div class="tracer-legend xmap-legend">
        ${opts.legendHtml || ""}
        <span><i class="xmap-sq xmap-sq-primary"></i> Route reaction</span>
        <span><i class="xmap-sq xmap-sq-active"></i> Other active</span>
        <span><i class="xmap-sq xmap-sq-inactive"></i> Inactive</span>
        <span><i class="xmap-sq xmap-sq-blocked"></i> Blocked (both bounds 0)</span>
        ${opts.hasKo ? '<span><i class="xmap-sq xmap-sq-lost"></i> Active → inactive after KO</span><span><i class="xmap-sq xmap-sq-gain"></i> Inactive → active after KO</span>' : ""}
        <span class="stoich">Two-headed arrow: reversible reaction with no flux. Hover for details.</span>
      </div>
      <h4>Reactions in the map
        <label class="debug-toggle"><input type="checkbox" id="${p}Biomass"> Include biomass reaction</label>
        <button type="button" class="secondary" id="${p}Csv">Download CSV</button></h4>
      <div id="${p}Table"></div>`;
    root.querySelectorAll(`input[name="${p}Mode"]`).forEach(r => r.addEventListener("change", () => {
      S.mode = r.value; draw(); drawTable();
    }));
    el("ShowInactive").addEventListener("change", applyVisibility);
    el("Layout").addEventListener("change", layout);
    el("Find").addEventListener("input", highlight);
    el("Biomass").addEventListener("change", drawTable);
    el("Csv").addEventListener("click", downloadCsv);
    if (opts.koNote) { const a = root.querySelector(`input[name="${p}Mode"][value="after"]`); if (a) a.title = opts.koNote; }
    draw(); drawTable();
  }

  function draw() {
    if (typeof cytoscape === "undefined") {
      el("Cy").innerHTML = `<div class="note error">The network library did not load (static/vendor/cytoscape.min.js). Reload the page with Ctrl+F5; if it persists, open /static/vendor/cytoscape.min.js in the browser to see why.</div>`;
      return;
    }
    const m = S.data, mode = S.mode, knocked = new Set(S.opts.knocked || []);
    const comps = [...new Set(m.metabolites.map(x => x.compartment))];
    const color = c => LANE_COLORS[comps.indexOf(c) % LANE_COLORS.length];
    const els = [];
    m.metabolites.forEach(x => els.push({
      data: Object.assign({}, x, { label: x.name || x.id, kind: "met", laneColor: color(x.compartment) }), classes: x.role }));
    m.reactions.forEach(r => {
      const { state, flux } = mapReactionState(r, mode);
      const wasActive = Math.abs(r.flux_before) > FLUX_EPS;
      const delta = mode !== "after" ? "" : wasActive && state !== "active" ? "lost" : !wasActive && state === "active" ? "gain" : "";
      const cls = [state, r.primary ? "primary" : "", r.extra ? "extra" : "", delta, mode === "after" && knocked.has(r.id) ? "knocked" : ""].join(" ");
      els.push({ data: Object.assign({}, r, { label: r.id, kind: "rxn", state, flux }), classes: cls });
      r.mets.forEach(([mid, coeff]) => {
        // Direction follows the flux when there is one, otherwise the written equation.
        const substrate = state === "active" ? (coeff < 0) === (flux > 0) : coeff < 0;
        const both = state !== "active" && r.reversible;
        els.push({
          data: { id: `${r.id}|${mid}`, source: substrate ? mid : r.id, target: substrate ? r.id : mid, state, coeff },
          classes: `${state}${r.primary ? " primary" : ""}${both ? " both" : ""}`,
        });
      });
    });
    if (S.cy) S.cy.destroy();
    S.cy = cytoscape({ container: el("Cy"), elements: els, wheelSensitivity: 0.25, maxZoom: 2.5, style: MAP_STYLE });
    layout();
    applyVisibility();
    attachTooltips(S.cy);
  }

  function layout() {
    const how = el("Layout").value, cy = S.cy;
    const roots = S.data.metabolites.filter(x => x.role === "start").map(x => x.id);
    if (how === "breadthfirst") {
      cy.layout({ name: "breadthfirst", roots, directed: true, spacingFactor: 1.15, padding: 24 }).run();
    } else if (how === "lanes") {
      cy.layout({ name: "cose", animate: false, padding: 24, nodeRepulsion: 9000 }).run();
      // One column per compartment (cytosol, periplasm, extracellular); reactions sit at the mean of their metabolites.
      const comps = [...new Set(S.data.metabolites.map(x => x.compartment))]
        .sort((a, b) => (LANE_RANK[a] ?? 1) - (LANE_RANK[b] ?? 1) || a.localeCompare(b));
      const X = c => comps.indexOf(c) * 420;
      cy.nodes("[kind='met']").forEach(n => n.position({ x: X(n.data("compartment")) + n.position("x") % 180, y: n.position("y") * 1.4 }));
      cy.nodes("[kind='rxn']").forEach(n => {
        const nb = n.neighborhood("node"); let sx = 0;
        nb.forEach(q => { sx += q.position("x"); });
        n.position({ x: nb.length ? sx / nb.length : 0, y: n.position("y") * 1.4 });
      });
      cy.fit(undefined, 24);
    } else {
      cy.layout({ name: "cose", animate: false, padding: 24, nodeRepulsion: 9000 }).run();
    }
    cy.fit(undefined, 24);
  }

  function applyVisibility() {
    const cy = S.cy, showInactive = el("ShowInactive").checked;
    cy.elements().removeClass("xmap-hidden");
    if (!showInactive) {
      cy.nodes("[kind='rxn']").filter(n => n.data("state") !== "active").forEach(n => n.addClass("xmap-hidden"));
      cy.edges().filter(e => e.data("state") !== "active").addClass("xmap-hidden");
      cy.nodes("[kind='met']").filter(n => n.connectedEdges().not(".xmap-hidden").empty() && n.data("role") === "neighbour").addClass("xmap-hidden");
    }
    const rx = cy.nodes("[kind='rxn']").not(".xmap-hidden").length, mt = cy.nodes("[kind='met']").not(".xmap-hidden").length;
    el("Count").textContent = `${mt} metabolites · ${rx} reactions`;
    highlight();
  }

  function highlight() {
    const q = el("Find").value.trim().toLowerCase(), cy = S.cy;
    cy.nodes().removeClass("hit");
    if (!q) return;
    const hits = cy.nodes().not(".xmap-hidden").filter(n => `${n.data("id")} ${n.data("name") || ""}`.toLowerCase().includes(q));
    hits.addClass("hit");
    if (hits.length) cy.animate({ fit: { eles: hits, padding: 80 }, duration: 150 });
  }

  function attachTooltips(cy) {
    const metHtml = d => `<div class="tooltip-title">${escapeHtml(d.name || d.id)}</div>
      <div class="tooltip-row"><span class="tooltip-label">ID</span><code>${escapeHtml(d.id)}</code></div>
      <div class="tooltip-row"><span class="tooltip-label">Compartment</span>${escapeHtml(d.compartment_name || d.compartment || "—")}</div>
      <div class="tooltip-row"><span class="tooltip-label">Formula</span>${escapeHtml(d.formula || "—")}</div>`;
    const rxnHtml = d => `<div class="tooltip-title">${escapeHtml(d.id)}${d.name ? ` — ${escapeHtml(d.name)}` : ""}</div>
      <div class="tooltip-row"><span class="tooltip-label">Reaction</span><code>${escapeHtml(d.equation || "—")}</code></div>
      <div class="tooltip-row"><span class="tooltip-label">Status</span>${escapeHtml(d.state)} (flux ${fmt(d.flux)})</div>
      <div class="tooltip-row"><span class="tooltip-label">Bounds</span>[${fmt(d.lower_bound, 2)}, ${fmt(d.upper_bound, 2)}]</div>
      <div class="tooltip-row"><span class="tooltip-label">Subsystem</span>${escapeHtml(d.subsystem || "—")}</div>
      <div class="tooltip-row"><span class="tooltip-label">GPR</span>${escapeHtml(d.genes || "—")}</div>
      ${d.hidden_mets && d.hidden_mets.length ? `<div class="tooltip-row"><span class="tooltip-label">Also uses</span>${escapeHtml(d.hidden_mets.join(", "))}</div>` : ""}`;
    cy.on("mouseover", "node", ev => {
      const o = ev.originalEvent;
      showTooltip((ev.target.data("kind") === "rxn" ? rxnHtml : metHtml)(ev.target.data()), o ? o.clientX : 0, o ? o.clientY : 0);
    });
    cy.on("mousemove", "node", ev => { const o = ev.originalEvent; if (o) positionTooltip(o.clientX, o.clientY); });
    cy.on("mouseout", "node", () => hideTooltip());
    cy.on("pan zoom drag", () => hideTooltip());
    cy.container().addEventListener("mouseleave", () => hideTooltip());
  }

  function rows() {
    const withBiomass = el("Biomass").checked;
    return S.data.reactions.filter(r => withBiomass || !r.biomass)
      .map(r => MAP_COLUMNS.map(([, f]) => f(r, mapReactionState(r, S.mode))))
      .sort((a, b) => (a[MAP_HOP_COL] === "route" ? -1 : a[MAP_HOP_COL] === "added" ? 0 : a[MAP_HOP_COL])
                    - (b[MAP_HOP_COL] === "route" ? -1 : b[MAP_HOP_COL] === "added" ? 0 : b[MAP_HOP_COL]));
  }

  function drawTable() {
    el("Table").innerHTML = `<div class="table-scroll"><table class="map-table"><thead><tr>${MAP_COLUMNS.map(([h]) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows().map(r => `<tr>${r.map((v, i) => `<td class="${i === 2 ? "map-eq map-wrap" : [1, 3, 9].includes(i) ? "map-wrap" : ""}">${escapeHtml(i === MAP_FLUX_COL ? fmt(v) : v ?? "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  }

  function downloadCsv() {
    const q = v => `"${String(v ?? "").replace(/"/g, '""')}"`;
    const csv = [MAP_COLUMNS.map(([h]) => h), ...rows()].map(r => r.map(q).join(",")).join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `${S.opts.csvName || p}_${S.mode}_ko_neighbourhood.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function destroy() { if (S.cy) { S.cy.destroy(); S.cy = null; } }
  return { render, destroy };
}

const MAP_STYLE = [
  { selector: "node", style: { label: "data(label)", "font-size": 9, "text-valign": "bottom", "text-margin-y": 4,
      "text-wrap": "ellipsis", "text-max-width": "80px", width: 24, height: 24, "background-color": "#e2e8f0",
      "border-width": 3, "border-color": "data(laneColor)" } },
  { selector: "node.primary", style: { "background-color": "#64748b" } },
  { selector: "node.start", style: { "background-color": "#2563eb", width: 32, height: 32 } },
  { selector: "node.target", style: { "background-color": "#f59e0b", width: 32, height: 32 } },
  { selector: "node[kind='rxn']", style: { shape: "round-rectangle", width: 34, height: 16, "border-width": 1.5, "border-color": "#94a3b8",
      "background-color": "#fff", "font-size": 8, "text-valign": "center", "text-margin-y": 0, "text-max-width": "34px" } },
  { selector: "node[kind='rxn'].active", style: { "background-color": "#dcfce7", "border-color": "#16a34a" } },
  { selector: "node[kind='rxn'].primary", style: { "background-color": "#dbeafe", "border-color": "#2563eb", "border-width": 3 } },
  { selector: "node[kind='rxn'].extra", style: { "border-color": "#7c3aed", "border-width": 3 } },
  { selector: "node[kind='rxn'].inactive", style: { "background-color": "#f1f5f9", "border-color": "#94a3b8", color: "#64748b" } },
  { selector: "node[kind='rxn'].blocked", style: { "background-color": "#fef2f2", "border-color": "#dc2626", "border-style": "dashed", color: "#b91c1c" } },
  { selector: "node[kind='rxn'].lost", style: { "background-color": "#fee2e2", "border-color": "#dc2626", "border-width": 3 } },
  { selector: "node[kind='rxn'].gain", style: { "background-color": "#fef9c3", "border-color": "#ca8a04", "border-width": 3 } },
  { selector: "node.knocked", style: { "border-color": "#dc2626", "border-width": 4, "border-style": "double" } },
  { selector: "node.hit", style: { "overlay-color": "#facc15", "overlay-opacity": 0.5, "overlay-padding": 8 } },
  { selector: "edge", style: { width: 1.5, "line-color": "#cbd5e1", "target-arrow-color": "#cbd5e1", "target-arrow-shape": "triangle", "curve-style": "bezier" } },
  { selector: "edge.active", style: { width: 3, "line-color": "#16a34a", "target-arrow-color": "#16a34a" } },
  { selector: "edge.active.primary", style: { width: 4.5, "line-color": "#2563eb", "target-arrow-color": "#2563eb" } },
  { selector: "edge.blocked", style: { "line-style": "dashed", "line-color": "#fca5a5", "target-arrow-color": "#fca5a5" } },
  { selector: "edge.both", style: { "source-arrow-shape": "triangle", "source-arrow-color": "#cbd5e1" } },
  { selector: ".xmap-hidden", style: { display: "none" } },
];
MAP_STYLE.push(
  { selector: "edge.primary:not(.active)", style: { width: 3, "line-color": "#93c5fd", "target-arrow-color": "#93c5fd" } },
  { selector: "node[kind='rxn'].primary.inactive", style: { "background-color": "#eff6ff", color: "#1d4ed8" } },
);
