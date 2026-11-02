"""Demand & Sink Audit (on-request, part of the Network Gaps tab).

Demand and sink reactions (cobra's model.demands / model.sinks) are
single-metabolite boundary reactions used to model things like forced
accumulation, biomass side-components, or buffered cofactor pools -- they're
often added by hand during model curation and can go stale without anyone
noticing, since they don't show up in the Exchange Essentiality tab (that's
exchanges only). This mirrors the same essentiality test used there
(reaction knockout, KO growth < 5% of WT growth), applied to demand/sink
reactions instead, plus whether each one even carries flux in the current
FBA solution at all -- a demand/sink with zero flux AND zero essentiality is
a reasonable candidate for "is this reaction still needed?"
"""
from annotation.naming import clean_metabolite_display_name
from core.knockouts import reaction_knockout
from core.memo import not_error, remember
from core.shared import safe_float, subsystem_value, wt_solution as solve_wt


def compute_demand_sink_audit(model):
    """Memoized per model; see _compute_demand_sink_audit."""
    return remember(model, "demand_sink_audit", lambda: _compute_demand_sink_audit(model), cache_if=not_error)


def _compute_demand_sink_audit(model):
    """Audit every demand and sink reaction: metabolite, bounds/
    reversibility, whether it carries flux in the current (fresh) FBA
    solution, and a reaction-knockout essentiality test identical in
    definition to the one used for exchanges (core.knockouts, shared with
    exchange essentiality and the FROG reaction deletions).
    """
    wt_solution = solve_wt(model)
    if wt_solution.status != "optimal":
        return {"error": f"WT optimization was not optimal (status: {wt_solution.status})."}
    wt_growth = max(0.0, safe_float(wt_solution.objective_value) or 0.0)
    fluxes = wt_solution.fluxes

    rows = []
    for kind, reactions in (("demand", model.demands), ("sink", model.sinks)):
        for rxn in reactions:
            met = next(iter(rxn.metabolites.keys()), None)
            wt_flux = safe_float(fluxes.get(rxn.id)) if hasattr(fluxes, "get") else None

            ko_growth = None
            ko_status = "not tested"
            if wt_growth > 0:
                value, ko_status = reaction_knockout(model, rxn)  # shared with FROG and exchange essentiality
                if value is not None:
                    ko_growth = max(0.0, value)

            ratio = None
            essential = False
            if ko_growth is not None and wt_growth > 0:
                ratio = ko_growth / wt_growth
                essential = ratio < 0.05

            rows.append({
                "id": rxn.id,
                "name": rxn.name,
                "kind": kind,
                "metabolite_id": met.id if met else None,
                "metabolite_name": clean_metabolite_display_name(met) if met else None,
                "compartment": met.compartment if met else None,
                "lower_bound": safe_float(rxn.lower_bound),
                "upper_bound": safe_float(rxn.upper_bound),
                "reversible": bool(rxn.lower_bound < 0 and rxn.upper_bound > 0),
                "wt_flux": wt_flux,
                "used_in_wt_solution": bool(wt_flux is not None and abs(wt_flux) > 1e-9),
                "ko_growth": ko_growth,
                "ko_growth_fraction": ratio,
                "essential": essential,
                "ko_status": ko_status,
                "subsystem": subsystem_value(rxn),
                "gene_reaction_rule": getattr(rxn, "gene_reaction_rule", ""),
                "reaction_string": rxn.reaction,
            })

    rows.sort(key=lambda r: (r["kind"], r["id"]))
    n_demand = sum(1 for r in rows if r["kind"] == "demand")
    n_sink = sum(1 for r in rows if r["kind"] == "sink")
    n_unused = sum(1 for r in rows if not r["used_in_wt_solution"])
    n_essential = sum(1 for r in rows if r["essential"])

    return {
        "rows": rows,
        "wt_growth": wt_growth,
        "note": (
            f"{n_demand} demand reaction(s), {n_sink} sink reaction(s). {n_unused} carry no flux in the current "
            f"FBA solution; {n_essential} are essential (reaction knockout gives growth < 5% of WT growth)."
        ),
    }
