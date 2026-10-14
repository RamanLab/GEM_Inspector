// ---------------------------------------------------------------------------
// Page flow: home -> (single model upload | multiple model upload) -> results.
// Only one view is visible at a time. The analysis code itself lives elsewhere;
// app.js calls showView("results") once a model has been analysed.
// ---------------------------------------------------------------------------
const MODULE_OVERVIEW = [
  {
    title: "Overview",
    blurb: "Understand what is in the model before digging in.",
    features: [
      ["Summary", "Counts, compartments, growth rate and diet applied, plus MEMOTE quality scoring.", "available"],
      ["Metabolites & Reactions", "Searchable, sortable tables of everything in the model.", "available"],
      ["Objective", "The objective function and the biomass reaction it optimises.", "available"],
      ["Generate report", "One report with charts, quality findings and the sections you choose; HTML plus an optional Excel workbook.", "available"],
      ["GPR explorer", "Browse genes, rules and the reactions they control.", "planned"],
    ],
  },
  {
    title: "Diagnostics & Comparative Analyses",
    blurb: "Find out why a model behaves the way it does.",
    features: [
      ["Minimal medium", "The smallest set of nutrients that still supports growth.", "available"],
      ["Exchange essentiality", "Which exchanges the cell cannot grow without.", "available"],
      ["Network gaps & audits", "Dead-end metabolites, blocked reactions, demand/sink checks.", "available"],
      ["Reaction balance & audit", "Mass/charge imbalances, with suggested fixes and an export.", "available"],
      ["Biomass precursors", "Which biomass components the model can actually produce.", "available"],
      ["FROG report", "Standard reproducibility analysis: FBA, FVA, gene and reaction deletions.", "available"],
      ["Gene essentiality", "Single and double gene knockouts across the model.", "planned"],
    ],
  },
  {
    title: "Debugging Toolkit",
    blurb: "Fix models that will not grow or give odd results.",
    features: [
      ["Exchange debugging", "Find which exchanges to open so a non-growing model grows.", "available"],
      ["Pathway tracer", "Trace routes between metabolites and see the effect of knockouts.", "available"],
      ["Compare models", "Match reactions and metabolites between two models, including bounds and coefficients.", "available"],
      ["Gap-filling suggestions", "Propose reactions to add from a reference database.", "planned"],
    ],
  },
  {
    title: "Annotation & Translation",
    blurb: "Make identifiers consistent across databases.",
    features: [
      ["ID namespaces & annotation", "Detect which databases the ids belong to and how well annotated the model is.", "available"],
      ["SEED → VMH translation", "Rename ModelSEED ids to VMH, with a mapping report and the translated model.", "available"],
      ["Translate via MetaNetX", "Convert between BiGG, VMH, ModelSEED, KEGG, MetaCyc and ChEBI through MetaNetX.", "available"],
      ["Annotation enrichment", "Add missing database cross-references to metabolites and reactions.", "planned"],
    ],
  },
];

const SLUG = { available: "Available", planned: "Coming soon" };

function renderModuleGrid() {
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
  $("moduleGrid").innerHTML = MODULE_OVERVIEW.map((m, i) => `
    <article class="module-card m${i + 1}">
      <h3>${esc(m.title)}</h3>
      <p class="module-blurb">${esc(m.blurb)}</p>
      <ul>${m.features.map(([name, what, state]) => `
        <li class="feat ${state}">
          <span class="feat-head"><strong>${esc(name)}</strong><span class="status-chip ${state}">${SLUG[state]}</span></span>
          <span class="feat-what">${esc(what)}</span>
        </li>`).join("")}
      </ul>
    </article>`).join("");
}

const VIEWS = { home: "viewHome", single: "viewSingle", multi: "viewMulti", results: "app" };

function showView(name) {
  Object.entries(VIEWS).forEach(([key, id]) => $(id).classList.toggle("hidden", key !== name));
  // While results are showing, the progress line of a still-running analysis
  // moves into the slim bar at the top of the results page.
  const inResults = name === "results";
  const holder = inResults ? $("resultsStatus") : $("viewSingle").querySelector(".upload-single");
  if (inResults) {
    $("resultsFile").textContent = ($("modelFile").files[0] || {}).name || "";
    holder.append($("status"), $("mainProgress"));
  } else if ($("status").parentNode !== holder) {
    holder.append($("status"), $("mainProgress"));
  }
  window.scrollTo(0, 0);
}

function resetSingleUpload() {
  $("modelFile").value = "";
  $("filename").textContent = "";
  $("analyzeBtn").disabled = true;
  $("status").textContent = "";
  $("dietMode").value = "none";
  $("dietMode").dispatchEvent(new Event("change"));
}

(function () {
  renderModuleGrid();
  $("chooseSingle").addEventListener("click", () => showView("single"));
  $("chooseMulti").addEventListener("click", () => showView("multi"));
  document.querySelectorAll("[data-go]").forEach(b => b.addEventListener("click", () => showView(b.dataset.go)));
  $("homeLink").addEventListener("click", (ev) => { ev.preventDefault(); showView("home"); });
  $("newModelBtn").addEventListener("click", () => { showView("single"); resetSingleUpload(); });

  $("dietExampleBtn").addEventListener("click", () => {
    const csv = "exchange,flux\nEX_glc__D_e,10\nEX_o2_e,20\nEX_nh4_e,1000\nEX_pi_e,1000\nEX_h2o_e,1000\nEX_h_e,1000\n";
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = "example_diet.csv";
    a.click();
    URL.revokeObjectURL(a.href);
  });
  $("dietMode").addEventListener("change", () => { if ($("dietMode").value === "custom") $("dietHelp").open = true; });
})();
