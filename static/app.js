let DATA = null;
let MODEL_ID = null; // Kept at module scope so the debug step can reach the
                      // same cached model after the initial analysis finishes.
let COMP_NAMES = {}; // compartment id -> friendly display name, set after analysis
const $ = (id) => document.getElementById(id);

// Sort state for tables
let sortState = {};

const fileInput = $("modelFile");
const analyzeBtn = $("analyzeBtn");
const filename = $("filename");
const status = $("status");
const dropzone = $("dropzone");
const dietMode = $("dietMode");
const dietDropzone = $("dietDropzone");
const dietFileInput = $("dietFile");
const dietFilenameEl = $("dietFilename");
const reportBtn = $("reportBtn");
reportBtn.addEventListener("click", () => {
  if (!DATA) return;
  renderReportModal();
});

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  analyzeBtn.disabled = !file;
  filename.textContent = file ? file.name : "";
});

["dragenter","dragover"].forEach(e => dropzone.addEventListener(e, ev => {
  ev.preventDefault(); dropzone.classList.add("drag");
}));
["dragleave","drop"].forEach(e => dropzone.addEventListener(e, ev => {
  ev.preventDefault(); dropzone.classList.remove("drag");
}));
dropzone.addEventListener("drop", ev => {
  const file = ev.dataTransfer.files[0];
  if (!file) return;
  fileInput.files = ev.dataTransfer.files;
  analyzeBtn.disabled = false;
  filename.textContent = file.name;
});

// --- Diet / media controls ---
dietMode.addEventListener("change", () => {
  const isCustom = dietMode.value === "custom";
  dietDropzone.classList.toggle("hidden", !isCustom);
  if (!isCustom) {
    dietFileInput.value = "";
    dietFilenameEl.textContent = "";
  }
});

dietFileInput.addEventListener("change", () => {
  const file = dietFileInput.files[0];
  dietFilenameEl.textContent = file ? file.name : "";
});

["dragenter","dragover"].forEach(e => dietDropzone.addEventListener(e, ev => {
  ev.preventDefault(); dietDropzone.classList.add("drag");
}));
["dragleave","drop"].forEach(e => dietDropzone.addEventListener(e, ev => {
  ev.preventDefault(); dietDropzone.classList.remove("drag");
}));
dietDropzone.addEventListener("drop", ev => {
  const file = ev.dataTransfer.files[0];
  if (!file) return;
  dietFileInput.files = ev.dataTransfer.files;
  dietFilenameEl.textContent = file.name;
});

analyzeBtn.addEventListener("click", async () => {
  const file = fileInput.files[0];
  if (!file) return;

  if (dietMode.value === "custom" && !dietFileInput.files[0]) {
    status.innerHTML = `<span class="error">Choose a diet file, or switch "Diet / media" back to something else.</span>`;
    return;
  }

  analyzeBtn.disabled = true;
  status.textContent = "Loading model and running initial analysis…";
  progressStart("mainProgress", true);

  try {
    const form = new FormData();
    form.append("model", file);
    form.append("diet_mode", dietMode.value);
    if (dietMode.value === "custom" && dietFileInput.files[0]) {
      form.append("diet_file", dietFileInput.files[0]);
    }

    // Phase 1: Quick analysis
    const quickResponse = await fetch("/api/analyze-quick", { method:"POST", body:form });
    const quickData = await quickResponse.json();
    if (!quickResponse.ok) throw new Error(quickData.error || "Analysis failed");

    // Store quick results and model ID
    const modelId = quickData.model_id;
    delete quickData.model_id;
    MODEL_ID = modelId;
    DATA = quickData;
    DATA.exchanges = []; // Will be filled by streaming
    sortState = {};
    COMP_NAMES = Object.fromEntries((DATA.stats.compartment_details || []).map(c => [c.id, c.name]));
    renderDebugDefault([], []);
    BALANCE_RESULT = null;
    PRECURSOR_RESULT = null;
    TRACER_RESULT = null;
    TRACER_KO_VIEW = "before";
    TRACER_HIGHLIGHT_KO = true;
    if (TRACER_CY) { TRACER_CY.destroy(); TRACER_CY = null; }
    MINMED_RESULT = null;
    NETGAPS_RESULT = null;
    DSAUDIT_RESULT = null;
    FROG_RESULT = null;
    if (CURRENT_FROG_EVENTSOURCE) { CURRENT_FROG_EVENTSOURCE.close(); CURRENT_FROG_EVENTSOURCE = null; }
    closeReportModal();
    resetMemote();

    // Show initial results
    renderAll();
    showView("results");
    goToTab("overview"); // Overview is always the landing page for a new model
    status.textContent = "Performing exchange knockouts…";

    // Phase 2: Stream KO analysis
    streamKOAnalysis(modelId);

  } catch (err) {
    status.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    analyzeBtn.disabled = false;
    progressDone("mainProgress");
  }
});

// Kept at module scope so a new analysis run can always find and close
// whatever stream a *previous* run left open (see streamKOAnalysis).
let CURRENT_KO_EVENTSOURCE = null;

function streamKOAnalysis(modelId) {
  // Bug fix: re-uploading a model while a previous model's KO-essentiality
  // stream was still running left that old EventSource open with no
  // reference anywhere. Its "complete" handler would still fire later and
  // overwrite DATA.exchanges/essentiality_rule/transport_rule -- which by
  // then belong to the *new* model -- with the stale model's results.
  // Closing any previous stream before opening this one, plus the modelId
  // guard in the handlers below (belt-and-braces against a message that was
  // already in flight the instant close() was called), eliminates the race.
  if (CURRENT_KO_EVENTSOURCE) {
    CURRENT_KO_EVENTSOURCE.close();
    CURRENT_KO_EVENTSOURCE = null;
  }

  const eventSource = new EventSource(`/api/analyze-ko/${modelId}`);
  CURRENT_KO_EVENTSOURCE = eventSource;
  let receivedAny = false;

  eventSource.onopen = () => {
    console.log("Connection opened for model:", modelId);
  };

  eventSource.onmessage = (event) => {
    if (modelId !== MODEL_ID) { eventSource.close(); return; } // superseded by a newer analysis
    try {
      receivedAny = true;
      const msg = JSON.parse(event.data);
      console.log("Received message:", msg.type);

      if (msg.type === "info") {
        status.textContent = msg.message;
      } else if (msg.type === "progress") {
        status.textContent = `Testing exchanges: ${msg.current}/${msg.total} - ${msg.message}`;
        updateProgressBar(msg.current, msg.total);
      } else if (msg.type === "complete") {
        DATA.exchanges = msg.exchanges;
        DATA.essentiality_rule = msg.essentiality_rule;
        DATA.transport_rule = msg.transport_rule;

        // Re-render with completed data
        renderExchanges();
        status.textContent = "Analysis complete!";
        analyzeBtn.disabled = false;
        progressDone("mainProgress");
        eventSource.close();
        if (CURRENT_KO_EVENTSOURCE === eventSource) CURRENT_KO_EVENTSOURCE = null;
      }
    } catch (err) {
      console.error("Parse error:", err, "Raw data:", event.data);
    }
  };

  eventSource.onerror = (err) => {
    if (modelId !== MODEL_ID) { eventSource.close(); return; } // superseded by a newer analysis
    console.error("EventSource error:", err, "Received any data:", receivedAny);
    if (receivedAny) {
      // If we received data but got an error, it might just be connection closing normally
      status.textContent = "Analysis complete!";
      analyzeBtn.disabled = false;
    } else {
      status.innerHTML = `<span class="error">Connection error - try uploading again</span>`;
    }
    progressDone("mainProgress");
    eventSource.close();
    if (CURRENT_KO_EVENTSOURCE === eventSource) CURRENT_KO_EVENTSOURCE = null;
    analyzeBtn.disabled = false;
  };
}

// ---------------------------------------------------------------------------
// Shared progress-bar helpers for every long-running analysis (initial
// upload/KO essentiality, FROG report, minimal medium, network gaps,
// demand/sink audit, pathway tracer, generated report). Each analysis's
// panel gets a `progressBarHtml(id)` track next to its status line;
// progressStart shows it (indeterminate, unless a real current/total is
// known -- only the KO-essentiality stream and FROG's 4 stages have one),
// progressSet moves a determinate bar, and progressDone hides it again.
// ---------------------------------------------------------------------------
function progressBarHtml(id) {
  return `<div class="progress-track" id="${id}" style="display:none;"><div class="progress-fill"></div></div>`;
}
function progressStart(id, indeterminate) {
  const el = $(id);
  if (!el) return;
  el.style.display = "";
  el.classList.toggle("indeterminate", indeterminate !== false);
  const fill = el.querySelector(".progress-fill");
  if (fill) fill.style.width = indeterminate === false ? "0%" : "";
}
function progressSet(id, pct) {
  const el = $(id);
  if (!el) return;
  el.style.display = "";
  el.classList.remove("indeterminate");
  const fill = el.querySelector(".progress-fill");
  if (fill) fill.style.width = Math.max(0, Math.min(100, pct)) + "%";
}
function progressDone(id) {
  const el = $(id);
  if (!el) return;
  el.classList.remove("indeterminate");
  const fill = el.querySelector(".progress-fill");
  if (fill) fill.style.width = "100%";
  setTimeout(() => { el.style.display = "none"; }, 300);
}
function updateProgressBar(current, total) {
  progressSet("mainProgress", Math.round((current / total) * 100));
}

// ---- Navigation: 4 modules (+ References) on top, sub-tabs under each. ----
// Every sub-tab is still a `.tab[data-tab]` button controlling the `.panel`
// with that id, so existing code (e.g. `$("debugTab").click()`) keeps working.
const LAST_TAB_IN_MODULE = {};

function showModule(moduleId) {
  document.querySelectorAll(".modbtn").forEach(b => b.classList.toggle("active", b.dataset.module === moduleId));
  document.querySelectorAll(".subnav").forEach(n => n.classList.toggle("hidden", n.dataset.module !== moduleId));
}

function goToTab(tabId) {
  const btn = document.querySelector(`.tab[data-tab="${tabId}"]`);
  if (btn) btn.click();
}

document.querySelectorAll(".tab").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(x => x.classList.remove("active"));
    btn.classList.add("active");
    $(btn.dataset.tab).classList.add("active");
    const nav = btn.closest(".subnav");
    if (nav) {
      LAST_TAB_IN_MODULE[nav.dataset.module] = btn.dataset.tab;
      showModule(nav.dataset.module);
    }
  });
});

document.querySelectorAll(".modbtn").forEach(mb => {
  mb.addEventListener("click", () => {
    const m = mb.dataset.module;
    if (m === "references") {
      document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
      document.querySelectorAll(".panel").forEach(x => x.classList.remove("active"));
      $("references").classList.add("active");
      showModule("references");
      return;
    }
    const target = LAST_TAB_IN_MODULE[m]
      || document.querySelector(`.subnav[data-module="${m}"] .tab`)?.dataset.tab;
    if (target) goToTab(target);
  });
});

