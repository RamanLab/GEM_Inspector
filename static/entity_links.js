// ---------------------------------------------------------------------------
// Cross-linking for reaction, metabolite and gene ids.
//
// Any id rendered with entityLink() is a hyperlink: hovering shows a small
// metadata card, clicking jumps to that entity's tab filtered to it.
// Counts rendered with metReactionsLink() open a popup listing the metabolite's
// reactions (also a sortable table whose ids are links again).
// Loaded after app.js; uses DATA, goToTab, escapeHtml, fmt, makeSortable.
// ---------------------------------------------------------------------------
const ENTITY_KINDS = {
  rxn:  { tab: "reactions",   search: "rxnSearch",  rows: () => DATA.reactions },
  met:  { tab: "metabolites", search: "metSearch",  rows: () => DATA.metabolites },
  gene: { tab: "genes",       search: "geneSearch", rows: () => DATA.genes },
};

// id -> row lookups, rebuilt whenever a different model's DATA is loaded.
const entityIndex = { data: null };
function entityRow(kind, id) {
  if (entityIndex.data !== DATA) {
    entityIndex.data = DATA;
    for (const k in ENTITY_KINDS) entityIndex[k] = new Map((ENTITY_KINDS[k].rows() || []).map(r => [r.id, r]));
  }
  return entityIndex[kind].get(id);
}

// ---- link markup -----------------------------------------------------------
function entityLink(kind, id) {
  return `<a class="ent-link" data-ent="${kind}" data-id="${escapeHtml(id)}">${escapeHtml(id)}</a>`;
}

// A metabolite's reactions: first `max` as links, the rest behind "+N more".
function metReactionsLink(metId, label) {
  return `<a class="ent-rxnset" data-met="${escapeHtml(metId)}" title="Show all reactions of ${escapeHtml(metId)}">${label}</a>`;
}
function metReactionLinks(m, max = 5) {
  const ids = m.reactions || [];
  if (!ids.length) return "—";
  const more = ids.length - max;
  return `<div class="gene-list">${ids.slice(0, max).map(id => entityLink("rxn", id)).join(", ")}` +
    `${more > 0 ? ` ${metReactionsLink(m.id, `+${more} more`)}` : ""}</div>`;
}

// Plain list of ids of one kind, e.g. a gene's reactions.
function entityLinkList(kind, ids) {
  return ids && ids.length ? `<div class="gene-list">${ids.map(id => entityLink(kind, id)).join(", ")}</div>` : "—";
}

// A GPR rule with every gene id turned into a link; and/or/parentheses kept.
function gprHtml(rule) {
  if (!rule || !rule.trim()) return "—";
  return escapeHtml(rule).replace(/[^\s()]+/g, tok =>
    /^(and|or)$/i.test(tok) || !entityRow("gene", tok.replace(/&amp;/g, "&")) ? tok : entityLink("gene", tok.replace(/&amp;/g, "&")));
}

// A reaction equation with every metabolite id turned into a link; coefficients and arrows kept.
function equationHtml(eq) {
  if (!eq || !eq.trim()) return "—";
  return eq.split(/(\s+)/).map(tok => entityRow("met", tok) ? entityLink("met", tok) : escapeHtml(tok)).join("");
}

// Table-search helper: a query starting with "=" is an exact id match (used
// when arriving from a link); anything else is a substring search.
function searchMatches(q, id, haystack) {
  return !q || (q[0] === "=" ? id.toLowerCase() === q.slice(1) : haystack.toLowerCase().includes(q));
}

// ---- navigation ------------------------------------------------------------
function openEntity(kind, id) {
  const spec = ENTITY_KINDS[kind];
  closeEntityPopup();
  hideEntityCard();
  goToTab(spec.tab);
  const panel = $(spec.tab);
  panel.querySelectorAll(".toolbar select").forEach(s => { s.value = ""; });
  const box = $(spec.search);
  box.value = "=" + id;
  box.dispatchEvent(new Event("input"));
  panel.scrollIntoView({ block: "start" });
}

