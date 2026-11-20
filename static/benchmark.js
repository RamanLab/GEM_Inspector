// ---------------------------------------------------------------------------
// Benchmark / compare models (home page, third card).
// Upload 2-6 models, optionally pick a reference, choose or edit a shared
// medium, run on the server (streamed), then show the comparison and offer
// the Excel report. MAX_MODELS must match benchmark/routes.py.
// Loaded before views.js; uses $, escapeHtml, fmt, readNdjson, progress*.
// ---------------------------------------------------------------------------
const BENCH_MAX_MODELS = 6;


function benchPct(x) { return x === null || x === undefined ? "—" : (100 * x).toFixed(1) + "%"; }

function benchTable(head, rows, cls) {
  return `<div class="table-wrap"><table class="data ${cls || ""}"><thead><tr>${head.map(h => `<th>${h}</th>`).join("")}</tr></thead>
    <tbody>${rows.join("")}</tbody></table></div>`;
}
function benchSection(title, body, note) {
  return `<div class="bench-sec"><h3>${title}</h3>${note ? `<p class="muted">${note}</p>` : ""}${body}</div>`;
}
function benchMatrix(names, m) {
  const rows = m.map((row, i) => `<tr><th>${escapeHtml(names[i])}</th>${row.map(v => `<td>${fmt(v, 3)}</td>`).join("")}</tr>`);
  return benchTable([""].concat(names.map(escapeHtml)), rows, "bench-matrix");
}
function benchRate(v) { return v === null || v === undefined ? "—" : fmt(v, 4); }