function escapeHtml(x) {
  return String(x ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;" }[c]));
}
function fmt(x, digits=4) {
  if (x === null || x === undefined || Number.isNaN(Number(x))) return "—";
  const n = Number(x);
  if (!Number.isFinite(n)) return n > 0 ? "∞" : "-∞";
  return n.toFixed(digits).replace(/\.?0+$/, "");
}
function join(x) { return (x || []).join(", "); }

// ---------------------------------------------------------------------------
// Generic "export this table to CSV" helper, shared by the Minimal Medium
// and Network Gaps tabs (and reusable by any future one). `columns` is a
// list of {key, label} -- or {value: row => ..., label} for a computed
// column -- and `rows` is the array of row objects currently on screen
// (whatever the table is showing right now, respecting any sort already
// applied). Runs entirely client-side: no server round-trip, just a Blob
// download via a throwaway <a download> link.
// ---------------------------------------------------------------------------
function csvCell(value) {
  if (value === null || value === undefined) return "";
  const s = String(value);
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}
function exportTableToCsv(filename, columns, rows) {
  const header = columns.map(c => csvCell(c.label)).join(",");
  const lines = (rows || []).map(row =>
    columns.map(c => csvCell(typeof c.value === "function" ? c.value(row) : row[c.key])).join(",")
  );
  const csv = [header, ...lines].join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Per-table "Columns" visibility picker + CSV/TSV export, shared by every
// data table in the app. Call attachTableTools(tableId, toolbarEl, columns,
// getRows, exportBaseName) once, right after a table's <thead> (with one
// <th> per entry in `columns`, in the same order) has been put in the DOM.
//
// getRows() must return the table's CURRENT on-screen rows -- whatever the
// active filter/sort is showing right now, not the full unfiltered dataset
// -- so export always matches what the user is looking at.
//
// The "Columns" picker only hides/shows cells on screen (via a per-table
// <style> block keyed on column position, since sorting only reorders rows,
// never columns). The "Export" picker is a *separate* set of checkboxes
// (defaulted to the same visible set) so a one-off export can include a
// different column selection than what's currently shown, without touching
// the on-screen table.
// ---------------------------------------------------------------------------
const TABLE_COLUMN_STATE = {}; // tableId -> Set of visible column keys

function tableColumnState(tableId, columns) {
  if (!TABLE_COLUMN_STATE[tableId]) {
    TABLE_COLUMN_STATE[tableId] = new Set(columns.map(c => c.key));
  }
  return TABLE_COLUMN_STATE[tableId];
}

function applyColumnVisibility(tableId, columns) {
  const visible = tableColumnState(tableId, columns);
  let css = "";
  columns.forEach((c, i) => {
    if (!visible.has(c.key)) {
      css += `#${tableId} th:nth-child(${i + 1}), #${tableId} td:nth-child(${i + 1}) { display:none; }\n`;
    }
  });
  const styleElId = `${tableId}-colstyle`;
  let styleEl = document.getElementById(styleElId);
  if (!styleEl) {
    styleEl = document.createElement("style");
    styleEl.id = styleElId;
    document.head.appendChild(styleEl);
  }
  styleEl.textContent = css;
}

function delimCell(value, delimiter) {
  if (value === null || value === undefined) return "";
  const s = String(value);
  const re = delimiter === "\t" ? /["\t\r\n]/ : /[",\r\n]/;
  return re.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function downloadDelimited(filename, columns, rows, delimiter) {
  const header = columns.map(c => delimCell(c.label, delimiter)).join(delimiter);
  const lines = (rows || []).map(row =>
    columns.map(c => delimCell(typeof c.value === "function" ? c.value(row) : row[c.key], delimiter)).join(delimiter)
  );
  const text = [header, ...lines].join("\r\n");
  const mime = delimiter === "\t" ? "text/tab-separated-values;charset=utf-8;" : "text/csv;charset=utf-8;";
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Closes every open Columns/Export popover except (optionally) one.
function closeAllTableToolPanels(except) {
  document.querySelectorAll(".tt-panel").forEach(p => { if (p !== except) p.classList.add("hidden"); });
}
document.addEventListener("click", () => closeAllTableToolPanels());

// `columns` must match the table's actual <th> order 1:1 (drives on-screen
// show/hide). `exportColumns` (optional, defaults to `columns`) is what the
// Export panel offers -- it can include extra fields that aren't shown as
// table columns at all (e.g. a full reaction string), since export doesn't
// need positional alignment with the DOM the way visibility does.
function attachTableTools(tableId, toolbarEl, columns, getRows, exportBaseName, exportColumns) {
  if (!toolbarEl) return;
  exportColumns = exportColumns || columns;
  applyColumnVisibility(tableId, columns);
  const visible = tableColumnState(tableId, columns);
  const exportKeyOf = (c, i) => c.key || `col${i}`;

  const wrap = document.createElement("div");
  wrap.className = "table-tools";
  wrap.innerHTML = `
    <div class="tt-dropdown">
      <button type="button" class="tt-btn" data-tt="cols-${tableId}">Columns ▾</button>
      <div class="tt-panel hidden" data-tt-panel="cols-${tableId}">
        <div class="tt-panel-title">Show columns</div>
        ${columns.map(c => `<label class="tt-check"><input type="checkbox" data-role="vis" value="${escapeHtml(c.key)}" ${visible.has(c.key) ? "checked" : ""}> ${escapeHtml(c.label)}</label>`).join("")}
      </div>
    </div>
    <div class="tt-dropdown">
      <button type="button" class="tt-btn" data-tt="exp-${tableId}">Export ▾</button>
      <div class="tt-panel hidden tt-panel-wide" data-tt-panel="exp-${tableId}">
        <div class="tt-panel-title">Columns to export</div>
        <div class="tt-export-cols">
          ${exportColumns.map((c, i) => `<label class="tt-check"><input type="checkbox" data-role="exp" value="${escapeHtml(exportKeyOf(c, i))}" ${(!c.key || visible.has(c.key)) ? "checked" : ""}> ${escapeHtml(c.label)}</label>`).join("")}
        </div>
        <div class="tt-export-actions">
          <button type="button" data-fmt="csv">Download CSV</button>
          <button type="button" data-fmt="tsv">Download TSV</button>
        </div>
      </div>
    </div>
  `;
  toolbarEl.appendChild(wrap);

  wrap.querySelector(`[data-tt-panel="cols-${tableId}"]`).addEventListener("change", (ev) => {
    if (ev.target.dataset.role !== "vis") return;
    const key = ev.target.value;
    if (ev.target.checked) visible.add(key); else visible.delete(key);
    applyColumnVisibility(tableId, columns);
  });

  wrap.querySelectorAll('[data-fmt]').forEach(btn => {
    btn.addEventListener("click", () => {
      const panel = wrap.querySelector(`[data-tt-panel="exp-${tableId}"]`);
      const chosenKeys = new Set([...panel.querySelectorAll('input[data-role="exp"]:checked')].map(el => el.value));
      const chosenCols = exportColumns.filter((c, i) => chosenKeys.has(exportKeyOf(c, i)));
      if (!chosenCols.length) { window.alert("Choose at least one column to export."); return; }
      const delim = btn.dataset.fmt === "tsv" ? "\t" : ",";
      downloadDelimited(`${exportBaseName}.${btn.dataset.fmt}`, chosenCols, getRows(), delim);
      closeAllTableToolPanels();
    });
  });

  wrap.querySelectorAll(".tt-btn").forEach(btn => {
    btn.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const key = btn.dataset.tt;
      const panel = wrap.querySelector(`[data-tt-panel="${key}"]`);
      const isOpen = !panel.classList.contains("hidden");
      closeAllTableToolPanels();
      if (!isOpen) panel.classList.remove("hidden");
    });
  });
  wrap.addEventListener("click", (ev) => ev.stopPropagation());
}

// Make table sortable by adding click handlers to headers
function makeSortable(tableId, rows, renderFn) {
  const table = $(tableId);
  if (!table) return;
  
  const headers = table.querySelectorAll("th");
  headers.forEach((th, colIndex) => {
    th.classList.add("sortable");
    th.style.cursor = "pointer";
    
    th.addEventListener("click", () => {
      const key = sortState[tableId] || {};
      const isAsc = key.col === colIndex ? !key.asc : true;
      sortState[tableId] = { col: colIndex, asc: isAsc };
      
      // Update header indicators
      headers.forEach(h => h.textContent = h.textContent.replace(/\s*[↑↓]\s*$/, ""));
      th.textContent += (isAsc ? " ↑" : " ↓");
      
      // Get column key from th data attribute or determine from content
      const colKey = th.dataset.key;
      
      const sorted = [...rows].sort((a, b) => {
        let aVal = a[colKey];
        let bVal = b[colKey];
        
        // Handle null/undefined
        if (aVal == null && bVal == null) return 0;
        if (aVal == null) return isAsc ? 1 : -1;
        if (bVal == null) return isAsc ? -1 : 1;
        
        // Numeric comparison
        if (typeof aVal === "number" && typeof bVal === "number") {
          return isAsc ? aVal - bVal : bVal - aVal;
        }
        
        // String comparison
        aVal = String(aVal).toLowerCase();
        bVal = String(bVal).toLowerCase();
        return isAsc ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      });
      
      renderFn(sorted);
    });
  });
}

function renderAll() {
  renderSummary();
  renderOverview();
  renderReactions();
  renderMetabolites();
  renderExchanges();
  renderObjective();
  renderMinimalMedium();
  renderNetworkGaps();
  renderTracer();
  renderFrog();
  renderAnnotation();
  renderReferences();
  renderBalance();
  renderPrecursors();
  renderModelCompare();
  renderTranslate(); renderMetanetxTranslate(); renderBalanceAudit(); renderGenes(); renderThresholdRows();
}

function renderSummary() {
  const s = DATA.stats;
  const cards = [
    ["Genes", s.genes], ["Metabolites", s.metabolites], ["Reactions", s.reactions],
    ["Compartments", s.compartments], ["WT growth", fmt(s.wt_growth)], ["Solver", s.solver]
  ];
  $("summary").innerHTML = cards.map(([l,v]) =>
    `<div class="summary-card"><div class="label">${escapeHtml(l)}</div><div class="value">${escapeHtml(v)}</div></div>`
  ).join("");
}

// One "ID annotation" detail card (namespace or compartment convention) for
// the Overview tab — label, the detected value, an example id, and (for a
// namespace) what fraction of ids matched it.
function annotationCardHtml(title, label, example, coveragePct) {
  const pct = coveragePct != null ? `<div class="mini-stat-label">${fmt(coveragePct, 1)}% of ids matched</div>` : "";
  return `
    <div class="objective-card">
      <div class="mini-stat-label">${escapeHtml(title)}</div>
      <div class="annot-value">${escapeHtml(label || "Unknown")}</div>
      ${example ? `<div class="stoich">e.g. <code>${escapeHtml(example)}</code></div>` : ""}
      ${pct}
    </div>
  `;
}

// Renders the <li> list for one kind ("metabolite"/"reaction") of unmapped
// ids, with a same-model, same-name "likely duplicate" note per entry when
// compute_unmapped_id_audit found one (see app.py for why this is a
// same-model name check rather than a lookup against an external table --
// the bundled MetaNetX cross-reference files carry no names at all).
function unmappedAuditItemsHtml(items, kind, limit) {
  if (!items || !items.length) return "";
  const shown = limit ? items.slice(0, limit) : items;
  const rows = shown.map(it => {
    const dupes = (it.likely_duplicate_of || []).map(d =>
      `<code>${escapeHtml(d.id)}</code> (MetaNetX <code>${escapeHtml(d.metanetx_id)}</code>)`
    ).join(", ");
    const dupeNote = dupes
      ? ` — same name as ${dupes}, which IS mapped. This id likely comes from a different namespace than the rest of the model. Check the predominant namespace above, look up <code>${escapeHtml(it.id)}</code>'s equivalent id there, and rename/re-edit it in your model file to match.`
      : "";
    return `<li><code>${escapeHtml(it.id)}</code>${it.name ? " — " + escapeHtml(it.name) : ""}${dupeNote}</li>`;
  }).join("");
  const more = limit && items.length > shown.length
    ? `<div class="stoich">…and ${items.length - shown.length} more (filter the ${kind === "metabolite" ? "Metabolites" : "Reactions"} tab to "MetaNetX: unmapped" to see all of them).</div>`
    : "";
  return `<ul style="margin:6px 0 0 18px; padding:0;">${rows}</ul>${more}`;
}

// Warning box(es) for the Overview tab (and, via a higher limit, the
// generated report) listing metabolites/reactions that never matched any
// bundled MetaNetX namespace, so the user can go check whether a handful of
// ids were pulled in from a different namespace than the rest of the model.
function namespaceAuditWarningsHtml(limit) {
  const audit = DATA.namespace_audit;
  const s = DATA.stats || {};
  if (!audit) return "";
  const parts = [];
  if (audit.unmapped_metabolite_count > 0) {
    const total = audit.unmapped_metabolite_count + audit.mapped_metabolite_count;
    parts.push(`
      <div class="note">
        <strong>${audit.unmapped_metabolite_count} of ${total} metabolites</strong> did not map to MetaNetX.
        This model is predominantly in the <strong>${escapeHtml((s.namespace_metabolites || {}).label || "detected")}</strong> namespace —
        these ids are highlighted red in the Metabolites tab; look up each one's id in that namespace and rename it to match.
        ${unmappedAuditItemsHtml(audit.unmapped_metabolites, "metabolite", limit)}
      </div>
    `);
  }
  if (audit.unmapped_reaction_count > 0) {
    const total = audit.unmapped_reaction_count + audit.mapped_reaction_count;
    parts.push(`
      <div class="note">
        <strong>${audit.unmapped_reaction_count} of ${total} reactions</strong> did not map to MetaNetX.
        This model is predominantly in the <strong>${escapeHtml((s.namespace_reactions || {}).label || "detected")}</strong> namespace —
        these ids are highlighted red in the Reactions tab; look up each one's id in that namespace and rename it to match.
        ${unmappedAuditItemsHtml(audit.unmapped_reactions, "reaction", limit)}
      </div>
    `);
  }
  return parts.join("");
}

function renderOverview() {
  const s = DATA.stats;
  const d = DATA.diet;
  const ns = s.namespace_metabolites || {};
  const nsR = s.namespace_reactions || {};
  const conv = s.compartment_convention || {};
  const grLabel = s.reaction_gene_ratio != null ? `1 : ${fmt(s.reaction_gene_ratio, 2)}` : "—";

  $("overview").innerHTML = `
    <h2>Model overview</h2>
    <div class="mini-stats">
      <div class="mini-stat"><div class="mini-stat-value">${escapeHtml(s.metabolites)}</div><div class="mini-stat-label">Metabolites</div></div>
      <div class="mini-stat"><div class="mini-stat-value">${escapeHtml(s.reactions)}</div><div class="mini-stat-label">Reactions</div></div>
      <div class="mini-stat"><div class="mini-stat-value">${escapeHtml(s.genes)}</div><div class="mini-stat-label">Genes</div></div>
      <div class="mini-stat" title="Genes : reactions, i.e. one gene maps to roughly this many reactions on average."><div class="mini-stat-value">${escapeHtml(grLabel)}</div><div class="mini-stat-label">Gene : Reaction ratio</div></div>
      <div class="mini-stat"><div class="mini-stat-value">${fmt(s.wt_growth)}</div><div class="mini-stat-label">WT growth</div></div>
      <div class="mini-stat"><div class="mini-stat-value">${escapeHtml(s.solver)}</div><div class="mini-stat-label">Solver</div></div>
    </div>

    <div id="memoteBox"></div>

    <h3>Compartments</h3>
    <div class="chip-row">${s.compartment_details.map(c => {
      const extra = c.raw_name && c.raw_name !== c.name ? ` (model-provided name: ${c.raw_name})` : "";
      return `<span class="badge" title="Compartment code: ${escapeHtml(c.id)}${escapeHtml(extra)}">${escapeHtml(c.name)}</span>`;
    }).join(" ")}</div>

    <h3>Other details</h3>
    <dl class="kv">
      <dt>Model ID</dt><dd>${escapeHtml(s.model_id)}</dd>
      <dt>Model name</dt><dd>${escapeHtml(s.model_name || "—")}</dd>
      <dt>Objective direction</dt><dd>${escapeHtml(s.objective_direction)}</dd>
      <dt>WT optimization</dt><dd>${escapeHtml(s.wt_status)}</dd>
    </dl>
    ${d ? renderDietSummary(d) : ""}
    <h3>Analysis rule</h3>
    <div class="note">${escapeHtml(DATA.essentiality_rule)}</div>
    <div class="note">${escapeHtml(DATA.transport_rule)}</div>
  `;
  renderMemoteBox();
}

function renderAnnotation() {
  const s = DATA.stats;
  const ns = s.namespace_metabolites || {};
  const nsR = s.namespace_reactions || {};
  const conv = s.compartment_convention || {};
  $("annotation").innerHTML = `
    <h2>ID namespaces &amp; annotation</h2>
    <p class="memote-desc">Which identifier convention the model uses for metabolites, reactions and compartments, and how consistently. More annotation and translation tools will be added to this module.</p>
    <div class="objective-grid">
      ${annotationCardHtml("ID namespace — metabolites", ns.label, ns.example, ns.coverage != null ? ns.coverage * 100 : null)}
      ${annotationCardHtml("ID namespace — reactions", nsR.label, nsR.example, nsR.coverage != null ? nsR.coverage * 100 : null)}
      ${annotationCardHtml("Compartment annotation", conv.label, conv.example, null)}
    </div>
    ${namespaceAuditWarningsHtml(15)}
  `;
}

function renderDietSummary(d) {
  const modeLabels = { none: "Model's original bounds", complete: "Complete media", minimal: "Minimal media (computed)", custom: "Custom diet" };
  const label = modeLabels[d.mode] || d.mode;
  const cls = d.error ? "error" : "note";
  let html = `<h3>Diet / media</h3><div class="${cls}"><strong>${escapeHtml(label)}.</strong> ${escapeHtml(d.note || "")}</div>`;
  if (d.unmatched && d.unmatched.length) {
    html += `<div class="note">Unmatched diet entries (no matching exchange reaction found in this model): ${
      d.unmatched.map(u => `<span class="badge bad">${escapeHtml(u.id)} (${fmt(u.flux, 4)})</span>`).join(" ")
    }</div>`;
  }
  return html;
}

function reactionStatsHtml(rows) {
  const total = rows.length;
  const byType = {};
  rows.forEach(r => { byType[r.type] = (byType[r.type] || 0) + 1; });
  const withGpr = rows.filter(r => (r.gene_reaction_rule || "").trim()).length;
  const withSub = rows.filter(r => (r.subsystem || "").trim()).length;

  const typeCards = Object.keys(byType).sort().map(t => {
    const info = REACTION_TYPE_INFO[t];
    return `
    <div class="mini-stat"${info ? ` title="${escapeHtml(info)}"` : ""}>
      <div class="mini-stat-value">${byType[t]}</div>
      <div class="mini-stat-label">${escapeHtml(t)} <span class="stoich">${total ? fmt(100 * byType[t] / total, 1) : "0"}%</span></div>
    </div>`;
  }).join("");

  return `
    <h3>Reaction statistics</h3>
    <div class="mini-stats">
      ${typeCards}
      <div class="mini-stat" title="Fraction of reactions that have a gene-protein-reaction (GPR) rule assigned.">
        <div class="mini-stat-value">${total ? fmt(100 * withGpr / total, 1) : "0"}%</div>
        <div class="mini-stat-label">have a GPR <span class="stoich">${withGpr}/${total}</span></div>
      </div>
      <div class="mini-stat" title="Fraction of reactions that have a subsystem assigned.">
        <div class="mini-stat-value">${total ? fmt(100 * withSub / total, 1) : "0"}%</div>
        <div class="mini-stat-label">have a subsystem <span class="stoich">${withSub}/${total}</span></div>
      </div>
    </div>
  `;
}

const REACTION_TABLE_COLUMNS = [
  { key: "id", label: "Original ID" },
  { key: "metanetx_id", label: "MetaNetX ID" },
  { key: "name", label: "Name" },
  { key: "type", label: "Type" },
  { key: "subsystem", label: "Subsystem" },
  { key: "gene_reaction_rule", label: "GPR" },
  { key: "compartments", label: "Compartment", value: r => (r.compartments || []).map(c => COMP_NAMES[c] || c).join("; ") },
  { key: "wt_flux", label: "WT flux" },
  { key: "balance", label: "Balance" },
  { key: "balance_detail", label: "Imbalance / note" },
];

const BALANCE_INFO = {
  balanced: "Every element (and the charge, where charges are given) sums to zero across the reaction.",
  unbalanced: "At least one element or the charge does not balance. Click to see what is wrong.",
  unknown: "Can't be checked: one or more metabolites has no chemical formula. Click to see which.",
  "n/a": "Not expected to balance: exchange/demand/sink and biomass/objective reactions are skipped.",
};

function balanceBadge(r) {
  const st = r.balance || "n/a";
  const tip = `${BALANCE_INFO[st] || ""}${r.balance_detail ? " " + r.balance_detail : ""}`;
  if (st === "unbalanced" || st === "unknown") {
    return `<a class="badge ${st === "unbalanced" ? "bad" : "warn"} bal-link" data-rxn="${escapeHtml(r.id)}" title="${escapeHtml(tip)}">${st} ↗</a>`;
  }
  return `<span class="badge ${st === "balanced" ? "good" : ""}" title="${escapeHtml(tip)}">${escapeHtml(st)}</span>`;
}

let rxnCurrentRows = [];

function renderReactions() {
  const types = [...new Set(DATA.reactions.map(r => r.type))].sort();
  $("reactions").innerHTML = `
    ${reactionStatsHtml(DATA.reactions)}
    <h3>Reactions</h3>
    <div class="toolbar">
      <input id="rxnSearch" type="text" placeholder="Search ID, name, subsystem…">
      <select id="rxnType"><option value="">All types</option>${types.map(t => `<option>${escapeHtml(t)}</option>`).join("")}</select>
      <select id="rxnSubsystem"><option value="">All subsystems</option>${subsystems(DATA.reactions).map(t => `<option>${escapeHtml(t)}</option>`).join("")}</select>
      <select id="rxnMapped">
        <option value="">MetaNetX: all</option>
        <option value="mapped">MetaNetX: mapped only</option>
        <option value="unmapped">MetaNetX: unmapped only</option>
      </select>
      <select id="rxnGpr">
        <option value="">GPR: all</option>
        <option value="has">GPR: has a rule</option>
        <option value="none">GPR: no rule</option>
      </select>
      <select id="rxnBalance">
        <option value="">Balance: all</option>
        <option value="balanced">Balance: balanced</option>
        <option value="unbalanced">Balance: unbalanced</option>
        <option value="unknown">Balance: can't check (no formula)</option>
        <option value="n/a">Balance: not applicable</option>
      </select>
      <select id="rxnComp">
        <option value="">All compartments</option>
        ${[...new Set(DATA.reactions.flatMap(r => r.compartments || []))].sort().map(c => `<option value="${escapeHtml(c)}">${escapeHtml(COMP_NAMES[c] || c)}</option>`).join("")}
      </select>
      <span id="rxnCount"></span>
    </div>
    <div id="rxnBalanceBar" class="note hidden"></div>
    <div class="table-wrap"><table id="rxnTable">
      <thead><tr>
        <th data-key="id">Original ID</th>
        <th data-key="metanetx_id">MetaNetX ID</th>
        <th data-key="name">Name</th>
        <th data-key="type">Type</th>
        <th data-key="subsystem">Subsystem</th>
        <th data-key="gene_reaction_rule">GPR</th>
        <th data-key="compartments">Compartment</th>
        <th data-key="wt_flux">WT flux</th>
        <th data-key="balance" title="Mass/charge balance of the reaction">Balance</th>
      </tr></thead>
      <tbody id="rxnBody"></tbody>
    </table></div>
  `;
  const redraw = (filtered) => {
    const q = $("rxnSearch").value.toLowerCase();
    const type = $("rxnType").value;
    const sub = $("rxnSubsystem").value;
    const mapped = $("rxnMapped").value;
    const gpr = $("rxnGpr").value;
    const comp = $("rxnComp").value;
    const bal = $("rxnBalance").value;
    const rows = filtered ? filtered : DATA.reactions.filter(r =>
      (!q || `${r.id} ${r.metanetx_id || ""} ${r.name} ${r.subsystem} ${r.gene_reaction_rule}`.toLowerCase().includes(q)) &&
      (!type || r.type === type) && (!sub || r.subsystem === sub) &&
      (!mapped || (mapped === "mapped" ? !!r.metanetx_id : !r.metanetx_id)) &&
      (!gpr || (gpr === "has" ? !!(r.gene_reaction_rule || "").trim() : !(r.gene_reaction_rule || "").trim())) &&
      (!comp || (r.compartments || []).includes(comp)) &&
      (!bal || (r.balance || "n/a") === bal)
    );
    rxnCurrentRows = rows;
    const bar = $("rxnBalanceBar");
    if (bal === "unbalanced" || bal === "unknown") {
      bar.classList.remove("hidden");
      bar.innerHTML = `<strong>${rows.length}</strong> reaction(s) ${bal === "unbalanced" ? "are not mass/charge balanced" : "can't be checked (missing formulas)"}. ` +
        `<button type="button" id="rxnBalanceGo">See what's wrong in Diagnostics → Reaction Balance</button>`;
      $("rxnBalanceGo").addEventListener("click", () => openBalanceDiagnostics(null, bal));
    } else {
      bar.classList.add("hidden");
    }
    $("rxnCount").textContent = `${rows.length} / ${DATA.reactions.length}`;
    $("rxnBody").innerHTML = rows.map(r => `<tr class="${r.metanetx_id ? "" : "row-unmapped"}" title="${r.metanetx_id ? "" : "Not mapped to MetaNetX -- see the warning in the Overview tab"}">
      <td><strong>${escapeHtml(r.id)}</strong></td>
      <td>${escapeHtml(r.metanetx_id || "—")}</td>
      <td class="wrap">${escapeHtml(r.name)}</td>
      <td>${reactionTypeBadge(r.type)}</td><td>${escapeHtml(r.subsystem || "—")}</td>
      <td class="wrap">${escapeHtml(r.gene_reaction_rule || "—")}</td>
      <td>${compartmentBadges(r.compartments)}</td>
      <td class="num">${fmt(r.wt_flux)}</td>
      <td>${balanceBadge(r)}</td>
    </tr>`).join("");
    $("rxnBody").querySelectorAll(".bal-link").forEach(a => a.addEventListener("click", () => openBalanceDiagnostics(a.dataset.rxn)));
  };
  ["rxnSearch","rxnType","rxnSubsystem","rxnMapped","rxnGpr","rxnComp","rxnBalance"].forEach(id => $(id).addEventListener("input", () => redraw()));
  redraw();
  setTimeout(() => makeSortable("rxnTable", DATA.reactions, redraw), 0);
  attachTableTools("rxnTable", $("reactions").querySelector(".toolbar"), REACTION_TABLE_COLUMNS, () => rxnCurrentRows, "reactions");
}

const METABOLITE_TABLE_COLUMNS = [
  { key: "id", label: "Original ID" },
  { key: "metanetx_id", label: "MetaNetX ID" },
  { key: "name", label: "Name" },
  { key: "compartment", label: "Compartment", value: m => COMP_NAMES[m.compartment] || m.compartment || "" },
  { key: "formula", label: "Formula" },
  { key: "charge", label: "Charge" },
  { key: "reaction_count", label: "# Reactions" },
  { key: "produced_count", label: "# Produced in" },
  { key: "consumed_count", label: "# Consumed in" },
  { key: "reversible_count", label: "# Reversible" },
];

let metCurrentRows = [];

function renderMetabolites() {
  const comps = [...new Set(DATA.metabolites.map(m => m.compartment).filter(Boolean))].sort();
  $("metabolites").innerHTML = `
    <div class="toolbar">
      <input id="metSearch" type="text" placeholder="Search metabolite ID, name, formula…">
      <select id="metComp"><option value="">All compartments</option>${comps.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(COMP_NAMES[c] || c)}</option>`).join("")}</select>
      <select id="metMapped">
        <option value="">MetaNetX: all</option>
        <option value="mapped">MetaNetX: mapped only</option>
        <option value="unmapped">MetaNetX: unmapped only</option>
      </select>
      <span id="metCount"></span>
    </div>
    <div class="table-wrap"><table id="metTable">
      <thead><tr>
        <th data-key="id">Original ID</th>
        <th data-key="metanetx_id">MetaNetX ID</th>
        <th data-key="name" class="col-name-md">Name</th>
        <th data-key="compartment">Compartment</th>
        <th data-key="formula">Formula</th>
        <th data-key="charge">Charge</th>
        <th data-key="reaction_count"># Reactions</th>
        <th data-key="produced_count"># Produced in</th>
        <th data-key="consumed_count"># Consumed in</th>
        <th data-key="reversible_count"># Reversible</th>
      </tr></thead>
      <tbody id="metBody"></tbody>
    </table></div>
  `;
  const redraw = (filtered) => {
    const q = $("metSearch").value.toLowerCase();
    const comp = $("metComp").value;
    const mapped = $("metMapped").value;
    const rows = filtered ? filtered : DATA.metabolites.filter(m =>
      (!q || `${m.id} ${m.metanetx_id || ""} ${m.name} ${m.formula}`.toLowerCase().includes(q)) &&
      (!comp || m.compartment === comp) &&
      (!mapped || (mapped === "mapped" ? !!m.metanetx_id : !m.metanetx_id))
    );
    metCurrentRows = rows;
    $("metCount").textContent = `${rows.length} / ${DATA.metabolites.length}`;
    $("metBody").innerHTML = rows.map(m => `<tr class="${m.metanetx_id ? "" : "row-unmapped"}" title="${m.metanetx_id ? "" : "Not mapped to MetaNetX -- see the warning in the Overview tab"}">
      <td><strong id="met-${escapeHtml(m.id)}">${escapeHtml(m.id)}</strong></td>
      <td>${escapeHtml(m.metanetx_id || "—")}</td>
      <td class="col-name-md" title="${escapeHtml(m.name)}">${escapeHtml(m.name)}</td>
      <td>${compartmentBadges([m.compartment])}</td>
      <td>${escapeHtml(m.formula || "—")}</td><td>${escapeHtml(m.charge ?? "—")}</td>
      <td class="num">${m.reaction_count ?? 0}</td>
      <td class="num">${m.produced_count ?? 0}</td>
      <td class="num">${m.consumed_count ?? 0}</td>
      <td class="num">${m.reversible_count ?? 0}</td>
    </tr>`).join("");
  };
  ["metSearch","metComp","metMapped"].forEach(id => $(id).addEventListener("input", () => redraw()));
  redraw();
  setTimeout(() => makeSortable("metTable", DATA.metabolites, redraw), 0);
  attachTableTools("metTable", $("metabolites").querySelector(".toolbar"), METABOLITE_TABLE_COLUMNS, () => metCurrentRows, "metabolites");
}

const EXCHANGE_TABLE_COLUMNS = [
  { key: "id", label: "Original ID" },
  { key: "metanetx_id", label: "MetaNetX ID" },
  { key: "name", label: "Name" },
  { key: "metabolites", label: "Metabolite Original ID", value: r => join(r.metabolites) },
  { key: "metabolite_metanetx_ids", label: "Metabolite MetaNetX ID", value: r => join(r.metabolite_metanetx_ids) },
  { key: "metabolite_names", label: "Metabolite name", value: r => join(r.metabolite_names) },
  { key: "lower_bound", label: "LB" },
  { key: "upper_bound", label: "UB" },
  { key: "wt_flux", label: "WT flux" },
  { key: "uptake_allowed", label: "Uptake?", value: r => r.uptake_allowed ? "Yes" : "No" },
  { key: "ko_growth_fraction", label: "Growth retained after KO" },
  { key: "essential", label: "Essential?", value: r => r.essential ? "ESSENTIAL" : "No" },
];

let exCurrentRows = [];

function renderExchanges() {
  const exchanges = DATA.exchanges || [];
  const essentialExchanges = exchanges.filter(e => e.essential);
  renderDebugDefault(exchanges, essentialExchanges);
  const tested = exchanges.filter(e => e.ko_growth !== null && e.ko_growth !== undefined);
  const avgFraction = tested.length
    ? tested.reduce((sum, e) => sum + (e.ko_growth_fraction || 0), 0) / tested.length
    : null;

  const statCards = exchanges.length ? [
    ["Exchanges tested", exchanges.length],
    ["Essential", essentialExchanges.length],
    ["Non-essential", exchanges.length - essentialExchanges.length],
    ["Avg. KO growth retained", avgFraction == null ? "—" : `${fmt(avgFraction * 100, 1)}%`],
  ] : [];

  $("exchanges").innerHTML = `
    <div class="note">${escapeHtml(DATA.essentiality_rule)} Essentiality testing can be the slowest part for large models because each exchange is optimized after KO. Hover a row for the full reaction.</div>
    ${statCards.length ? `<div class="mini-stats">${statCards.map(([l, v]) =>
      `<div class="mini-stat"><div class="mini-stat-value">${escapeHtml(v)}</div><div class="mini-stat-label">${escapeHtml(l)}</div></div>`
    ).join("")}</div>` : ""}
    <div class="toolbar">
      <input id="exSearch" type="text" placeholder="Search exchange ID or metabolite…">
      <select id="exEssential"><option value="">All</option><option value="essential">Essential only</option><option value="nonessential">Non-essential</option></select>
      <select id="exUptake"><option value="">Uptake: all</option><option value="yes">Uptake allowed</option><option value="no">Uptake blocked</option></select>
      <span id="exCount"></span>
      ${essentialExchanges.length > 0 ? `<button id="debugExBtn" style="margin-left:auto;">🔍 Debug Essential Exchanges (${essentialExchanges.length})</button>` : ''}
    </div>
    <div class="table-wrap"><table id="exTable">
      <thead><tr>
        <th data-key="id">Original ID</th>
        <th data-key="metanetx_id">MetaNetX ID</th>
        <th data-key="name">Name</th>
        <th data-key="metabolites">Metabolite Original ID</th>
        <th data-key="metabolite_metanetx_ids">Metabolite MetaNetX ID</th>
        <th data-key="metabolite_names">Metabolite name</th>
        <th data-key="lower_bound">LB</th>
        <th data-key="upper_bound">UB</th>
        <th data-key="wt_flux">WT flux</th>
        <th data-key="uptake_allowed">Uptake?</th>
        <th data-key="ko_growth_fraction">Growth retained after KO</th>
        <th data-key="essential">Essential?</th>
      </tr></thead>
      <tbody id="exBody"></tbody>
    </table></div>
  `;

  // Add debug button listener
  if (essentialExchanges.length > 0) {
    const debugBtn = $("debugExBtn");
    if (debugBtn) {
      debugBtn.addEventListener("click", () => showDebugModal(essentialExchanges));
    }
  }

  const byId = new Map(exchanges.map(r => [r.id, r]));

  const redraw = (filtered) => {
    const q = $("exSearch").value.toLowerCase();
    const ess = $("exEssential").value;
    const uptake = $("exUptake").value;
    const rows = filtered ? filtered : exchanges.filter(r => {
      const matchQ = !q || `${r.id} ${r.metanetx_id || ""} ${r.name} ${r.metabolites.join(" ")} ${join(r.metabolite_metanetx_ids)} ${r.metabolite_names.join(" ")}`.toLowerCase().includes(q);
      const matchEss = !ess || (ess === "essential" ? r.essential : !r.essential);
      const matchUp = !uptake || (uptake === "yes" ? r.uptake_allowed : !r.uptake_allowed);
      return matchQ && matchEss && matchUp;
    });
    exCurrentRows = rows;
    $("exCount").textContent = `${rows.length} / ${exchanges.length}`;
    $("exBody").innerHTML = rows.map(r => `<tr data-row-id="${escapeHtml(r.id)}" class="${r.essential ? "row-essential" : ""}">
      <td><strong>${escapeHtml(r.id)}</strong></td>
      <td>${escapeHtml(r.metanetx_id || "—")}</td>
      <td class="wrap">${escapeHtml(r.name)}</td>
      <td>${escapeHtml(join(r.metabolites))}</td>
      <td>${escapeHtml(join(r.metabolite_metanetx_ids))}</td>
      <td>${escapeHtml(join(r.metabolite_names))}</td>
      <td class="num">${fmt(r.lower_bound, 2)}</td><td class="num">${fmt(r.upper_bound, 2)}</td><td class="num">${fmt(r.wt_flux)}</td>
      <td>${r.uptake_allowed ? "Yes" : "No"}</td>
      <td>${growthBar(r.ko_growth_fraction)}</td>
      <td><span class="badge ${r.essential ? "bad" : "good"}">${r.essential ? "ESSENTIAL" : "No"}</span></td>
    </tr>`).join("");
  };
  ["exSearch","exEssential","exUptake"].forEach(id => $(id).addEventListener("input", () => redraw()));
  redraw();
  setTimeout(() => makeSortable("exTable", exchanges, redraw), 0);
  attachRowTooltip("exBody", byId, buildExchangeTooltipHtml);
  attachTableTools("exTable", $("exchanges").querySelector(".toolbar"), EXCHANGE_TABLE_COLUMNS, () => exCurrentRows, "exchange_essentiality");
}

// A small inline bar visualizing what fraction of WT growth survives the
// knockout — quicker to scan at a glance than the raw percentage alone.
function growthBar(fraction) {
  if (fraction == null) return `<span class="stoich">not tested</span>`;
  const pct = Math.max(0, Math.min(100, fraction * 100));
  const color = pct < 5 ? "var(--bad)" : pct < 50 ? "#d97706" : "var(--good)";
  return `<div class="growth-bar-wrap">
    <div class="growth-bar"><div class="growth-bar-fill" style="width:${pct}%;background:${color};"></div></div>
    <span class="growth-bar-pct">${fmt(pct, 1)}%</span>
  </div>`;
}

function buildExchangeTooltipHtml(r) {
  return `
    <div class="tooltip-title">${escapeHtml(r.id)}${r.name ? ` — ${escapeHtml(r.name)}` : ""}</div>
    <div class="tooltip-row"><span class="tooltip-label">Reaction</span><code>${escapeHtml(r.reaction_string || "—")}</code></div>
    <div class="tooltip-row"><span class="tooltip-label">Subsystem</span>${escapeHtml(r.subsystem || "—")}</div>
    <div class="tooltip-row"><span class="tooltip-label">GPR</span>${escapeHtml(r.gene_reaction_rule || "—")}</div>
    <div class="tooltip-row"><span class="tooltip-label">Bounds</span>[${fmt(r.lower_bound, 2)}, ${fmt(r.upper_bound, 2)}]</div>
    <div class="tooltip-row"><span class="tooltip-label">WT flux</span>${fmt(r.wt_flux)}</div>
    <div class="tooltip-row"><span class="tooltip-label">KO growth</span>${fmt(r.ko_growth)} (${escapeHtml(r.ko_status)})</div>
  `;
}

// ---------------------------------------------------------------------------
// Generic row-hover tooltip: a single fixed-position element reused across
// tables (so it's never clipped by a scrolling .table-wrap), populated and
// repositioned as the mouse moves over rows carrying a data-row-id.
// ---------------------------------------------------------------------------

let TOOLTIP_EL = null;
function ensureTooltip() {
  if (!TOOLTIP_EL) {
    TOOLTIP_EL = document.createElement("div");
    TOOLTIP_EL.className = "hover-tooltip";
    document.body.appendChild(TOOLTIP_EL);
  }
  return TOOLTIP_EL;
}
function positionTooltip(x, y) {
  const el = ensureTooltip();
  const pad = 16;
  const rect = el.getBoundingClientRect();
  let left = x + pad;
  let top = y + pad;
  if (left + rect.width > window.innerWidth - 8) left = x - rect.width - pad;
  if (top + rect.height > window.innerHeight - 8) top = y - rect.height - pad;
  el.style.left = Math.max(8, left) + "px";
  el.style.top = Math.max(8, top) + "px";
}
function showTooltip(html, x, y) {
  const el = ensureTooltip();
  el.innerHTML = html;
  el.style.display = "block";
  positionTooltip(x, y);
}
function hideTooltip() {
  if (TOOLTIP_EL) TOOLTIP_EL.style.display = "none";
}

function attachRowTooltip(tbodyId, rowsById, buildHtml) {
  const tbody = $(tbodyId);
  if (!tbody) return;
  let lastRowId = null;
  tbody.addEventListener("mousemove", ev => {
    const tr = ev.target.closest("tr[data-row-id]");
    if (!tr) { hideTooltip(); lastRowId = null; return; }
    const rowId = tr.dataset.rowId;
    if (rowId !== lastRowId) {
      const row = rowsById.get(rowId);
      if (!row) { hideTooltip(); lastRowId = null; return; }
      showTooltip(buildHtml(row), ev.clientX, ev.clientY);
      lastRowId = rowId;
    } else {
      positionTooltip(ev.clientX, ev.clientY);
    }
  });
  tbody.addEventListener("mouseleave", () => { hideTooltip(); lastRowId = null; });
}

// Small colored tag for a metabolite's net role in the biomass/objective
// reaction(s) specifically -- distinct from the per-model produced/consumed
// *counts* further down the row, which tally every reaction in the model.
const BIOMASS_ROLE_INFO = {
  produced: "Net produced by the objective/biomass reaction(s) (positive net stoichiometric coefficient).",
  consumed: "Net consumed by the objective/biomass reaction(s) (negative net stoichiometric coefficient) -- a biomass building block.",
  neutral: "Net coefficient in the objective/biomass reaction(s) is zero (cancels out across multiple objective reactions, if more than one).",
};
function biomassRoleBadge(role) {
  const cls = role === "produced" ? "good" : role === "consumed" ? "bad" : "";
  const info = BIOMASS_ROLE_INFO[role];
  return `<span class="badge ${cls}"${info ? ` title="${escapeHtml(info)}"` : ""}>${escapeHtml(role || "—")}</span>`;
}

const OBJECTIVE_TABLE_COLUMNS = [
  { key: "metabolite_id", label: "Original ID" },
  { key: "metabolite_metanetx_id", label: "MetaNetX ID" },
  { key: "metabolite_name", label: "Name" },
  { key: "compartment", label: "Compartment", value: o => COMP_NAMES[o.compartment] || o.compartment || "" },
  { key: "coefficient", label: "Coefficient" },
  { key: "biomass_role", label: "Biomass role" },
  { key: "direct_exchange", label: "Direct Exchange?" },
  // { key: "appears_in_reactions", label: "In Objective Reactions" },
  { key: "reaction_count", label: "# Reactions (model-wide)" },
  { key: "produced_count", label: "# Produced in" },
  { key: "consumed_count", label: "# Consumed in" },
  { key: "reversible_count", label: "# Reversible" },
];

let objCurrentRows = [];

// Card(s) showing the full biomass/objective reaction expression -- both by
// metabolite name (easier to read) and by metabolite id (matches the ids in
// the table below) -- for the Objective tab and the report's Objective
// section.
function objectiveReactionExpressionHtml(open) {
  const comps = (DATA.objective || []).filter(c => c && !c.error);
  if (!comps.length) return "";
  return `
    <details class="biomass-details"${open ? " open" : ""}>
      <summary>Biomass / objective reaction${comps.length > 1 ? "s" : ""} — expression (by metabolite ID)</summary>
      <div class="biomass-body objective-grid">
        ${comps.map(c => `
          <div class="objective-card">
            <div class="mini-stat-label">${escapeHtml(c.reaction_id)}${c.reaction_name ? " — " + escapeHtml(c.reaction_name) : ""}</div>
            <div class="reaction-expr">${escapeHtml(c.reaction || "—")}</div>
          </div>
        `).join("")}
      </div>
    </details>
  `;
}

function renderObjective() {
  $("objective").innerHTML = `
    ${objectiveReactionExpressionHtml()}
    <div class="note bio-link" style="background:#eff6ff;border-color:#bfdbfe;color:#1e3a8a;">
      Can the cell actually make every biomass precursor? <button type="button" id="objPrecBtn">Check precursor producibility →</button>
    </div>
    <div class="toolbar">
      <input id="objSearch" type="text" placeholder="Filter metabolite or exchange…">
      <select id="objBiomassRole">
        <option value="">Biomass role: all</option>
        <option value="produced">Biomass role: produced</option>
        <option value="consumed">Biomass role: consumed</option>
      </select>
    </div>
    <div class="table-wrap"><table id="objTable">
      <thead><tr>
        <th data-key="metabolite_id">Original ID</th>
        <th data-key="metabolite_metanetx_id">MetaNetX ID</th>
        <th data-key="metabolite_name" class="col-name-md">Name</th>
        <th data-key="compartment">Compartment</th>
        <th data-key="coefficient">Coefficient</th>
        <th data-key="biomass_role">Biomass role</th>
        <th data-key="direct_exchange">Direct Exchange?</th>
        <!-- <th data-key="appears_in_reactions">In Objective Reactions</th> -->
        <th data-key="reaction_count"># Reactions (model-wide)</th>
        <th data-key="produced_count"># Produced in</th>
        <th data-key="consumed_count"># Consumed in</th>
        <th data-key="reversible_count"># Reversible</th>
      </tr></thead>
      <tbody id="objBody"></tbody>
    </table></div>
  `;

  const redraw = (filtered) => {
    const q = $("objSearch").value.toLowerCase();
    const role = $("objBiomassRole").value;
    const rows = filtered ? filtered : (DATA.objective_metabolites || []).filter(o =>
      (!q || `${o.metabolite_id} ${o.metabolite_metanetx_id || ""} ${o.metabolite_name} ${o.direct_exchange || ""}`.toLowerCase().includes(q)) &&
      (!role || o.biomass_role === role)
    );
    objCurrentRows = rows;

    $("objBody").innerHTML = rows.length > 0 ? rows.map(o => `<tr>
      <td><strong><a href="#met-${escapeHtml(o.metabolite_id)}" style="cursor:pointer;color:inherit;text-decoration:underline;">${escapeHtml(o.metabolite_id)}</a></strong></td>
      <td>${escapeHtml(o.metabolite_metanetx_id || "—")}</td>
      <td class="col-name-md" title="${escapeHtml(o.metabolite_name || "")}">${escapeHtml(o.metabolite_name || "—")}</td>
      <td>${compartmentBadges([o.compartment])}</td>
      <td>${fmt(o.coefficient, 8)}</td>
      <td>${biomassRoleBadge(o.biomass_role)}</td>
      <td>${o.direct_exchange ? `<strong>${escapeHtml(o.direct_exchange)}</strong>` : "—"}</td>
      <!-- <td class="num">${o.appears_in_reactions}</td> -->
      <td class="num">${o.reaction_count ?? 0}</td>
      <td class="num">${o.produced_count ?? 0}</td>
      <td class="num">${o.consumed_count ?? 0}</td>
      <td class="num">${o.reversible_count ?? 0}</td>
    </tr>`).join("") : `<tr><td colspan="12" class="note">No objective metabolites found (or all filtered as common).</td></tr>`;
  };

  $("objPrecBtn").addEventListener("click", () => goToTab("precursors"));
  ["objSearch","objBiomassRole"].forEach(id => $(id).addEventListener("input", () => redraw()));
  redraw();
  setTimeout(() => makeSortable("objTable", DATA.objective_metabolites || [], redraw), 0);
  attachTableTools("objTable", $("objective").querySelector(".toolbar"), OBJECTIVE_TABLE_COLUMNS, () => objCurrentRows, "objective_metabolites");
}

function formatStoich(rows) {
  if (!rows || !rows.length) return "—";
  return rows.map(x => `${fmt(Math.abs(x.coefficient), 8)} × ${escapeHtml(x.name || x.id)} <span class="badge" title="Compartment code: ${escapeHtml(x.compartment || "?")}">${escapeHtml(x.id)} [${escapeHtml(COMP_NAMES[x.compartment] || x.compartment || "?")}]</span>`).join("<br>");
}

function subsystems(rows) {
  return [...new Set(rows.map(r => r.subsystem).filter(Boolean))].sort();
}

// Plain-language definitions for every reaction classification this app
// uses (see classify_reactions() in app.py), shown as a hover tooltip
// wherever the tag itself appears — table cells, stat cards, audit "Kind"
// columns — so a tag like "demand" is self-explanatory without needing the
// analysis-rule footnotes. Compartment tags are handled separately by
// compartmentBadges() below and intentionally don't use this.
const REACTION_TYPE_INFO = {
  exchange: "Exchange reaction: a boundary reaction that lets this metabolite enter or leave the system across the model's outer boundary (COBRApy model.exchanges).",
  demand: "Demand reaction: an irreversible outlet that consumes a metabolite without producing anything, used to drain it out of the system (COBRApy model.demands) — often for a dead-end or a metabolite being force-produced.",
  sink: "Sink reaction: a reversible outlet allowing a metabolite to be added to or removed from the system, typically for metabolites with an unspecified source or fate (COBRApy model.sinks).",
  transport: "Transport reaction: its metabolites span more than one compartment, moving material between compartments (heuristic: not exchange/demand/sink, but touches >1 compartment).",
  internal: "Internal reaction: an ordinary metabolic reaction confined to a single compartment (not exchange, demand, sink, or transport).",
};

function reactionTypeBadge(type) {
  const info = REACTION_TYPE_INFO[type];
  return `<span class="badge"${info ? ` title="${escapeHtml(info)}"` : ""}>${escapeHtml(type)}</span>`;
}

// Compartment badge showing the full friendly name (e.g. "Cytosol") instead
// of the raw shorthand code, with the code itself available on hover for
// anyone who wants to cross-check it against the model file. Used wherever
// a compartment is displayed, so the full name shows up consistently across
// every table (Metabolites, Reactions, Objective, Exchanges, Tracer, ...).
function compartmentBadges(compartmentIds) {
  const ids = (compartmentIds || []).filter(Boolean);
  if (!ids.length) return "—";
  return ids.map(id =>
    `<span class="badge" title="Compartment code: ${escapeHtml(id)}">${escapeHtml(COMP_NAMES[id] || id)}</span>`
  ).join(" ");
}

// ---------------------------------------------------------------------------
// Minimal Medium tab (on-request, as soon as the model loads).
//
// Separate from the "Diet / media" choice made before clicking "Analyze
// model" (which, for mode "minimal", permanently constrains the analyzed
// model to a computed minimal medium at 100% of its own max growth). This
// tab instead reports -- non-destructively, repeatable for any growth
// cutoff -- what the minimal nutrient set looks like, without touching the
// model that's actually being analyzed elsewhere in the app.
// ---------------------------------------------------------------------------

let MINMED_RESULT = null;

function renderMinimalMedium() {
  $("minmed").innerHTML = `
    <div class="note">
      Compute the smallest set of nutrients (exchange reactions) that sustains a chosen fraction of the model's
      own maximum growth rate, via <code>cobra.medium.minimal_medium</code>. This is a separate, on-request
      calculation from the "Diet / media" choice made before analysis — it never changes the analyzed model, and
      you can recompute it for a different growth cutoff at any time.
    </div>
    <div class="toolbar">
      <label for="minmedCutoff">Growth cutoff (fraction of WT growth, 0–1)</label>
      <input id="minmedCutoff" type="number" min="0.01" max="1" step="0.01" value="1.0" style="width:5.5em;">
      <button id="minmedRunBtn" type="button">Compute minimal medium</button>
      <span id="minmedCount"></span>
    </div>
    <div id="minmedStatus" class="debug-status"></div>
    ${progressBarHtml("minmedProgress")}
    <div id="minmedResults"></div>
  `;
  $("minmedRunBtn").addEventListener("click", runMinimalMedium);
}

async function runMinimalMedium() {
  const cutoffInput = $("minmedCutoff");
  let cutoff = parseFloat(cutoffInput.value);
  if (!Number.isFinite(cutoff) || cutoff <= 0) cutoff = 1.0;
  cutoff = Math.max(0.01, Math.min(1, cutoff));
  cutoffInput.value = cutoff;

  if (!MODEL_ID) {
    $("minmedStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`;
    return;
  }

  const btn = $("minmedRunBtn");
  btn.disabled = true;
  $("minmedStatus").textContent = `Computing minimal medium at ${(cutoff * 100).toFixed(0)}% of WT growth…`;
  progressStart("minmedProgress");
  $("minmedResults").innerHTML = "";
  $("minmedCount").textContent = "";

  try {
    const res = await fetch("/api/minimal-medium", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: MODEL_ID, growth_cutoff_fraction: cutoff }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Minimal medium computation failed");

    MINMED_RESULT = data;
    $("minmedStatus").textContent = data.note || "";
    progressDone("minmedProgress");
    renderMinimalMediumTable(data.components || []);
    setTimeout(() => makeSortable("minmedTable", data.components || [], renderMinimalMediumTable), 0);
  } catch (err) {
    MINMED_RESULT = null;
    $("minmedStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    progressDone("minmedProgress");
    $("minmedResults").innerHTML = "";
  } finally {
    btn.disabled = false;
  }
}

