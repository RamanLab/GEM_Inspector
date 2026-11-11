"""Exchange debugging: the active-flux route from an exchange's metabolite to
biomass, plus its neighbourhood (see map_graph)."""
from annotation.naming import is_trivial_metabolite
from core.shared import classify_reactions
from debugging.map_graph import build_map


def build_exchange_map(model, exchange_id, biomass_id, primary_paths, wt, ko, currency, hide_trivial, hops,
                       compartment_names):
    start = list(model.reactions.get_by_id(exchange_id).metabolites)[0]
    trivial_ids = {m.id for m in model.metabolites
                   if hide_trivial and m.id != start.id and is_trivial_metabolite(m, currency)}
    primary_rxns = {r["id"] for p in primary_paths for r in p["reactions"]} | {exchange_id}
    primary_mets = {start.id} | {m["id"] for p in primary_paths for m in p["metabolites"]}
    drawn = {}
    if primary_paths:
        # A route ends at the metabolites the biomass reaction consumes; only those are drawn for it.
        primary_rxns.add(biomass_id)
        drawn[biomass_id] = {p["metabolites"][-1]["id"] for p in primary_paths}
    result = build_map(model, classify_reactions(model), wt, ko, compartment_names, trivial_ids,
                       primary_rxns, primary_mets, start_ids={start.id}, biomass_id=biomass_id,
                       drawn=drawn, hops=hops)
    result["start_metabolite"] = start.id
    return result
