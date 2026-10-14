// ---------------------------------------------------------------------------
// Quality thresholds. One shared set of values: shown on the analysis tabs they
// belong to (Summary: growth range, Network Gaps: % blocked / dead-end) and in
// the "Generate report" popup, and used for the report's Quality findings.
// Loaded after app.js.
// ---------------------------------------------------------------------------
const REPORT_THRESHOLDS = { mu_min: 0.05, mu_max: 2, blocked_warn_pct: 15, deadend_warn_pct: 10 };

function thresholdInputHtml(name, label, width) {
  return `<label class="th-field">${label} <input type="number" step="any" data-th="${name}" value="${REPORT_THRESHOLDS[name]}" style="width:${width || "5.5em"}"></label>`;
}

// Keep every input with the same data-th in step with REPORT_THRESHOLDS.
function bindThresholdInputs(root) {
  root.querySelectorAll("[data-th]").forEach(input => {
    input.addEventListener("input", () => {
      const v = parseFloat(input.value);
      if (!Number.isFinite(v)) return;
      REPORT_THRESHOLDS[input.dataset.th] = v;
      document.querySelectorAll(`[data-th="${input.dataset.th}"]`).forEach(o => { if (o !== input) o.value = input.value; });
      updateThresholdVerdicts();
    });
  });
}

function thresholdVerdict(ok, text) {
  return `<span class="badge ${ok ? "good" : "warn"}">${ok ? "OK" : "Check"}</span> ${escapeHtml(text)}`;
}

function updateThresholdVerdicts() {
  const g = $("growthVerdict");
  if (g && DATA) {
    const mu = DATA.stats.wt_growth, t = REPORT_THRESHOLDS;
    g.innerHTML = thresholdVerdict(mu >= t.mu_min && mu <= t.mu_max,
      `WT growth ${fmt(mu)} 1/h is ${mu >= t.mu_min && mu <= t.mu_max ? "inside" : "outside"} the expected range.`);
  }
  const n = $("gapsVerdict");
  if (n) {
    if (!NETGAPS_RESULT || !DATA) { n.textContent = "Run the analysis below to compare it with these thresholds."; return; }
    const t = REPORT_THRESHOLDS;
    const bp = 100 * (NETGAPS_RESULT.blocked_reactions || []).length / Math.max(1, DATA.stats.reactions);
    const dp = 100 * (NETGAPS_RESULT.dead_end_metabolites || []).length / Math.max(1, DATA.stats.metabolites);
    n.innerHTML = thresholdVerdict(bp <= t.blocked_warn_pct, `${fmt(bp, 3)}% of reactions are blocked.`) + " &nbsp; " +
                  thresholdVerdict(dp <= t.deadend_warn_pct, `${fmt(dp, 3)}% of metabolites are dead ends.`);
  }
}

// Called from renderAll(): adds the threshold rows to the Summary and Network Gaps tabs.
function renderThresholdRows() {
  const summary = $("overview").querySelector(".mini-stats");
  if (summary) {
    summary.insertAdjacentHTML("afterend", `<div class="threshold-row" id="growthRow">
      ${thresholdInputHtml("mu_min", "Expected growth from")} ${thresholdInputHtml("mu_max", "to")} 1/h
      <span id="growthVerdict"></span></div>`);
    bindThresholdInputs($("growthRow"));
  }
  const note = $("gaps").querySelector(".note");
  if (note) {
    note.insertAdjacentHTML("afterend", `<div class="threshold-row" id="gapsRow">
      ${thresholdInputHtml("blocked_warn_pct", "Warn if blocked reactions &gt;")} % ${thresholdInputHtml("deadend_warn_pct", "dead-end metabolites &gt;")} %
      <span id="gapsVerdict"></span></div>`);
    bindThresholdInputs($("gapsRow"));
  }
  updateThresholdVerdicts();
}
