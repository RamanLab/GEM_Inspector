// ---------------------------------------------------------------------------
// Diet / media pop-up. Curated media (LB, M9, ...) in the dropdown, with an editable table of
// bounds. Picking one fills the table with the medium's compounds at the
// defaults (uptake lower bound -1000, secretion upper bound 1000); every value
// can be edited, rows removed or added. On "Analyze" the rows are sent with the
// model and matched to its exchange reactions by metabolite id (server side;
// compounds without an exchange are listed after the analysis).
// Setting the upper bound below 0 forces uptake of that nutrient.
// Loaded after app.js (uses dietMode, $, escapeHtml); app.js calls dietRowsForUpload().
// ---------------------------------------------------------------------------
const DIET_UI = { rows: null, key: null };

async function loadMediaOptions() {
  try {
    const res = await fetch("/api/media");
    const { media } = await res.json();
    media.forEach(m => {
      const opt = document.createElement("option");
      opt.value = "medium:" + m.key;
      opt.textContent = `${m.key} — ${m.description} (${m.size} compounds)`;
      dietMode.appendChild(opt);
    });
  } catch (err) { /* the built-in options still work */ }
}

function dietRowHtml(r, i) {
  const num = (field, v) => `<input type="number" step="any" data-i="${i}" data-f="${field}" value="${v}">`;
  return `<tr><td><code>${escapeHtml(r.id)}</code></td><td>${escapeHtml(r.name || "")}</td>
    <td>${num("lower_bound", r.lower_bound)}</td><td>${num("upper_bound", r.upper_bound)}</td>
    <td><button type="button" class="secondary" data-del="${i}" aria-label="Remove">×</button></td></tr>`;
}

function renderDietTable() {
  const wrap = $("dietTableWrap");
  if (!DIET_UI.rows) { wrap.classList.add("hidden"); wrap.innerHTML = ""; return; }
  wrap.classList.remove("hidden");
  wrap.innerHTML = `
    <div class="stoich">Each compound is matched to the model's exchange reaction for that metabolite when the model is loaded; compounds the model lacks are reported afterwards.
      <strong>Lower bound</strong> = uptake (default −1000). <strong>Upper bound</strong> = secretion (default 1000); set it below 0 to <em>force</em> uptake.
      Exchanges not listed are closed for uptake.</div>
    <div class="table-wrap diet-table"><table><thead><tr><th>Metabolite</th><th>Name</th><th>Lower bound</th><th>Upper bound</th><th></th></tr></thead>
      <tbody>${DIET_UI.rows.map(dietRowHtml).join("")}</tbody></table></div>
    <div class="toolbar"><input type="text" id="dietAddId" placeholder="Add a metabolite or exchange id (e.g. glc__D)">
      <button type="button" class="secondary" id="dietAddBtn">Add row</button>
      <button type="button" class="secondary" id="dietResetBtn">Reset to defaults</button></div>`;
  wrap.querySelectorAll("input[data-f]").forEach(inp => inp.addEventListener("input", () => {
    const v = parseFloat(inp.value);
    if (!Number.isNaN(v)) DIET_UI.rows[Number(inp.dataset.i)][inp.dataset.f] = v;
  }));
  wrap.querySelectorAll("[data-del]").forEach(b => b.addEventListener("click", () => {
    DIET_UI.rows.splice(Number(b.dataset.del), 1); DIET_UI.edited = true; renderDietTable(); updateDietSummary();
  }));
  $("dietAddBtn").addEventListener("click", () => {
    const id = $("dietAddId").value.trim();
    if (id) { DIET_UI.rows.push({ id, name: "", lower_bound: -1000, upper_bound: 1000 }); DIET_UI.edited = true; renderDietTable(); updateDietSummary(); }
  });
  $("dietResetBtn").addEventListener("click", () => selectMedium(DIET_UI.key));
}

async function selectMedium(key) {
  try {
    const res = await fetch("/api/media/" + encodeURIComponent(key));
    const medium = await res.json();
    if (!res.ok) throw new Error(medium.error);
    DIET_UI.key = key;
    DIET_UI.rows = medium.compounds.map(c => Object.assign({}, c));
    DIET_UI.edited = false;
  } catch (err) { DIET_UI.rows = null; }
  renderDietTable();
  updateDietSummary();
}

dietMode.addEventListener("change", () => {
  if (dietMode.value.startsWith("medium:")) selectMedium(dietMode.value.slice(7));
  else { DIET_UI.rows = null; renderDietTable(); }
  updateDietSummary();
});

// ---- the pop-up and the one-line summary on the upload page ----
function openDietModal() { $("dietModal").classList.remove("hidden"); }
function closeDietModal() { $("dietModal").classList.add("hidden"); updateDietSummary(); }

function updateDietSummary() {
  const mode = dietMode.value, label = dietMode.selectedOptions[0].textContent;
  let text = label;
  if (mode === "custom") text = dietFileInput.files[0] ? `Custom diet: ${dietFileInput.files[0].name}` : "Custom diet — no file chosen yet";
  else if (mode.startsWith("medium:") && DIET_UI.rows) {
    text = `${label.replace(/ \(\d+ compounds\)$/, "")} — ${DIET_UI.rows.length} compounds${DIET_UI.edited ? ", edited" : ""}`;
  }
  $("dietSummary").textContent = text;
  $("dietModalStatus").textContent = mode === "custom" && !dietFileInput.files[0] ? "Choose a diet file to continue." : "";
}

$("dietOpenBtn").addEventListener("click", () => { $("dietReanalyze").classList.add("hidden"); openDietModal(); });
$("dietClose").addEventListener("click", closeDietModal);
$("dietDone").addEventListener("click", closeDietModal);
$("dietModal").addEventListener("click", ev => { if (ev.target === $("dietModal")) closeDietModal(); });
document.addEventListener("keydown", ev => { if (ev.key === "Escape" && !$("dietModal").classList.contains("hidden")) closeDietModal(); });
dietFileInput.addEventListener("change", updateDietSummary);

// The diet mode and rows to send: a curated medium goes as a "custom" diet with the table's rows.
function dietUploadFields() {
  if (dietMode.value.startsWith("medium:") && DIET_UI.rows) return { mode: "custom", rows: JSON.stringify(DIET_UI.rows) };
  return { mode: dietMode.value, rows: null };
}

loadMediaOptions();

// ---- change the diet of the loaded model and analyse it again (no new upload) ----
$("dietChangeBtn").addEventListener("click", () => { $("dietReanalyze").classList.remove("hidden"); openDietModal(); });
$("dietReanalyze").addEventListener("click", async () => {
  if (!MODEL_ID) return;
  if (dietMode.value === "custom" && !dietFileInput.files[0]) { $("dietModalStatus").textContent = "Choose a diet file first."; return; }
  const btn = $("dietReanalyze"), note = $("dietModalStatus");
  btn.disabled = true; note.textContent = "Analysing the model again under this diet…";
  try {
    const form = new FormData();
    addDietFields(form);
    const res = await fetch(`/api/reanalyze/${MODEL_ID}`, { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Analysis failed");
    showAnalysis(data);
    closeDietModal();
  } catch (err) {
    note.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});
