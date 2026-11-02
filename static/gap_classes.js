// ---------------------------------------------------------------------------
// Network Gaps: class badges and the class chips that filter the two tables.
// The tables and the run sequence are in app.js. Loaded after app.js.
// ---------------------------------------------------------------------------
const gapsFilter = { dead: null, blocked: null };

const GAP_BADGE_STYLE = {
  rnp: "bad", rnc: "bad", dnp: "warn", unc: "warn",
  dead_end_linked: "bad", not_dead_end_linked: "warn",
};

function gapClassBadge(key, label) {
  return `<span class="badge ${GAP_BADGE_STYLE[key] || ""}">${escapeHtml(label || key)}</span>`;
}

// Classes of one row: dead-end metabolites can have several, reactions one.
function gapClassesOf(kind, row) {
  return kind === "dead" ? row.classes : [row.class];
}

// The rows of one table that pass its class filter.
function gapRows(kind) {
  const rows = kind === "dead" ? gapsDeadData.dead_end_metabolites : gapsBlockedData.blocked_reactions;
  return gapsFilter[kind] ? rows.filter(r => gapClassesOf(kind, r).includes(gapsFilter[kind])) : rows;
}

function gapChipsHtml(kind, rows, labels) {
  const counts = {};
  rows.forEach(r => gapClassesOf(kind, r).forEach(c => { counts[c] = (counts[c] || 0) + 1; }));
  const chips = Object.entries(labels).filter(([key]) => counts[key]).map(([key, label]) =>
    `<button type="button" class="gap-chip ${gapsFilter[kind] === key ? "active" : ""}" data-kind="${kind}" data-class="${key}">${escapeHtml(label)} <strong>${counts[key]}</strong></button>`);
  return chips.length ? `<div class="gap-chips">${chips.join("")}</div>` : "";
}

function drawGapChips() {
  if (gapsDeadData) $("gapsDeadChips").innerHTML = gapChipsHtml("dead", gapsDeadData.dead_end_metabolites, gapsDeadData.class_labels);
  if (gapsBlockedData) $("gapsBlockedChips").innerHTML = gapChipsHtml("blocked", gapsBlockedData.blocked_reactions,
    { dead_end_linked: "Dead-end-linked", not_dead_end_linked: "Not dead-end-linked" });
}

document.addEventListener("click", ev => {
  const chip = ev.target.closest(".gap-chip");
  if (!chip) return;
  const { kind, class: key } = chip.dataset;
  gapsFilter[kind] = gapsFilter[kind] === key ? null : key;
  drawGapTables();
});