// ---- hover card ------------------------------------------------------------
const ENTITY_CARD_MAX_IDS = 24;
let entityCardEl = null, entityCardTimer = null;

function cardRow(label, value) {
  return value === null || value === undefined || value === "" ? "" :
    `<div><span class="ent-k">${label}</span> ${value}</div>`;
}

function reactionCardHtml(r) {
  return `<div class="ent-title">${escapeHtml(r.id)}</div>
    <div>${escapeHtml(r.name || "")}</div>
    <div class="ent-eq">${escapeHtml(r.equation || "")}</div>
    ${cardRow("Type", escapeHtml(r.type))}${cardRow("Subsystem", escapeHtml(r.subsystem))}
    ${cardRow("Bounds", `${fmt(r.lower_bound, 6)} … ${fmt(r.upper_bound, 6)}`)}
    ${cardRow("WT flux", fmt(r.wt_flux))}${cardRow("GPR", escapeHtml(r.gene_reaction_rule))}`;
}

function metaboliteCardHtml(m) {
  return `<div class="ent-title">${escapeHtml(m.id)}</div>
    <div>${escapeHtml(m.name || "")}</div>
    ${cardRow("Formula", escapeHtml(m.formula))}${cardRow("Charge", escapeHtml(m.charge))}
    ${cardRow("Compartment", escapeHtml(COMP_NAMES[m.compartment] || m.compartment))}
    ${cardRow("Reactions", `${m.reaction_count ?? 0} (${m.produced_count ?? 0} produced, ${m.consumed_count ?? 0} consumed, ${m.reversible_count ?? 0} reversible)`)}`;
}

function geneCardHtml(g) {
  return `<div class="ent-title">${escapeHtml(g.id)}</div>
    <div>${escapeHtml(g.name || "")}</div>
    ${cardRow("Reactions", g.reaction_count)}${cardRow("Active in WT", g.active_count)}
    ${cardRow("Lost if deleted", (g.lost_on_ko || []).length)}${cardRow("Functional", g.functional ? "Yes" : "No")}`;
}

// The reaction ids of a metabolite, as links, for hovering over a count.
function metaboliteReactionsCardHtml(m) {
  const ids = m.reactions || [];
  const more = ids.length - ENTITY_CARD_MAX_IDS;
  return `<div class="ent-title">${escapeHtml(m.id)} — ${ids.length} reaction(s)</div>
    <div class="ent-ids">${ids.slice(0, ENTITY_CARD_MAX_IDS).map(id => entityLink("rxn", id)).join(", ")}</div>
    <div class="ent-hint">${more > 0 ? `+${more} more — ` : ""}click to open the full list</div>`;
}

function entityCardHtml(el) {
  if (el.dataset.met) {
    const m = entityRow("met", el.dataset.met);
    return m && metaboliteReactionsCardHtml(m);
  }
  const row = entityRow(el.dataset.ent, el.dataset.id);
  if (!row) return null;
  return { rxn: reactionCardHtml, met: metaboliteCardHtml, gene: geneCardHtml }[el.dataset.ent](row);
}

function hideEntityCard() {
  clearTimeout(entityCardTimer);
  if (entityCardEl) entityCardEl.classList.add("hidden");
}

function showEntityCard(el) {
  const html = entityCardHtml(el);
  if (!html) return;
  if (!entityCardEl) {
    entityCardEl = document.createElement("div");
    entityCardEl.className = "ent-card hidden";
    // Stay open while the pointer is on the card so its ids can be clicked.
    entityCardEl.addEventListener("mouseenter", () => clearTimeout(entityCardTimer));
    entityCardEl.addEventListener("mouseleave", hideEntityCard);
    document.body.appendChild(entityCardEl);
  }
  clearTimeout(entityCardTimer);
  entityCardEl.innerHTML = html;
  entityCardEl.classList.remove("hidden");
  const rect = el.getBoundingClientRect();
  const { width, height } = entityCardEl.getBoundingClientRect();
  const left = Math.min(Math.max(8, rect.left), window.innerWidth - width - 8);
  const top = rect.bottom + height + 8 > window.innerHeight ? Math.max(8, rect.top - height - 4) : rect.bottom + 4;
  entityCardEl.style.left = `${left + window.scrollX}px`;
  entityCardEl.style.top = `${top + window.scrollY}px`;
}

