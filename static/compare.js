// ---------------------------------------------------------------------------
// Debugging Toolkit: Compare Models tab.
// Compares the loaded model (A) with a second uploaded model (B): naming
// conventions first, then genes / metabolites / reactions / biomass components
// split into shared and only-in-one lists, each exportable (ids + MetaNetX ids).
// Loaded after app.js and list_export.js.
// ---------------------------------------------------------------------------
let COMPARE_RESULT = null;

const COMPARE_PREVIEW_LIMIT = 200;

const COMPARE_SECTIONS = [
  { key: "genes", title: "Genes" },
  { key: "metabolites", title: "Metabolites" },
  { key: "reactions", title: "Reactions" },
  { key: "biomass", title: "Biomass components" },
];

function renderModelCompare() {
  COMPARE_RESULT = null;
  $("compare").innerHTML = `
    <h2>Compare models</h2>
    <div class="note">
      Compare the loaded model (<strong>A</strong>) with a second model (<strong>B</strong>). The naming conventions
      of both models are reported first, then genes, metabolites, reactions and biomass components are split into
      what both models share and what is only in one of them. Items are matched by identical id first, then by
      MetaNetX id, then (metabolites) by id without its compartment tag and (reactions) by identical equation.
      Paired reactions are also checked for different flux bounds and stoichiometric coefficients, and paired
      biomass components for different coefficients. Nothing is changed in either model.
    </div>
    <div class="toolbar">
      <label for="compareFile">Model B</label>
      <input id="compareFile" type="file" accept=".xml,.sbml,.json,.yml,.yaml,.mat,.gz,.zip,.bz2">
      <button id="compareRunBtn" type="button" disabled>Compare models</button>
    </div>
    <div id="compareStatus" class="debug-status"></div>
    <div id="compareResults"></div>
  `;
  $("compareFile").addEventListener("change", () => { $("compareRunBtn").disabled = !$("compareFile").files[0]; });
  $("compareRunBtn").addEventListener("click", runModelCompare);
}