const MINMED_CSV_COLUMNS = [
  { key: "exchange_id", label: "Exchange Original ID" },
  { key: "exchange_metanetx_id", label: "Exchange MetaNetX ID" },
  { key: "exchange_name", label: "Exchange reaction name" },
  { key: "metabolite_id", label: "Metabolite Original ID" },
  { key: "metabolite_metanetx_id", label: "Metabolite MetaNetX ID" },
  { key: "metabolite_name", label: "Metabolite name" },
  { key: "uptake_flux", label: "Flux" },
];

let minmedCurrentRows = [];

function renderMinimalMediumTable(components) {
  minmedCurrentRows = components;
  $("minmedCount").textContent = `${components.length} component(s)`;
  if (!components.length) {
    $("minmedResults").innerHTML = `<div class="note">No components returned.</div>`;
    return;
  }
  $("minmedResults").innerHTML = `
    <div class="toolbar"></div>
    <div class="table-wrap"><table id="minmedTable">
      <thead><tr>
        <th data-key="exchange_id">Exchange Original ID</th>
        <th data-key="exchange_metanetx_id">Exchange MetaNetX ID</th>
        <th data-key="exchange_name">Exchange reaction name</th>
        <th data-key="metabolite_id">Metabolite Original ID</th>
        <th data-key="metabolite_metanetx_id">Metabolite MetaNetX ID</th>
        <th data-key="metabolite_name">Metabolite name</th>
        <th data-key="uptake_flux">Flux</th>
      </tr></thead>
      <tbody>${components.map(c => `<tr>
        <td><strong>${escapeHtml(c.exchange_id)}</strong></td>
        <td>${escapeHtml(c.exchange_metanetx_id || "—")}</td>
        <td class="wrap">${escapeHtml(c.exchange_name || "—")}</td>
        <td>${escapeHtml(c.metabolite_id || "—")}</td>
        <td>${escapeHtml(c.metabolite_metanetx_id || "—")}</td>
        <td>${escapeHtml(c.metabolite_name || "—")}</td>
        <td class="num">${fmt(c.uptake_flux, 4)}</td>
      </tr>`).join("")}</tbody>
    </table></div>
  `;
  attachTableTools("minmedTable", $("minmedResults").querySelector(".toolbar"), MINMED_CSV_COLUMNS, () => minmedCurrentRows, "minimal_medium");
}

// ---------------------------------------------------------------------------
// Network Gaps tab (on-request, as soon as the model loads).
//
// Two complementary diagnostics under the model's current bounds (whatever
// diet was applied at upload): reactions that can't carry any flux at all
// ("blocked"), and metabolites that structurally can only ever be produced
// or only ever be consumed ("dead ends") -- often *why* a reaction ends up
// blocked, though not the only possible reason, which is why both are shown
// together. Both tables export to CSV independently.
// ---------------------------------------------------------------------------

let NETGAPS_RESULT = null;

const NETGAPS_BLOCKED_CSV_COLUMNS = [
  { key: "id", label: "Original ID" },
  { key: "metanetx_id", label: "MetaNetX ID" },
  { key: "name", label: "Reaction name" },
  { key: "subsystem", label: "Subsystem" },
  { key: "type", label: "Type" },
  { key: "compartments", label: "Compartment", value: r => (r.compartments || []).map(c => COMP_NAMES[c] || c).join("; ") },
  { key: "lower_bound", label: "LB" },
  { key: "upper_bound", label: "UB" },
  { key: "gene_reaction_rule", label: "GPR" },
  { key: "reaction_string", label: "Reaction" },
];
const NETGAPS_DEADEND_CSV_COLUMNS = [
  { key: "id", label: "Metabolite Original ID" },
  { key: "metanetx_id", label: "Metabolite MetaNetX ID" },
  { key: "name", label: "Metabolite name" },
  { key: "compartment", label: "Compartment" },
  { key: "reason", label: "Reason" },
  { key: "reactions", value: r => join(r.reactions), label: "Reactions involved" },
];
// Positional subset of NETGAPS_BLOCKED_CSV_COLUMNS matching the Blocked
// reactions table's actual <th> order (that constant has one extra field,
// reaction_string, offered only in the Export panel via exportColumns, not
// shown as its own table column).
const NETGAPS_BLOCKED_TABLE_COLUMNS = NETGAPS_BLOCKED_CSV_COLUMNS.slice(0, 9);

const NETGAPS_REASON_LABELS = {
  no_consuming_reaction: "Never consumed (only ever produced)",
  no_producing_reaction: "Never produced (only ever consumed)",
  fully_blocked: "Fully blocked (bounds allow neither direction)",
  no_reactions: "No reactions at all",
};

function renderNetworkGaps() {
  $("gaps").innerHTML = `
    <h2>Blocked reactions &amp; dead-end metabolites</h2>
    <div class="note">
      Two independent structural diagnostics: reactions that can't carry any flux at all under the model's
      current bounds (via COBRApy's flux-variability-based <code>find_blocked_reactions</code>), and metabolites
      that can only ever be produced or only ever be consumed given their reactions' bounds/reversibility alone
      ("dead ends", judged purely by stoichiometry and directionality — not informed by the blocked-reaction
      results). Any metabolite that participates in a transport reaction is excluded from the dead-end list,
      since a transporter can supply or drain that exact species from another compartment even when it looks
      locally dead-ended. Neither diagnostic ever changes the analyzed model.
      <strong>Blocked reactions are relative to the medium/diet currently applied to this model</strong> —
      switching to a different diet (or editing exchange bounds) can unblock a reaction shown here, or block one
      that isn't. Blocked-reaction detection can take a while for large models (it runs flux variability analysis
      on every reaction that carries no flux in the current solution).
    </div>
    <div class="toolbar">
      <button id="gapsRunBtn" type="button">Compute network gaps</button>
      <span id="gapsCount"></span>
    </div>
    <div id="gapsStatus" class="debug-status"></div>
    ${progressBarHtml("gapsProgress")}
    <div id="gapsResults"></div>

    <h2>Demand &amp; sink audit</h2>
    <div class="note">
      Every demand and sink reaction (single-metabolite boundary reactions used for things like forced
      accumulation or buffered cofactor pools — distinct from exchanges, so they don't appear in the Exchange
      essentiality tab), with its bounds, whether it carries flux in the current FBA solution, and the same
      reaction-knockout essentiality test used for exchanges. A demand/sink that's unused AND non-essential is a
      reasonable candidate for "does the model still need this?" — and one that's unused but silently essential
      (like an over-permissive sink papering over a thermodynamically unrealistic loop) is worth a closer look.
    </div>
    <div class="toolbar">
      <button id="dsAuditRunBtn" type="button">Run demand &amp; sink audit</button>
      <span id="dsAuditCount"></span>
    </div>
    <div id="dsAuditStatus" class="debug-status"></div>
    ${progressBarHtml("dsAuditProgress")}
    <div id="dsAuditResults"></div>
  `;
  $("gapsRunBtn").addEventListener("click", runNetworkGaps);
  $("dsAuditRunBtn").addEventListener("click", runDemandSinkAudit);
}

