"""Network Gaps tab (on-request, as soon as the model loads).

Two independent diagnostics:

  1. Blocked reactions:
     COBRApy FVA-based find_blocked_reactions(). A reaction is blocked if
     it cannot carry flux under the model's current bounds.

  2. Dead-end metabolites:
     Independent stoichiometric check using reaction stoichiometry and
     current reaction directionality. No FVA results are used here.
     A metabolite is a dead end if it cannot both be produced and
     consumed.

The two diagnostics are intentionally kept separate: blocked reactions are
LP/FVA-based, dead-end metabolites are stoichiometry + reaction bounds
only.
"""
import numpy as np
import scipy.sparse as sp
from cobra.flux_analysis import find_blocked_reactions

from annotation.naming import clean_metabolite_display_name, compartment_display_name
from annotation.namespace_mapping import detect_metabolite_namespace_and_map, detect_reaction_namespace_and_map
from core.memo import not_error, remember
from core.shared import classify_reactions, safe_float, subsystem_value
from diagnostics.solver_utils import run_with_exact_solver


def cobra_to_stoichiometric_matrix(model):
    """Build the stoichiometric matrix S (metabolites x reactions)."""
    met_index = {met.id: i for i, met in enumerate(model.metabolites)}

    S = sp.lil_matrix((len(model.metabolites), len(model.reactions)), dtype=float)
    for j, rxn in enumerate(model.reactions):
        for met, coeff in rxn.metabolites.items():
            S[met_index[met.id], j] = coeff

    return S.tocsr()


def find_dead_end_metabolites(model, exclude_transport=True):
    """Identify dead-end metabolites independently of FVA.

    A metabolite is considered a dead end if it cannot BOTH:
      - be produced by at least one allowed reaction direction, and
      - be consumed by at least one allowed reaction direction.

    Allowed directions come only from reaction bounds:
      - upper_bound > 0  -> forward direction allowed
      - lower_bound < 0  -> reverse direction allowed

    FVA-blocked reactions are not removed or treated specially here.
    Metabolites involved in cross-compartment reactions are excluded when
    exclude_transport=True.
    """
    mets = list(model.metabolites)
    rxns = list(model.reactions)
    if not mets or not rxns:
        return []

    S = cobra_to_stoichiometric_matrix(model)
    lb = np.asarray([rxn.lower_bound for rxn in rxns], dtype=float)
    ub = np.asarray([rxn.upper_bound for rxn in rxns], dtype=float)

    # Reaction directionality.
    forward_allowed = ub > 0
    reverse_allowed = lb < 0

    # Stoichiometric signs: positive coefficient -> produced, negative -> consumed.
    Spos = S.multiply(S > 0)
    Sneg = S.multiply(S < 0)

    # Can each metabolite be PRODUCED? Forward reaction: positive
    # coefficient produces it. Reverse reaction: negative coefficient
    # produces it.
    production = Spos.dot(forward_allowed.astype(float)) - Sneg.dot(reverse_allowed.astype(float))
    can_be_produced = np.asarray(production > 0).ravel()

    # Can each metabolite be CONSUMED? Forward reaction: negative
    # coefficient consumes it. Reverse reaction: positive coefficient
    # consumes it.
    consumption = Sneg.dot(forward_allowed.astype(float)) - Spos.dot(reverse_allowed.astype(float))
    can_be_consumed = np.asarray(consumption < 0).ravel()

    # Dead end = cannot both be produced and consumed.
    is_dead_end = ~(can_be_produced & can_be_consumed)
    dead_end_idx = np.flatnonzero(is_dead_end)

    # Exclude metabolites involved in cross-compartment reactions.
    transport_met_ids = set()
    if exclude_transport:
        for rxn in rxns:
            rxn_mets = list(rxn.metabolites)
            compartments = {met.compartment for met in rxn_mets if met.compartment is not None}
            if len(compartments) > 1:
                for met in rxn_mets:
                    transport_met_ids.add(met.id)

    dead_ends = []
    for i in dead_end_idx:
        met = mets[i]
        touching = sorted(rxn.id for rxn in met.reactions)

        if not touching:
            dead_ends.append({"id": met.id, "reason": "no_reactions", "reactions": []})
            continue

        if exclude_transport and met.id in transport_met_ids:
            continue

        if can_be_produced[i]:
            reason = "no_consuming_reaction"
        elif can_be_consumed[i]:
            reason = "no_producing_reaction"
        else:
            reason = "fully_blocked"

        dead_ends.append({"id": met.id, "reason": reason, "reactions": touching})

    return dead_ends