function benchRenderResults(target, runId, r) {
  const n = r.names, nm = n.map(escapeHtml);
  const out = [];
  if (r.warnings.length) out.push(`<div class="warn-box">${r.warnings.map(escapeHtml).join("<br>")}</div>`);
  const med = r.medium.map((m, i) => `${nm[i]}: ${m.mode === "custom" ? `${m.applied} of ${m.requested} medium entries applied` + (m.unmatched.length ? ` (no exchange for ${m.unmatched.map(escapeHtml).join(", ")})` : "") : "own medium"}`);
  out.push(`<p class="muted">${r.mode === "reference" ? `Benchmarked against <strong>${escapeHtml(n[r.reference])}</strong>.` : "All models compared with each other."}
    Medium: ${med.join("; ")}.</p>`);
  out.push(`<p><a class="button-link" href="/api/benchmark/${runId}/download">Download Excel report</a></p>`);

  // similarity
  const pairs = r.similarity.pairs.filter(p => r.mode !== "reference" || p.a === r.reference || p.b === r.reference);
  const sim = pairs.map(p => {
    const c = (k) => `${p[k].matched} / ${p[k].a} vs ${p[k].b}`;
    return `<tr><td>${nm[p.a]} vs ${nm[p.b]}</td>
      <td>${fmt(p.metabolites.jaccard_strict, 3)}</td><td>${fmt(p.metabolites.jaccard_relaxed, 3)}</td><td>${c("metabolites")}</td>
      <td>${fmt(p.reactions.jaccard_strict, 3)}</td><td>${fmt(p.reactions.jaccard_relaxed, 3)}</td><td>${c("reactions")}</td>
      <td>${fmt(p.genes.jaccard_strict, 3)}</td></tr>`;
  });
  let simHtml = benchTable(["Pair", "Metabolites Jaccard (id/MetaNetX)", "Metabolites Jaccard (all matches)", "Matched", "Reactions Jaccard (id/MetaNetX)",
    "Reactions Jaccard (all matches)", "Matched", "Genes Jaccard"], sim);
  if (n.length > 2) {
    const M = r.similarity.matrix;
    simHtml += `<h4>Reactions, all matches</h4>${benchMatrix(n, M.reactions_relaxed)}<h4>Metabolites, all matches</h4>${benchMatrix(n, M.metabolites_relaxed)}`;
  }
  out.push(benchSection("Similarity", simHtml,
    "Strict counts a match by identifier (or MetaNetX id). All matches also count metabolites with the same formula, charge and compartment, and reactions with the same stoichiometry."));

  // overview
  const ov = (label, fn) => `<tr><th>${label}</th>${r.overview.map(o => `<td>${fn(o)}</td>`).join("")}</tr>`;
  const ovRows = [
    ov("Model id", o => escapeHtml(o.model_id)), ov("Genes", o => o.genes), ov("Metabolites", o => o.metabolites), ov("Reactions", o => o.reactions),
    ov("Compartments", o => o.compartments), ov("Growth (WT)", o => `${fmt(o.wt_growth, 4)} (${escapeHtml(o.wt_status)})`),
    ov("Metabolite namespace", o => escapeHtml(o.namespace_metabolites)), ov("Reaction namespace", o => escapeHtml(o.namespace_reactions)),
    ov("Compartment convention", o => escapeHtml(o.compartment_convention)),
    ov("Metabolites with a known id", o => benchPct(o.mapped_metabolites)), ov("Reactions with a known id", o => benchPct(o.mapped_reactions)),
    ov("Internal / transport / exchange", o => ["internal", "transport", "exchange"].map(k => o.reaction_types[k] ?? 0).join(" / ")),
    ov("Reactions with GPR", o => benchPct(o.with_gpr)), ov("Reactions with subsystem", o => benchPct(o.with_subsystem)),
  ];
  out.push(benchSection("Overview", benchTable([""].concat(nm), ovRows)));

  // biomass
  const bsum = r.biomass.summary.map((b, i) => `<tr><th>${nm[i]}</th><td><code>${escapeHtml(b.reaction || "—")}</code></td><td>${b.n_components ?? "—"}</td>
    <td>${b.n_consumed ?? "—"}</td><td>${b.n_produced ?? "—"}</td><td>${b.mass_g_per_gdw == null ? "—" : fmt(b.mass_g_per_gdw, 3)}</td></tr>`);
  const bcomp = r.biomass.components.map(c => `<tr class="${c.differs ? "bench-diff" : ""}"><td>${escapeHtml(c.name)}</td><td><code>${escapeHtml(c.key)}</code></td>
    ${c.coefficients.map(v => `<td>${v == null ? "—" : fmt(v, 4)}</td>`).join("")}</tr>`);
  const bj = n.length > 1 ? `<h4>Biomass component overlap (Jaccard)</h4>${benchMatrix(n, r.biomass.jaccard)}` : "";
  out.push(benchSection("Biomass",
    benchTable(["Model", "Reaction", "Components", "Consumed", "Produced", "Building-block mass (g/gDW)"], bsum) + bj +
    `<h4>Components</h4>` + benchTable(["Metabolite", "Key"].concat(nm), bcomp),
    "Components are lined up through the metabolite matches. Highlighted rows are missing from some models or have different coefficients."));

  // maintenance
  const mt = r.maintenance.map((m, i) => `<tr><th>${nm[i]}</th><td>${m.gam == null ? '<span class="badge warn">not found</span>' : fmt(m.gam, 3)}</td>
    <td>${m.ngam_id ? `<code>${escapeHtml(m.ngam_id)}</code>` : '<span class="badge warn">not found</span>'}</td>
    <td>${m.ngam_lower == null ? "—" : fmt(m.ngam_lower, 3)}</td><td>${m.ngam_id ? (m.ngam_forced ? "yes" : "no") : "—"}</td></tr>`);
  out.push(benchSection("Maintenance (GAM / NGAM)", benchTable(["Model", "GAM", "NGAM reaction", "NGAM lower bound", "NGAM forced"], mt)));

  // sources
  const src = r.sources.map((s, i) => {
    const f = (x) => x ? `${escapeHtml(x.name || x.metabolite)} (${benchRate(Math.abs(x.rate))})` : "—";
    return `<tr><th>${nm[i]}</th><td>${f(s.carbon)}</td><td>${f(s.nitrogen)}</td></tr>`;
  });
  out.push(benchSection("Main carbon and nitrogen source", benchTable(["Model", "Carbon", "Nitrogen"], src)));

  // uptake / secretion / essential
  const flux = (rows) => rows.map(x => `<tr class="${x.differs ? "bench-diff" : ""}"><td>${escapeHtml(x.name)}</td><td><code>${escapeHtml(x.key)}</code></td>
    ${x.rates.map(v => `<td>${benchRate(v)}</td>`).join("")}</tr>`);
  out.push(benchSection("Uptake (at optimal growth)", benchTable(["Metabolite", "Key"].concat(nm), flux(r.uptake)), "Highlighted rows differ between models."));
  out.push(benchSection("Secretion (at optimal growth)", benchTable(["Metabolite", "Key"].concat(nm), flux(r.secretion))));
  const ess = r.essential.map(x => `<tr class="${x.differs ? "bench-diff" : ""}"><td>${escapeHtml(x.name)}</td><td><code>${escapeHtml(x.key)}</code></td>
    ${x.status.map(s => `<td>${escapeHtml(s || "—")}</td>`).join("")}</tr>`);
  out.push(benchSection("Essential exchanges", benchTable(["Metabolite", "Key"].concat(nm), ess),
    "An uptake is essential when closing it drops growth below 5% of the wild type."));

  // core carbon FVA
  const core = r.core.map(c => {
    const cells = c.models.map(m => m ? `${escapeHtml(m.status)}<br><span class="muted">${fmt(m.min, 3)} to ${fmt(m.max, 3)}${m.flipped ? " (direction flipped)" : ""}</span>` : "—");
    return `<tr class="${c.flags.length ? "bench-diff" : ""}"><td><code>${escapeHtml(c.id)}</code></td><td>${escapeHtml(c.group)}</td>
      ${cells.map(x => `<td>${x}</td>`).join("")}<td>${c.flags.map(escapeHtml).join("; ")}</td></tr>`;
  });
  out.push(benchSection("Core carbon metabolism: FVA flux ranges", benchTable(["Reaction", "Pathway"].concat(nm, ["Differences"]), core),
    `Flux variability at ${Math.round(100 * r.fva_fraction)}% of the optimum, for the listed reactions only.`));

  $(target).innerHTML = out.join("");
}