async function runNetworkGaps() {
  if (!MODEL_ID) {
    $("gapsStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`;
    return;
  }

  const btn = $("gapsRunBtn");
  btn.disabled = true;
  $("gapsStatus").textContent = "Computing blocked reactions and dead-end metabolites…";
  progressStart("gapsProgress");
  $("gapsResults").innerHTML = "";
  $("gapsCount").textContent = "";

  try {
    const res = await fetch("/api/network-gaps", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: MODEL_ID }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Network gaps computation failed");

    NETGAPS_RESULT = data;
    $("gapsStatus").textContent = data.note || "";
    progressDone("gapsProgress");
    $("gapsCount").textContent =
      `${data.blocked_reactions.length} blocked reaction(s) · ${data.dead_end_metabolites.length} dead-end metabolite(s)`;
    renderNetworkGapsResults(data);
  } catch (err) {
    NETGAPS_RESULT = null;
    $("gapsStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    progressDone("gapsProgress");
    $("gapsResults").innerHTML = "";
  } finally {
    btn.disabled = false;
  }
}

function renderNetworkGapsResults(data) {
  if (typeof updateThresholdVerdicts === "function") setTimeout(updateThresholdVerdicts, 0);
  $("gapsResults").innerHTML = `
    <h3>Blocked reactions</h3>
    <div id="gapsBlockedWrap"></div>
    <h3>Dead-end metabolites</h3>
    <div id="gapsDeadendWrap"></div>
  `;
  renderBlockedReactionsTable(data.blocked_reactions || []);
  setTimeout(() => makeSortable("gapsBlockedTable", data.blocked_reactions || [], renderBlockedReactionsTable), 0);
  renderDeadEndTable(data.dead_end_metabolites || []);
  setTimeout(() => makeSortable("gapsDeadendTable", data.dead_end_metabolites || [], renderDeadEndTable), 0);
}

let gapsBlockedCurrentRows = [];
let gapsDeadendCurrentRows = [];

function renderBlockedReactionsTable(rows) {
  gapsBlockedCurrentRows = rows;
  const wrap = $("gapsBlockedWrap");
  if (!rows.length) {
    wrap.innerHTML = `<div class="note">No blocked reactions found under the model's current bounds.</div>`;
    return;
  }
  wrap.innerHTML = `
    <div class="toolbar"></div>
    <div class="table-wrap"><table id="gapsBlockedTable">
      <thead><tr>
        <th data-key="id">Original ID</th>
        <th data-key="metanetx_id">MetaNetX ID</th>
        <th data-key="name">Name</th>
        <th data-key="subsystem">Subsystem</th>
        <th data-key="type">Type</th>
        <th data-key="compartments">Compartment</th>
        <th data-key="lower_bound">LB</th>
        <th data-key="upper_bound">UB</th>
        <th data-key="gene_reaction_rule">GPR</th>
      </tr></thead>
      <tbody>${rows.map(r => `<tr class="${r.metanetx_id ? "" : "row-unmapped"}">
        <td><strong>${escapeHtml(r.id)}</strong></td>
        <td>${escapeHtml(r.metanetx_id || "—")}</td>
        <td class="wrap">${escapeHtml(r.name || "—")}</td>
        <td>${escapeHtml(r.subsystem || "—")}</td>
        <td>${reactionTypeBadge(r.type)}</td>
        <td>${compartmentBadges(r.compartments)}</td>
        <td class="num">${fmt(r.lower_bound, 2)}</td>
        <td class="num">${fmt(r.upper_bound, 2)}</td>
        <td class="wrap">${escapeHtml(r.gene_reaction_rule || "—")}</td>
      </tr>`).join("")}</tbody>
    </table></div>
  `;
  attachTableTools("gapsBlockedTable", wrap.querySelector(".toolbar"), NETGAPS_BLOCKED_TABLE_COLUMNS, () => gapsBlockedCurrentRows, "blocked_reactions", NETGAPS_BLOCKED_CSV_COLUMNS);
}

function renderDeadEndTable(rows) {
  gapsDeadendCurrentRows = rows;
  const wrap = $("gapsDeadendWrap");
  if (!rows.length) {
    wrap.innerHTML = `<div class="note">No dead-end metabolites found.</div>`;
    return;
  }
  wrap.innerHTML = `
    <div class="toolbar"></div>
    <div class="table-wrap"><table id="gapsDeadendTable">
      <thead><tr>
        <th data-key="id">Metabolite Original ID</th>
        <th data-key="metanetx_id">Metabolite MetaNetX ID</th>
        <th data-key="name">Metabolite name</th>
        <th data-key="compartment">Compartment</th>
        <th data-key="reason">Reason</th>
        <th data-key="reactions">Reactions involved</th>
      </tr></thead>
      <tbody>${rows.map(r => `<tr>
        <td><strong>${escapeHtml(r.id)}</strong></td>
        <td>${escapeHtml(r.metanetx_id || "—")}</td>
        <td>${escapeHtml(r.name || "—")}</td>
        <td>${compartmentBadges([r.compartment])}</td>
        <td>${escapeHtml(NETGAPS_REASON_LABELS[r.reason] || r.reason)}</td>
        <td class="wrap">${escapeHtml(join(r.reactions))}</td>
      </tr>`).join("")}</tbody>
    </table></div>
  `;
  attachTableTools("gapsDeadendTable", wrap.querySelector(".toolbar"), NETGAPS_DEADEND_CSV_COLUMNS, () => gapsDeadendCurrentRows, "dead_end_metabolites");
}

let DSAUDIT_RESULT = null;

const DSAUDIT_CSV_COLUMNS = [
  { key: "id", label: "Reaction ID" },
  { key: "name", label: "Reaction name" },
  { key: "kind", label: "Kind (demand/sink)" },
  { key: "metabolite_id", label: "Metabolite ID" },
  { key: "metabolite_name", label: "Metabolite name" },
  { key: "compartment", label: "Compartment" },
  { key: "lower_bound", label: "LB" },
  { key: "upper_bound", label: "UB" },
  { key: "wt_flux", label: "WT flux" },
  { value: r => (r.used_in_wt_solution ? "Yes" : "No"), label: "Used in WT solution?" },
  { key: "ko_growth", label: "KO growth" },
  { value: r => (r.ko_growth_fraction == null ? "" : r.ko_growth_fraction), label: "KO growth fraction" },
  { value: r => (r.essential ? "Yes" : "No"), label: "Essential?" },
];
// Positional subset/reshaping of DSAUDIT_CSV_COLUMNS matching the Demand &
// sink audit table's actual <th> order (that table merges metabolite
// name+id into one visible cell and doesn't show compartment/ko_growth as
// separate columns; the fuller DSAUDIT_CSV_COLUMNS is offered via
// exportColumns instead).
const DSAUDIT_TABLE_COLUMNS = [
  { key: "kind", label: "Kind" },
  { key: "id", label: "ID" },
  { key: "name", label: "Name" },
  { key: "metabolite_id", label: "Metabolite", value: r => r.metabolite_name || r.metabolite_id || "" },
  { key: "lower_bound", label: "LB" },
  { key: "upper_bound", label: "UB" },
  { key: "wt_flux", label: "WT flux" },
  { key: "ko_growth_fraction", label: "Growth retained after KO" },
  { key: "essential", label: "Essential?", value: r => (r.essential ? "Yes" : "No") },
];

async function runDemandSinkAudit() {
  if (!MODEL_ID) {
    $("dsAuditStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`;
    return;
  }

  const btn = $("dsAuditRunBtn");
  btn.disabled = true;
  $("dsAuditStatus").textContent = "Auditing demand and sink reactions…";
  progressStart("dsAuditProgress");
  $("dsAuditResults").innerHTML = "";
  $("dsAuditCount").textContent = "";

  try {
    const res = await fetch("/api/demand-sink-audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: MODEL_ID }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Demand & sink audit failed");

    DSAUDIT_RESULT = data;
    $("dsAuditStatus").textContent = data.note || "";
    progressDone("dsAuditProgress");
    $("dsAuditCount").textContent = `${data.rows.length} reaction(s)`;
    renderDemandSinkAuditTable(data.rows || []);
    setTimeout(() => makeSortable("dsAuditTable", data.rows || [], renderDemandSinkAuditTable), 0);
  } catch (err) {
    DSAUDIT_RESULT = null;
    $("dsAuditStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    progressDone("dsAuditProgress");
    $("dsAuditResults").innerHTML = "";
  } finally {
    btn.disabled = false;
  }
}

let dsAuditCurrentRows = [];

function renderDemandSinkAuditTable(rows) {
  dsAuditCurrentRows = rows;
  if (!rows.length) {
    $("dsAuditResults").innerHTML = `<div class="note">No demand or sink reactions found in this model.</div>`;
    return;
  }
  $("dsAuditResults").innerHTML = `
    <div class="toolbar"></div>
    <div class="table-wrap"><table id="dsAuditTable">
      <thead><tr>
        <th data-key="kind">Kind</th>
        <th data-key="id">ID</th>
        <th data-key="name">Name</th>
        <th data-key="metabolite_id">Metabolite</th>
        <th data-key="lower_bound">LB</th>
        <th data-key="upper_bound">UB</th>
        <th data-key="wt_flux">WT flux</th>
        <th data-key="ko_growth_fraction">Growth retained after KO</th>
        <th data-key="essential">Essential?</th>
      </tr></thead>
      <tbody>${rows.map(r => `<tr class="${r.essential ? "row-essential" : ""}">
        <td>${reactionTypeBadge(r.kind)}</td>
        <td><strong>${escapeHtml(r.id)}</strong></td>
        <td class="wrap">${escapeHtml(r.name || "—")}</td>
        <td>${escapeHtml(r.metabolite_name || r.metabolite_id || "—")} <span class="stoich">${escapeHtml(r.metabolite_id || "")}</span></td>
        <td class="num">${fmt(r.lower_bound, 2)}</td>
        <td class="num">${fmt(r.upper_bound, 2)}</td>
        <td class="num">${fmt(r.wt_flux)}${r.used_in_wt_solution ? "" : ` <span class="stoich">(unused)</span>`}</td>
        <td>${growthBar(r.ko_growth_fraction)}</td>
        <td><span class="badge ${r.essential ? "bad" : "good"}">${r.essential ? "ESSENTIAL" : "No"}</span></td>
      </tr>`).join("")}</tbody>
    </table></div>
  `;
  attachTableTools("dsAuditTable", $("dsAuditResults").querySelector(".toolbar"), DSAUDIT_TABLE_COLUMNS, () => dsAuditCurrentRows, "demand_sink_audit", DSAUDIT_CSV_COLUMNS);
}

// ---------------------------------------------------------------------------
// Exchange debugging (on-request, after the initial analysis).
//
// Trace, for each essential exchange the user picks, the active-flux path
// from the exchanged metabolite through to biomass — once with the exchange
// active ("before KO") and once with it reversibly knocked out ("after KO"),
// so the two can be compared side by side.
// ---------------------------------------------------------------------------

function showDebugModal(essentialExchanges) {
  renderDebugSelection(essentialExchanges);
  $("debugTab").click();
}

// The Exchange Debugging tab is always available. Until the exchange
// essentiality analysis has finished it shows a short waiting message; once
// done it shows the selection of essential exchanges to trace.
function renderDebugDefault(exchanges, essentialExchanges) {
  if (!exchanges || !exchanges.length) {
    $("debug").innerHTML = `<div class="note">Exchange debugging starts from the essential exchanges found by the exchange essentiality analysis. That analysis is still running (or hasn't started) — this page fills in automatically when it finishes.</div>`;
  } else if (!essentialExchanges.length) {
    $("debug").innerHTML = `<div class="note" style="background:#ecfdf5;border-color:#a7f3d0;color:#047857;">No essential exchanges were found, so there is nothing to debug here. (Essential = knocking out the exchange drops growth below 5% of wild type.)</div>`;
  } else {
    renderDebugSelection(essentialExchanges);
  }
}

function renderDebugSelection(essentialExchanges) {
  const rows = essentialExchanges.map(e => `
    <label class="debug-check-row">
      <input type="checkbox" class="debugExCheck" value="${escapeHtml(e.id)}" checked>
      <span class="debug-check-id">${escapeHtml(e.id)}</span>
      <span class="debug-check-name">${escapeHtml(join(e.metabolite_names) || join(e.metabolites))}</span>
    </label>`).join("");

  $("debug").innerHTML = `
    <div class="note">
      Trace active flux from each selected essential exchange's metabolite through to biomass — once with the
      exchange active (before knockout) and once with it blocked (after knockout). Only reactions carrying
      non-zero flux in the current FBA solution are followed, so a missing path can mean the metabolite is
      rerouted differently after knockout, or that no active route to biomass remains.
    </div>
    <div class="toolbar">
      <button id="debugSelectAll" type="button">Select all</button>
      <button id="debugSelectNone" type="button">Select none</button>
      <span id="debugSelCount"></span>
      <label class="debug-toggle">
        <input type="checkbox" id="debugHideTrivial" checked>
        Hide common cofactors (H, H2O, ATP/ADP, NAD(H), Pi…)
      </label>
      <button id="debugRunBtn" type="button" style="margin-left:auto;">Run debugging analysis</button>
    </div>
    <div class="debug-select-list">${rows || '<div class="note">No essential exchanges to debug.</div>'}</div>
    <div id="debugStatus" class="debug-status"></div>
    ${progressBarHtml("debugProgress")}
    <div id="debugResults"></div>
  `;

  const checks = () => Array.from(document.querySelectorAll(".debugExCheck"));
  const updateCount = () => {
    const n = checks().filter(c => c.checked).length;
    $("debugSelCount").textContent = `${n} selected`;
  };
  checks().forEach(c => c.addEventListener("change", updateCount));
  updateCount();

  const selectAllBtn = $("debugSelectAll");
  const selectNoneBtn = $("debugSelectNone");
  if (selectAllBtn) selectAllBtn.addEventListener("click", () => { checks().forEach(c => c.checked = true); updateCount(); });
  if (selectNoneBtn) selectNoneBtn.addEventListener("click", () => { checks().forEach(c => c.checked = false); updateCount(); });

  const runBtn = $("debugRunBtn");
  if (runBtn) {
    runBtn.addEventListener("click", () => {
      const selected = checks().filter(c => c.checked).map(c => c.value);
      if (!selected.length) {
        $("debugStatus").innerHTML = `<span class="error">Select at least one exchange to debug.</span>`;
        return;
      }
      const hideTrivial = $("debugHideTrivial") ? $("debugHideTrivial").checked : true;
      runDebugAnalysis(selected, hideTrivial);
    });
  }
}

async function runDebugAnalysis(exchangeIds, hideTrivial) {
  const btn = $("debugRunBtn");
  if (btn) btn.disabled = true;
  $("debugStatus").textContent = `Tracing ${exchangeIds.length} exchange(s) to biomass (before and after knockout)…`;
  progressStart("debugProgress");
  $("debugResults").innerHTML = "";

  try {
    if (!MODEL_ID) throw new Error("Model session expired — please re-run the initial analysis.");

    const res = await fetch("/api/debug-exchanges", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: MODEL_ID,
        exchange_ids: exchangeIds,
        exclude_trivial_metabolites: hideTrivial,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Debug analysis failed");

    $("debugStatus").textContent = `Done. Biomass reaction: ${data.biomass_reaction}. ${data.trivial_metabolite_rule || ""}`;
    progressDone("debugProgress");
    renderDebugResults(data.results);
  } catch (err) {
    $("debugStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    progressDone("debugProgress");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderDebugResults(results) {
  const cards = Object.entries(results).map(([exchId, r]) => {
    if (r.error) {
      return `<div class="debug-card">
        <h3>${escapeHtml(exchId)}</h3>
        <div class="error">${escapeHtml(r.error)}</div>
      </div>`;
    }
    const gi = r.growth_impact || {};
    return `<div class="debug-card">
      <h3>${escapeHtml(r.exchange_id)} <span class="stoich">${escapeHtml(r.exchange_name || "")}</span></h3>
      <dl class="kv">
        <dt>Exchanged metabolite</dt>
        <dd>${escapeHtml(r.internal_metabolite.name || r.internal_metabolite.id)} <span class="badge">${escapeHtml(r.internal_metabolite.id)}</span></dd>
        <dt>Biomass reaction</dt><dd>${escapeHtml(r.biomass_reaction)}</dd>
        <dt>WT growth</dt><dd>${fmt(gi.wt_growth)}</dd>
        <dt>Growth after KO</dt>
        <dd>${fmt(gi.ko_growth)}${gi.ko_growth_fraction == null ? "" : ` (${fmt(gi.ko_growth_fraction * 100, 2)}% of WT)`}</dd>
      </dl>
      <div class="debug-compare">
        <div class="debug-col">
          <h4>Before KO</h4>
          ${renderDebugTrace(r.before_ko)}
        </div>
        <div class="debug-col">
          <h4>After KO</h4>
          ${renderDebugTrace(r.after_ko)}
        </div>
      </div>
    </div>`;
  }).join("");

  $("debugResults").innerHTML = cards || `<div class="note">No results.</div>`;
}

function renderDebugTrace(trace) {
  if (!trace) return `<div class="note">No data.</div>`;
  if (trace.status !== "success") {
    return `<div class="note">FBA status: ${escapeHtml(trace.status)}${trace.error ? " — " + escapeHtml(trace.error) : ""}</div>`;
  }
  const header = `<div class="stoich">Exchange flux: ${fmt(trace.exchange_flux)} · Biomass flux: ${fmt(trace.biomass_flux)} · Active reactions: ${trace.num_active_reactions}</div>`;
  if (!trace.paths || !trace.paths.length) {
    return header + `<div class="note">No active-flux pathway to biomass found.</div>`;
  }
  const paths = trace.paths.map((p, i) => {
    const steps = p.reactions.map((rxn, idx) => {
      const met = p.metabolites[idx + 1];
      return `<div class="debug-step">
        <span class="debug-arrow">↓</span> <span class="badge">${escapeHtml(rxn.id)}</span> flux=${fmt(rxn.flux)}
        <div class="debug-met">→ ${escapeHtml(met.name || met.id)} <span class="stoich">${escapeHtml(met.id)}</span></div>
      </div>`;
    }).join("");
    return `<div class="debug-path">
      <div class="debug-path-title">Path ${i + 1}</div>
      <div class="debug-met">${escapeHtml(p.metabolites[0].name || p.metabolites[0].id)} <span class="stoich">${escapeHtml(p.metabolites[0].id)}</span></div>
      ${steps}
    </div>`;
  }).join("");
  return header + paths;
}

// ---------------------------------------------------------------------------
// Pathway Tracer — a general-purpose module, separate from exchange
// essentiality/debugging. Traces active-flux paths between ANY starting
// point (a metabolite, or a reaction resolved to its current-flux products)
// and ANY target metabolite, for however many BFS "levels" the user asks
// for. Never runs on its own — the tab renders an empty selection form as
// soon as the model loads, and nothing is computed until "Run trace" is
// clicked. Two view modes: a text/words view (same style as the exchange
// debugger) and an interactive, filterable Cytoscape.js network view.
// ---------------------------------------------------------------------------

let TRACER_RESULT = null;
let TRACER_CY = null;
let TRACER_KO_VIEW = "before";     // "before" | "after" — which snapshot the words/network view renders
let TRACER_HIGHLIGHT_KO = true;    // whether changed reactions are called out (badge / edge color)

function renderTracer() {
  const metOptions = (DATA.metabolites || []).map(m => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.name || "")}</option>`).join("");
  const rxnOptions = (DATA.reactions || []).map(r => `<option value="${escapeHtml(r.id)}">${escapeHtml(r.name || "")}</option>`).join("");

  $("tracer").innerHTML = `
    <div class="note">
      Trace active-flux pathways between any starting point and any target metabolite — not tied to biomass or
      exchanges. Only reactions carrying non-zero flux in the current FBA solution are followed, and common
      cofactors can be hidden from the trace, same as exchange debugging. Nothing runs automatically — pick a
      start and target below and click "Run trace".
    </div>
    <datalist id="tracerMetList">${metOptions}</datalist>
    <datalist id="tracerRxnList">${rxnOptions}</datalist>
    <datalist id="tracerKoList">${metOptions}${rxnOptions}</datalist>
    <div class="tracer-form">
      <div class="tracer-field">
        <label>Start from</label>
        <select id="tracerStartType">
          <option value="metabolite">Metabolite</option>
          <option value="reaction">Reaction</option>
        </select>
      </div>
      <div class="tracer-field tracer-field-wide">
        <label id="tracerStartLabel">Starting metabolite</label>
        <input id="tracerStartId" type="text" list="tracerMetList" placeholder="Search metabolite ID or name…">
      </div>
      <div class="tracer-field tracer-field-wide">
        <label>Target metabolite</label>
        <input id="tracerTargetId" type="text" list="tracerMetList" placeholder="Search metabolite ID or name…">
      </div>
      <div class="tracer-field">
        <label>Max levels</label>
        <input id="tracerMaxLevels" type="number" min="1" max="100" value="15">
      </div>
      <div class="tracer-field">
        <label>Max paths</label>
        <input id="tracerMaxPaths" type="number" min="1" max="100" value="10">
      </div>
      <div class="tracer-field">
        <label>&nbsp;</label>
        <label class="debug-toggle tracer-inline-toggle">
          <input type="checkbox" id="tracerHideTrivial" checked>
          Hide common cofactors
        </label>
      </div>
      <div class="tracer-field">
        <label>View as</label>
        <div class="tracer-view-toggle">
          <label><input type="radio" name="tracerView" value="text" checked> Words</label>
          <label><input type="radio" name="tracerView" value="network"> Network</label>
        </div>
      </div>
      <div class="tracer-field tracer-field-wide">
        <label>Compare knockout (optional)</label>
        <input id="tracerKnockouts" type="text" list="tracerKoList" placeholder="e.g. EX_glc_D_e, atp_c — comma separated">
      </div>
      <div class="tracer-field">
        <label>&nbsp;</label>
        <button id="tracerRunBtn" type="button">Run trace</button>
      </div>
    </div>
    <div class="tracer-ko-hint stoich">
      Leave blank for a single trace. List one or more reaction or metabolite ids to also trace the same
      start → target with them knocked out, so you can toggle before/after and see which reactions in the
      traced paths changed flux. A reaction is blocked directly; a metabolite is "knocked out" by blocking
      every reaction it participates in (can be a large effect for a highly-connected metabolite).
    </div>
    <div id="tracerStatus" class="debug-status"></div>
    ${progressBarHtml("tracerProgress")}
    <div id="tracerResults"></div>
  `;

  const startTypeSel = $("tracerStartType");
  startTypeSel.addEventListener("change", () => {
    const isRxn = startTypeSel.value === "reaction";
    $("tracerStartLabel").textContent = isRxn ? "Starting reaction" : "Starting metabolite";
    $("tracerStartId").setAttribute("list", isRxn ? "tracerRxnList" : "tracerMetList");
    $("tracerStartId").placeholder = isRxn ? "Search reaction ID or name…" : "Search metabolite ID or name…";
    $("tracerStartId").value = "";
  });

  $("tracerRunBtn").addEventListener("click", runPathwayTrace);
  document.querySelectorAll('input[name="tracerView"]').forEach(r => r.addEventListener("change", () => {
    if (TRACER_RESULT) renderTracerActiveView();
  }));
}

async function runPathwayTrace() {
  const startType = $("tracerStartType").value;
  const startId = $("tracerStartId").value.trim();
  const targetId = $("tracerTargetId").value.trim();
  const maxLevels = parseInt($("tracerMaxLevels").value, 10) || 15;
  const maxPaths = parseInt($("tracerMaxPaths").value, 10) || 10;
  const hideTrivial = $("tracerHideTrivial").checked;
  const knockouts = $("tracerKnockouts").value.split(",").map(s => s.trim()).filter(Boolean);

  if (!startId) { $("tracerStatus").innerHTML = `<span class="error">Choose a starting ${escapeHtml(startType)}.</span>`; return; }
  if (!targetId) { $("tracerStatus").innerHTML = `<span class="error">Choose a target metabolite.</span>`; return; }
  if (!MODEL_ID) { $("tracerStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`; return; }

  const btn = $("tracerRunBtn");
  btn.disabled = true;
  $("tracerStatus").textContent = knockouts.length ? "Tracing pathway and comparing knockout…" : "Tracing pathway…";
  progressStart("tracerProgress");
  $("tracerResults").innerHTML = "";
  hideTooltip();
  if (TRACER_CY) { TRACER_CY.destroy(); TRACER_CY = null; }
  TRACER_KO_VIEW = "before";
  TRACER_HIGHLIGHT_KO = true;

  try {
    const res = await fetch("/api/trace-pathway", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_id: MODEL_ID,
        start_type: startType,
        start_id: startId,
        target_metabolite_id: targetId,
        max_levels: maxLevels,
        max_paths: maxPaths,
        exclude_trivial_metabolites: hideTrivial,
        knockouts,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Pathway trace failed");

    TRACER_RESULT = data;
    const starts = data.start_metabolites || [];
    const startLabel = starts.length > 1 ? `${starts.length} starting metabolites` : (starts[0] || {}).id || startId;
    let statusMsg = `Found ${data.paths.length} path(s) from ${startLabel} to ${data.target_metabolite.id} ` +
      `(max ${data.max_levels} levels). Active reactions in solution: ${data.num_active_reactions}.`;
    if (data.knockout) {
      if (data.knockout.error) {
        statusMsg += ` Knockout comparison could not run: ${data.knockout.error}`;
      } else {
        const gi = data.knockout.growth_impact || {};
        statusMsg += ` Knockout comparison ready — WT growth ${fmt(gi.wt_growth)} → KO growth ${fmt(gi.ko_growth)}` +
          `${gi.ko_growth_fraction == null ? "" : ` (${fmt(gi.ko_growth_fraction * 100, 1)}% retained)`}.`;
      }
    }
    $("tracerStatus").textContent = statusMsg;
    progressDone("tracerProgress");
    renderTracerResults();
  } catch (err) {
    TRACER_RESULT = null;
    $("tracerStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    progressDone("tracerProgress");
    $("tracerResults").innerHTML = "";
  } finally {
    btn.disabled = false;
  }
}

function renderTracerResults() {
  if (!TRACER_RESULT) return;
  $("tracerResults").innerHTML = `<div id="tracerKoToolbar"></div><div id="tracerViewContent"></div>`;
  renderTracerKoToolbar();
  renderTracerActiveView();
}

// The optional before/after-knockout comparison toolbar: growth-impact
// summary, a Before KO / After KO toggle, and a "highlight changed
// reactions" checkbox. Rendered once per trace run — the view toggles
// below only re-render #tracerViewContent, not this toolbar, so the user's
// radio/checkbox choices aren't lost while switching Words/Network.
function renderTracerKoToolbar() {
  const el = $("tracerKoToolbar");
  const ko = TRACER_RESULT && TRACER_RESULT.knockout;
  if (!ko) { el.innerHTML = ""; return; }

  if (ko.error) {
    el.innerHTML = `<div class="note error">Knockout comparison: ${escapeHtml(ko.error)}</div>`;
    return;
  }

  const targetsLabel = (ko.targets || []).map(t => `${escapeHtml(t.id)} (${escapeHtml(t.type)})`).join(", ");
  const blockedLabel = (ko.blocked_reactions || []).join(", ");
  const gi = ko.growth_impact || {};
  const hasAfter = !!(ko.after_ko && !ko.after_ko.error);

  el.innerHTML = `
    <div class="tracer-ko-toolbar">
      <div class="tracer-ko-summary">
        <strong>Knockout comparison:</strong> ${targetsLabel} → blocked reaction(s): <code>${escapeHtml(blockedLabel || "—")}</code>.
        WT growth ${fmt(gi.wt_growth)} → KO growth ${fmt(gi.ko_growth)}${gi.ko_growth_fraction == null ? "" : ` (${fmt(gi.ko_growth_fraction * 100, 1)}% retained)`}.
        ${ko.not_found && ko.not_found.length ? `<br><span class="stoich">Not found in model, skipped: ${escapeHtml(ko.not_found.join(", "))}</span>` : ""}
        ${!hasAfter && ko.after_ko && ko.after_ko.error ? `<br><span class="stoich">After-KO trace: ${escapeHtml(ko.after_ko.error)}</span>` : ""}
      </div>
      <div class="tracer-ko-controls">
        <div class="tracer-view-toggle">
          <label><input type="radio" name="tracerKoView" value="before" ${TRACER_KO_VIEW === "before" ? "checked" : ""}> Before KO</label>
          <label><input type="radio" name="tracerKoView" value="after" ${TRACER_KO_VIEW === "after" ? "checked" : ""} ${hasAfter ? "" : "disabled"}> After KO</label>
        </div>
        <label class="debug-toggle tracer-inline-toggle">
          <input type="checkbox" id="tracerHighlightKo" ${TRACER_HIGHLIGHT_KO ? "checked" : ""}>
          Highlight KO-affected reactions
        </label>
      </div>
    </div>
  `;

  document.querySelectorAll('input[name="tracerKoView"]').forEach(r => r.addEventListener("change", ev => {
    TRACER_KO_VIEW = ev.target.value;
    renderTracerActiveView();
  }));
  const highlightCb = $("tracerHighlightKo");
  if (highlightCb) highlightCb.addEventListener("change", () => {
    TRACER_HIGHLIGHT_KO = highlightCb.checked;
    renderTracerActiveView();
  });
}

// The paths currently on display: the baseline ("before KO") trace, or —
// when the toggle is set to "after" and an after-KO trace actually
// succeeded — the after-KO trace's paths instead. Everything else
// (target metabolite, start type/id) is shared between the two, so only
// "paths" and "start_metabolites" need swapping.
function getActiveTracerData() {
  const base = TRACER_RESULT;
  const ko = base && base.knockout;
  if (TRACER_KO_VIEW === "after" && ko && !ko.error && ko.after_ko && !ko.after_ko.error) {
    return Object.assign({}, base, {
      paths: ko.after_ko.paths,
      start_metabolites: ko.after_ko.start_metabolites || base.start_metabolites,
    });
  }
  return base;
}

function renderTracerActiveView() {
  const view = (document.querySelector('input[name="tracerView"]:checked') || {}).value || "text";
  hideTooltip();
  if (TRACER_CY) { TRACER_CY.destroy(); TRACER_CY = null; }
  const data = getActiveTracerData();
  if (view === "network") {
    renderTracerNetworkView(data);
  } else {
    renderTracerTextView(data);
  }
}

// Per-reaction before/after-KO summary, used by both the words view (as an
// inline badge) and the network view (as an edge color class). Returns null
// when there's no knockout comparison, highlighting is off, or this
// reaction isn't one of the ones the comparison tracked.
function tracerFluxDelta(rxnId) {
  if (!TRACER_HIGHLIGHT_KO) return null;
  const ko = TRACER_RESULT && TRACER_RESULT.knockout;
  if (!ko || ko.error || !ko.flux_comparison) return null;
  return ko.flux_comparison[rxnId] || null;
}

function fluxDeltaBadge(rxnId) {
  const fc = tracerFluxDelta(rxnId);
  if (!fc) return "";
  if (fc.active_before && !fc.active_after) {
    return `<span class="badge bad">KO: blocked (${fmt(fc.before_flux)} → 0)</span>`;
  }
  if (!fc.active_before && fc.active_after) {
    return `<span class="badge good">KO: new route (0 → ${fmt(fc.after_flux)})</span>`;
  }
  if (Math.abs(fc.after_flux - fc.before_flux) > 1e-6) {
    return `<span class="badge">KO: ${fmt(fc.before_flux)} → ${fmt(fc.after_flux)}</span>`;
  }
  return `<span class="badge good">KO: unaffected</span>`;
}

function fluxDeltaClass(rxnId) {
  const fc = tracerFluxDelta(rxnId);
  if (!fc) return "";
  if (fc.active_before && !fc.active_after) return "ko-removed";
  if (!fc.active_before && fc.active_after) return "ko-added";
  if (Math.abs(fc.after_flux - fc.before_flux) > 1e-6) return "ko-changed";
  return "";
}

function renderTracerTextView(data) {
  if (!data.paths || !data.paths.length) {
    $("tracerViewContent").innerHTML = `<div class="note">No active-flux pathway found from ${escapeHtml(data.start_id)} to ${escapeHtml(data.target_metabolite.id)} ${TRACER_KO_VIEW === "after" ? "(after knockout)" : ""}.</div>`;
    return;
  }
  const paths = data.paths.map((p, i) => {
    const steps = p.reactions.map((rxn, idx) => {
      const met = p.metabolites[idx + 1];
      return `<div class="debug-step">
        <span class="debug-arrow">↓</span> <span class="badge">${escapeHtml(rxn.id)}</span> flux=${fmt(rxn.flux)}
        ${rxn.subsystem ? `<span class="stoich"> · ${escapeHtml(rxn.subsystem)}</span>` : ""}
        ${fluxDeltaBadge(rxn.id)}
        <div class="debug-met">→ ${escapeHtml(met.name || met.id)} <span class="stoich">${escapeHtml(met.id)}</span></div>
      </div>`;
    }).join("");
    return `<div class="debug-path">
      <div class="debug-path-title">Path ${i + 1}</div>
      <div class="debug-met">${escapeHtml(p.metabolites[0].name || p.metabolites[0].id)} <span class="stoich">${escapeHtml(p.metabolites[0].id)}</span></div>
      ${steps}
    </div>`;
  }).join("");
  $("tracerViewContent").innerHTML = `<div class="debug-col tracer-text-col">${paths}</div>`;
}

function renderTracerNetworkView(data) {
  const showKoLegend = TRACER_HIGHLIGHT_KO && TRACER_RESULT && TRACER_RESULT.knockout && !TRACER_RESULT.knockout.error;
  $("tracerViewContent").innerHTML = `
    <div class="tracer-network-toolbar">
      <select id="tracerFilterSubsystem"><option value="">All subsystems</option></select>
      <label class="tracer-flux-filter">Min |flux| <input id="tracerFilterFlux" type="number" min="0" step="0.01" value="0"></label>
      <input id="tracerFilterSearch" type="text" placeholder="Highlight metabolite or reaction…">
      <span id="tracerNetCount" class="stoich"></span>
    </div>
    <div id="tracerCyContainer" class="tracer-cy-container"></div>
    <div class="tracer-legend">
      <span><i class="tracer-dot tracer-dot-start"></i> Start</span>
      <span><i class="tracer-dot tracer-dot-target"></i> Target</span>
      <span><i class="tracer-dot tracer-dot-mid"></i> Intermediate</span>
      ${showKoLegend ? `
        <span><i class="tracer-dot tracer-dot-ko-removed"></i> Removed by KO</span>
        <span><i class="tracer-dot tracer-dot-ko-added"></i> New route after KO</span>
        <span><i class="tracer-dot tracer-dot-ko-changed"></i> Flux changed</span>
      ` : ""}
      <span class="stoich">Hover a metabolite or reaction for details.</span>
    </div>
  `;

  if (!data.paths || !data.paths.length) {
    $("tracerCyContainer").innerHTML = `<div class="note">No active-flux pathway found from ${escapeHtml(data.start_id)} to ${escapeHtml(data.target_metabolite.id)} ${TRACER_KO_VIEW === "after" ? "(after knockout)" : ""}.</div>`;
    document.querySelectorAll(".tracer-network-toolbar select, .tracer-network-toolbar input").forEach(el => el.disabled = true);
    return;
  }

  const startIds = new Set((data.start_metabolites || []).map(m => m.id));
  const targetId = data.target_metabolite.id;

  const nodesById = new Map();
  const edges = [];
  const subsystems = new Set();

  data.paths.forEach((p, pathIdx) => {
    // Keep the full metabolite/reaction record from the API response (id,
    // name, compartment, formula, charge, reaction string, bounds, GPR,
    // type…) so the hover tooltip below has everything it needs without a
    // second request — the network view is just a different rendering of
    // the same data the text view already gets.
    p.metabolites.forEach(m => {
      if (!nodesById.has(m.id)) nodesById.set(m.id, m);
    });
    p.reactions.forEach((rxn, idx) => {
      const source = p.metabolites[idx].id;
      const target = p.metabolites[idx + 1].id;
      if (rxn.subsystem) subsystems.add(rxn.subsystem);
      edges.push(Object.assign({}, rxn, {
        id: `e_${pathIdx}_${idx}`,
        source, target,
        rxnId: rxn.id, rxnName: rxn.name || "",
        koClass: fluxDeltaClass(rxn.id),
      }));
    });
  });

  const elements = [];
  nodesById.forEach(n => {
    let role = "intermediate";
    if (startIds.has(n.id)) role = "start";
    if (n.id === targetId) role = "target";
    elements.push({ data: Object.assign({}, n, { label: n.name || n.id }), classes: role });
  });
  edges.forEach(e => {
    elements.push({
      data: Object.assign({}, e, {
        label: e.rxnId,
        flux: Math.abs(e.flux),
        rawFlux: e.flux,
      }),
      classes: e.koClass || "",
    });
  });

  const subsystemSelect = $("tracerFilterSubsystem");
  [...subsystems].sort().forEach(s => {
    const opt = document.createElement("option");
    opt.value = s; opt.textContent = s;
    subsystemSelect.appendChild(opt);
  });

  TRACER_CY = cytoscape({
    container: $("tracerCyContainer"),
    elements,
    style: [
      { selector: "node", style: {
        "label": "data(label)", "font-size": 9, "text-valign": "bottom", "text-margin-y": 4,
        "text-wrap": "ellipsis", "text-max-width": "70px",
        "width": 26, "height": 26, "background-color": "#94a3b8", "border-width": 2, "border-color": "#64748b",
      }},
      { selector: "node.start", style: { "background-color": "#2563eb", "border-color": "#1e40af", "width": 32, "height": 32 } },
      { selector: "node.target", style: { "background-color": "#047857", "border-color": "#065f46", "width": 32, "height": 32 } },
      { selector: "node.tracer-dimmed", style: { "opacity": 0.15 } },
      { selector: "node.tracer-highlighted", style: { "border-color": "#f59e0b", "border-width": 4 } },
      { selector: "edge", style: {
        "width": "mapData(flux, 0, 20, 1.5, 7)", "line-color": "#94a3b8", "target-arrow-color": "#94a3b8",
        "target-arrow-shape": "triangle", "curve-style": "bezier", "label": "data(label)",
        "font-size": 8, "color": "#475569", "text-background-color": "#ffffff", "text-background-opacity": 0.85,
        "text-rotation": "autorotate",
      }},
      { selector: "edge.tracer-dimmed", style: { "opacity": 0.08 } },
      { selector: "edge.tracer-highlighted", style: { "line-color": "#f59e0b", "target-arrow-color": "#f59e0b", "width": 4 } },
      // Before/after-knockout comparison overlay (see fluxDeltaClass) —
      // only applied to edges when a knockout was traced and "Highlight
      // KO-affected reactions" is checked.
      { selector: "edge.ko-removed", style: { "line-color": "#dc2626", "target-arrow-color": "#dc2626", "line-style": "dashed", "width": 3 } },
      { selector: "edge.ko-added", style: { "line-color": "#16a34a", "target-arrow-color": "#16a34a", "width": 4 } },
      { selector: "edge.ko-changed", style: { "line-color": "#d97706", "target-arrow-color": "#d97706", "width": 4 } },
      { selector: ".tracer-hidden", style: { "display": "none" } },
    ],
    layout: { name: "breadthfirst", roots: [...startIds], directed: true, spacingFactor: 1.25, padding: 24 },
    wheelSensitivity: 0.25,
  });

  attachTracerNetworkTooltips(TRACER_CY);

  $("tracerNetCount").textContent = `${nodesById.size} metabolites · ${edges.length} reaction hops`;

  const applyFilters = () => {
    const subVal = subsystemSelect.value;
    const fluxMin = parseFloat($("tracerFilterFlux").value) || 0;
    const search = $("tracerFilterSearch").value.trim().toLowerCase();

    TRACER_CY.edges().forEach(e => {
      const passSub = !subVal || e.data("subsystem") === subVal;
      const passFlux = e.data("flux") >= fluxMin;
      e.toggleClass("tracer-hidden", !(passSub && passFlux));
    });
    TRACER_CY.nodes().forEach(n => {
      const visibleEdges = n.connectedEdges().filter(e => !e.hasClass("tracer-hidden"));
      const isEndpoint = startIds.has(n.id()) || n.id() === targetId;
      n.toggleClass("tracer-hidden", !(visibleEdges.length > 0 || isEndpoint));
    });

    TRACER_CY.elements().removeClass("tracer-highlighted tracer-dimmed");
    if (search) {
      const visible = TRACER_CY.elements().not(".tracer-hidden");
      const matches = visible.filter(el =>
        (el.data("label") || "").toLowerCase().includes(search) ||
        (el.data("rxnName") || "").toLowerCase().includes(search) ||
        (el.id() || "").toLowerCase().includes(search)
      );
      if (matches.length) {
        visible.addClass("tracer-dimmed");
        matches.removeClass("tracer-dimmed").addClass("tracer-highlighted");
      }
    }
  };

  subsystemSelect.addEventListener("change", applyFilters);
  $("tracerFilterFlux").addEventListener("input", applyFilters);
  $("tracerFilterSearch").addEventListener("input", applyFilters);
  if (!subsystems.size) subsystemSelect.disabled = true;
}

// Hover tooltip content for a network node (metabolite) / edge (reaction) —
// reuses the same fixed-position tooltip element as the exchange table
// (ensureTooltip/showTooltip/positionTooltip/hideTooltip above).
function buildTracerNodeTooltipHtml(d) {
  return `
    <div class="tooltip-title">${escapeHtml(d.name || d.id)}</div>
    <div class="tooltip-row"><span class="tooltip-label">ID</span><code>${escapeHtml(d.id)}</code></div>
    <div class="tooltip-row"><span class="tooltip-label">Compartment</span>${escapeHtml(d.compartment_name || d.compartment || "—")}${d.compartment ? ` <span class="stoich">(${escapeHtml(d.compartment)})</span>` : ""}</div>
    <div class="tooltip-row"><span class="tooltip-label">Formula</span>${escapeHtml(d.formula || "—")}</div>
    <div class="tooltip-row"><span class="tooltip-label">Charge</span>${d.charge === null || d.charge === undefined ? "—" : d.charge}</div>
  `;
}

function buildTracerEdgeTooltipHtml(d) {
  return `
    <div class="tooltip-title">${escapeHtml(d.rxnId)}${d.rxnName ? ` — ${escapeHtml(d.rxnName)}` : ""}</div>
    <div class="tooltip-row"><span class="tooltip-label">Reaction</span><code>${escapeHtml(d.reaction_string || "—")}</code></div>
    <div class="tooltip-row"><span class="tooltip-label">Subsystem</span>${escapeHtml(d.subsystem || "—")}</div>
    <div class="tooltip-row"><span class="tooltip-label">Type</span>${escapeHtml(d.type || "—")}</div>
    <div class="tooltip-row"><span class="tooltip-label">GPR</span>${escapeHtml(d.gene_reaction_rule || "—")}</div>
    <div class="tooltip-row"><span class="tooltip-label">Bounds</span>[${fmt(d.lower_bound, 2)}, ${fmt(d.upper_bound, 2)}]</div>
    <div class="tooltip-row"><span class="tooltip-label">Flux (this trace)</span>${fmt(d.rawFlux)}</div>
  `;
}

function attachTracerNetworkTooltips(cy) {
  const showFor = (ev, buildHtml) => {
    const orig = ev.originalEvent;
    const x = orig ? orig.clientX : 0;
    const y = orig ? orig.clientY : 0;
    showTooltip(buildHtml(ev.target.data()), x, y);
  };
  cy.on("mouseover", "node", ev => showFor(ev, buildTracerNodeTooltipHtml));
  cy.on("mouseover", "edge", ev => showFor(ev, buildTracerEdgeTooltipHtml));
  cy.on("mousemove", "node, edge", ev => {
    const orig = ev.originalEvent;
    if (orig) positionTooltip(orig.clientX, orig.clientY);
  });
  cy.on("mouseout", "node, edge", () => hideTooltip());
  cy.on("pan zoom drag", () => hideTooltip());
  // cy's own "mouseout" only fires when the pointer moves off an element
  // while still inside the container; a mouse move that jumps straight from
  // a node/edge to somewhere else on the page never reaches cytoscape at
  // all, so the tooltip needs its own listener on the container itself.
  const container = cy.container();
  if (container) container.addEventListener("mouseleave", () => hideTooltip());
}

// ---------------------------------------------------------------------------
// Shared "save this generated HTML report" helpers -- used by both the FROG
// tab's own "save as HTML" button and the multi-section Generate Report
// modal below. Saving to an arbitrary path only works because this Flask
// server and the browser are expected to be on the same machine (the local-
// desktop-use pattern this whole app assumes): /api/browse-save-path opens a
// native "Save As" dialog in a short-lived helper process on that same
// machine, and /api/save-report then writes the given HTML straight to the
// chosen path. When no path is given (or Browse isn't available here -- no
// tkinter, no display, or this is actually a remote deployment), the report
// is instead downloaded straight through the browser, the same client-side
// Blob mechanism already used for CSV export.
// ---------------------------------------------------------------------------

function reportDocumentHtml(title, bodyHtml) {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
  :root {
    --accent:#2563eb; --accent-dark:#1d4ed8; --accent-soft:#eef2ff;
    --bg:#f1f4f9; --card-bg:#ffffff; --border:#e2e8f0; --border-soft:#edf1f7;
    --text:#0f172a; --muted:#64748b; --muted-soft:#94a3b8;
    --good:#16a34a; --bad:#dc2626; --warn:#b45309;
    --th-bg:#f8fafc; --row-alt:#fbfcfe; --card-alt:#fbfcfe; --note-bg:#fffbeb; --note-bd:#fde68a; --note-fg:#854d0e; --code-bg:rgba(15,23,42,.06);
    --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300; --s-other:#8f8e88; --grid:#e3e2de;
    color-scheme:light;
  }
  [data-theme="dark"] {
    --accent:#6ea0ff; --accent-dark:#3b6fd4; --accent-soft:#222c4a;
    --bg:#111622; --card-bg:#1a2133; --border:#2c3652; --border-soft:#252e46;
    --text:#e8ebf3; --muted:#a6b0c6; --muted-soft:#7e8aa5;
    --good:#3fbf8a; --bad:#f2766b; --warn:#e0a040;
    --th-bg:#202941; --row-alt:#1e2638; --card-alt:#1e2638; --note-bg:#2a2414; --note-bd:#5c4a17; --note-fg:#f0d28a; --code-bg:rgba(255,255,255,.08);
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#2aa02a; --s-other:#8f8e88; --grid:#34332f;
    color-scheme:dark;
  }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif; background:var(--bg); color:var(--text); }
  .report-wrap { max-width:1180px; margin:0 auto; padding:0 24px 60px; }

  .report-cover {
    margin:0 -24px 28px; padding:38px 40px 30px; color:#fff;
    background:linear-gradient(135deg,var(--accent-dark),var(--accent) 60%,#4f8ef7);
    border-radius:0 0 18px 18px;
  }
  .report-cover-kicker { font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; opacity:.85; margin-bottom:6px; }
  .report-cover h1 { font-size:26px; margin:0 0 8px; line-height:1.25; }
  .report-cover-meta { font-size:13px; opacity:.92; margin-bottom:22px; }
  .report-cover-meta strong { font-weight:700; }
  .report-stats { display:flex; flex-wrap:wrap; gap:12px; }
  .report-stat {
    flex:1 1 130px; min-width:110px; background:rgba(255,255,255,.14); border:1px solid rgba(255,255,255,.28);
    border-radius:10px; padding:12px 14px;
  }
  .report-stat-value { font-size:20px; font-weight:700; line-height:1.2; }
  .report-stat-label { font-size:11px; text-transform:uppercase; letter-spacing:.04em; opacity:.85; margin-top:2px; }

  .toc { margin:0 0 28px; padding:18px 22px; background:var(--card-bg); border:1px solid var(--border); border-radius:14px; box-shadow:0 1px 2px rgba(15,23,42,.04); }
  .toc-title { font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin-bottom:10px; }
  .toc ol { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(auto-fill,minmax(230px,1fr)); gap:6px 18px; counter-reset:toc; }
  .toc li { counter-increment:toc; }
  .toc li::before { content:counter(toc); display:inline-flex; align-items:center; justify-content:center; width:18px; height:18px; margin-right:8px; border-radius:50%; background:var(--accent-soft); color:var(--accent-dark); font-size:10.5px; font-weight:700; }
  .toc a { color:var(--text); text-decoration:none; font-size:13px; }
  .toc a:hover { color:var(--accent-dark); text-decoration:underline; }

  .report-section {
    background:var(--card-bg); border:1px solid var(--border); border-radius:14px;
    padding:22px 24px 8px; margin-bottom:22px; box-shadow:0 1px 2px rgba(15,23,42,.04);
    counter-increment:section;
  }
  h2 { font-size:17px; margin:0 0 14px; padding-bottom:12px; border-bottom:1px solid var(--border-soft); display:flex; align-items:center; gap:10px; }
  h2::before {
    content:counter(section); flex:0 0 auto; width:24px; height:24px; border-radius:50%;
    background:var(--accent); color:#fff; font-size:12px; font-weight:700; display:inline-flex;
    align-items:center; justify-content:center;
  }
  h3 { font-size:13px; margin:18px 0 8px; color:var(--muted); text-transform:uppercase; letter-spacing:.03em; }
  .report-meta { color:var(--muted); font-size:13px; margin-bottom:4px; }
  .report-note { padding:10px 13px; background:var(--note-bg); border:1px solid var(--note-bd); border-left:3px solid var(--warn); border-radius:8px; color:var(--note-fg); margin-bottom:14px; font-size:12.5px; }
  .report-note ul { margin:6px 0 0 18px; padding:0; }
  .report-note li { margin-bottom:4px; }
  code { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; background:var(--code-bg); border-radius:4px; padding:1px 4px; font-size:11.5px; }

  .objective-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:14px; margin-bottom:14px; }
  .objective-card { border:1px solid var(--border); border-radius:12px; padding:14px 16px; background:var(--card-alt); }
  .objective-card .mini-stat-label { font-size:11px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted); font-weight:700; }
  .reaction-expr { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; font-size:12.5px; line-height:1.5; word-break:break-word; margin-top:6px; }
  .biomass-details { border:1px solid var(--border); border-radius:12px; margin-bottom:14px; overflow:hidden; }
  .biomass-details summary { cursor:pointer; padding:10px 14px; font-weight:700; font-size:13px; background:var(--th-bg); }
  .biomass-details .biomass-body { padding:4px 16px 14px; margin:0; }
  .stoich { color:var(--muted); font-size:11.5px; margin-top:4px; }

  table { width:100%; border-collapse:collapse; font-size:12.5px; margin-bottom:8px; }
  th, td { padding:8px 10px; border-bottom:1px solid var(--border-soft); text-align:left; vertical-align:top; }
  th { background:var(--th-bg); position:sticky; top:0; font-weight:700; color:var(--text); white-space:nowrap; }
  tbody tr:nth-child(even) { background:var(--row-alt); }
  tbody tr:hover { background:var(--accent-soft); }
  .table-scroll { max-height:560px; overflow:auto; border:1px solid var(--border-soft); border-radius:10px; margin-bottom:18px; }

  .report-footer { text-align:center; color:var(--muted-soft); font-size:11.5px; padding:24px 0 4px; border-top:1px solid var(--border-soft); margin-top:8px; }

  .report-toggle { position:fixed; top:12px; right:14px; z-index:5; border:1px solid var(--border); background:var(--card-bg); color:var(--text); border-radius:999px; padding:5px 12px; font-size:12px; cursor:pointer; }
  .rc-figure { margin:14px 0 18px; }
  .rc-figure figcaption { font-size:13px; font-weight:700; margin-bottom:6px; color:var(--text); }
  .rc-svg { width:100%; max-width:760px; height:auto; display:block; }
  .rc-t { fill:var(--muted); font:12px -apple-system,"Segoe UI",Inter,sans-serif; }
  .rc-v { fill:var(--text); font-weight:600; }
  .rc-axis, .rc-grid { stroke:var(--grid); stroke-width:1; }
  .rc-legend { display:flex; flex-wrap:wrap; gap:4px 16px; margin-top:6px; font-size:12px; color:var(--muted); }
  .rc-legend i { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; vertical-align:-1px; }
  .rc-note { color:var(--muted); font-size:12px; margin-top:2px; }
  .rc-grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:6px 24px; }
  .finding-list { margin:6px 0 14px 18px; padding:0; }
  .finding-list li { margin-bottom:5px; }
  @media print {
    .report-toggle { display:none; }
    body { background:#fff; }
    .report-cover { border-radius:0; margin:0 0 20px; }
    .report-section { box-shadow:none; break-inside:avoid-page; }
    .table-scroll { max-height:none; overflow:visible; }
    th { position:static; }
  }
</style>
</head>
<body>
<button class="report-toggle" type="button" onclick="var r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark';this.textContent=r.dataset.theme==='dark'?'Light theme':'Dark theme'">Dark theme</button>
<div class="report-wrap">
${bodyHtml}
<div class="report-footer">Generated by the Genome-scale Model Inspector — ${escapeHtml(new Date().toLocaleString())}</div>
</div>
</body>
</html>`;
}

// Shared cover/header block for a generated report: a colored band with the
// report title, model label, generated timestamp, and an optional row of
// at-a-glance stat cards (label/value pairs).
function reportCoverHtml(title, modelLabel, statPairs, extraMeta) {
  const meta = [`Model: <strong>${escapeHtml(modelLabel)}</strong>`, `Generated ${escapeHtml(new Date().toLocaleString())}`];
  if (extraMeta) meta.push(extraMeta);
  return `
    <div class="report-cover">
      <div class="report-cover-kicker">Genome-scale Model Inspector</div>
      <h1>${escapeHtml(title)}</h1>
      <div class="report-cover-meta">${meta.join(" &nbsp;·&nbsp; ")}</div>
      ${statPairs && statPairs.length ? `<div class="report-stats">${statPairs.map(([l, v]) =>
        `<div class="report-stat"><div class="report-stat-value">${escapeHtml(v)}</div><div class="report-stat-label">${escapeHtml(l)}</div></div>`
      ).join("")}</div>` : ""}
    </div>
  `;
}

// Table-of-contents block, numbered to match each section's own h2 counter.
function reportTocHtml(entries) {
  if (!entries.length) return "";
  return `
    <nav class="toc">
      <div class="toc-title">Contents</div>
      <ol>${entries.map(([id, label]) => `<li><a href="#sec-${id}">${escapeHtml(label)}</a></li>`).join("")}</ol>
    </nav>
  `;
}

// Plain (non-interactive) table markup for embedding in a generated report
// -- distinct from the live, sortable/filterable DOM tables elsewhere in
// this file. Numbers are run through fmt() for readability; everything else
// is shown as-is (escaped). `columns` uses the same {key,label} / {value:
// row => ..., label} shape as exportTableToCsv's columns.
function staticTableHtml(columns, rows, opts) {
  opts = opts || {};
  if (!rows || !rows.length) return `<div class="report-note">${escapeHtml(opts.emptyMessage || "No rows.")}</div>`;
  const head = columns.map(c => `<th>${escapeHtml(c.label)}</th>`).join("");
  const body = rows.map(row => `<tr>${columns.map(c => {
    const raw = typeof c.value === "function" ? c.value(row) : row[c.key];
    let cell;
    if (raw === null || raw === undefined) cell = "—";
    else if (typeof raw === "number") cell = fmt(raw, opts.digits || 6);
    else cell = String(raw);
    return `<td>${escapeHtml(cell)}</td>`;
  }).join("")}</tr>`).join("");
  return `<div class="table-scroll"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

async function pickSavePath(defaultName) {
  try {
    const res = await fetch(`/api/browse-save-path?default_name=${encodeURIComponent(defaultName)}`);
    return await res.json(); // { path } or { path: null, error }
  } catch (err) {
    return { path: null, error: err.message };
  }
}

function downloadHtmlFile(filename, html) {
  const blob = new Blob([html], { type: "text/html;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// Writes `html` to `path` on this machine via /api/save-report when a path
// was given, otherwise downloads it straight through the browser. Returns
// {ok, message} rather than throwing, so callers can show the outcome
// inline without their own try/catch.
async function saveGeneratedHtml(html, path, defaultFilename) {
  if (path && path.trim()) {
    try {
      const res = await fetch("/api/save-report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: path.trim(), html }),
      });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || "Could not save the report.");
      return { ok: true, message: `Saved to ${data.path}` };
    } catch (err) {
      return { ok: false, message: err.message };
    }
  }
  downloadHtmlFile(defaultFilename, html);
  return { ok: true, message: `Downloaded as ${defaultFilename}.` };
}

// Renders a "Save to [___] [Browse…]" row into `container` and wires the
// Browse button to /api/browse-save-path. Returns a getter for whatever
// path is currently in the text field (possibly empty, meaning "download
// instead"). idPrefix must be unique per container on the page.
function attachSavePathPicker(container, idPrefix, defaultName) {
  container.innerHTML = `
    <div class="report-savepath-row">
      <label style="font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.03em;">Save to</label>
      <input id="${idPrefix}Input" type="text" placeholder="Leave blank to download via your browser instead">
      <button type="button" id="${idPrefix}BrowseBtn">Browse…</button>
    </div>
    <div class="report-savepath-note" id="${idPrefix}Note">
      "Browse…" opens a native Save-As dialog on this computer (works when this app is running on your own machine).
      You can also type a full path directly, or leave it blank to download through your browser instead.
    </div>
  `;
  const input = container.querySelector(`#${idPrefix}Input`);
  const browseBtn = container.querySelector(`#${idPrefix}BrowseBtn`);
  const note = container.querySelector(`#${idPrefix}Note`);
  const defaultNoteHtml = note.innerHTML;

  browseBtn.addEventListener("click", async () => {
    browseBtn.disabled = true;
    note.textContent = "Opening Save As dialog…";
    const result = await pickSavePath(defaultName);
    browseBtn.disabled = false;
    if (result.path) {
      input.value = result.path;
      note.textContent = "Path chosen — click Generate/Save to write the report there.";
    } else if (result.error) {
      note.innerHTML = `<span class="error">${escapeHtml(result.error)}</span> — type a path manually, or leave blank to download instead.`;
    } else {
      note.innerHTML = defaultNoteHtml; // user cancelled the dialog
    }
  });

  return () => input.value;
}

function sanitizeForFilename(name) {
  return String(name || "model").replace(/[^a-z0-9_.-]+/gi, "_");
}

// ---------------------------------------------------------------------------
// FROG Report tab (on-request) -- the reproducibility-check standard used
// across the SBML/COMBINE community for genome-scale metabolic models:
// Flux variability analysis, Reaction deletions, Objective value, Gene
// deletions, all run against the model's current bounds (whatever diet was
// applied at upload). F, R, and G can each be skipped independently -- R and
// G are one LP solve per reaction/gene, so they're the slow part for a large
// genome-scale model -- and FVA's growth cutoff is configurable, same idea
// as the Minimal Medium tab's cutoff.
// ---------------------------------------------------------------------------

let FROG_RESULT = null;
let FROG_PARAMS = null; // query string FROG_RESULT was computed with; the report reuses it when identical
let CURRENT_FROG_EVENTSOURCE = null;

const FROG_FVA_CSV_COLUMNS = [
  { key: "id", label: "Reaction ID" },
  { key: "minimum", label: "Minimum flux" },
  { key: "maximum", label: "Maximum flux" },
];
const FROG_REACTION_DELETION_CSV_COLUMNS = [
  { key: "id", label: "Reaction ID" },
  { key: "growth", label: "Growth after knockout" },
  { key: "status", label: "Solver status" },
];
const FROG_GENE_DELETION_CSV_COLUMNS = [
  { key: "id", label: "Gene ID" },
  { key: "growth", label: "Growth after knockout" },
  { key: "status", label: "Solver status" },
];

function frogDefaultFilename() {
  const name = DATA && DATA.stats && (DATA.stats.model_id || DATA.stats.model_name);
  return `${sanitizeForFilename(name)}_frog_report.html`;
}

function renderFrog() {
  $("frog").innerHTML = `
    <div class="note">
      <strong>FROG</strong> is a model-reproducibility check standard used in the SBML/COMBINE community:
      <strong>F</strong>lux variability analysis, <strong>R</strong>eaction deletions, <strong>O</strong>bjective
      value, <strong>G</strong>ene deletions — all computed against this model's current bounds (whatever diet was
      applied at upload), so this model + medium can be cross-checked against any other FBA tool's results for the
      same inputs. R and G are one LP solve per reaction/gene, so they can take a while on a large genome-scale
      model — uncheck either to skip it.
    </div>
    <div class="frog-config">
      <label>FVA growth cutoff (fraction of optimum)
        <input id="frogFvaFraction" type="number" min="0" max="1" step="0.01" value="1.0">
      </label>
      <label><input id="frogIncludeFva" type="checkbox" checked> Include flux variability analysis (F)</label>
      <label><input id="frogIncludeRxnDel" type="checkbox" checked> Include reaction deletions (R)</label>
      <label><input id="frogIncludeGeneDel" type="checkbox" checked> Include gene deletions (G)</label>
      <button id="frogRunBtn" type="button">Run FROG report</button>
    </div>
    <div id="frogStatus" class="debug-status"></div>
    ${progressBarHtml("frogProgress")}
    <div id="frogResults"></div>
  `;
  $("frogRunBtn").addEventListener("click", runFrogReport);
}

function runFrogReport() {
  if (!MODEL_ID) {
    $("frogStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`;
    return;
  }
  if (CURRENT_FROG_EVENTSOURCE) {
    CURRENT_FROG_EVENTSOURCE.close();
    CURRENT_FROG_EVENTSOURCE = null;
  }

  let fvaFraction = parseFloat($("frogFvaFraction").value);
  if (!Number.isFinite(fvaFraction)) fvaFraction = 1.0;
  fvaFraction = Math.max(0, Math.min(1, fvaFraction));
  $("frogFvaFraction").value = fvaFraction;

  const includeFva = $("frogIncludeFva").checked;
  const includeRxnDel = $("frogIncludeRxnDel").checked;
  const includeGeneDel = $("frogIncludeGeneDel").checked;

  const btn = $("frogRunBtn");
  btn.disabled = true;
  $("frogStatus").textContent = "Starting FROG report…";
  progressStart("frogProgress");
  $("frogResults").innerHTML = "";
  FROG_RESULT = null;
  FROG_PARAMS = null;

  const modelId = MODEL_ID;
  const params = new URLSearchParams({
    fva_fraction: String(fvaFraction),
    include_fva: includeFva ? "1" : "0",
    include_reaction_deletions: includeRxnDel ? "1" : "0",
    include_gene_deletions: includeGeneDel ? "1" : "0",
  });
  const paramsKey = params.toString();
  const eventSource = new EventSource(`/api/frog-report/${modelId}?${paramsKey}`);
  CURRENT_FROG_EVENTSOURCE = eventSource;

  eventSource.onmessage = (event) => {
    if (modelId !== MODEL_ID) { eventSource.close(); return; } // superseded by a newer analysis
    let msg;
    try { msg = JSON.parse(event.data); } catch (err) { return; }

    if (msg.type === "info") {
      $("frogStatus").textContent = msg.message;
    } else if (msg.type === "error") {
      $("frogStatus").innerHTML = `<span class="error">${escapeHtml(msg.message)}</span>`;
      progressDone("frogProgress");
      btn.disabled = false;
      eventSource.close();
      if (CURRENT_FROG_EVENTSOURCE === eventSource) CURRENT_FROG_EVENTSOURCE = null;
    } else if (msg.type === "complete") {
      FROG_RESULT = msg;
      FROG_PARAMS = paramsKey;
      $("frogStatus").textContent = msg.note || "Done.";
      progressDone("frogProgress");
      renderFrogResults(msg);
      btn.disabled = false;
      eventSource.close();
      if (CURRENT_FROG_EVENTSOURCE === eventSource) CURRENT_FROG_EVENTSOURCE = null;
    }
  };

  eventSource.onerror = () => {
    if (modelId !== MODEL_ID) { eventSource.close(); return; }
    if (!FROG_RESULT) {
      $("frogStatus").innerHTML = `<span class="error">Connection error while running the FROG report — try again.</span>`;
      progressDone("frogProgress");
    }
    btn.disabled = false;
    eventSource.close();
    if (CURRENT_FROG_EVENTSOURCE === eventSource) CURRENT_FROG_EVENTSOURCE = null;
  };
}

function renderFrogResults(data) {
  const obj = data.objective || {};
  $("frogResults").innerHTML = `
    <div class="frog-obj-card">
      <div class="mini-stat"><div class="mini-stat-value">${escapeHtml(obj.objective_reaction || "—")}</div><div class="mini-stat-label">Objective reaction</div></div>
      <div class="mini-stat"><div class="mini-stat-value">${escapeHtml(obj.status || "—")}</div><div class="mini-stat-label">Status</div></div>
      <div class="mini-stat"><div class="mini-stat-value">${fmt(obj.value)}</div><div class="mini-stat-label">Objective value (O)</div></div>
    </div>
    <h3>Flux variability analysis (F)</h3>
    <div id="frogFvaWrap"></div>
    <h3>Reaction deletions (R)</h3>
    <div id="frogRxnDelWrap"></div>
    <h3>Gene deletions (G)</h3>
    <div id="frogGeneDelWrap"></div>
    <div id="frogSaveSection" style="margin-top:22px; border-top:1px solid var(--line); padding-top:16px;">
      <div class="report-section-title" style="margin-bottom:8px;">Save this FROG report as a standalone HTML file</div>
      <div id="frogSavePath"></div>
      <div class="toolbar" style="margin-top:10px;">
        <button id="frogSaveBtn" type="button">Save FROG report</button>
        <span id="frogSaveStatus" class="debug-status"></span>
      </div>
    </div>
  `;

  renderFrogFvaTable(data.fva ? data.fva.reactions : null);
  renderFrogReactionDeletionTable(data.reaction_deletions ? data.reaction_deletions.reactions : null);
  renderFrogGeneDeletionTable(data.gene_deletions ? data.gene_deletions.genes : null);

  const getPath = attachSavePathPicker($("frogSavePath"), "frogSavePath", frogDefaultFilename());
  $("frogSaveBtn").addEventListener("click", async () => {
    const saveBtn = $("frogSaveBtn");
    saveBtn.disabled = true;
    $("frogSaveStatus").textContent = "Saving…";
    const html = buildFrogReportHtml(data);
    const result = await saveGeneratedHtml(html, getPath(), frogDefaultFilename());
    $("frogSaveStatus").innerHTML = result.ok ? escapeHtml(result.message) : `<span class="error">${escapeHtml(result.message)}</span>`;
    saveBtn.disabled = false;
  });
}

let frogFvaCurrentRows = [];
let frogRxnDelCurrentRows = [];
let frogGeneDelCurrentRows = [];

function renderFrogFvaTable(rows) {
  const wrap = $("frogFvaWrap");
  frogFvaCurrentRows = rows || [];
  if (!rows) { wrap.innerHTML = `<div class="note">Not computed (unchecked before running).</div>`; return; }
  if (!rows.length) { wrap.innerHTML = `<div class="note">No reactions.</div>`; return; }
  wrap.innerHTML = `
    <div class="toolbar"></div>
    <div class="table-wrap"><table id="frogFvaTable">
      <thead><tr><th data-key="id">Reaction ID</th><th data-key="minimum">Minimum flux</th><th data-key="maximum">Maximum flux</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td><strong>${escapeHtml(r.id)}</strong></td><td class="num">${fmt(r.minimum, 6)}</td><td class="num">${fmt(r.maximum, 6)}</td></tr>`).join("")}</tbody>
    </table></div>
  `;
  attachTableTools("frogFvaTable", wrap.querySelector(".toolbar"), FROG_FVA_CSV_COLUMNS, () => frogFvaCurrentRows, "frog_fva");
  setTimeout(() => makeSortable("frogFvaTable", rows, renderFrogFvaTable), 0);
}

function renderFrogReactionDeletionTable(rows) {
  const wrap = $("frogRxnDelWrap");
  frogRxnDelCurrentRows = rows || [];
  if (!rows) { wrap.innerHTML = `<div class="note">Not computed (unchecked before running).</div>`; return; }
  if (!rows.length) { wrap.innerHTML = `<div class="note">No reactions.</div>`; return; }
  wrap.innerHTML = `
    <div class="toolbar"></div>
    <div class="table-wrap"><table id="frogRxnDelTable">
      <thead><tr><th data-key="id">Reaction ID</th><th data-key="growth">Growth after knockout</th><th data-key="status">Status</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td><strong>${escapeHtml(r.id)}</strong></td><td class="num">${fmt(r.growth, 6)}</td><td>${escapeHtml(r.status)}</td></tr>`).join("")}</tbody>
    </table></div>
  `;
  attachTableTools("frogRxnDelTable", wrap.querySelector(".toolbar"), FROG_REACTION_DELETION_CSV_COLUMNS, () => frogRxnDelCurrentRows, "frog_reaction_deletions");
  setTimeout(() => makeSortable("frogRxnDelTable", rows, renderFrogReactionDeletionTable), 0);
}

function renderFrogGeneDeletionTable(rows) {
  const wrap = $("frogGeneDelWrap");
  frogGeneDelCurrentRows = rows || [];
  if (!rows) { wrap.innerHTML = `<div class="note">Not computed (unchecked before running).</div>`; return; }
  if (!rows.length) { wrap.innerHTML = `<div class="note">No genes.</div>`; return; }
  wrap.innerHTML = `
    <div class="toolbar"></div>
    <div class="table-wrap"><table id="frogGeneDelTable">
      <thead><tr><th data-key="id">Gene ID</th><th data-key="growth">Growth after knockout</th><th data-key="status">Status</th></tr></thead>
      <tbody>${rows.map(r => `<tr><td><strong>${escapeHtml(r.id)}</strong></td><td class="num">${fmt(r.growth, 6)}</td><td>${escapeHtml(r.status)}</td></tr>`).join("")}</tbody>
    </table></div>
  `;
  attachTableTools("frogGeneDelTable", wrap.querySelector(".toolbar"), FROG_GENE_DELETION_CSV_COLUMNS, () => frogGeneDelCurrentRows, "frog_gene_deletions");
  setTimeout(() => makeSortable("frogGeneDelTable", rows, renderFrogGeneDeletionTable), 0);
}

// Body markup shared by both the standalone FROG report (below) and the
// FROG section embedded in the combined Generate Report (further down).
function buildFrogSectionBody(data) {
  const obj = data.objective || {};
  return `
    <section class="report-section">
    <h2 id="sec-frog">FROG report</h2>
    <div class="report-note">${escapeHtml(data.note || "")}</div>
    <h3>Objective (O)</h3>
    ${staticTableHtml(
      [{ key: "objective_reaction", label: "Objective reaction" }, { key: "status", label: "Status" }, { key: "value", label: "Value" }],
      [obj]
    )}
    <h3>Flux variability analysis (F)</h3>
    ${data.fva
      ? `<div class="report-meta">Fraction of optimum: ${fmt(data.fva.fraction_of_optimum, 4)}</div>${staticTableHtml(FROG_FVA_CSV_COLUMNS, data.fva.reactions, { emptyMessage: "No reactions." })}`
      : `<div class="report-note">Not included in this run.</div>`}
    <h3>Reaction deletions (R)</h3>
    ${data.reaction_deletions ? reportStatusStack(data.reaction_deletions.reactions, "status", "Reaction deletions by solver status") +
      rcHist(data.reaction_deletions.reactions.map(r => r.growth), { title: "Growth after deleting each reaction", xLabel: "objective value", bins: 20 }) : ""}
    ${data.reaction_deletions
      ? staticTableHtml(FROG_REACTION_DELETION_CSV_COLUMNS, data.reaction_deletions.reactions, { emptyMessage: "No reactions." })
      : `<div class="report-note">Not included in this run.</div>`}
    <h3>Gene deletions (G)</h3>
    ${data.gene_deletions ? reportStatusStack(data.gene_deletions.genes, "status", "Gene deletions by solver status") +
      rcHist(data.gene_deletions.genes.map(g => g.growth), { title: "Growth after deleting each gene", xLabel: "objective value", bins: 20 }) : ""}
    ${data.gene_deletions
      ? staticTableHtml(FROG_GENE_DELETION_CSV_COLUMNS, data.gene_deletions.genes, { emptyMessage: "No genes." })
      : `<div class="report-note">Not included in this run.</div>`}
    </section>
  `;
}

function buildFrogReportHtml(data) {
  const modelLabel = DATA && DATA.stats && (DATA.stats.model_name || DATA.stats.model_id) || "model";
  const obj = data.objective || {};
  const stats = [
    ["Objective reaction", obj.objective_reaction || "—"],
    ["Objective value", fmt(obj.value)],
    ["F rows", data.fva ? (data.fva.reactions || []).length : "—"],
    ["R rows", data.reaction_deletions ? (data.reaction_deletions.reactions || []).length : "—"],
    ["G rows", data.gene_deletions ? (data.gene_deletions.genes || []).length : "—"],
  ];
  const body = `
    ${reportCoverHtml(`FROG report — ${modelLabel}`, modelLabel, stats)}
    ${buildFrogSectionBody(data)}
  `;
  return reportDocumentHtml(`FROG report — ${modelLabel}`, body);
}

// ---------------------------------------------------------------------------
// "Generate report" modal (on-request) -- lets the user pick which sections
// to include (each recomputed fresh with its own configurable cutoffs,
// independent of whatever's currently shown in the tabs) and assembles them
// into one self-contained HTML file, saved the same way as the FROG tab's
// own "save as HTML" button above.
// ---------------------------------------------------------------------------

const REPORT_SECTIONS = [
  { key: "quality", title: "Quality findings", hint: "Key statistics and automatic findings against the thresholds below." },
  { key: "overview", title: "Overview", hint: "Model stats, compartments and the diet/media summary, with charts." },
  { key: "metabolites", title: "Metabolites", hint: "The full metabolite table, with a formula-coverage chart." },
  { key: "reactions", title: "Reactions", hint: "The full reaction table, with reaction-type and subsystem charts." },
  { key: "genes", title: "Genes", hint: "Every gene with its reactions, with charts." },
  { key: "objective", title: "Objective", hint: "Objective metabolites and their coefficients." },
  { key: "exchanges", title: "Exchange essentiality", hint: "Every exchange, tested for knockout essentiality, with a chart." },
  { key: "balance", title: "Reaction balance", hint: "Mass/charge balance status and the problem reactions." },
  { key: "minimal_medium", title: "Minimal medium", hint: "Smallest nutrient set for a chosen growth cutoff.", cutoff: true },
  { key: "network_gaps", title: "Network gaps (blocked reactions & dead ends)", hint: "Structural connectivity gaps under the model's current bounds." },
  { key: "demand_sink_audit", title: "Demand & sink audit", hint: "Every demand/sink reaction's usage and knockout essentiality." },
  { key: "pathway_tracer", title: "Pathway tracer", hint: "Included only if you've already run a trace this session.", requiresTracer: true },
  { key: "frog", title: "FROG report (F/R/O/G reproducibility check)", hint: "Can be slow for large models — configure below.", frog: true },
];

function reportDefaultFilename() {
  const name = DATA && DATA.stats && (DATA.stats.model_id || DATA.stats.model_name);
  return `${sanitizeForFilename(name)}_report.html`;
}

function closeReportModal() {
  const overlay = $("reportModalOverlay");
  if (overlay) overlay.remove();
}

function renderReportModal() {
  closeReportModal();
  const root = $("reportModalRoot");
  root.innerHTML = `
    <div class="modal-overlay" id="reportModalOverlay">
      <div class="modal-box">
        <div class="modal-header">
          <h2>Generate report</h2>
          <button class="modal-close" id="reportModalCloseBtn" type="button">✕</button>
        </div>
        <div class="modal-body">
          <div class="note">
            Pick the sections to include. Analyses you have already run in the tabs are reused rather than repeated;
            the rest are computed now. The result is one self-contained HTML report with charts (light or dark, switchable
            in the page), and optionally an Excel workbook of the key statistics and findings.
          </div>
          <details class="report-options" id="reportThresholds">
            <summary>Quality thresholds and Excel</summary>
            <div class="toolbar">
              ${thresholdInputHtml("mu_min", "Growth rate min (1/h)")} ${thresholdInputHtml("mu_max", "max (1/h)")}
              ${thresholdInputHtml("blocked_warn_pct", "Warn if blocked reactions &gt; %")} ${thresholdInputHtml("deadend_warn_pct", "dead-end metabolites &gt; %")}
            </div>
            <div class="toolbar"><label><input type="checkbox" id="reportExcel"> Also download the Excel workbook</label></div>
            <div class="stoich">The same thresholds appear on the Summary and Network Gaps tabs and stay in sync.</div>
          </details>
          <div id="reportSectionList"></div>
          <div id="reportSavePath" style="margin-top:18px;"></div>
        </div>
        <div class="modal-footer">
          <span class="modal-status" id="reportModalStatus"></span>
          ${progressBarHtml("reportModalProgress")}
          <button id="reportGenerateBtn" type="button">Generate report</button>
        </div>
      </div>
    </div>
  `;

  $("reportModalCloseBtn").addEventListener("click", closeReportModal);
  $("reportModalOverlay").addEventListener("click", ev => {
    if (ev.target.id === "reportModalOverlay") closeReportModal();
  });

  const listEl = $("reportSectionList");
  listEl.innerHTML = REPORT_SECTIONS.map(sec => {
    const disabled = sec.requiresTracer && !TRACER_RESULT;
    let opts = "";
    if (sec.cutoff) {
      opts = `<div class="report-section-opts">
        <label>Growth cutoff (0–1) <input type="number" id="reportCutoff_${sec.key}" min="0.01" max="1" step="0.01" value="1.0"></label>
      </div>`;
    }
    if (sec.frog) {
      opts = `<div class="report-section-opts">
        <label>FVA cutoff (0–1) <input type="number" id="reportFrogFraction" min="0" max="1" step="0.01" value="1.0"></label>
        <label><input type="checkbox" id="reportFrogFva" checked> Include FVA (F)</label>
        <label><input type="checkbox" id="reportFrogRxnDel" checked> Include reaction deletions (R)</label>
        <label><input type="checkbox" id="reportFrogGeneDel" checked> Include gene deletions (G)</label>
      </div>`;
    }
    return `
      <label class="report-section-row">
        <input type="checkbox" id="reportSection_${sec.key}" ${disabled ? "disabled" : "checked"}>
        <div class="report-section-main">
          <div class="report-section-title">${escapeHtml(sec.title)}</div>
          <div class="report-section-hint">${escapeHtml(disabled ? "Run a pathway trace first to include it." : sec.hint)}</div>
          ${opts}
        </div>
      </label>
    `;
  }).join("");

  bindThresholdInputs($("reportThresholds"));
  const getPath = attachSavePathPicker($("reportSavePath"), "reportSavePath", reportDefaultFilename());
  $("reportGenerateBtn").addEventListener("click", () => runGenerateReport(getPath));
}

function runFrogReportForModal(fraction, includeFva, includeRxnDel, includeGeneDel, setStatus) {
  return new Promise((resolve, reject) => {
    const params = new URLSearchParams({
      fva_fraction: String(fraction),
      include_fva: includeFva ? "1" : "0",
      include_reaction_deletions: includeRxnDel ? "1" : "0",
      include_gene_deletions: includeGeneDel ? "1" : "0",
    });
    const eventSource = new EventSource(`/api/frog-report/${MODEL_ID}?${params.toString()}`);
    eventSource.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch (err) { return; }
      if (msg.type === "info") {
        setStatus(msg.message);
      } else if (msg.type === "error") {
        eventSource.close();
        reject(new Error(msg.message));
      } else if (msg.type === "complete") {
        eventSource.close();
        resolve(msg);
      }
    };
    eventSource.onerror = () => {
      eventSource.close();
      reject(new Error("Connection error while running the FROG report."));
    };
  });
}

// Report-only version of the unmapped-id warning box (uses .report-note,
// the report document's own warning styling, and a much higher cap since a
// generated report has no interactive filter to fall back on). Shares the
// same per-item "likely duplicate" list markup as the live Overview tab.
function reportUnmappedWarningHtml(kind, limit) {
  const audit = DATA.namespace_audit;
  const s = DATA.stats || {};
  if (!audit) return "";
  if (kind === "metabolite") {
    if (!audit.unmapped_metabolite_count) return "";
    const total = audit.unmapped_metabolite_count + audit.mapped_metabolite_count;
    return `
      <div class="report-note">
        <strong>${audit.unmapped_metabolite_count} of ${total} metabolites</strong> did not map to MetaNetX.
        This model is predominantly in the <strong>${escapeHtml((s.namespace_metabolites || {}).label || "detected")}</strong> namespace —
        look up each one's id in that namespace and rename it to match.
        ${unmappedAuditItemsHtml(audit.unmapped_metabolites, "metabolite", limit)}
      </div>
    `;
  }
  if (!audit.unmapped_reaction_count) return "";
  const total = audit.unmapped_reaction_count + audit.mapped_reaction_count;
  return `
    <div class="report-note">
      <strong>${audit.unmapped_reaction_count} of ${total} reactions</strong> did not map to MetaNetX.
      This model is predominantly in the <strong>${escapeHtml((s.namespace_reactions || {}).label || "detected")}</strong> namespace —
      look up each one's id in that namespace and rename it to match.
      ${unmappedAuditItemsHtml(audit.unmapped_reactions, "reaction", limit)}
    </div>
  `;
}

const BALANCE_COLORS = { balanced: "var(--good)", unbalanced: "var(--bad)", unknown: "var(--warn)", "n/a": "var(--s-other)" };

function reportStatusStack(rows, key, title, colors) {
  const counts = {};
  rows.forEach(r => { counts[r[key]] = (counts[r[key]] || 0) + 1; });
  const order = Object.keys(counts).sort((a, b) => counts[b] - counts[a]);
  return rcStack(order.map((k, i) => ({ label: k, value: counts[k], color: (colors && colors[k]) || RC_SERIES[i % RC_SERIES.length] })), { title });
}

function reportOverviewCharts() {
  const rxnTypes = reportStatusStack(DATA.reactions, "type", "Reactions by type");
  const bal = reportStatusStack(DATA.reactions, "balance", "Reaction balance status", BALANCE_COLORS);
  const comps = rcBars(rcCountBy(DATA.metabolites, m => COMP_NAMES[m.compartment] || m.compartment, 8), { title: "Metabolites per compartment" });
  const subs = rcBars(rcCountBy(DATA.reactions.filter(r => r.subsystem), r => r.subsystem, 12), { title: "Reactions per subsystem (top 12)" });
  return `${rxnTypes}${bal}<div class="rc-grid2">${comps}${subs}</div>`;
}

function reportOverviewSectionHtml() {
  const s = DATA.stats;
  const d = DATA.diet;
  const grLabel = s.reaction_gene_ratio != null ? `1 : ${fmt(s.reaction_gene_ratio, 2)}` : "—";
  const rows = [
    { k: "Model ID", v: s.model_id }, { k: "Model name", v: s.model_name || "—" },
    { k: "Genes", v: s.genes }, { k: "Metabolites", v: s.metabolites }, { k: "Reactions", v: s.reactions },
    { k: "Gene : Reaction ratio", v: grLabel },
    { k: "Compartments", v: s.compartments }, { k: "Objective direction", v: s.objective_direction },
    { k: "WT optimization", v: s.wt_status }, { k: "WT objective value", v: s.wt_growth }, { k: "Solver", v: s.solver },
    { k: "Detected metabolite namespace", v: `${(s.namespace_metabolites || {}).label || "—"}${s.namespace_metabolites && s.namespace_metabolites.coverage != null ? ` (${fmt(s.namespace_metabolites.coverage * 100, 1)}% of ids matched)` : ""}` },
    { k: "Detected reaction namespace", v: `${(s.namespace_reactions || {}).label || "—"}${s.namespace_reactions && s.namespace_reactions.coverage != null ? ` (${fmt(s.namespace_reactions.coverage * 100, 1)}% of ids matched)` : ""}` },
  ];
  const dietNote = d ? `<div class="report-note"><strong>Diet:</strong> ${escapeHtml(d.mode)} — ${escapeHtml(d.note || "")}</div>` : "";
  return `
    <section class="report-section">
    <h2 id="sec-overview">Overview</h2>
    ${staticTableHtml([{ key: "k", label: "Field" }, { key: "v", label: "Value" }], rows)}
    ${dietNote}
    ${reportOverviewCharts()}
    </section>
  `;
}

function reportMetabolitesSectionHtml() {
  // Reuses the live Metabolites tab's own column definitions (original/
  // MetaNetX id, compartment, formula, charge, and the four reaction-role
  // counts), so the report always mirrors whatever the on-screen table
  // currently shows rather than a separately-maintained, easily-stale list.
  return `
    <section class="report-section">
    <h2 id="sec-metabolites">Metabolites</h2>
    ${reportUnmappedWarningHtml("metabolite", 200)}
    ${reportStatusStack(DATA.metabolites.map(m => ({ f: (m.formula || "").trim() ? "formula present" : "formula missing" })), "f", "Metabolites with a chemical formula", { "formula present": "var(--s1)", "formula missing": "var(--warn)" })}
    ${rcHist(DATA.metabolites.map(m => m.reaction_count || 0), { title: "Reactions per metabolite", xLabel: "number of reactions", bins: 20 })}
    ${staticTableHtml(METABOLITE_TABLE_COLUMNS, DATA.metabolites, { emptyMessage: "No metabolites." })}
    </section>
  `;
}

function reportReactionsSectionHtml() {
  return `
    <section class="report-section">
    <h2 id="sec-reactions">Reactions</h2>
    ${reportUnmappedWarningHtml("reaction", 200)}
    ${reportStatusStack(DATA.reactions, "type", "Reactions by type")}
    ${reportStatusStack(DATA.reactions.map(r => ({ f: Math.abs(r.wt_flux || 0) > 1e-9 ? "carries flux (WT)" : "no flux (WT)" })), "f", "Reactions carrying flux in the wild-type solution", { "carries flux (WT)": "var(--s1)", "no flux (WT)": "var(--s-other)" })}
    ${rcBars(rcCountBy(DATA.reactions.filter(r => r.subsystem), r => r.subsystem, 15), { title: "Reactions per subsystem (top 15)" })}
    ${staticTableHtml(REACTION_TABLE_COLUMNS, DATA.reactions, { emptyMessage: "No reactions." })}
    </section>
  `;
}

function reportGenesSectionHtml() {
  const genes = DATA.genes || [];
  const top = [...genes].sort((a, b) => b.reaction_count - a.reaction_count).slice(0, 15).map(g => ({ label: g.name ? `${g.id} (${g.name})` : g.id, value: g.reaction_count }));
  return `
    <section class="report-section">
    <h2 id="sec-genes">Genes</h2>
    ${reportStatusStack(genes.map(g => ({ f: g.lost_on_ko.length ? "deletion disables a reaction" : "no reaction depends on it alone" })), "f", "Genes by effect of a single deletion", { "deletion disables a reaction": "var(--s2)", "no reaction depends on it alone": "var(--s1)" })}
    ${rcHist(genes.map(g => g.reaction_count), { title: "Reactions per gene", xLabel: "number of reactions", bins: 15 })}
    ${rcBars(top, { title: "Genes with the most reactions (top 15)" })}
    ${staticTableHtml(GENE_TABLE_COLUMNS, genes, { emptyMessage: "This model has no genes defined." })}
    </section>
  `;
}

function reportBalanceSectionHtml(data) {
  const c = data.counts || {};
  return `
    <section class="report-section">
    <h2 id="sec-balance">Reaction balance</h2>
    ${rcStack(Object.keys(c).map(k => ({ label: k, value: c[k], color: BALANCE_COLORS[k] || "var(--s-other)" })), { title: "Reactions by balance status" })}
    ${staticTableHtml([{ key: "id", label: "Reaction" }, { key: "name", label: "Name" }, { key: "status", label: "Status" }, { key: "problem", label: "Problem" }],
      data.reactions || [], { emptyMessage: "Every checkable reaction is balanced." })}
    </section>
  `;
}

function reportQualitySectionHtml(report) {
  const m = report.models[0];
  const rows = report.columns.map(c => ({ k: c.label, v: reportCell(m.metrics[c.key]) }));
  const t = REPORT_THRESHOLDS;
  return `
    <section class="report-section">
    <h2 id="sec-quality">Quality findings</h2>
    <div class="report-meta">Thresholds: growth ${t.mu_min}–${t.mu_max} 1/h, blocked reactions &gt; ${t.blocked_warn_pct}%, dead-end metabolites &gt; ${t.deadend_warn_pct}%.</div>
    ${m.findings.length
      ? `<ul class="finding-list">${m.findings.map(f => `<li>${escapeHtml(f)}</li>`).join("")}</ul>`
      : `<div class="report-note">No threshold violations.</div>`}
    <h3>Key statistics</h3>
    ${staticTableHtml([{ key: "k", label: "Statistic" }, { key: "v", label: "Value" }], rows)}
    </section>
  `;
}

function reportObjectiveSectionHtml() {
  return `
    <section class="report-section">
    <h2 id="sec-objective">Objective</h2>
    ${objectiveReactionExpressionHtml(true)}
    ${staticTableHtml(OBJECTIVE_TABLE_COLUMNS, DATA.objective_metabolites || [], { emptyMessage: "No objective metabolites." })}
    </section>
  `;
}

function reportExchangesCharts() {
  const tested = (DATA.exchanges || []).filter(e => e.ko_growth_fraction !== null && e.ko_growth_fraction !== undefined);
  if (!tested.length) return "";
  const lowest = [...tested].sort((a, b) => a.ko_growth_fraction - b.ko_growth_fraction).slice(0, 20)
    .map(e => ({ label: e.id, value: Math.round(1000 * e.ko_growth_fraction) / 10, color: e.essential ? "var(--s2)" : "var(--s1)" }));
  return reportStatusStack(tested.map(e => ({ f: e.essential ? "essential" : "not essential" })), "f", "Exchanges by essentiality", { essential: "var(--s2)", "not essential": "var(--s1)" }) +
    rcBars(lowest, { title: "Growth retained after knocking out each exchange (% of WT, 20 lowest)", unit: "%", note: "Orange bars are essential exchanges (growth below 5% of WT)." });
}

function reportExchangesSectionHtml() {
  return `<section class="report-section"><h2 id="sec-exchanges">Exchange essentiality</h2>${reportExchangesCharts()}${staticTableHtml(EXCHANGE_TABLE_COLUMNS, DATA.exchanges || [], { emptyMessage: "No exchange data (essentiality test may not have finished yet)." })}</section>`;
}

function reportMinimalMediumSectionHtml(data) {
  return `
    <section class="report-section">
    <h2 id="sec-minmed">Minimal medium</h2>
    <div class="report-note">${escapeHtml(data.note || "")}</div>
    ${rcBars((data.components || []).map(c => ({ label: c.metabolite_name || c.exchange_id, value: Math.abs(c.uptake_flux || 0) })).sort((a, b) => b.value - a.value).slice(0, 25),
      { title: "Uptake flux of each minimal-medium component (top 25)", unit: "mmol/gDW/h" })}
    ${staticTableHtml(MINMED_CSV_COLUMNS, data.components || [], { emptyMessage: "No components." })}
    </section>
  `;
}

function reportNetworkGapsSectionHtml(data) {
  return `
    <section class="report-section">
    <h2 id="sec-gaps">Network gaps</h2>
    <div class="report-note">${escapeHtml(data.note || "")}</div>
    ${rcStack([
      { label: "blocked", value: (data.blocked_reactions || []).length, color: "var(--s2)" },
      { label: "can carry flux", value: Math.max(0, DATA.stats.reactions - (data.blocked_reactions || []).length), color: "var(--s1)" },
    ], { title: "Reactions that can carry flux" })}
    ${rcBars(rcCountBy(data.blocked_reactions || [], r => r.subsystem, 12), { title: "Blocked reactions per subsystem (top 12)" })}
    ${rcBars(rcCountBy(data.dead_end_metabolites || [], d => NETGAPS_REASON_LABELS[d.reason] || d.reason, 6), { title: "Dead-end metabolites by reason" })}
    <h3>Blocked reactions</h3>
    ${staticTableHtml(NETGAPS_BLOCKED_CSV_COLUMNS, data.blocked_reactions || [], { emptyMessage: "No blocked reactions." })}
    <h3>Dead-end metabolites</h3>
    ${staticTableHtml(NETGAPS_DEADEND_CSV_COLUMNS, data.dead_end_metabolites || [], { emptyMessage: "No dead-end metabolites." })}
    </section>
  `;
}

function reportDemandSinkSectionHtml(data) {
  return `
    <section class="report-section">
    <h2 id="sec-dsaudit">Demand &amp; sink audit</h2>
    <div class="report-note">${escapeHtml(data.note || "")}</div>
    ${reportStatusStack((data.rows || []).map(r => ({ f: `${r.kind}${r.essential ? " (essential)" : ""}` })), "f", "Demand and sink reactions")}
    ${staticTableHtml(DSAUDIT_CSV_COLUMNS, data.rows || [], { emptyMessage: "No demand or sink reactions." })}
    </section>
  `;
}

function reportTracerSectionHtml(result) {
  const rows = (result.paths || []).map((p, i) => ({
    path: `Path ${i + 1}`,
    steps: p.reactions.map((rxn, idx) => `${rxn.id} (flux=${fmt(rxn.flux)}) -> ${p.metabolites[idx + 1].id}`).join("  ;  "),
  }));
  return `
    <section class="report-section">
    <h2 id="sec-tracer">Pathway tracer (most recent trace)</h2>
    <div class="report-meta">${escapeHtml(result.start_id)} → ${escapeHtml(result.target_metabolite.id)} — ${result.paths.length} path(s), growth ${fmt(result.growth)}.</div>
    ${staticTableHtml([{ key: "path", label: "Path" }, { key: "steps", label: "Steps" }], rows, { emptyMessage: "No paths found." })}
    </section>
  `;
}

async function runGenerateReport(getPath) {
  const statusEl = $("reportModalStatus");
  const btn = $("reportGenerateBtn");
  btn.disabled = true;
  progressStart("reportModalProgress");

  const setStatus = (msg, isError) => {
    statusEl.innerHTML = isError ? `<span class="error">${escapeHtml(msg)}</span>` : escapeHtml(msg);
  };

  try {
    if (!MODEL_ID) throw new Error("Model session expired — please re-run the initial analysis.");

    const wantSections = {};
    REPORT_SECTIONS.forEach(sec => {
      const cb = $(`reportSection_${sec.key}`);
      wantSections[sec.key] = !!(cb && cb.checked && !cb.disabled);
    });

    const sectionsHtml = [];
    const tocEntries = [];

    // Overview / Metabolites / Reactions / Objective / Exchanges are already
    // in memory from the initial analysis -- no re-fetch needed.
    const wantExcel = !!($("reportExcel") && $("reportExcel").checked);
    if (wantSections.quality || wantExcel) {
      setStatus("Computing key statistics and findings…");
      const t = REPORT_THRESHOLDS;
      const res = await fetch("/api/model-report", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: MODEL_ID, mu_min: t.mu_min, mu_max: t.mu_max, blocked_warn_pct: t.blocked_warn_pct,
          deadend_warn_pct: t.deadend_warn_pct, essentiality: "1", minimal_medium: "1", network_gaps: "1", demand_sink: "1", balance: "1" }),
      });
      let qualityReport = null;
      await readNdjson(res, ev => {
        if (ev.type === "error") throw new Error(ev.error);
        if (ev.type === "complete") qualityReport = ev.report;
      });
      if (!qualityReport) throw new Error("The quality analysis ended without a result.");
      if (wantSections.quality) {
        sectionsHtml.push(reportQualitySectionHtml(qualityReport));
        tocEntries.push(["quality", "Quality findings"]);
      }
      if (wantExcel) {
        const a = document.createElement("a");
        a.href = `/api/model-report/${encodeURIComponent(MODEL_ID)}/download?format=xlsx`;
        a.download = "model_report.xlsx";
        document.body.appendChild(a); a.click(); a.remove();
      }
    }
    if (wantSections.overview) {
      sectionsHtml.push(reportOverviewSectionHtml());
      tocEntries.push(["overview", "Overview"]);
    }
    if (wantSections.metabolites) {
      sectionsHtml.push(reportMetabolitesSectionHtml());
      tocEntries.push(["metabolites", "Metabolites"]);
    }
    if (wantSections.reactions) {
      sectionsHtml.push(reportReactionsSectionHtml());
      tocEntries.push(["reactions", "Reactions"]);
    }
    if (wantSections.genes) {
      sectionsHtml.push(reportGenesSectionHtml());
      tocEntries.push(["genes", "Genes"]);
    }
    if (wantSections.objective) {
      sectionsHtml.push(reportObjectiveSectionHtml());
      tocEntries.push(["objective", "Objective"]);
    }
    if (wantSections.exchanges) {
      sectionsHtml.push(reportExchangesSectionHtml());
      tocEntries.push(["exchanges", "Exchange essentiality"]);
    }
    if (wantSections.balance) {
      setStatus("Checking reaction balance…");
      const res = await fetch("/api/balance-diagnostics", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id: MODEL_ID }) });
      const data = await res.json();
      if (!res.ok || data.error) throw new Error(data.error || "Balance check failed.");
      sectionsHtml.push(reportBalanceSectionHtml(data));
      tocEntries.push(["balance", "Reaction balance"]);
    }
    if (wantSections.minimal_medium) {
      let data = MINMED_RESULT;
      if (!data) {
        setStatus("Computing minimal medium…");
        const cutoffInput = $("reportCutoff_minimal_medium");
        let cutoff = parseFloat(cutoffInput ? cutoffInput.value : 1.0);
        if (!Number.isFinite(cutoff) || cutoff <= 0) cutoff = 1.0;
        cutoff = Math.max(0.01, Math.min(1, cutoff));
        const res = await fetch("/api/minimal-medium", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: MODEL_ID, growth_cutoff_fraction: cutoff }),
        });
        data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || "Minimal medium computation failed.");
      }
      sectionsHtml.push(reportMinimalMediumSectionHtml(data));
      tocEntries.push(["minmed", "Minimal medium"]);
    }
    if (wantSections.network_gaps) {
      let data = NETGAPS_RESULT;
      if (!data) {
        setStatus("Computing network gaps (blocked reactions & dead ends)…");
        const res = await fetch("/api/network-gaps", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: MODEL_ID }),
        });
        data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || "Network gaps computation failed.");
      }
      sectionsHtml.push(reportNetworkGapsSectionHtml(data));
      tocEntries.push(["gaps", "Network gaps"]);
    }
    if (wantSections.demand_sink_audit) {
      let data = DSAUDIT_RESULT;
      if (!data) {
        setStatus("Running demand & sink audit…");
        const res = await fetch("/api/demand-sink-audit", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: MODEL_ID }),
        });
        data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || "Demand & sink audit failed.");
      }
      sectionsHtml.push(reportDemandSinkSectionHtml(data));
      tocEntries.push(["dsaudit", "Demand & sink audit"]);
    }
    if (wantSections.pathway_tracer && TRACER_RESULT) {
      sectionsHtml.push(reportTracerSectionHtml(TRACER_RESULT));
      tocEntries.push(["tracer", "Pathway tracer"]);
    }
    if (wantSections.frog) {
      const fraction = parseFloat(($("reportFrogFraction") || {}).value) || 1.0;
      const includeFva = $("reportFrogFva") ? $("reportFrogFva").checked : true;
      const includeRxnDel = $("reportFrogRxnDel") ? $("reportFrogRxnDel").checked : true;
      const includeGeneDel = $("reportFrogGeneDel") ? $("reportFrogGeneDel").checked : true;
      const wantedKey = new URLSearchParams({
        fva_fraction: String(fraction),
        include_fva: includeFva ? "1" : "0",
        include_reaction_deletions: includeRxnDel ? "1" : "0",
        include_gene_deletions: includeGeneDel ? "1" : "0",
      }).toString();
      let frogData = FROG_RESULT && FROG_PARAMS === wantedKey ? FROG_RESULT : null; // same settings already run in the FROG tab
      if (!frogData) {
        setStatus("Running FROG report (this can take a while for large models)…");
        frogData = await runFrogReportForModal(fraction, includeFva, includeRxnDel, includeGeneDel, setStatus);
      }
      sectionsHtml.push(buildFrogSectionBody(frogData));
      tocEntries.push(["frog", "FROG report"]);
    }

    if (!sectionsHtml.length) throw new Error("Select at least one section to include.");

    setStatus("Assembling final report…");
    const modelLabel = (DATA.stats && (DATA.stats.model_name || DATA.stats.model_id)) || "model";
    const s = DATA.stats || {};
    const coverStats = [
      ["Genes", s.genes], ["Metabolites", s.metabolites], ["Reactions", s.reactions],
      ["Compartments", s.compartments], ["WT growth", fmt(DATA.wt_growth)],
      ["Gene : Reaction ratio", s.reaction_gene_ratio != null ? `1 : ${fmt(s.reaction_gene_ratio, 2)}` : "—"],
    ];
    const body = `
      ${reportCoverHtml(`Model Inspector report`, modelLabel, coverStats)}
      ${reportTocHtml(tocEntries)}
      ${sectionsHtml.join("\n")}
    `;
    const html = reportDocumentHtml(`Model report — ${modelLabel}`, body);

    setStatus("Saving…");
    const result = await saveGeneratedHtml(html, getPath(), reportDefaultFilename());
    setStatus(result.message, !result.ok);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    btn.disabled = false;
    progressDone("reportModalProgress");
  }
}

