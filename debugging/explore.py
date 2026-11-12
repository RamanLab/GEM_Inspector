"""Pathway Explorer: grow a graph one step at a time from any metabolite or
reaction, and test which metabolites the network can make or use.

"Upstream" of a metabolite are the reactions that can make it, "downstream" the
reactions that can use it, judged by the reaction bounds (a reversible reaction
counts both ways). Upstream of a reaction are the metabolites it consumes (and
what makes them), downstream the ones it produces (and what uses them).
"""
from cobra import Reaction

from core.knockouts import reaction_knockout
from debugging.map_graph import FLUX_TOLERANCE, _background_info, _met_record, _rxn_record

MAX_NEW_REACTIONS = 40   # per expansion, active reactions first
TEST_TOLERANCE = 1e-7


def can_make(rxn, met, tol=FLUX_TOLERANCE):
    coeff = rxn.metabolites[met]
    return (coeff > 0 and rxn.upper_bound > tol) or (coeff < 0 and rxn.lower_bound < -tol)


def can_use(rxn, met, tol=FLUX_TOLERANCE):
    coeff = rxn.metabolites[met]
    return (coeff < 0 and rxn.upper_bound > tol) or (coeff > 0 and rxn.lower_bound < -tol)


def _neighbour_reactions(model, kind, ident, direction):
    """[(reaction, the metabolite it was reached from)] for one step in `direction`."""
    ups, downs = direction in ("up", "both"), direction in ("down", "both")
    if kind == "metabolite":
        met = model.metabolites.get_by_id(ident)
        return [(r, met) for r in met.reactions if (ups and can_make(r, met)) or (downs and can_use(r, met))]
    rxn = model.reactions.get_by_id(ident)
    found = []
    for met in rxn.metabolites:
        if (ups and can_use(rxn, met)):   # a substrate of this reaction: who makes it?
            found += [(r, met) for r in met.reactions if r is not rxn and can_make(r, met)]
        if (downs and can_make(rxn, met)):  # a product: who uses it?
            found += [(r, met) for r in met.reactions if r is not rxn and can_use(r, met)]
    return found


def expand(model, wt, kind, ident, direction, trivial_ids, compartment_names, types, biomass_id):
    """One step from a node. Returns the reactions found (with their metabolites)
    and the metabolite records, for the browser to merge into its graph."""
    trivial_ids = set(trivial_ids) - ({ident} if kind == "metabolite" else set())
    fva, dead_ends = _background_info(model)
    found = {}
    for rxn, via in _neighbour_reactions(model, kind, ident, direction):
        found.setdefault(rxn.id, (rxn, via))
    ordered = sorted(found.values(), key=lambda rv: (abs(wt.fluxes[rv[0].id]) <= FLUX_TOLERANCE, len(rv[0].metabolites)))
    truncated = len(ordered) > MAX_NEW_REACTIONS
    ordered = ordered[:MAX_NEW_REACTIONS]

    work = model.copy()  # knockouts below change bounds; the copy shares the memo
    wt_growth = max(0.0, wt.objective_value or 0.0)
    reactions, met_ids = [], set()
    if kind == "reaction":
        ordered = [(model.reactions.get_by_id(ident), None)] + ordered
    for rxn, via in ordered:
        shown = {m.id for m in rxn.metabolites if m.id not in trivial_ids}
        drawn = {via.id} if rxn.id == biomass_id and via is not None else None  # keep the biomass hub readable
        if rxn.id == biomass_id and via is None:
            drawn = set()
        rec = _rxn_record(rxn, types, wt, None, trivial_ids, shown, 1, False, False, biomass_id, drawn, fva)
        value, _ = reaction_knockout(work, work.reactions.get_by_id(rxn.id))
        rec["essential"] = (value is None or value < 1e-6) and wt_growth > 0
        reactions.append(rec)
        met_ids.update(m for m, _ in rec["mets"])
    if kind == "metabolite":
        met_ids.add(ident)
    metabolites = [_met_record(model.metabolites.get_by_id(m), "seed" if m == ident else "neighbour",
                               compartment_names, dead_ends) for m in met_ids]
    return {"reactions": reactions, "metabolites": metabolites, "truncated": truncated, "found": len(found)}


def test_metabolites(model, ids):
    """{id: {"make": bool, "use": bool}}: can the network make the metabolite
    (a temporary demand carries flux) and use it (a temporary supply is absorbed),
    under the current bounds. Runs on a copy."""
    work = model.copy()
    out = {}
    for mid in ids:
        met = work.metabolites.get_by_id(mid)
        res = {}
        for key, coeff in (("make", -1), ("use", 1)):
            with work:
                test = Reaction("_gi_test", lower_bound=0, upper_bound=1000)
                work.add_reactions([test])
                test.add_metabolites({met: coeff})
                work.objective = test
                value = work.slim_optimize(error_value=0.0)
            res[key] = bool(value and value > TEST_TOLERANCE)
        out[mid] = res
    return out