// Wire one benchmark panel. p = id prefix of its elements; loaded = {name, id()} when model A is the model already loaded in the app.
function benchSetup(p, loaded) {
  const BENCH = { files: [], rows: [] };
function benchRender() {
  const names = (loaded ? [loaded.name] : []).concat(BENCH.files.map(f => f.name));
  $(p + "FileList").textContent = names.length ? names.map((n, i) => `${i + 1}. ${n}`).join("   ") : "";
  $(p + "Btn").disabled = names.length < 2 || names.length > BENCH_MAX_MODELS;
  const ref = $(p + "Ref");
  const keep = ref ? ref.value : "";
  if (ref) ref.innerHTML = names.map((n, i) => `<option value="${i}">${escapeHtml(n)}</option>`).join("");
  if (ref && keep && Number(keep) < names.length) ref.value = keep;
  if (names.length > BENCH_MAX_MODELS) {
    $(p + "Status").textContent = `At most ${BENCH_MAX_MODELS} models here. Use the stand-alone script for more.`;
  } else $(p + "Status").textContent = "";
}

function benchSetFiles(list) {
  BENCH.files = Array.from(list);
  benchRender();
}

function benchMediumTable() {
  $(p + "MediumBody").innerHTML = BENCH.rows.map((r, i) => {
    const num = (f) => `<input type="number" step="any" data-i="${i}" data-f="${f}" value="${r[f]}">`;
    return `<tr><td><code>${escapeHtml(r.id)}</code></td><td>${escapeHtml(r.name || "")}</td><td>${num("lower_bound")}</td><td>${num("upper_bound")}</td>
      <td><button type="button" class="secondary" data-del="${i}" aria-label="Remove">×</button></td></tr>`;
  }).join("");
}

async function benchLoadMedia() {
  try {
    const { media } = await (await fetch("/api/media")).json();
    media.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.key;
      opt.textContent = `${m.key} — ${m.description} (${m.size} compounds)`;
      $(p + "Medium").appendChild(opt);
    });
  } catch (err) { /* "own medium" still works */ }
  try {
    const d = await (await fetch("/api/benchmark/defaults")).json();
    $(p + "Core").value = Object.values(d.core || {}).flat().join(", ");
  } catch (err) { /* the server falls back to its default list when empty */ }
}

async function benchChooseMedium() {
  const key = $(p + "Medium").value;
  $(p + "MediumBox").classList.toggle("hidden", key === "own");
  if (key === "own") { BENCH.rows = []; return; }
  try {
    const res = await fetch("/api/media/" + encodeURIComponent(key));
    const medium = await res.json();
    if (!res.ok) throw new Error(medium.error);
    BENCH.rows = medium.compounds.map(c => ({ id: c.id, name: c.name || "", lower_bound: c.lower_bound, upper_bound: c.upper_bound }));
  } catch (err) { BENCH.rows = []; }
  benchMediumTable();
}

