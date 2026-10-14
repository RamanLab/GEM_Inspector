// ---------------------------------------------------------------------------
// Landing page: "Analyze multiple models". Upload several model files, get a
// side-by-side statistics table and quality findings, and download the
// comparison as an Excel workbook and an HTML report.
// Loaded after report_common.js.
// ---------------------------------------------------------------------------
(function () {
  const card = $("multiCard");
  if (!card) return;
  card.querySelector(".report-options-slot").innerHTML = reportOptionsHtml("multi");
  const input = $("multiFiles");
  const button = $("multiBtn");
  const status = $("multiStatus");
  const results = $("multiResults");

  const dropzone = $("multiDropzone");
  ["dragenter", "dragover"].forEach(e => dropzone.addEventListener(e, ev => { ev.preventDefault(); dropzone.classList.add("drag"); }));
  ["dragleave", "drop"].forEach(e => dropzone.addEventListener(e, ev => { ev.preventDefault(); dropzone.classList.remove("drag"); }));
  dropzone.addEventListener("drop", ev => {
    if (ev.dataTransfer.files.length) { input.files = ev.dataTransfer.files; input.dispatchEvent(new Event("change")); }
  });

  input.addEventListener("change", () => {
    const n = input.files.length;
    $("multiFilename").textContent = n ? `${n} file(s) selected` : "";
    button.disabled = n < 2;
    status.textContent = n === 1 ? "Choose at least two models." : "";
  });

  button.addEventListener("click", async () => {
    const form = new FormData();
    [...input.files].forEach(f => form.append("models", f));
    Object.entries(reportOptionsValues("multi")).forEach(([k, v]) => form.append(k, v));
    button.disabled = true;
    results.innerHTML = "";
    status.textContent = "Starting…";
    try {
      const res = await fetch("/api/multi-analyze", { method: "POST", body: form });
      let final = null;
      await readNdjson(res, ev => {
        if (ev.type === "progress") status.textContent = `${ev.message} (${ev.current}/${ev.total})`;
        if (ev.type === "error") throw new Error(ev.error);
        if (ev.type === "complete") final = ev;
      });
      if (!final) throw new Error("The analysis ended without a result.");
      status.textContent = "";
      draw(final);
    } catch (err) {
      status.innerHTML = `<span class="error">${escapeHtml(err.message)}</span>`;
    } finally {
      button.disabled = input.files.length < 2;
    }
  });

  function draw(final) {
    const report = final.report;
    const failed = final.failed.length
      ? `<div class="note"><strong>Skipped:</strong> ${final.failed.map(f => `${escapeHtml(f.file)} (${escapeHtml(f.error)})`).join("; ")}</div>` : "";
    results.innerHTML = `
      <h3>Comparison of ${report.n_models} model(s)</h3>
      ${failed}${reportObservationsHtml(report)}
      ${reportDownloadsHtml(`/api/multi-report/${encodeURIComponent(final.run_id)}?`)}
      ${reportSummaryHtml(report)}
      <h3>Findings</h3>${reportFindingsHtml(report)}`;
  }
})();
