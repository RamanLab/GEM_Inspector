// ---------------------------------------------------------------------------
// Shared pieces of the model-report UI (single-model "Model report" tab and
// the multi-model card on the landing page): QC option controls, reading the
// streamed progress, and the summary table / findings. Loaded after app.js.
// ---------------------------------------------------------------------------

// Controls for the QC thresholds and the optional analyses. `prefix` keeps the
// element ids of the two places that use them apart.
function reportOptionsHtml(prefix) {
  const num = (name, label, value) => `<label>${label} <input id="${prefix}_${name}" type="number" step="any" value="${value}" style="width:5.5em"></label>`;
  const box = (name, label, checked = true) => `<label><input id="${prefix}_${name}" type="checkbox"${checked ? " checked" : ""}> ${label}</label>`;
  return `
    <details class="report-options">
      <summary>Thresholds and analyses</summary>
      <div class="toolbar">
        ${num("mu_min", "Growth rate min (1/h)", 0.05)} ${num("mu_max", "max (1/h)", 2)}
        ${num("blocked_warn_pct", "Warn if blocked reactions &gt; %", 15)} ${num("deadend_warn_pct", "dead-end metabolites &gt; %", 10)}
      </div>
      <div class="toolbar">
        ${box("essentiality", "Exchange essentiality")} ${box("minimal_medium", "Minimal medium")}
        ${box("network_gaps", "Blocked reactions &amp; dead ends")} ${box("demand_sink", "Demand &amp; sink audit")} ${box("balance", "Mass/charge balance")}
      </div>
      <div class="stoich">Each analysis re-solves the model many times; switch off the ones you don't need for a faster report.</div>
    </details>`;
}

// The option values as a plain object (thresholds as numbers, analyses as "1"/"0").
function reportOptionsValues(prefix) {
  const out = {};
  ["mu_min", "mu_max", "blocked_warn_pct", "deadend_warn_pct"].forEach(n => { out[n] = $(`${prefix}_${n}`).value; });
  ["essentiality", "minimal_medium", "network_gaps", "demand_sink", "balance"].forEach(n => { out[n] = $(`${prefix}_${n}`).checked ? "1" : "0"; });
  return out;
}

// Read a newline-delimited JSON response, calling onEvent for each event.
async function readNdjson(response, onEvent) {
  if (!response.ok && !(response.headers.get("content-type") || "").includes("ndjson")) {
    let message = "Request failed";
    try { message = (await response.json()).error || message; } catch (e) { /* not JSON */ }
    throw new Error(message);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    let newline;
    while ((newline = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (line) onEvent(JSON.parse(line));
    }
    if (done) break;
  }
  if (buffer.trim()) onEvent(JSON.parse(buffer));
}

function reportCell(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : Number(value.toPrecision(4)).toString();
  return String(value);
}

// Compact table of the key numbers (one row per model) with finding counts.
function reportSummaryHtml(report) {
  const head = report.columns.map(c => `<th>${escapeHtml(c.label)}</th>`).join("") + "<th>Findings</th>";
  const rows = report.models.map(m => `<tr>${report.columns.map(c => `<td>${escapeHtml(reportCell(m.metrics[c.key]))}</td>`).join("")}
      <td><span class="badge ${m.findings.length ? "warn" : "good"}">${m.findings.length}</span></td></tr>`).join("");
  return `<div class="table-wrap" style="max-height:none;"><table><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function reportObservationsHtml(report) {
  return report.observations.length ? `<div class="note">${report.observations.map(escapeHtml).join("<br>")}</div>` : "";
}

function reportFindingsHtml(report) {
  return report.models.map(m => `
    <details class="memote-issue">
      <summary><strong>${escapeHtml(m.metrics.display_name)}</strong><span class="badge ${m.findings.length ? "warn" : "good"}">${m.findings.length}</span>
        <span class="stoich">${escapeHtml(m.metrics.source_file)}</span></summary>
      <div class="memote-issue-body">${m.findings.length ? `<ul>${m.findings.map(f => `<li>${escapeHtml(f)}</li>`).join("")}</ul>` : "No threshold violations."}</div>
    </details>`).join("");
}

function reportDownloadsHtml(base) {
  return `<div class="toolbar">
    <a href="${base}format=xlsx" download><button type="button" style="background:var(--accent);color:#fff;">Download Excel (.xlsx)</button></a>
    <a href="${base}format=html" download><button type="button">Download HTML</button></a>
    <a href="${base}format=html&inline=1" target="_blank" rel="noopener"><button type="button">Open HTML report</button></a>
  </div>`;
}
