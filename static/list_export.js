// ---------------------------------------------------------------------------
// "Copy to clipboard" / "Download CSV" buttons for lists of ids, shared by the
// Compare Models and SEED -> VMH Translation tabs. Loaded after app.js and uses
// its delimCell() helper.
//
// Usage: put exportButtonsHtml(key) next to a list, then call
// wireExportButtons(root, resolve) once on the container. resolve(key) returns
// {filename, columns, rows} -- the columns/rows to export for that list.
// ---------------------------------------------------------------------------

function listToDelimited(columns, rows, delimiter) {
  const line = cells => cells.map(c => delimCell(c, delimiter)).join(delimiter);
  const header = line(columns.map(c => c.label));
  const body = (rows || []).map(row => line(columns.map(c => (typeof c.value === "function" ? c.value(row) : row[c.key]))));
  return [header, ...body].join("\r\n");
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (err) {
    // Clipboard API unavailable (e.g. non-secure context): fall back to a hidden textarea.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(area);
    return ok;
  }
}

function downloadText(filename, text, mime) {
  const blob = new Blob([text], { type: mime || "text/plain;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportButtonsHtml(key) {
  const k = escapeHtml(key);
  return `<span class="export-btns">
    <button type="button" class="tt-btn" data-export-key="${k}" data-export-action="copy" title="Copy as tab-separated text (pastes into Excel)">Copy</button>
    <button type="button" class="tt-btn" data-export-key="${k}" data-export-action="download" title="Download as a CSV file">Download CSV</button>
  </span>`;
}

function wireExportButtons(root, resolve) {
  root.querySelectorAll("button[data-export-key]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const spec = resolve(btn.dataset.exportKey);
      if (!spec) return;
      if (btn.dataset.exportAction === "copy") {
        const ok = await copyText(listToDelimited(spec.columns, spec.rows, "\t"));
        const original = btn.textContent;
        btn.textContent = ok ? "Copied ✓" : "Copy failed";
        setTimeout(() => { btn.textContent = original; }, 1500);
      } else {
        downloadText(spec.filename, listToDelimited(spec.columns, spec.rows, ","), "text/csv;charset=utf-8;");
      }
    });
  });
}

// Bounded preview table for long id lists (the full list is what gets exported).
function previewTableHtml(columns, rows, limit) {
  const shown = rows.slice(0, limit);
  const head = columns.map(c => `<th>${escapeHtml(c.label)}</th>`).join("");
  const body = shown.map(r => `<tr>${columns.map(c => `<td>${escapeHtml(typeof c.value === "function" ? c.value(r) : r[c.key])}</td>`).join("")}</tr>`).join("");
  const more = rows.length > limit ? `<div class="stoich" style="margin-top:6px;">Showing the first ${limit} of ${rows.length}. Copy / Download includes all of them.</div>` : "";
  return `<div class="table-wrap" style="max-height:320px;"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${more}`;
}