async function runModelCompare() {
  const file = $("compareFile").files[0];
  if (!file) return;
  if (!MODEL_ID) { $("compareStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`; return; }

  $("compareRunBtn").disabled = true;
  $("compareStatus").textContent = "Comparing the two models…";
  $("compareResults").innerHTML = "";
  try {
    const form = new FormData();
    form.append("model_id", MODEL_ID);
    form.append("model_b", file);
    const res = await fetch("/api/compare-models", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Comparison failed");
    COMPARE_RESULT = data;
    $("compareStatus").textContent = "";
    drawModelCompare();
  } catch (err) {
    $("compareStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
  } finally {
    $("compareRunBtn").disabled = false;
  }
}

// --- Columns ---------------------------------------------------------------

const COMPARE_MNX_COLUMN = { key: "metanetx_id", label: "MetaNetX id" };
const COMPARE_NAME_COLUMN = { key: "name", label: "Name" };

function compareColumns(sectionKey, group) {
  const idA = { key: "id_a", label: "Model A id" };
  const idB = { key: "id_b", label: "Model B id" };
  const tail = sectionKey === "genes" ? [COMPARE_NAME_COLUMN] : [COMPARE_MNX_COLUMN, COMPARE_NAME_COLUMN];
  if (group === "only_a") return [idA, ...tail];
  if (group === "only_b") return [idB, ...tail];
  const cols = [idA, idB, ...tail, { key: "matched_by", label: "Matched by" }];
  if (sectionKey === "reactions") {
    cols.push({ key: "lb_a", label: "Lower bound A" }, { key: "ub_a", label: "Upper bound A" },
      { key: "lb_b", label: "Lower bound B" }, { key: "ub_b", label: "Upper bound B" },
      { key: "differences", label: "Differences" });
  }
  if (sectionKey === "biomass") {
    cols.push({ key: "coefficient_a", label: "Coefficient A" }, { key: "coefficient_b", label: "Coefficient B" },
      { label: "Differs", value: r => (r.coefficient_a !== r.coefficient_b ? "yes" : "") });
  }
  return cols;
}

// --- Drawing ---------------------------------------------------------------

function compareNamingCell(info) {
  const cov = info.coverage ? ` · ${(info.coverage * 100).toFixed(0)}% of ids` : "";
  const ex = info.example ? `<div class="stoich">e.g. ${escapeHtml(info.example)}${cov}</div>` : "";
  return `<strong>${escapeHtml(info.label)}</strong>${ex}`;
}

function compareConsistencyBadge(consistent) {
  if (consistent === true) return `<span class="badge good">consistent</span>`;
  if (consistent === false) return `<span class="badge bad">differs</span>`;
  return `<span class="badge warn" title="Neither model's ids were recognized, so this can't be confirmed">can't tell</span>`;
}

function compareNamingHtml(naming) {
  const verdict = naming.any_inconsistent
    ? `<div class="note">The two models use <strong>different conventions</strong>. Identical-id matching will miss items, so matching falls back to MetaNetX ids and compartment-stripped ids.</div>`
    : naming.all_consistent
      ? `<div class="note" style="background:#ecfdf5;border-color:#a7f3d0;color:#047857;">Both models use the same naming conventions.</div>`
      : `<div class="note">Some conventions could not be recognized in either model, so consistency can't be confirmed for them.</div>`;
  return `
    <h3>Naming conventions</h3>
    ${verdict}
    <div class="table-wrap" style="max-height:none;"><table>
      <thead><tr><th></th><th>Model A: ${escapeHtml(COMPARE_RESULT.labels.a)}</th><th>Model B: ${escapeHtml(COMPARE_RESULT.labels.b)}</th><th>Consistent?</th></tr></thead>
      <tbody>${naming.rows.map(r => `<tr><td>${escapeHtml(r.aspect)}</td><td>${compareNamingCell(r.model_a)}</td><td>${compareNamingCell(r.model_b)}</td><td>${compareConsistencyBadge(r.consistent)}</td></tr>`).join("")}</tbody>
    </table></div>`;
}

function compareSummaryHtml(result) {
  const rows = COMPARE_SECTIONS.filter(s => result[s.key].counts).map(s => {
    const c = result[s.key].counts;
    return `<tr><td>${s.title}</td><td>${c.total_a}</td><td><strong>${c.shared}</strong></td><td>${c.only_a}</td><td>${c.only_b}</td><td>${c.total_b}</td><td>${c.differ === undefined ? "" : `<strong>${c.differ}</strong>`}</td></tr>`;
  }).join("");
  return `
    <h3>Summary</h3>
    <div class="table-wrap" style="max-height:none;"><table>
      <thead><tr><th></th><th>In model A</th><th>Shared</th><th>Only in A</th><th>Only in B</th><th>In model B</th><th>Shared, but differ</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function compareGroupHtml(sectionKey, group, label, rows, columnGroup) {
  const columns = compareColumns(sectionKey, columnGroup || group);
  return `
    <details class="memote-issue">
      <summary><strong>${escapeHtml(label)}</strong><span class="badge">${rows.length}</span></summary>
      <div class="memote-issue-body">
        ${rows.length ? `<div class="toolbar">${exportButtonsHtml(`${sectionKey}:${group}`)}</div>${previewTableHtml(columns, rows, COMPARE_PREVIEW_LIMIT)}` : "Nothing in this group."}
      </div>
    </details>`;
}

function compareBiomassHeaderHtml(b) {
  const one = (side, r) => r
    ? `<div><strong>Model ${side}:</strong> ${escapeHtml(r.id)} <span class="stoich">${escapeHtml(r.name)} · ${r.n_components} metabolites</span></div>`
    : `<div><strong>Model ${side}:</strong> not found</div>`;
  return `<div class="note" style="background:#f8fafc;border-color:var(--line);color:var(--text);">${one("A", b.reaction_a)}${one("B", b.reaction_b)}${b.error ? `<div class="error">${escapeHtml(b.error)}</div>` : ""}</div>`;
}

function compareSectionHtml(result, section) {
  const data = result[section.key];
  const header = section.key === "biomass" ? compareBiomassHeaderHtml(data) : "";
  if (!data.counts) return `<h3>${section.title}</h3>${header}`;
  return `
    <h3>${section.title}</h3>
    ${header}
    ${compareGroupHtml(section.key, "shared", `In both models`, data.shared)}
    ${data.differ ? compareGroupHtml(section.key, "differ", `In both, but bounds or coefficients differ`, data.differ, "shared") : ""}
    ${compareGroupHtml(section.key, "only_a", `Only in model A`, data.only_a)}
    ${compareGroupHtml(section.key, "only_b", `Only in model B`, data.only_b)}`;
}

function compareReportButtonsHtml() {
  const base = `/api/compare-models/${encodeURIComponent(MODEL_ID)}/report`;
  return `<div class="toolbar">
    <strong>Comparison report:</strong>
    <a href="${base}?format=xlsx" download><button type="button" style="background:var(--accent);color:#fff;">Download Excel (.xlsx)</button></a>
    <a href="${base}?format=html" download><button type="button">Download HTML</button></a>
  </div>`;
}

function drawModelCompare() {
  const r = COMPARE_RESULT;
  if (!r) return;
  const root = $("compareResults");
  root.innerHTML = [compareReportButtonsHtml(), compareNamingHtml(r.naming), compareSummaryHtml(r), ...COMPARE_SECTIONS.map(s => compareSectionHtml(r, s))].join("");
  wireExportButtons(root, key => {
    const [sectionKey, group] = key.split(":");
    return {
      filename: `model_comparison_${sectionKey}_${group}.csv`,
      columns: compareColumns(sectionKey, group === "differ" ? "shared" : group),
      rows: COMPARE_RESULT[sectionKey][group],
    };
  });
}