// ---- results ----
async function benchRun() {
  const fd = new FormData();
  if (loaded) fd.append("model_id", loaded.id());
  BENCH.files.forEach(f => fd.append("models", f, f.name));
  const reference = !loaded && $(p + "Mode").value === "reference" ? $(p + "Ref").value : "";
  fd.append("reference", reference);
  const custom = $(p + "Medium").value !== "own";
  fd.append("medium_mode", custom ? "custom" : "own");
  fd.append("medium_rows", JSON.stringify(custom ? BENCH.rows : []));
  fd.append("fva_fraction", $(p + "Fraction").value || "1");
  fd.append("core_ids", $(p + "Core").value);
  $(p + "Btn").disabled = true;
  $(p + "Results").innerHTML = "";
  $(p + "Status").textContent = "Starting…";
  progressStart(p + "Progress", true);
  try {
    const res = await fetch("/api/benchmark/run", { method: "POST", body: fd });
    let done = false;
    await readNdjson(res, (ev) => {
      if (ev.type === "progress") $(p + "Status").textContent = ev.message;
      else if (ev.type === "error") throw new Error(ev.error);
      else if (ev.type === "complete") { done = true; benchRenderResults(p + "Results", ev.run_id, ev.result); $(p + "Status").textContent = "Done."; }
    });
    if (!done) throw new Error("The benchmark ended without a result.");
  } catch (err) {
    $(p + "Status").textContent = "";
    $(p + "Results").innerHTML = `<div class="warn-box">${escapeHtml(err.message)}</div>`;
  } finally {
    progressDone(p + "Progress");
    benchRender();
  }
}

{
  $(p + "Files").addEventListener("change", (e) => benchSetFiles(e.target.files));
  const zone = $(p + "Dropzone");
  if (zone) {
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("drag"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("drag"); benchSetFiles(e.dataTransfer.files); });
  }
  if ($(p + "Mode")) $(p + "Mode").addEventListener("change", () => $(p + "RefWrap").classList.toggle("hidden", $(p + "Mode").value !== "reference"));
  $(p + "Medium").addEventListener("change", benchChooseMedium);
  $(p + "MediumBody").addEventListener("input", (e) => {
    const t = e.target;
    if (t.dataset.f) BENCH.rows[Number(t.dataset.i)][t.dataset.f] = Number(t.value);
  });
  $(p + "MediumBody").addEventListener("click", (e) => {
    const b = e.target.closest("[data-del]");
    if (b) { BENCH.rows.splice(Number(b.dataset.del), 1); benchMediumTable(); }
  });
  $(p + "AddBtn").addEventListener("click", () => {
    const id = $(p + "AddId").value.trim();
    if (!id) return;
    BENCH.rows.push({ id, name: "", lower_bound: -10, upper_bound: 1000 });
    $(p + "AddId").value = "";
    benchMediumTable();
  });
  $(p + "Btn").addEventListener("click", benchRun);
  benchLoadMedia();
}
}

// Controls for the in-depth benchmark inside Debugging Toolkit > Compare Models (model A = the loaded model).
function benchControlsHtml(p) {
  return `<div class="warn-box"><strong>Use the same uptake medium.</strong> Growth, uptake, essentiality and flux ranges depend on the medium.
      Either make sure both models already have the same medium, or choose a base medium and edit it (change bounds, remove or add uptakes); it is applied to both.</div>
    <div class="toolbar"><label for="${p}Files">Model B</label>
      <input id="${p}Files" type="file" accept=".xml,.sbml,.json,.yml,.yaml,.mat,.gz,.zip,.bz2"></div>
    <div id="${p}FileList" class="muted"></div>
    <div class="bench-opts">
      <label>Medium <select id="${p}Medium"><option value="own">Each model's own medium</option></select></label>
      <label>FVA fraction of optimum <input id="${p}Fraction" type="number" min="0" max="1" step="0.05" value="1"></label>
    </div>
    <div id="${p}MediumBox" class="hidden">
      <div class="table-wrap"><table class="data"><thead><tr><th>Metabolite</th><th>Name</th><th>Lower bound</th><th>Upper bound</th><th></th></tr></thead><tbody id="${p}MediumBody"></tbody></table></div>
      <div class="toolbar"><input id="${p}AddId" placeholder="metabolite id, e.g. glc__D"> <button type="button" class="secondary" id="${p}AddBtn">Add uptake</button></div>
    </div>
    <details class="bench-core"><summary>Core carbon reactions (editable list, BiGG ids)</summary><textarea id="${p}Core" rows="5"></textarea></details>
    <button id="${p}Btn" type="button" disabled>Run in-depth benchmark</button>
    <span id="${p}Status"></span>
    <div class="progress-track" id="${p}Progress" style="display:none;"><div class="progress-fill"></div></div>
    <div id="${p}Results"></div>`;
}

benchSetup("bench", null);