// ---- reactions popup (filtered table) --------------------------------------
let entityPopupEl = null;

function closeEntityPopup() {
  if (entityPopupEl) entityPopupEl.classList.add("hidden");
}

function showMetaboliteReactionsPopup(metId) {
  const met = entityRow("met", metId);
  if (!met) return;
  hideEntityCard();
  if (!entityPopupEl) {
    entityPopupEl = document.createElement("div");
    entityPopupEl.className = "modal-overlay hidden";
    entityPopupEl.addEventListener("click", ev => { if (ev.target === entityPopupEl) closeEntityPopup(); });
    document.body.appendChild(entityPopupEl);
  }
  const rows = (met.reactions || []).map(id => entityRow("rxn", id)).filter(Boolean);
  entityPopupEl.innerHTML = `
    <div class="modal-box ent-popup">
      <div class="modal-header">
        <h2>Reactions of ${escapeHtml(met.id)} <span class="ent-k">${escapeHtml(met.name || "")}</span></h2>
        <button type="button" class="modal-close" aria-label="Close">✕</button>
      </div>
      <div class="modal-body">
        <div class="toolbar"><input id="entPopupSearch" type="text" placeholder="Filter these reactions…"><span id="entPopupCount"></span></div>
        <div class="table-wrap"><table id="entPopupTable">
          <thead><tr>
            <th data-key="id">Reaction</th><th data-key="name">Name</th><th data-key="equation">Equation</th>
            <th data-key="lower_bound">Lower</th><th data-key="upper_bound">Upper</th><th data-key="wt_flux">WT flux</th>
          </tr></thead>
          <tbody id="entPopupBody"></tbody>
        </table></div>
      </div>
    </div>`;
  entityPopupEl.querySelector(".modal-close").addEventListener("click", closeEntityPopup);
  const redraw = (filtered) => {
    const q = $("entPopupSearch").value.toLowerCase();
    const shown = filtered || rows.filter(r => !q || `${r.id} ${r.name} ${r.equation}`.toLowerCase().includes(q));
    $("entPopupCount").textContent = `${shown.length} / ${rows.length}`;
    $("entPopupBody").innerHTML = shown.map(r => `<tr>
      <td><strong>${entityLink("rxn", r.id)}</strong></td>
      <td class="wrap">${escapeHtml(r.name)}</td>
      <td class="wrap ent-eq">${escapeHtml(r.equation || "")}</td>
      <td class="num">${fmt(r.lower_bound, 6)}</td><td class="num">${fmt(r.upper_bound, 6)}</td>
      <td class="num">${fmt(r.wt_flux)}</td>
    </tr>`).join("");
  };
  $("entPopupSearch").addEventListener("input", () => redraw());
  redraw();
  makeSortable("entPopupTable", rows, redraw);
  entityPopupEl.classList.remove("hidden");
}

// ---- global delegated handlers ---------------------------------------------
const ENTITY_TARGETS = ".ent-link, .ent-rxnset";

document.addEventListener("mouseover", ev => {
  const el = ev.target.closest(ENTITY_TARGETS);
  if (el) showEntityCard(el);
});
document.addEventListener("mouseout", ev => {
  if (ev.target.closest(ENTITY_TARGETS)) entityCardTimer = setTimeout(hideEntityCard, 250);
});
document.addEventListener("click", ev => {
  const el = ev.target.closest(ENTITY_TARGETS);
  if (!el) return;
  ev.preventDefault();
  if (el.dataset.met) showMetaboliteReactionsPopup(el.dataset.met);
  else openEntity(el.dataset.ent, el.dataset.id);
});
document.addEventListener("keydown", ev => { if (ev.key === "Escape") closeEntityPopup(); });