def compute_network_gaps_report(model, zero_cutoff=None):
    """Memoized per model and cutoff; see _compute_network_gaps_report."""
    return remember(model, ("network_gaps", zero_cutoff),
                    lambda: _compute_network_gaps_report(model, zero_cutoff), cache_if=not_error)


def _compute_network_gaps_report(model, zero_cutoff=None):
    reaction_types = classify_reactions(model)
    compartment_names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}
    _, _, _, met_to_mnx = detect_metabolite_namespace_and_map(model)
    _, _, _, rxn_to_mnx = detect_reaction_namespace_and_map(model)

    # 1. Blocked reactions -- a completely independent FVA-based diagnostic.
    try:
        blocked_ids = run_with_exact_solver(
            model,
            lambda: find_blocked_reactions(model, zero_cutoff=zero_cutoff, open_exchanges=False, processes=1),
        )
    except Exception as exc:
        return {"error": f"Could not compute blocked reactions: {exc}"}

    blocked_reactions = []
    for rxn_id in sorted(blocked_ids):
        rxn = model.reactions.get_by_id(rxn_id)
        blocked_reactions.append({
            "id": rxn.id,
            "metanetx_id": rxn_to_mnx.get(rxn.id),
            "name": rxn.name,
            "subsystem": subsystem_value(rxn),
            "type": reaction_types.get(rxn.id, ""),
            "compartments": sorted({m.compartment for m in rxn.metabolites if m.compartment}),
            "reaction_string": rxn.reaction,
            "lower_bound": safe_float(rxn.lower_bound),
            "upper_bound": safe_float(rxn.upper_bound),
            "gene_reaction_rule": getattr(rxn, "gene_reaction_rule", ""),
        })

    # 2. Dead-end metabolites -- completely independent of blocked_ids. Uses
    # only stoichiometry and reaction bounds; no FVA results are involved.
    try:
        dead_end_raw = find_dead_end_metabolites(model, exclude_transport=True)
    except Exception as exc:
        return {"error": f"Could not compute dead-end metabolites: {exc}"}

    dead_end_metabolites = []
    for d in dead_end_raw:
        met = model.metabolites.get_by_id(d["id"])
        dead_end_metabolites.append({
            "id": met.id,
            "metanetx_id": met_to_mnx.get(met.id),
            "name": clean_metabolite_display_name(met),
            "compartment": met.compartment,
            "compartment_name": compartment_names.get(met.compartment, met.compartment),
            "formula": getattr(met, "formula", None),
            "reason": d["reason"],
            "reactions": d["reactions"],
        })

    return {
        "blocked_reactions": blocked_reactions,
        "dead_end_metabolites": dead_end_metabolites,
        "zero_cutoff": safe_float(zero_cutoff) if zero_cutoff is not None else safe_float(model.tolerance),
        "note": (
            f"{len(blocked_reactions)} blocked reaction(s) "
            "(cannot carry flux under the model's current bounds, "
            "using COBRApy's FVA-based analysis) and "
            f"{len(dead_end_metabolites)} dead-end metabolite(s) "
            "(cannot both be produced and consumed based only on "
            "stoichiometry and reaction directionality). "
            "The two diagnostics are independent: FVA-blocked "
            "reactions are not used when identifying dead-end "
            "metabolites. Metabolites participating in "
            "cross-compartment reactions are excluded from the "
            "dead-end list. Blocked reactions are relative to the "
            "medium/diet currently applied to this model -- opening "
            "or changing exchange bounds (a different diet) can "
            "unblock a reaction shown here, or block one that isn't."
        ),
    }
