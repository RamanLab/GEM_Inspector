// ---------------------------------------------------------------------------
// Overview > Genes: one row per gene with the reactions it is associated with
// and a few attributes. Loaded after app.js; renderGenes() is called from
// renderAll().
// ---------------------------------------------------------------------------
const GENE_TABLE_COLUMNS = [
  { key: "id", label: "Gene ID" },
  { key: "name", label: "Gene name" },
  { key: "reaction_count", label: "# Reactions" },
  { key: "reactions", label: "Reactions", value: g => join(g.reactions) },
  { key: "lost_on_ko", label: "Reactions lost if deleted", value: g => join(g.lost_on_ko) },
  { key: "active_count", label: "# Active in WT" },
  { key: "subsystems", label: "Subsystems", value: g => join(g.subsystems) },
  { key: "functional", label: "Functional", value: g => g.functional ? "Yes" : "No" },
  { key: "annotation", label: "Annotation", value: g => join(g.annotation) },
];

let geneCurrentRows = [];

function renderGenes() {
  const genes = DATA.genes || [];
  if (!genes.length) {
    $("genes").innerHTML = `<div class="note">This model has no genes defined.</div>`;
    return;
  }
  $("genes").innerHTML = `
    <div class="toolbar">
      <input id="geneSearch" type="text" placeholder="Search gene ID, name, reaction, subsystem…">
      <select id="geneFilter">
        <option value="">All genes</option>
        <option value="lost">Deleting it disables a reaction</option>
        <option value="active">Has an active reaction in WT</option>
        <option value="nonfunctional">Non-functional</option>
      </select>
      <span id="geneCount"></span>
    </div>
    <div class="table-wrap"><table id="geneTable">
      <thead><tr>
        <th data-key="id">Gene ID</th>
        <th data-key="name">Gene name</th>
        <th data-key="reaction_count"># Reactions</th>
        <th>Reactions</th>
        <th data-key="lost_count" title="Reactions whose GPR rule can no longer be satisfied if this gene is deleted">Reactions lost if deleted</th>
        <th data-key="active_count" title="Reactions of this gene that carry flux in the wild-type solution"># Active in WT</th>
        <th>Subsystems</th>
        <th data-key="functional">Functional</th>
        <th>Annotation</th>
      </tr></thead>
      <tbody id="geneBody"></tbody>
    </table></div>`;
  genes.forEach(g => { g.lost_count = g.lost_on_ko.length; });
  const redraw = (filtered) => {
    const q = $("geneSearch").value.toLowerCase();
    const f = $("geneFilter").value;
    const rows = filtered ? filtered : genes.filter(g =>
      (!q || `${g.id} ${g.name} ${g.reactions.join(" ")} ${g.subsystems.join(" ")}`.toLowerCase().includes(q)) &&
      (!f || (f === "lost" ? g.lost_count > 0 : f === "active" ? g.active_count > 0 : !g.functional)));
    geneCurrentRows = rows;
    $("geneCount").textContent = `${rows.length} / ${genes.length}`;
    const cell = (items) => items.length ? `<div class="gene-list">${items.map(escapeHtml).join(", ")}</div>` : "—";
    $("geneBody").innerHTML = rows.map(g => `<tr>
      <td><strong>${escapeHtml(g.id)}</strong></td>
      <td>${escapeHtml(g.name || "—")}</td>
      <td class="num">${g.reaction_count}</td>
      <td>${cell(g.reactions)}</td>
      <td>${g.lost_count ? `<div class="gene-list">${g.lost_on_ko.map(escapeHtml).join(", ")}</div>` : "—"}</td>
      <td class="num">${g.active_count}</td>
      <td>${cell(g.subsystems)}</td>
      <td>${g.functional ? "Yes" : "No"}</td>
      <td>${cell(g.annotation)}</td>
    </tr>`).join("");
  };
  ["geneSearch", "geneFilter"].forEach(id => $(id).addEventListener("input", () => redraw()));
  redraw();
  setTimeout(() => makeSortable("geneTable", genes, redraw), 0);
  attachTableTools("geneTable", $("genes").querySelector(".toolbar"), GENE_TABLE_COLUMNS, () => geneCurrentRows, "genes");
}
