"""Everything reported for one model in a benchmark: the overview statistics, biomass, maintenance,
uptake and secretion, essential exchanges and the core-carbon flux ranges, all under the medium
chosen for the run."""
from cobra.flux_analysis import flux_variability_analysis
from cobra.util.solver import linear_reaction_coefficients

from annotation.namespace_mapping import detect_metabolite_namespace_and_map
from annotation.naming import TRIVIAL_METABOLITES, clean_metabolite_display_name, metabolite_base_id
from benchmark.core_carbon import find_core_reactions
from core.knockouts import reaction_knockout
from core.shared import safe_float, wt_solution
from diagnostics.diet import apply_diet_to_model, entries_from_rows
from overview.analysis import quick_analyze

ESSENTIAL_FRACTION = 0.05


def apply_medium(model, medium):
    """Apply the shared medium ({"mode": "own"} or {"mode": "custom", "rows": [...]}) and report what matched."""
    if medium.get("mode") != "custom":
        return {"mode": "own", "applied": 0, "unmatched": [], "requested": 0}
    entries = entries_from_rows(medium.get("rows"))
    result = apply_diet_to_model(model, "custom", entries)
    return {"mode": "custom", "applied": len(result.get("applied", [])), "requested": len(entries),
            "unmatched": [u["id"] for u in result.get("unmatched", [])]}


def _biomass(model, met_to_mnx):
    objective = list(linear_reaction_coefficients(model))
    if not objective:
        return None
    rxn = objective[0]
    comps = []
    for met, coef in rxn.metabolites.items():
        comps.append({"id": met.id, "base": metabolite_base_id(met.id), "name": clean_metabolite_display_name(met),
                      "coefficient": float(coef), "formula": getattr(met, "formula", "") or "", "mnx": met_to_mnx.get(met.id)})
    produced = {c["id"] for c in comps if c["coefficient"] > 0}
    mass = 0.0
    for met, coef in rxn.metabolites.items():
        if coef < 0 and metabolite_base_id(met.id) not in TRIVIAL_METABOLITES:   # building blocks only, not ATP / H2O / cofactors
            try:
                mass += -coef * met.formula_weight / 1000.0
            except Exception:
                pass
    return {"reaction": rxn.id, "name": rxn.name or "", "components": comps,
            "n_consumed": sum(c["coefficient"] < 0 for c in comps), "n_produced": len(produced),
            "mass_g_per_gdw": mass}


def _essential_exchanges(model, wt_growth):
    out = []
    if wt_growth <= 1e-9:
        return out
    for ex in model.exchanges:
        if len(ex.metabolites) != 1 or ex.lower_bound >= 0:
            continue   # not open for uptake: nothing to test
        value, _ = reaction_knockout(model, ex)
        fraction = 0.0 if value is None else value / wt_growth
        (met,) = ex.metabolites
        out.append({"id": ex.id, "metabolite": met.id, "name": clean_metabolite_display_name(met),
                    "growth_fraction": fraction, "essential": fraction < ESSENTIAL_FRACTION})
    return out


def _core_fva(model, wanted, fraction, wt):
    found = find_core_reactions(model, wanted)
    ids = [r for r in found.values() if r]
    ranges = {}
    if ids and (wt.objective_value or 0) > 1e-9:
        try:
            df = flux_variability_analysis(model, reaction_list=ids, fraction_of_optimum=fraction, processes=1)
            ranges = {rid: (float(row["minimum"]), float(row["maximum"])) for rid, row in df.iterrows()}
        except Exception:
            ranges = {}
    rows = {}
    for wanted_id, rid in found.items():
        if rid is None:
            rows[wanted_id] = None
            continue
        low, high = ranges.get(rid, (None, None))
        rows[wanted_id] = {"id": rid, "wt_flux": safe_float(wt.fluxes[rid]), "min": low, "max": high}
    return rows


def build_profile(name, model, medium, core_ids, fva_fraction, progress):
    progress(f"{name}: applying the medium")
    medium_report = apply_medium(model, medium)
    progress(f"{name}: overview statistics")
    quick = quick_analyze(model)
    stats = quick["stats"]
    wt_growth = stats["wt_growth"] or 0.0
    wt = wt_solution(model)
    _, _, _, met_to_mnx = detect_metabolite_namespace_and_map(model)

    reactions = quick["reactions"]
    n = max(1, len(reactions))
    types, balance = {}, {}
    for r in reactions:
        types[r["type"]] = types.get(r["type"], 0) + 1
        balance[r["balance"]] = balance.get(r["balance"], 0) + 1
    overview = {
        "model_id": stats["model_id"], "genes": stats["genes"], "metabolites": stats["metabolites"], "reactions": stats["reactions"],
        "compartments": stats["compartments"], "wt_growth": wt_growth, "wt_status": stats["wt_status"],
        "objective_direction": stats["objective_direction"],
        "namespace_metabolites": stats["namespace_metabolites"]["label"], "namespace_reactions": stats["namespace_reactions"]["label"],
        "compartment_convention": (stats["compartment_convention"] or {}).get("label"),
        "mapped_metabolites": stats["mapped_metabolite_count"] / max(1, stats["metabolites"]),
        "mapped_reactions": stats["mapped_reaction_count"] / max(1, stats["reactions"]),
        "reaction_types": types,
        "with_gpr": sum(bool((r["gene_reaction_rule"] or "").strip()) for r in reactions) / n,
        "with_subsystem": sum(bool((r["subsystem"] or "").strip()) for r in reactions) / n,
        "balance": balance, "gene_reaction_ratio": stats["gene_reaction_ratio"],
    }
    progress(f"{name}: biomass and maintenance")
    biomass = _biomass(model, met_to_mnx)
    uptake = quick["uptake_secretion"]
    progress(f"{name}: essential exchanges")
    essential = _essential_exchanges(model, wt_growth)
    progress(f"{name}: flux variability of the core carbon reactions")
    core = _core_fva(model, core_ids, fva_fraction, wt)
    return {"name": name, "medium": medium_report, "overview": overview, "biomass": biomass, "maintenance": quick["maintenance"],
            "uptake": uptake["uptake"], "secretion": uptake["secretion"],
            "carbon_main": uptake["carbon_main"], "nitrogen_main": uptake["nitrogen_main"],
            "essential_exchanges": essential, "core": core}
