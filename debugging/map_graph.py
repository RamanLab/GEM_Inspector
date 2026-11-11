"""Neighbourhood graph shared by exchange debugging and the pathway tracer.

Given the reactions and metabolites of a route (the primary part), it adds every
reaction within `hops` reaction steps, active or not, and returns plain records
for the browser to draw. Currency/cofactor metabolites (`trivial_ids`) are left
out of the graph and only listed per reaction.
"""
from annotation.naming import clean_metabolite_display_name
from core.shared import safe_float, subsystem_value

FLUX_TOLERANCE = 1e-9


def _met_record(met, role, compartment_names):
    return {
        "id": met.id, "name": clean_metabolite_display_name(met), "role": role,
        "compartment": met.compartment,
        "compartment_name": compartment_names.get(met.compartment, met.compartment),
        "formula": getattr(met, "formula", None),
    }


def _rxn_record(rxn, types, wt, ko, trivial_ids, shown, hop, primary, extra, biomass_id, drawn):
    lb, ub = safe_float(rxn.lower_bound), safe_float(rxn.upper_bound)
    visible = [m for m in rxn.metabolites if m.id in shown and (drawn is None or m.id in drawn)]
    return {
        "id": rxn.id, "name": rxn.name, "equation": rxn.reaction, "type": types.get(rxn.id, ""),
        "subsystem": subsystem_value(rxn), "genes": getattr(rxn, "gene_reaction_rule", ""),
        "lower_bound": lb, "upper_bound": ub,
        "blocked": lb == 0 and ub == 0,
        "reversible": bool(lb is not None and ub is not None and lb < 0 < ub),
        "flux_before": float(wt.fluxes[rxn.id]),
        "flux_after": None if ko is None else float(ko.fluxes[rxn.id]),
        "hop": hop, "primary": primary, "extra": extra, "biomass": rxn.id == biomass_id,
        "mets": [[m.id, rxn.metabolites[m]] for m in visible],
        "hidden_mets": [m.id for m in rxn.metabolites if m not in visible],
    }


def build_map(model, types, wt, ko, compartment_names, trivial_ids, primary_rxns, primary_mets,
              start_ids=(), target_ids=(), extra_rxns=(), biomass_id=None, drawn=None,
              hops=1, max_reactions=300):
    """primary_rxns / primary_mets: the route. `drawn` maps a reaction id to the
    only metabolites to draw for it (used to keep the biomass reaction readable).
    ko: the knockout flux solution, or None when growth is lost (no meaningful
    flux then, so every reaction counts as inactive after the knockout)."""
    drawn = drawn or {}
    included = {rid: 0 for rid in primary_rxns}
    for rid in extra_rxns:
        included.setdefault(rid, 0)
    met_ids = set(primary_mets) | set(start_ids) | set(target_ids)
    frontier = set(met_ids)
    truncated = False
    for hop in range(1, hops + 1):
        candidates = {}
        for mid in frontier:
            for rxn in model.metabolites.get_by_id(mid).reactions:
                if rxn.id not in included and rxn.id != biomass_id:
                    candidates[rxn.id] = rxn
        # Active reactions first, then the smaller ones, so a cut-off keeps the most informative.
        ordered = sorted(candidates.values(),
                         key=lambda r: (abs(wt.fluxes[r.id]) <= FLUX_TOLERANCE, len(r.metabolites)))
        frontier = set()
        for rxn in ordered:
            if len(included) >= max_reactions:
                truncated = True
                break
            included[rxn.id] = hop
            frontier.update(m.id for m in rxn.metabolites if m.id not in trivial_ids and m.id not in met_ids)
        met_ids |= frontier
        if truncated:
            break

    for rid in included:
        if rid != biomass_id and rid not in drawn:
            met_ids.update(m.id for m in model.reactions.get_by_id(rid).metabolites if m.id not in trivial_ids)
    shown = (met_ids - trivial_ids) | set(start_ids) | set(target_ids)

    extra_rxns = set(extra_rxns)
    reactions = [
        _rxn_record(model.reactions.get_by_id(rid), types, wt, ko, trivial_ids, shown, hop,
                    rid in primary_rxns, rid in extra_rxns and rid not in primary_rxns, biomass_id, drawn.get(rid))
        for rid, hop in included.items()
    ]
    on_route = set(primary_mets)
    metabolites = [
        _met_record(model.metabolites.get_by_id(mid),
                    "start" if mid in start_ids else "target" if mid in target_ids
                    else "primary" if mid in on_route else "neighbour", compartment_names)
        for mid in shown
    ]
    return {"reactions": reactions, "metabolites": metabolites, "truncated": truncated,
            "max_reactions": max_reactions, "hops": hops}
