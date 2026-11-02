// ---------------------------------------------------------------------------
// The editable currency/cofactor list (H, H2O, ATP, NAD(P)H, ...). One list
// for the whole tool: the pathway tracer, exchange debugging and the network
// gaps classification all send it with their requests. It is kept in this
// browser and starts from the server's default. Loaded before app.js.
// ---------------------------------------------------------------------------
const CURRENCY_KEY = "gi.currencyMetabolites";
let currencyDefaults = [];
let currencyMemory = null; // fallback when localStorage is unavailable

fetch("/api/currency-defaults").then(r => r.json()).then(d => {
  currencyDefaults = d.currency_metabolites || [];
  refreshCurrencyButtons();
}).catch(() => {});

function savedCurrency() {
  try { return JSON.parse(localStorage.getItem(CURRENCY_KEY)); } catch (e) { return null; }
}
function storeCurrency(list) {
  try {
    if (list === null) localStorage.removeItem(CURRENCY_KEY); else localStorage.setItem(CURRENCY_KEY, JSON.stringify(list));
  } catch (e) { /* storage unavailable: the edit lasts until reload */ currencyMemory = list; }
}
// What to send to the server: the edited list, or null for "use the default".
function currencyPayload() {
  return savedCurrency() || currencyMemory;
}

function currencyButtonLabel() {
  return `Currency list (${(currencyPayload() || currencyDefaults).length})…`;
}

function currencyEditButton() {
  return `<button type="button" class="currency-edit" title="Edit the list of currency/cofactor metabolites used across the tool">${currencyButtonLabel()}</button>`;
}

function refreshCurrencyButtons() {
  document.querySelectorAll(".currency-edit").forEach(b => { b.textContent = currencyButtonLabel(); });
}

function openCurrencyEditor() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.innerHTML = `
    <div class="modal-box">
      <div class="modal-header"><h2>Currency / cofactor metabolites</h2>
        <button type="button" class="modal-close" aria-label="Close">✕</button></div>
      <div class="modal-body">
        <p class="note">Metabolite ids without the compartment suffix (e.g. <code>atp</code> matches atp_c and atp_e),
          separated by commas or new lines. These are hidden from pathway traces and never count as the cause of a gap
          in the network-gaps classification.</p>
        <textarea id="currencyText" rows="10" style="width:100%"></textarea>
      </div>
      <div class="modal-footer">
        <button type="button" id="currencyReset">Reset to default</button>
        <button type="button" id="currencySave" style="margin-left:auto">Save</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);
  const text = overlay.querySelector("#currencyText");
  text.value = (currencyPayload() || currencyDefaults).join(", ");
  const close = () => overlay.remove();
  const save = (list) => {
    storeCurrency(list);
    refreshCurrencyButtons();
    document.dispatchEvent(new Event("currency-changed"));
    close();
  };
  overlay.querySelector(".modal-close").addEventListener("click", close);
  overlay.addEventListener("click", ev => { if (ev.target === overlay) close(); });
  overlay.querySelector("#currencyReset").addEventListener("click", () => save(null));
  overlay.querySelector("#currencySave").addEventListener("click", () =>
    save([...new Set(text.value.split(/[\s,;]+/).map(s => s.trim().toLowerCase()).filter(Boolean))]));
}

document.addEventListener("click", ev => { if (ev.target.closest(".currency-edit")) openCurrencyEditor(); });
