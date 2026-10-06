"""Diet / media application.

A "diet" constrains which metabolites the model may take up (exchange
reaction lower bounds) and by how much. Three built-in options plus a
user-uploaded custom diet file:
  - "none"     : leave the model's own bounds exactly as uploaded.
  - "complete" : open every exchange to unrestricted uptake ("rich media").
  - "minimal"  : compute the smallest set of nutrients (via
                 cobra.medium.minimal_medium) that sustains the same max
                 growth the model achieves with everything open.
  - "custom"   : close every exchange, then open exactly the ones named in
                 an uploaded diet file, at the given bound.

Only lower bounds (uptake capacity) are ever touched; secretion (upper
bounds) is left as defined in the uploaded model.
"""
import csv
import io

from cobra.medium import minimal_medium

from annotation.naming import metabolite_base_id
from core.shared import safe_float
from diagnostics.solver_utils import run_with_exact_solver


def build_exchange_index(model):
    """Map an exchange reaction's own id, its single metabolite's full id,
    and that metabolite's compartment-stripped base id, all lowercased, to
    the exchange reaction's real id. Used to match diet-file entries
    (which may use a different compartment-tag convention than this model,
    e.g. "glc_D_e" vs this model's "glc_D_e0", or VMH-style "glc_D[e]")
    against this model's actual exchange reactions.
    """
    by_rxn_id, by_full_met_id, by_base_met_id = {}, {}, {}
    for exch in model.exchanges:
        by_rxn_id[exch.id.lower()] = exch.id
        if len(exch.metabolites) == 1:
            (met,) = exch.metabolites.keys()
            by_full_met_id.setdefault(met.id.lower(), exch.id)
            by_base_met_id.setdefault(metabolite_base_id(met.id), exch.id)
    return by_rxn_id, by_full_met_id, by_base_met_id


def parse_diet_file(file_storage):
    """Parse an uploaded diet/media file into (raw_id, flux_value) pairs.

    Accepts CSV, TSV, or semicolon-separated text with at least two
    columns: an identifier (an exchange reaction id, or a bare/
    compartment-tagged metabolite id) and a flux value. Following the VMH
    diet-file convention, a positive flux is treated as an uptake magnitude
    and negated into a lower bound; a non-positive value is used directly
    as the lower bound. A header row is auto-detected (any row whose second
    column isn't a number) and skipped.
    """
    raw = file_storage.read()
    text = raw.decode("utf-8-sig", errors="replace") if isinstance(raw, bytes) else raw

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel  # default to comma-separated

    entries = []
    for row in csv.reader(io.StringIO(text), dialect):
        cells = [c.strip() for c in row]
        if not any(cells):
            continue
        if len(cells) < 2:
            continue
        raw_id = cells[0].strip('"').strip("'")
        try:
            flux = float(cells[1])
        except ValueError:
            continue  # header row, or an unparseable line -- skip rather than fail the whole file
        if raw_id:
            entries.append((raw_id, flux))
    return entries


def resolve_diet_entries(model, entries):
    """Match parsed diet entries against this model's actual exchange
    reactions. Returns (matched: {exchange_id: lower_bound}, unmatched:
    [{"id":..., "flux":...}, ...]) so unmatched entries can be surfaced to
    the user rather than silently dropped."""
    by_rxn_id, by_full_met_id, by_base_met_id = build_exchange_index(model)
    matched, unmatched = {}, []

    for raw_id, flux in entries:
        lower_bound = -flux if flux > 0 else flux
        key = raw_id.strip().lower()

        exch_id = by_rxn_id.get(key) or by_full_met_id.get(key)
        if exch_id is None:
            exch_id = by_base_met_id.get(metabolite_base_id(raw_id.strip()))
        if exch_id is None and not key.startswith("ex_"):
            exch_id = by_rxn_id.get("ex_" + key)

        if exch_id is None:
            unmatched.append({"id": raw_id, "flux": flux})
        else:
            matched[exch_id] = lower_bound

    return matched, unmatched


def apply_diet_to_model(model, mode, diet_entries=None):
    """Constrain exchange lower bounds according to the requested diet mode.
    Returns a summary dict describing what was applied/skipped, suitable for
    returning straight to the frontend."""
    if mode not in ("none", "complete", "minimal", "custom"):
        return {"mode": mode, "applied": [], "unmatched": [], "note": f"Unknown diet mode '{mode}'; no changes made.", "error": True}

    if mode == "none":
        return {"mode": "none", "applied": [], "unmatched": [], "note": "Using the model's original exchange bounds, unchanged."}

    if mode == "complete":
        applied = []
        for exch in model.exchanges:
            exch.lower_bound = -1000.0
            applied.append(exch.id)
        return {
            "mode": "complete",
            "applied": applied,
            "unmatched": [],
            "note": f"All {len(applied)} exchange reactions opened to unrestricted uptake (lower bound -1000).",
        }

    if mode == "minimal":
        # The target is the model's OWN maximum growth rate, under its own
        # original bounds exactly as uploaded -- never a growth rate
        # computed after forcing every exchange open first, which would let
        # FBA route flux through byproduct/secretion exchanges run in
        # reverse (no thermodynamic constraints stop it) and inflate the
        # target to a biologically unrealistic value. minimal_medium's own
        # open_exchanges=True below already searches over every exchange
        # (temporarily, inside its own model context) while solving for
        # whatever target is passed in, so nothing needs to be opened here
        # first.
        target_growth = safe_float(model.slim_optimize(error_value=0.0)) or 0.0

        if target_growth <= 1e-9:
            return {
                "mode": "minimal", "applied": [], "unmatched": [],
                "note": "Model cannot grow under its own original bounds; a minimal medium is undefined.",
                "error": True,
            }

        try:
            medium = run_with_exact_solver(
                model, lambda: minimal_medium(model, target_growth, minimize_components=False, open_exchanges=True)
            )
        except Exception as exc:
            return {
                "mode": "minimal", "applied": [], "unmatched": [],
                "note": f"Could not compute a minimal medium: {exc}", "error": True,
            }
        if medium is None:
            return {
                "mode": "minimal", "applied": [], "unmatched": [],
                "note": "Minimal-medium computation was infeasible for this model.", "error": True,
            }

        for exch in model.exchanges:
            exch.lower_bound = 0.0
        applied = []
        for rxn_id, flux in medium.items():
            if flux <= 0:
                continue
            model.reactions.get_by_id(rxn_id).lower_bound = -abs(float(flux))
            applied.append(rxn_id)
        return {
            "mode": "minimal",
            "applied": applied,
            "unmatched": [],
            "note": f"Computed the smallest set of {len(applied)} nutrient(s) that sustains the model's original maximum growth rate ({target_growth:.4g}).",
        }

    # mode == "custom"
    for exch in model.exchanges:
        exch.lower_bound = 0.0
    matched, unmatched = resolve_diet_entries(model, diet_entries or [])
    applied = []
    for exch_id, lower_bound in matched.items():
        rxn = model.reactions.get_by_id(exch_id)
        rxn.lower_bound = min(lower_bound, rxn.upper_bound)
        applied.append(exch_id)

    total = len(applied) + len(unmatched)
    note = f"Applied {len(applied)} of {total} diet entries."
    if unmatched:
        note += f" {len(unmatched)} entries could not be matched to an exchange reaction in this model (shown below)."
    return {"mode": "custom", "applied": applied, "unmatched": unmatched, "note": note}
