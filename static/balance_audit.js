// ---------------------------------------------------------------------------
// Diagnostics: Balance Audit tab.
// For every unbalanced reaction (and optionally every reaction that can't be
// checked for lack of formulas): the suggested fix, which metabolites to
// check, and each metabolite's MetaNetX id and ids in BiGG / VMH / ModelSEED /
// KEGG / MetaCyc. Lists can be copied or downloaded; the Excel file has it all.
// Loaded after app.js and list_export.js.
// ---------------------------------------------------------------------------
let AUDIT_RESULT = null;

const AUDIT_PREVIEW_LIMIT = 300;

const AUDIT_REACTION_COLUMNS = [
  { key: "id", label: "Reaction id" },
  { key: "name", label: "Name" },
  { key: "status", label: "Status" },
  { key: "imbalance", label: "Imbalance" },
  { key: "suggestion", label: "Suggested fix" },
  { key: "suggestion_type", label: "Fix type" },
  { label: "Fix verified", value: r => (r.verified ? "yes" : "no") },
  { key: "other_suggestions", label: "Other suggestions" },
  { key: "metabolites_to_check", label: "Metabolites to check" },
  { key: "metabolite_mapping", label: "Metabolite mapping (id -> MetaNetX -> databases)" },
  { key: "reaction", label: "Reaction" },
];

function auditMetaboliteColumns(databases) {
  return [
    { key: "reaction_id", label: "Reaction id" }, { key: "metabolite_id", label: "Metabolite id" }, { key: "name", label: "Name" },
    { key: "coefficient", label: "Coefficient" }, { key: "compartment", label: "Compartment" },
    { key: "formula", label: "Formula" }, { key: "charge", label: "Charge" },
    { key: "metanetx_id", label: "MetaNetX id" }, { key: "reference_formula", label: "Reference formula" },
    { key: "reference_charge", label: "Reference charge" },
    { key: "formula_check", label: "Formula check" }, { key: "mapping_check", label: "Mapping check" },
    ...databases.map(d => ({ key: d, label: d })),
  ];
}

function renderBalanceAudit() {
  AUDIT_RESULT = null;
  $("balanceaudit").innerHTML = `
    <h2>Unbalanced reaction audit</h2>
    <div class="note">
      For each unbalanced reaction this checks the metabolites' original mapping (MetaNetX id and the ids in BiGG, VMH,
      ModelSEED, KEGG and MetaCyc), checks each formula and charge (against the MetaNetX reference when
      <code>data/chem_prop.tsv</code> is present, and against the same compound in other compartments), and suggests a fix.
      Every suggestion is verified by recomputing the balance. Nothing in the model is changed.
    </div>
    <div class="toolbar">
      <label><input id="auditUnknown" type="checkbox" checked> also audit reactions that can't be checked (missing formulas)</label>
      <button id="auditRunBtn" type="button">Audit unbalanced reactions</button>
    </div>
    <div id="auditStatus" class="debug-status"></div>
    <div id="auditResults"></div>
  `;
  $("auditRunBtn").addEventListener("click", runBalanceAudit);
}

async function runBalanceAudit() {
  if (!MODEL_ID) { $("auditStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`; return; }
  $("auditRunBtn").disabled = true;
  $("auditStatus").textContent = "Auditing reactions…";
  $("auditResults").innerHTML = "";
  try {
    const res = await fetch("/api/balance-audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: MODEL_ID, include_unknown: $("auditUnknown").checked }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Audit failed");
    AUDIT_RESULT = data;
    $("auditStatus").textContent = "";
    drawBalanceAudit();
  } catch (err) {
    $("auditStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
  } finally {
    $("auditRunBtn").disabled = false;
  }
}

function drawBalanceAudit() {
  const r = AUDIT_RESULT;
  if (!r) return;
  const c = r.counts;
  const cards = [["Unbalanced", c.unbalanced, "bad"], ["Can't check", c.unknown, "warn"], ["Audited", c.audited, ""], ["Fix verified", c.with_verified_fix, "good"]];
  const root = $("auditResults");
  const metColumns = auditMetaboliteColumns(r.databases);
  root.innerHTML = `
    <div class="note">${escapeHtml(r.note)}</div>
    <div class="toolbar">${cards.map(([label, n, cls]) => `<span class="badge ${cls}">${label}: ${n}</span>`).join(" ")}</div>
    ${r.reactions.length ? `
      <div class="toolbar">
        <strong>Reactions &amp; suggested fixes</strong>
        ${exportButtonsHtml("reactions")}
        <a href="/api/balance-audit/${encodeURIComponent(MODEL_ID)}/report" download><button type="button" style="background:var(--accent);color:#fff;">Download Excel (.xlsx)</button></a>
      </div>
      ${previewTableHtml(AUDIT_REACTION_COLUMNS, r.reactions, AUDIT_PREVIEW_LIMIT)}
      <details class="memote-issue">
        <summary><strong>Metabolite details</strong><span class="badge">${r.metabolites.length}</span><span class="stoich">formula check and database ids for every metabolite of these reactions</span></summary>
        <div class="memote-issue-body">
          <div class="toolbar">${exportButtonsHtml("metabolites")}</div>
          ${previewTableHtml(metColumns, r.metabolites, AUDIT_PREVIEW_LIMIT)}
        </div>
      </details>` : `<p>No unbalanced reactions to audit.</p>`}`;
  wireExportButtons(root, key => key === "reactions"
    ? { filename: "unbalanced_reaction_audit.csv", columns: AUDIT_REACTION_COLUMNS, rows: AUDIT_RESULT.reactions }
    : { filename: "unbalanced_reaction_metabolites.csv", columns: metColumns, rows: AUDIT_RESULT.metabolites });
}