// ---------------------------------------------------------------------------
// MEMOTE (run on request from the Overview page)
// The run happens in a separate process on the server; this code starts it,
// polls its progress, and shows the result. Polling continues while the user
// is on other tabs, and a small status pill in the toolbar tracks it.
// ---------------------------------------------------------------------------
const MEMOTE_PAPER_URL = "https://doi.org/10.1038/s41587-020-0446-y";
const MEMOTE_DOCS_URL = "https://memote.readthedocs.io/";
let MEMOTE_STATE = null;      // last status payload from the server (or null)
let MEMOTE_TIMER = null;
let MEMOTE_SHOW_ALL = false;

function resetMemote() {
  if (MEMOTE_TIMER) { clearInterval(MEMOTE_TIMER); MEMOTE_TIMER = null; }
  if (MODEL_ID_PREVIOUS_FOR_MEMOTE && MEMOTE_STATE && MEMOTE_STATE.status === "running") {
    fetch(`/api/memote/${MODEL_ID_PREVIOUS_FOR_MEMOTE}/cancel`, { method: "POST" }).catch(() => {});
  }
  MEMOTE_STATE = null;
  MEMOTE_SHOW_ALL = false;
  MODEL_ID_PREVIOUS_FOR_MEMOTE = MODEL_ID;
  updateMemotePill();
}
let MODEL_ID_PREVIOUS_FOR_MEMOTE = null;

