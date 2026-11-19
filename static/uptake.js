// Overview > Uptake & secretion: what the wild-type solution takes up and gives off,
// with the carbon and nitrogen sources picked out. Data: DATA.uptake_secretion.

function uptakeTable(rows, extraHead, extraCells) {
  if (!rows.length) return `<div class="note">None in the current solution.</div>`;
  return `<div class="table-wrap"><table class="sub-table">
    <thead><tr><th>Exchange</th><th>Metabolite</th><th>Formula</th><th>Rate</th><th>LB</th><th>UB</th>${extraHead}</tr></thead>
    <tbody>${rows.map(r => `<tr>
      <td>${entityLink("rxn", r.id)}</td><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.formula || "—")}</td>
      <td class="num">${fmt(r.rate)}</td><td class="num">${fmt(r.lower_bound, 2)}</td><td class="num">${fmt(r.upper_bound, 2)}</td>
      ${extraCells(r)}</tr>`).join("")}</tbody></table></div>`;
}

function sourceCard(title, main, element, unit) {
  const body = main
    ? `<div class="maint-value">${escapeHtml(main.name)}</div>
       <div class="maint-sub">${entityLink("rxn", main.id)} · ${escapeHtml(main.formula || "")} · ${fmt(main.rate, 3)} mmol/gDW/h
         · ${main[element === "C" ? "c_atoms" : "n_atoms"]} ${element} per molecule = ${fmt(main[element === "C" ? "carbon" : "nitrogen"], 3)} ${unit}</div>`
    : `<div class="maint-value muted">none found</div>`;
  return `<div class="maint-card ${main ? "" : "missing"}"><div class="maint-title">${title}</div>${body}</div>`;
}

function renderUptake() {
  const u = DATA.uptake_secretion;
  if (!u) { $("uptake").innerHTML = ""; return; }
  const pct = r => (r.share == null ? "inorganic" : `${fmt(r.share * 100, 3)} %`);
  const warnings = [];
  if (!u.carbon_main) warnings.push("<strong>No carbon source found.</strong> Nothing that contains carbon is taken up in the current solution (or the metabolites have no formulas). Growth would need a carbon-containing uptake.");
  if (!u.nitrogen_main) warnings.push("<strong>No nitrogen source found.</strong> No nitrogen-containing uptake carries flux in the current solution.");
  if (u.no_formula) warnings.push(`${u.no_formula} exchanged metabolite(s) have no formula, so their carbon/nitrogen content could not be counted.`);
  if (u.carbon.length > 1 && u.carbon_main && u.carbon_main.share != null && u.carbon_main.share < 0.9)
    warnings.push("More than one carbon source is taken up; the main one is the one that brings in the most carbon atoms.");

  $("uptake").innerHTML = `
    <h2>Uptake &amp; secretion</h2>
    <div class="note">What the model takes in and gives off in the wild-type solution (rates in mmol/gDW/h, under the diet chosen at upload).
      The main carbon source is the organic uptake bringing in the most carbon atoms per hour; the nitrogen source is chosen the same way.</div>
    <div class="maint-grid">
      ${sourceCard("Main carbon source", u.carbon_main, "C", "C-mmol/gDW/h")}
      ${sourceCard("Main nitrogen source", u.nitrogen_main, "N", "N-mmol/gDW/h")}
    </div>
    ${warnings.map(w => `<div class="warn-box maint-warn">${w}</div>`).join("")}
    <h3>Carbon sources</h3>
    ${uptakeTable(u.carbon, "<th>C atoms</th><th>C taken up</th><th>Share</th>",
      r => `<td class="num">${r.c_atoms}</td><td class="num">${fmt(r.carbon, 3)}</td><td class="num">${pct(r)}</td>`)}
    <h3>Nitrogen sources</h3>
    ${uptakeTable(u.nitrogen, "<th>N atoms</th><th>N taken up</th><th>Share</th>",
      r => `<td class="num">${r.n_atoms}</td><td class="num">${fmt(r.nitrogen, 3)}</td><td class="num">${fmt(r.share * 100, 3)} %</td>`)}
    <h3>All uptakes</h3>${uptakeTable(u.uptake, "", () => "")}
    <h3>All secretions</h3>${uptakeTable(u.secretion, "", () => "")}`;
}
