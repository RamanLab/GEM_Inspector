// ---------------------------------------------------------------------------
// Page flow: home -> (single model upload | multiple model upload) -> results.
// Only one view is visible at a time. The analysis code itself lives elsewhere;
// app.js calls showView("results") once a model has been analysed.
// ---------------------------------------------------------------------------
const MODULE_OVERVIEW = [
  {
    title: "Overview",
    blurb: "Characterise the model's composition and structure prior to detailed analysis.",
    features: [
      ["Summary", "Model dimensions, compartments, predicted growth rate and applied medium, with MEMOTE quality scoring.", "available"],
      ["Metabolites & Reactions", "Searchable, sortable tables of all model components, cross-linked by reaction, metabolite and gene.", "available"],
      ["Objective", "The objective function and the biomass reaction(s) it comprises.", "available"],
      ["Generate report", "A consolidated report with figures, quality findings and user-selected sections, exported as HTML with an optional Excel workbook.", "available"],
      ["GPR explorer", "Gene–protein–reaction associations and the reactions each gene controls.", "planned"],
    ],
  },
  {
    title: "Diagnostics & Comparative Analyses",
    blurb: "Identify the structural and environmental determinants of model behaviour.",
    features: [
      ["Minimal medium", "The minimal set of nutrients required to sustain a specified fraction of maximal growth.", "available"],
      ["Exchange essentiality", "Exchange reactions whose removal abolishes growth.", "available"],
      ["Network gaps & audits", "Dead-end metabolites, blocked reactions and demand/sink reaction tests.", "available"],
      ["Reaction balance & audit", "Elemental and charge imbalances per reaction, with suggested corrections and export.", "available"],
      ["Biomass precursors", "Producibility of each biomass precursor under the applied medium.", "available"],
      ["FROG report", "Standardised reproducibility analysis: FBA, FVA, and single gene and reaction deletions.", "available"],
      ["Gene essentiality", "Single and double gene knockout screens.", "planned"],
    ],
  },
  {
    title: "Debugging Toolkit",
    blurb: "Diagnose models that fail to grow or yield implausible predictions.",
    features: [
      ["Exchange debugging", "Identify the exchange reactions whose relaxation restores growth in a non-growing model.", "available"],
      ["Pathway tracer", "Trace metabolic routes between metabolites and assess the effect of knockouts.", "available"],
      ["Compare models", "Pairwise matching of reactions and metabolites, including bounds and stoichiometric coefficients.", "available"],
      ["Gap-filling suggestions", "Candidate reactions from a reference database to resolve network gaps.", "planned"],
    ],
  },
  {
    title: "Annotation & Translation",
    blurb: "Harmonise identifiers and annotations across biochemical databases.",
    features: [
      ["ID namespaces & annotation", "Detection of identifier namespaces and assessment of annotation coverage.", "available"],
      ["SEED → VMH translation", "Conversion of ModelSEED identifiers to VMH, with a mapping report and the translated model.", "available"],
      ["Translate via MetaNetX", "Cross-namespace conversion (BiGG, VMH, ModelSEED, KEGG, MetaCyc, ChEBI) via MetaNetX.", "available"],
      ["Annotation enrichment", "Supplementation of missing database cross-references for metabolites and reactions.", "planned"],
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