function memoteScoreColor(x) { return x >= 0.8 ? "#047857" : x >= 0.5 ? "#b45309" : "#b91c1c"; }
function memotePct(x) { return x == null ? "—" : Math.round(x * 100) + "%"; }

// Which tab shows the thing a MEMOTE test is about (best effort).
function memoteTargetTab(name) {
  if (/biomass|ngam|gam_/.test(name)) return ["objective", "Objective"];
  if (/annotation|sbo|namespace|gene_product/.test(name)) return ["annotation", "Annotation"];
  if (/blocked|orphan|deadend|disconnected|not_produced|not_consumed|cycle/.test(name)) return ["gaps", "Network Gaps & Audits"];
  if (/metabolite|formula|charge_presence/.test(name) && !/reaction/.test(name)) return ["metabolites", "Metabolites"];
  if (/reaction|gpr|transport|unbounded|stoich|mass_balance|charge_balance|protein_complex|oxygen/.test(name)) return ["reactions", "Reactions"];
  return null;
}

function memoteStageText(st) {
  if (st.stage === "retrying") return "The solver stopped unexpectedly; retrying with the exact (slower) solver…";
  if (st.stage === "rendering") return "Building the report…";
  if (st.stage === "testing" && st.total) {
    // `running` is the test in progress; `current` is the last one that finished.
    const name = (st.running || st.current || "").replace(/^test_/, "").replace(/_/g, " ");
    const skipped = (st.skipped || []).length
      ? ` (skipped for taking too long: ${st.skipped.map(n => n.replace(/^test_/, "").replace(/_/g, " ")).join(", ")})` : "";
    return `Running check ${Math.min(st.done + 1, st.total)} of ${st.total}${name ? " — " + name : ""}${skipped}. A check that makes no progress for 3 minutes is skipped automatically.`;
  }
  return "Loading the model…";
}

