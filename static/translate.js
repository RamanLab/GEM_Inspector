// ---------------------------------------------------------------------------
// Annotation & Translation: id translation tabs.
// createTranslatePanel() builds one tab that runs a translation of the loaded
// model, reports what was mapped / errored / has no available mapping (each
// list copyable or downloadable), and offers the translated model together
// with the report for download. This file defines the SEED -> VMH tab;
// metanetx_translate.js builds the "via MetaNetX" tab from the same factory.
// Loaded after app.js and list_export.js.
// ---------------------------------------------------------------------------
const TRANSLATE_PREVIEW_LIMIT = 200;

/* cfg: {
     panelId, key,                  // panel element id; prefix for generated element ids
     title, introHtml, controlsHtml, // header, explanation, extra controls (before the run button)
     runLabel, endpoint, downloadBase,
     requestBody(): object,         // POST body (model_id is added)
     groups: [{key, label, hint, file, columns}]
   } */
function createTranslatePanel(cfg) {
  let result = null;
  const id = name => `${cfg.key}${name}`;

  function render() {
    result = null;
    $(cfg.panelId).innerHTML = `
      <h2>${cfg.title}</h2>
      <div class="note">${cfg.introHtml}</div>
      <div class="toolbar">
        ${cfg.controlsHtml}
        <button id="${id("RunBtn")}" type="button">${cfg.runLabel}</button>
      </div>
      <div id="${id("Status")}" class="debug-status"></div>
      <div id="${id("Results")}"></div>
    `;
    $(id("RunBtn")).addEventListener("click", run);
  }

  async function run() {
    if (!MODEL_ID) { $(id("Status")).innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`; return; }
    $(id("RunBtn")).disabled = true;
    $(id("Status")).textContent = "Translating ids…";
    $(id("Results")).innerHTML = "";
    try {
      const res = await fetch(cfg.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: MODEL_ID, ...cfg.requestBody() }),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || "Translation failed");
      result = data;
      $(id("Status")).textContent = "";
      draw();
    } catch (err) {
      $(id("Status")).innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    } finally {
      $(id("RunBtn")).disabled = false;
    }
  }

  function countsHtml(r) {
    const row = (label, c) => `<tr><td>${label}</td><td>${c.total}</td><td><span class="badge good">${c.mapped}</span></td><td><span class="badge bad">${c.errors}</span></td><td><span class="badge warn">${c.unmapped}</span></td></tr>`;
    const ns = (label, side) => `${escapeHtml(side.label)} (${(side.coverage * 100).toFixed(0)}%)`;
    const before = r.before ? `Namespace before: metabolites <strong>${ns("", r.before.metabolites)}</strong>, reactions <strong>${ns("", r.before.reactions)}</strong>. ` : "";
    return `
      <div class="table-wrap" style="max-height:none;"><table>
        <thead><tr><th></th><th>Total</th><th>Mapped</th><th>Errors</th><th>No available mapping</th></tr></thead>
        <tbody>${row("Metabolites", r.counts.metabolites)}${row("Reactions", r.counts.reactions)}</tbody>
      </table></div>
      <div class="stoich" style="margin:8px 0 14px;">${before}Namespace of the translated model: metabolites <strong>${ns("", r.after.metabolites)}</strong>, reactions <strong>${ns("", r.after.reactions)}</strong>.</div>`;
  }

  function downloadsHtml() {
    const base = `${cfg.downloadBase}/${encodeURIComponent(MODEL_ID)}/download`;
    const link = (what, label, primary) => `<a href="${base}?what=${what}" download><button type="button"${primary ? ' style="background:var(--accent);color:#fff;"' : ""}>${label}</button></a>`;
    return `<div class="toolbar">${link("bundle", "Download translated model + report (.zip)", true)}${link("sbml", "Model (.xml)")}${link("json", "Model (.json)")}${link("summary", "Summary (.txt)")}</div>`;
  }

  function groupHtml(group, rows) {
    return `
      <details class="memote-issue"${group.key === "errors" && rows.length ? " open" : ""}>
        <summary><strong>${escapeHtml(group.label)}</strong><span class="badge">${rows.length}</span><span class="stoich">${escapeHtml(group.hint)}</span></summary>
        <div class="memote-issue-body">
          ${rows.length ? `<div class="toolbar">${exportButtonsHtml(group.key)}</div>${previewTableHtml(group.columns, rows, TRANSLATE_PREVIEW_LIMIT)}` : "Nothing in this group."}
        </div>
      </details>`;
  }

  function draw() {
    const r = result;
    if (!r) return;
    const root = $(id("Results"));
    const warning = r.source_check && r.source_check.warning ? `<div class="note">${escapeHtml(r.source_check.warning)}</div>` : "";
    root.innerHTML = `
      ${warning}
      ${countsHtml(r)}
      ${downloadsHtml()}
      ${cfg.groups.map(g => groupHtml(g, r[g.key])).join("")}`;
    wireExportButtons(root, key => {
      const group = cfg.groups.find(g => g.key === key);
      return { filename: group.file, columns: group.columns, rows: result[key] };
    });
  }

  return { render };
}

// --- SEED -> VMH ----------------------------------------------------------

const seedVmhPanel = createTranslatePanel({
  panelId: "translate",
  key: "translate",
  title: "Translate SEED &rarr; VMH",
  introHtml: `
      Renames the metabolite and reaction ids of a ModelSEED-namespace model to the VMH namespace, using the
      translation tables in the data folder. Every id ends up as <strong>mapped</strong>, an <strong>error</strong>
      (ambiguous in the table, or the new id would clash with another id), or <strong>no available mapping</strong>;
      the last two keep their original id. Gene and compartment ids are not translated. The translation starts from
      the model file as uploaded (before any diet), and the loaded model is not changed.`,
  controlsHtml: `
      <label for="translateStyle">Id style</label>
      <select id="translateStyle">
        <option value="vmh" selected>VMH style (h2o[c], EX_h2o(e))</option>
        <option value="keep">Keep the model's compartment tags (h2o_c0, EX_h2o_e0)</option>
      </select>`,
  runLabel: "Translate to VMH",
  endpoint: "/api/translate-seed-vmh",
  downloadBase: "/api/translate-seed-vmh",
  requestBody: () => ({ style: $("translateStyle").value }),
  groups: [
    { key: "mapped", label: "Mapped", hint: "Renamed to their VMH id.", file: "seed_to_vmh_mapped.csv",
      columns: [{ key: "kind", label: "Type" }, { key: "original_id", label: "SEED id (in model)" }, { key: "seed_id", label: "SEED id" },
        { key: "vmh_id", label: "VMH id" }, { key: "new_id", label: "New id in model" }, { key: "name", label: "Name" }] },
    { key: "errors", label: "Errors", hint: "Have a table entry but could not be renamed (ambiguous, or the new id would clash). Original id kept.", file: "seed_to_vmh_errors.csv",
      columns: [{ key: "kind", label: "Type" }, { key: "original_id", label: "SEED id (in model)" }, { key: "seed_id", label: "SEED id" },
        { key: "vmh_id", label: "VMH id(s)" }, { key: "reason", label: "Problem" }, { key: "name", label: "Name" }] },
    { key: "unmapped", label: "No available mapping", hint: "Not in the translation tables. Original id kept.", file: "seed_to_vmh_unmapped.csv",
      columns: [{ key: "kind", label: "Type" }, { key: "original_id", label: "SEED id (in model)" }, { key: "seed_id", label: "SEED id" },
        { key: "name", label: "Name" }, { key: "reason", label: "Reason" }] },
  ],
});

function renderTranslate() { seedVmhPanel.render(); }