function memoteIssueHtml(t) {
  const target = memoteTargetTab(t.name);
  const sample = (t.data_sample || []).slice(0, 15);
  const more = t.data_count && t.data_count > sample.length ? `\n… and ${t.data_count - sample.length} more` : "";
  return `
    <details class="memote-issue">
      <summary>
        <span class="badge bad">${t.score != null ? memotePct(t.score) : "issue"}</span>
        <strong>${escapeHtml(t.title)}</strong>
        ${t.data_count != null ? `<span class="stoich">${t.data_count} affected</span>` : ""}
        ${target ? `<button class="go-link" type="button" data-goto="${target[0]}">Look at ${escapeHtml(target[1])} →</button>` : ""}
      </summary>
      <div class="memote-issue-body">
        ${t.summary ? `<div>${escapeHtml(t.summary)}</div>` : ""}
        ${t.message ? `<div style="margin-top:6px;">${escapeHtml(t.message)}</div>` : ""}
        ${sample.length ? `<code>${escapeHtml(sample.join("\n") + more)}</code>` : ""}
      </div>
    </details>`;
}

function memoteResultHtml(r) {
  const tests = Object.values(r.tests);
  const issues = tests.filter(t => t.scored && t.status === "issue").sort((a, b) => b.impact - a.impact);
  const shown = MEMOTE_SHOW_ALL ? issues : issues.slice(0, 8);
  const total = r.total_score;
  const bars = r.sections.map(sec => `
    <div class="memote-bar-row">
      <span>${escapeHtml(sec.title)}</span>
      <div class="memote-bar"><div style="width:${Math.round((sec.score || 0) * 100)}%; background:${memoteScoreColor(sec.score || 0)};"></div></div>
      <strong>${memotePct(sec.score)}</strong>
    </div>`).join("");
  const statusBadge = t => t.status === "ok" ? '<span class="badge good">ok</span>'
    : t.status === "issue" ? '<span class="badge bad">issue</span>'
    : t.status === "info" ? '<span class="badge info">info</span>' : '<span class="badge skip">skipped</span>';
  const allCards = r.cards.map(c => `
    <details class="memote-issue">
      <summary><strong>${escapeHtml(c.title)}</strong></summary>
      <div class="memote-issue-body">
        <table><tbody>${c.sections.flatMap(sec => sec.tests).map(n => {
          const t = r.tests[n];
          return `<tr><td>${escapeHtml(t.title)}</td><td>${statusBadge(t)}</td><td>${t.data_count != null ? t.data_count : ""}</td></tr>`;
        }).join("")}</tbody></table>
      </div>
    </details>`).join("");
  const m = r.meta || {};
  return `
    <div class="memote-score">
      <div><div class="memote-score-num" style="color:${memoteScoreColor(total || 0)}">${memotePct(total)}</div>
        <div class="mini-stat-label">MEMOTE total score</div></div>
      <div class="memote-bars">${bars}</div>
    </div>
    <div class="chip-row" style="margin-bottom:12px;">
      <span class="badge good">${r.counts.ok} checks passed</span>
      <span class="badge bad">${r.counts.issue} need attention</span>
      <span class="badge info">${r.counts.info || 0} informational</span>
      <span class="badge skip">${r.counts.skipped} skipped</span>
      <span class="stoich">MEMOTE ${escapeHtml(m.memote_version || "")} · ${escapeHtml(m.duration_seconds)} s</span>
    </div>
    <h4 style="margin:14px 0 8px;">Needs attention <span class="stoich">(scored checks, largest impact on the score first)</span></h4>
    ${shown.length ? shown.map(memoteIssueHtml).join("") : '<div class="note" style="background:#ecfdf5;border-color:#a7f3d0;color:#047857;">No scored checks flagged an issue.</div>'}
    ${issues.length > 8 ? `<button type="button" class="secondary" data-memote-toggle="1">${MEMOTE_SHOW_ALL ? "Show fewer" : `Show all ${issues.length}`}</button>` : ""}
    <h4 style="margin:18px 0 8px;">All checks by category</h4>
    ${allCards}
    <div class="memote-actions" style="margin-top:14px;">
      <a href="/api/memote/${MODEL_ID}/report" target="_blank" rel="noopener"><button type="button">Open full MEMOTE report</button></a>
      <a href="/api/memote/${MODEL_ID}/report?download=1"><button type="button" class="secondary">Download report (HTML)</button></a>
      <button type="button" class="secondary" data-memote-rerun="1">Run again</button>
    </div>
    <p class="stoich" style="margin-top:8px;">MEMOTE was run on the model exactly as uploaded (before any diet was applied).</p>`;
}

function renderMemoteBox() {
  const box = $("memoteBox");
  if (!box) return;
  const st = MEMOTE_STATE;
  let body;
  // DATA.memote_message is only a hint from when the model was loaded; the
  // Run button always works (the server re-checks), so installing MEMOTE
  // doesn't require re-uploading the model.
  const hint = (DATA && DATA.memote_available === false && DATA.memote_message && !(st && st.status !== "error"))
    ? `<div class="note" style="margin-bottom:10px;">${escapeHtml(DATA.memote_message)}</div>` : "";
  if (st && (st.status === "running" || st.status === "queued")) {
    body = `
      <div class="memote-wait">
        <div class="progress-track"><div class="progress-fill" style="width:${st.percent || 3}%"></div></div>
        <div class="memote-wait-msg"><strong>${st.percent || 0}%</strong> · ${escapeHtml(memoteStageText(st))} · ${st.elapsed}s elapsed</div>
        <div class="memote-wait-msg">This can take a few minutes for large models. You don't need to wait here — feel free to explore the other tabs and come back later; the run continues in the background and the status shows at the top.</div>
      </div>
      <div class="memote-actions" style="margin-top:12px;"><button type="button" class="secondary" data-memote-cancel="1">Cancel</button></div>`;
  } else if (st && st.status === "done" && st.result) {
    body = memoteResultHtml(st.result);
  } else {
    const msg = st && st.status === "error" ? `<div class="error" style="margin-bottom:10px;"><strong>MEMOTE did not run.</strong><pre style="white-space:pre-wrap;max-height:260px;overflow:auto;margin:6px 0 0;font-size:12px;">${escapeHtml(st.error || "MEMOTE failed.")}</pre></div>`
      : st && st.status === "cancelled" ? `<div class="note">The run was cancelled.</div>` : "";
    body = `${hint}${msg}<div class="memote-actions"><button type="button" data-memote-run="1">Run MEMOTE</button>
      <span class="stoich">Takes from under a minute to several minutes depending on model size.</span>
      <button type="button" class="secondary" data-memote-test="1">Test MEMOTE setup</button></div>
      <pre id="memoteTestOut" class="hidden" style="white-space:pre-wrap;font-size:12px;background:#f8fafc;border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-top:10px;max-height:220px;overflow:auto;"></pre>`;
  }
  box.innerHTML = `
    <div class="memote-card">
      <div class="memote-head">
        <h3>Model quality check — MEMOTE</h3>
        <a class="info-link" href="${MEMOTE_PAPER_URL}" target="_blank" rel="noopener" title="About MEMOTE: Lieven et al., Nature Biotechnology 2020 (opens the paper)">i</a>
        <a class="stoich" href="${MEMOTE_DOCS_URL}" target="_blank" rel="noopener">documentation</a>
      </div>
      <p class="memote-desc">MEMOTE is the community standard test suite for genome-scale models: it checks stoichiometric consistency, mass and charge balance, annotation quality, biomass, network topology and more, and gives an overall score. It is not run automatically because it takes time — run it when you want a full quality audit.</p>
      ${body}
    </div>`;
  box.querySelector("[data-memote-run]")?.addEventListener("click", startMemote);
  box.querySelector("[data-memote-rerun]")?.addEventListener("click", startMemote);
  box.querySelector("[data-memote-test]")?.addEventListener("click", async (ev) => {
    const out = $("memoteTestOut");
    out.classList.remove("hidden");
    out.textContent = "Testing…";
    try {
      const r = await (await fetch("/api/memote-selftest")).json();
      out.textContent = (r.ok ? "OK — MEMOTE can be used by this app.\n\n" : "MEMOTE cannot be loaded by this app.\n\n") + r.output;
    } catch (err) { out.textContent = "Could not run the test: " + err.message; }
  });
  box.querySelector("[data-memote-cancel]")?.addEventListener("click", cancelMemote);
  box.querySelector("[data-memote-toggle]")?.addEventListener("click", () => { MEMOTE_SHOW_ALL = !MEMOTE_SHOW_ALL; renderMemoteBox(); });
  box.querySelectorAll("[data-goto]").forEach(b => b.addEventListener("click", ev => {
    ev.preventDefault(); ev.stopPropagation(); goToTab(b.dataset.goto);
  }));
  updateMemotePill();
}

function updateMemotePill() {
  const pill = $("memotePill");
  if (!pill) return;
  const st = MEMOTE_STATE;
  pill.className = "memote-pill hidden";
  if (!st || st.status === "none" || st.status === "cancelled") return;
  if (st.status === "running" || st.status === "queued") {
    pill.className = "memote-pill running";
    pill.textContent = `MEMOTE running… ${st.percent || 0}%`;
  } else if (st.status === "done" && st.result) {
    pill.className = "memote-pill done";
    pill.textContent = `MEMOTE score ${memotePct(st.result.total_score)}`;
  } else if (st.status === "error") {
    pill.className = "memote-pill error";
    pill.textContent = "MEMOTE failed";
  }
}

async function startMemote() {
  if (!MODEL_ID) return;
  MEMOTE_SHOW_ALL = false;
  try {
    const resp = await fetch(`/api/memote/${MODEL_ID}/start`, { method: "POST" });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.error || "Could not start MEMOTE");
    MEMOTE_STATE = data;
  } catch (err) {
    MEMOTE_STATE = { status: "error", error: err.message };
  }
  renderMemoteBox();
  pollMemote();
}

function pollMemote() {
  if (MEMOTE_TIMER) clearInterval(MEMOTE_TIMER);
  const forModel = MODEL_ID;
  MEMOTE_TIMER = setInterval(async () => {
    if (forModel !== MODEL_ID) { clearInterval(MEMOTE_TIMER); MEMOTE_TIMER = null; return; }
    try {
      const resp = await fetch(`/api/memote/${forModel}/status`);
      MEMOTE_STATE = await resp.json();
    } catch (err) { return; } // transient network problem: try again next tick
    if (!(MEMOTE_STATE.status === "running" || MEMOTE_STATE.status === "queued")) {
      clearInterval(MEMOTE_TIMER); MEMOTE_TIMER = null;
    }
    renderMemoteBox();
  }, 1500);
}

async function cancelMemote() {
  if (!MODEL_ID) return;
  await fetch(`/api/memote/${MODEL_ID}/cancel`, { method: "POST" }).catch(() => {});
  if (MEMOTE_TIMER) { clearInterval(MEMOTE_TIMER); MEMOTE_TIMER = null; }
  MEMOTE_STATE = { status: "cancelled" };
  renderMemoteBox();
}

$("memotePill").addEventListener("click", () => {
  goToTab("overview");
  $("memoteBox")?.scrollIntoView({ behavior: "smooth", block: "start" });
});

// ---------------------------------------------------------------------------
// References
// ---------------------------------------------------------------------------
const REFERENCES = [
  { name: "MEMOTE", why: "Model quality test suite run from the Overview page.",
    cite: "Lieven C. et al. MEMOTE for standardized genome-scale metabolic model testing. Nature Biotechnology 38, 272–276 (2020).",
    links: [["Paper", "https://doi.org/10.1038/s41587-020-0446-y"], ["Documentation", "https://memote.readthedocs.io/"], ["Source code", "https://github.com/opencobra/memote"]] },
  { name: "COBRApy", why: "Model loading, constraint-based analysis (FBA, FVA, knockouts) and solver interface.",
    cite: "Ebrahim A. et al. COBRApy: COnstraints-Based Reconstruction and Analysis for Python. BMC Systems Biology 7, 74 (2013).",
    links: [["Paper", "https://doi.org/10.1186/1752-0509-7-74"], ["Documentation", "https://cobrapy.readthedocs.io/"]] },
  { name: "Thiele & Palsson protocol", why: "The reconstruction and quality-control workflow that informs the checks in this tool.",
    cite: "Thiele I. & Palsson B.Ø. A protocol for generating a high-quality genome-scale metabolic reconstruction. Nature Protocols 5, 93–121 (2010).",
    links: [["Paper", "https://doi.org/10.1038/nprot.2009.203"]] },
  { name: "FROG reports / COMBINE", why: "Reproducible model-analysis reports (FBA, FVA, gene and reaction deletions).",
    cite: "FROG (FBA, Reaction deletion, Objective function and Gene deletion) reports are a COMBINE community specification for reproducible constraint-based model analysis; see the specification repository for the current reference.",
    links: [["Specification", "https://github.com/matthiaskoenig/fbc_curation"], ["COMBINE", "https://co.mbine.org/"]] },
  { name: "MetaNetX", why: "Cross-reference tables used for ID namespace detection and translation.",
    cite: "Moretti S. et al. MetaNetX/MNXref: unified namespace for metabolites and biochemical reactions in the context of metabolic models. Nucleic Acids Research 49, D570–D574 (2021).",
    links: [["Paper", "https://doi.org/10.1093/nar/gkaa992"], ["Website", "https://www.metanetx.org/"]] },
  { name: "libSBML", why: "Reading and validating SBML model files.",
    cite: "Bornstein B.J. et al. LibSBML: an API library for SBML. Bioinformatics 24, 880–881 (2008).",
    links: [["Paper", "https://doi.org/10.1093/bioinformatics/btn051"], ["Documentation", "https://sbml.org/software/libsbml/"]] },
  { name: "Cytoscape.js", why: "Network visualisation in the Pathway Tracer.",
    cite: "Franz M. et al. Cytoscape.js 2023 update: a graph theory library for visualization and analysis. Bioinformatics 39, btad031 (2023).",
    links: [["Paper", "https://doi.org/10.1093/bioinformatics/btad031"], ["Documentation", "https://js.cytoscape.org/"]] },
  { name: "GLPK", why: "Linear-programming solver used by default.",
    cite: "GNU Linear Programming Kit.",
    links: [["Documentation", "https://www.gnu.org/software/glpk/"]] },
];

function renderReferences() {
  $("references").innerHTML = `
    <h2>References</h2>
    <p class="memote-desc">Tools, standards and data resources this inspector builds on. Please cite them when you use results from this tool.</p>
    <div class="ref-list">${REFERENCES.map(r => `
      <div class="ref-item">
        <h4>${escapeHtml(r.name)}</h4>
        <p>${escapeHtml(r.why)}</p>
        <p>${escapeHtml(r.cite)}</p>
        <div>${r.links.map(([t, u]) => `<a href="${u}" target="_blank" rel="noopener">${escapeHtml(t)} ↗</a>`).join("")}</div>
      </div>`).join("")}</div>`;
}


// ---------------------------------------------------------------------------
// Diagnostics: Reaction Balance
// ---------------------------------------------------------------------------
let BALANCE_RESULT = null;
let BALANCE_FOCUS = null;       // reaction id to open/scroll to
let BALANCE_FILTER = "";        // "", "unbalanced", "unknown"

function renderBalance() {
  $("balance").innerHTML = `
    <h2>Reaction balance</h2>
    <div class="note">
      A reaction is <strong>balanced</strong> when every element (and the net charge) adds up to the same on both sides.
      This tab lists reactions that are <strong>unbalanced</strong> (and by how much of which element) and those that
      <strong>can't be checked</strong> because a metabolite has no chemical formula. Exchange/demand/sink and biomass
      reactions are skipped. Nothing is changed in the model.
    </div>
    <div class="toolbar">
      <button id="balRunBtn" type="button">Check reaction balance</button>
      <select id="balFilter">
        <option value="">Show: all problems</option>
        <option value="unbalanced">Show: unbalanced only</option>
        <option value="unknown">Show: can't check (no formula)</option>
      </select>
      <input id="balSearch" type="text" placeholder="Search reaction or metabolite ID…">
      <span id="balCount"></span>
    </div>
    <div id="balStatus" class="debug-status"></div>
    <div id="balResults"></div>
  `;
  $("balRunBtn").addEventListener("click", () => runBalance());
  $("balFilter").addEventListener("input", () => { BALANCE_FILTER = $("balFilter").value; drawBalance(); });
  $("balSearch").addEventListener("input", drawBalance);
  if (BALANCE_RESULT) drawBalance();
}

async function runBalance() {
  if (!MODEL_ID) { $("balStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`; return; }
  $("balStatus").textContent = "Checking every reaction…";
  $("balRunBtn").disabled = true;
  try {
    const res = await fetch("/api/balance-diagnostics", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id: MODEL_ID }) });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Balance check failed");
    BALANCE_RESULT = data;
    $("balStatus").textContent = "";
    drawBalance();
  } catch (err) {
    $("balStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
  } finally {
    $("balRunBtn").disabled = false;
  }
}

function openBalanceDiagnostics(rxnId, filter) {
  BALANCE_FOCUS = rxnId || null;
  if (rxnId) {
    const r = DATA.reactions.find(x => x.id === rxnId);
    BALANCE_FILTER = r && r.balance === "unknown" ? "unknown" : "unbalanced";
  } else {
    BALANCE_FILTER = filter || "";
  }
  goToTab("balance");
  if ($("balFilter")) $("balFilter").value = BALANCE_FILTER;
  if (BALANCE_RESULT) drawBalance(); else runBalance();
}

function drawBalance() {
  const data = BALANCE_RESULT;
  if (!data) return;
  const c = data.counts;
  const q = ($("balSearch").value || "").toLowerCase();
  let rows = data.reactions.filter(r =>
    (!BALANCE_FILTER || r.status === BALANCE_FILTER) &&
    (!q || `${r.id} ${r.name} ${r.metabolites.map(m => m.id).join(" ")}`.toLowerCase().includes(q)));
  $("balFilter").value = BALANCE_FILTER;
  $("balCount").textContent = `${rows.length} shown`;
  // Put the reaction the user clicked first.
  if (BALANCE_FOCUS) rows = [...rows.filter(r => r.id === BALANCE_FOCUS), ...rows.filter(r => r.id !== BALANCE_FOCUS)];
  const LIMIT = 300;
  const shown = rows.slice(0, LIMIT);
  const cards = [["Balanced", c.balanced, "good"], ["Unbalanced", c.unbalanced, "bad"], ["Can't check", c.unknown, "warn"], ["Not applicable", c["n/a"], ""]];
  $("balResults").innerHTML = `
    <div class="chip-row" style="margin-bottom:12px;">${cards.map(([l, v, cl]) => `<span class="badge ${cl}">${l}: ${v}</span>`).join(" ")}
      <span class="stoich">of ${data.total} reactions</span></div>
    ${shown.length ? shown.map(r => `
      <details class="memote-issue"${r.id === BALANCE_FOCUS ? " open" : ""} id="bal-${escapeHtml(r.id)}">
        <summary>
          <span class="badge ${r.status === "unbalanced" ? "bad" : "warn"}">${r.status === "unbalanced" ? "unbalanced" : "can't check"}</span>
          <strong>${escapeHtml(r.id)}</strong>
          <span class="stoich">${escapeHtml(r.name)}</span>
          ${r.status === "unbalanced" ? `<span class="stoich">${Object.entries(r.imbalance).map(([k, v]) => `${escapeHtml(k)} ${v > 0 ? "+" : ""}${fmt(v, 3)}`).join(", ")}</span>` : ""}
        </summary>
        <div class="memote-issue-body">
          <div><strong>What's wrong:</strong> ${escapeHtml(r.problem)}</div>
          <code>${escapeHtml(r.reaction)}</code>
          <table style="margin-top:8px;"><thead><tr><th>Metabolite</th><th>Name</th><th>Coefficient</th><th>Formula</th><th>Charge</th></tr></thead><tbody>
            ${r.metabolites.map(m => `<tr><td>${escapeHtml(m.id)}</td><td>${escapeHtml(m.name)}</td><td>${fmt(m.coefficient, 4)}</td>
              <td${m.formula ? "" : ' style="color:#b91c1c;font-weight:700;"'}>${escapeHtml(m.formula || "missing")}</td>
              <td${m.charge == null ? ' style="color:#b45309;"' : ""}>${m.charge == null ? "missing" : escapeHtml(m.charge)}</td></tr>`).join("")}
          </tbody></table>
        </div>
      </details>`).join("") : `<div class="note" style="background:#ecfdf5;border-color:#a7f3d0;color:#047857;">Nothing to show for this filter.</div>`}
    ${rows.length > LIMIT ? `<div class="note">Showing the first ${LIMIT} of ${rows.length}. Use the filter or search to narrow down.</div>` : ""}`;
  if (BALANCE_FOCUS) {
    const el = document.getElementById("bal-" + BALANCE_FOCUS);
    if (el) el.scrollIntoView({ block: "nearest" });
  }
}

// ---------------------------------------------------------------------------
// Diagnostics: Biomass precursor producibility
// ---------------------------------------------------------------------------
let PRECURSOR_RESULT = null;

function renderPrecursors() {
  $("precursors").innerHTML = `
    <h2>Biomass precursor check</h2>
    <div class="note">
      For each biomass reaction, every precursor (each metabolite the biomass reaction consumes) is tested on its own:
      can the model produce it at all? Each is tested <strong>under the current diet/medium</strong> and again
      <strong>with every exchange opened</strong>. A precursor that fails only on the current diet points to a missing
      nutrient; one that fails even with everything open points to a gap in the network. Cofactors such as ATP or NADPH
      that only work when their partner (ADP, NADP+) is returned are marked <em>cofactor</em>. The model is not changed.
    </div>
    <div class="toolbar"><button id="precRunBtn" type="button">Run precursor check</button><span id="precCount"></span></div>
    <div id="precStatus" class="debug-status"></div>
    ${progressBarHtml("precProgress")}
    <div id="precResults"></div>
  `;
  $("precRunBtn").addEventListener("click", runPrecursors);
  if (PRECURSOR_RESULT) drawPrecursors();
}

async function runPrecursors() {
  if (!MODEL_ID) { $("precStatus").innerHTML = `<span class="error">Model session expired — please re-run the initial analysis.</span>`; return; }
  $("precRunBtn").disabled = true;
  $("precStatus").textContent = "Testing each biomass precursor (two solves per precursor)…";
  progressStart("precProgress", true);
  try {
    const res = await fetch("/api/biomass-precursors", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id: MODEL_ID }) });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || "Precursor check failed");
    PRECURSOR_RESULT = data;
    $("precStatus").textContent = "";
    drawPrecursors();
  } catch (err) {
    $("precStatus").innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
  } finally {
    progressDone("precProgress");
    $("precRunBtn").disabled = false;
  }
}

function drawPrecursors() {
  const verdictBadge = v => v === "ok" ? '<span class="badge good">producible</span>'
    : v === "diet" ? '<span class="badge warn">needs a nutrient</span>'
    : v === "recycled" ? '<span class="badge info" title="Producible when its paired form is returned">cofactor</span>'
    : '<span class="badge bad">not producible</span>';
  const order = { gap: 0, diet: 1, recycled: 2, ok: 3 };
  $("precResults").innerHTML = PRECURSOR_RESULT.biomass_reactions.map(b => {
    const c = b.counts;
    const rows = [...b.precursors].sort((x, y) => order[x.verdict] - order[y.verdict] || x.id.localeCompare(y.id));
    return `
      <h3>${escapeHtml(b.id)} <span class="stoich">${escapeHtml(b.name)}</span></h3>
      <div class="chip-row" style="margin-bottom:10px;">
        <span class="badge good">producible: ${c.ok}</span>
        <span class="badge warn">needs a nutrient: ${c.diet}</span>
        <span class="badge info">cofactor: ${c.recycled}</span>
        <span class="badge bad">not producible: ${c.gap}</span>
        <span class="stoich">of ${b.precursors.length} precursors</span>
      </div>
      <div class="table-wrap"><table>
        <thead><tr><th>Precursor</th><th>Name</th><th>Compartment</th><th>Biomass coeff.</th><th>Max flux (current diet)</th><th>Max flux (exchanges open)</th><th># Producing reactions</th><th>Result</th><th>What's missing</th></tr></thead>
        <tbody>${rows.map(p => `<tr>
          <td><strong>${escapeHtml(p.id)}</strong></td><td class="wrap">${escapeHtml(p.name)}</td>
          <td>${compartmentBadges([p.compartment])}</td><td class="num">${fmt(Math.abs(p.coefficient), 4)}</td>
          <td class="num">${fmt(p.current.max_flux, 4)}</td><td class="num">${fmt(p.open.max_flux, 4)}</td>
          <td class="num">${p.producers}</td><td>${verdictBadge(p.verdict)}</td>
          <td class="wrap" style="white-space:normal;min-width:480px;">${escapeHtml(p.hint || "—")}</td></tr>`).join("")}</tbody>
      </table></div>`;
  }).join("");
}
