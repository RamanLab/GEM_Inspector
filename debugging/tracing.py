"""Shared active-flux pathway tracing.

Backs both the biomass-specific Exchange Debugging tab
(debug_exchange_to_biomass) and the general-purpose Pathway Tracer
(run_pathway_trace): a BFS over a graph built only from reactions carrying
non-zero flux in the current FBA solution, respecting actual flux
direction, with currency/cofactor metabolites optionally excluded as path
steps. Kept as small, independently testable functions so the two features
share exactly the same tracing logic without drifting apart.
"""
from collections import deque

from annotation.naming import clean_metabolite_display_name, compartment_display_name, is_trivial_metabolite
from core.shared import classify_reactions, clean, safe_float, subsystem_value


def compute_active_flux(model, solution, flux_tolerance=1e-9):
    """{reaction_id: flux} for every reaction carrying non-zero flux
    (abs(flux) > flux_tolerance) in the given FBA solution."""
    return {
        rxn.id: solution.fluxes[rxn.id]
        for rxn in model.reactions
        if abs(solution.fluxes[rxn.id]) > flux_tolerance
    }


def build_active_flux_downstream_graph(model, active_flux, flux_tolerance, trivial_ids):
    """Build {substrate_metabolite_id: [(reaction_id, product_metabolite_id), ...]}
    from only the reactions present in active_flux, respecting the actual
    flux direction (a reaction with negative flux is walked with its
    substrates/products swapped). Metabolite ids in trivial_ids are skipped
    both as a substrate key and as a product hop, so a trace never starts
    from or jumps onto them."""
    downstream = {}
    for rxn in model.reactions:
        if rxn.id not in active_flux:
            continue
        flux = active_flux[rxn.id]

        if flux > 0:
            substrates = [met for met, coeff in rxn.metabolites.items() if coeff < -flux_tolerance]
            products = [met for met, coeff in rxn.metabolites.items() if coeff > flux_tolerance]
        else:
            substrates = [met for met, coeff in rxn.metabolites.items() if coeff > flux_tolerance]
            products = [met for met, coeff in rxn.metabolites.items() if coeff < -flux_tolerance]

        for substrate in substrates:
            if substrate.id in trivial_ids:
                continue
            downstream.setdefault(substrate.id, [])
            for product in products:
                if product.id in trivial_ids:
                    continue
                downstream[substrate.id].append((rxn.id, product.id))
    return downstream


def bfs_flux_paths(downstream, start_met_id, is_target, max_paths=20, max_depth=20):
    """BFS from start_met_id over the `downstream` graph until `is_target`
    (a function of the current metabolite id) is true -- that node's path is
    recorded and not expanded further -- or max_paths/max_depth is reached. A
    reaction id is never revisited within the same path, which rules out
    cycles. Returns a list of paths, each a list of (reaction_id,
    next_metabolite_id) hops starting from start_met_id (an empty list means
    start_met_id itself already satisfies is_target).
    """
    queue = deque()
    queue.append((start_met_id, []))
    visited = set()
    paths = []

    while queue and len(paths) < max_paths:
        current_met, path = queue.popleft()

        if len(path) >= max_depth:
            continue

        state = (current_met, tuple(rxn_id for rxn_id, _ in path))
        if state in visited:
            continue
        visited.add(state)

        if is_target(current_met):
            paths.append(path)
            continue

        for rxn_id, next_met in downstream.get(current_met, []):
            if any(rxn_id == existing_rxn for existing_rxn, _ in path):
                continue
            new_path = path + [(rxn_id, next_met)]
            queue.append((next_met, new_path))

    return paths


def format_flux_path(model, solution, start_met, path, reaction_types=None, compartment_names=None):
    """Render a BFS path (a list of (reaction_id, next_metabolite_id) hops
    starting from start_met) as {"metabolites": [...], "reactions": [...]}
    with display names and per-step flux/subsystem -- used by both the text
    view and the network-graph view.

    Each metabolite/reaction step also carries the "basic info" fields
    needed for a hover tooltip in the network view (compartment, formula,
    charge for metabolites; reaction string, bounds, GPR, and a best-effort
    type for reactions), so the frontend never has to make a second request
    just to describe a node/edge the user is hovering.

    reaction_types/compartment_names are optional precomputed maps (see
    core.shared.classify_reactions / annotation.naming.compartment_display_name).
    A caller formatting many paths in one request should compute these once
    and pass them in, since they only depend on model structure, not on the
    path being formatted -- computed on the fly here (once per call) when
    omitted, so existing callers are unaffected.
    """
    if reaction_types is None:
        reaction_types = classify_reactions(model)
    if compartment_names is None:
        compartment_names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}

    def met_info(met):
        return {
            "id": met.id,
            "name": clean_metabolite_display_name(met),
            "compartment": met.compartment,
            "compartment_name": compartment_names.get(met.compartment, met.compartment),
            "formula": getattr(met, "formula", None),
            "charge": clean(getattr(met, "charge", None)),
        }

    formatted = {
        "metabolites": [met_info(start_met)],
        "reactions": [],
    }
    for rxn_id, next_met in path:
        rxn = model.reactions.get_by_id(rxn_id)
        flux = solution.fluxes[rxn_id]
        next_met_obj = model.metabolites.get_by_id(next_met)

        formatted["reactions"].append({
            "id": rxn_id,
            "flux": float(flux),
            "name": rxn.name,
            "subsystem": subsystem_value(rxn),
            "reaction_string": rxn.reaction,
            "type": reaction_types.get(rxn_id, ""),
            "lower_bound": safe_float(rxn.lower_bound),
            "upper_bound": safe_float(rxn.upper_bound),
            "reversible": bool(rxn.lower_bound < 0 and rxn.upper_bound > 0),
            "gene_reaction_rule": getattr(rxn, "gene_reaction_rule", ""),
        })
        formatted["metabolites"].append(met_info(next_met_obj))
    return formatted


def resolve_reaction_start_metabolites(model, reaction_id, solution, flux_tolerance=1e-9):
    """Resolve a reaction serving as a pathway-trace starting point into the
    metabolite(s) it actually produces under its current flux direction, so
    a general trace can begin from real graph nodes. Returns
    (metabolites, error_message) -- metabolites is empty and error_message is
    set when the reaction doesn't exist or carries no active flux in the
    current FBA solution (there's nothing meaningful to trace downstream
    from a dead reaction)."""
    try:
        rxn = model.reactions.get_by_id(reaction_id)
    except KeyError:
        return [], f"Reaction '{reaction_id}' not found in model"

    flux = solution.fluxes[reaction_id] if reaction_id in solution.fluxes else None
    if flux is None or abs(flux) <= flux_tolerance:
        return [], (
            f"Reaction '{reaction_id}' carries no active flux in the current FBA solution — "
            "nothing to trace downstream from."
        )

    if flux > 0:
        products = [met for met, coeff in rxn.metabolites.items() if coeff > flux_tolerance]
    else:
        products = [met for met, coeff in rxn.metabolites.items() if coeff < -flux_tolerance]

    return products, None


def debug_exchange_to_biomass(
    model,
    exchange_rxn_id,
    internal_metabolite_id,
    biomass_rxn_id,
    max_flux_paths=20,
    max_flux_path_depth=20,
    flux_tolerance=1e-9,
    exclude_trivial_metabolites=True,
    reaction_types=None,
    compartment_names=None,
    solution=None,
):
    """Trace active-flux pathways from an exchange-derived metabolite toward
    the biomass reaction. Only reactions carrying non-zero flux in the
    current model solution are considered.

    When exclude_trivial_metabolites is True (the default), currency/
    cofactor metabolites (see annotation.naming.TRIVIAL_METABOLITES -- H+,
    water, ATP/ADP, NAD(H), etc.) are never followed as a path step: a
    reaction that happens to also produce/consume one doesn't let the trace
    jump onto it. The requested start metabolite is always traced from,
    even if it happens to itself be on the trivial list.

    reaction_types/compartment_names are optional precomputed maps passed
    straight through to format_flux_path (see there) -- a caller tracing
    several exchanges in one request computes these once up front rather
    than recomputing them for every exchange's before/after-KO trace.

    `solution` is an already-solved FBA solution for the model as it stands
    (the "before KO" trace passes the one solved once for the whole request).
    """
    model.reactions.get_by_id(exchange_rxn_id)  # validate it exists before running FBA
    biomass = model.reactions.get_by_id(biomass_rxn_id)
    start_met = model.metabolites.get_by_id(internal_metabolite_id)

    if solution is None:
        solution = model.optimize()
    if solution.status != "optimal":
        return {"status": solution.status, "paths": [], "error": "FBA not optimal"}

    active_flux = compute_active_flux(model, solution, flux_tolerance)

    # Metabolite ids to skip as path steps (but never the start metabolite
    # itself, so tracing can still begin even if it happens to be trivial).
    trivial_ids = set()
    if exclude_trivial_metabolites:
        trivial_ids = {
            met.id for met in model.metabolites
            if met.id != start_met.id and is_trivial_metabolite(met)
        }

    downstream = build_active_flux_downstream_graph(model, active_flux, flux_tolerance, trivial_ids)

    def is_biomass_target(met_id):
        biomass_coeff = biomass.metabolites.get(model.metabolites.get_by_id(met_id), 0)
        return biomass_coeff < -flux_tolerance

    paths = bfs_flux_paths(downstream, start_met.id, is_biomass_target, max_flux_paths, max_flux_path_depth)
    formatted_paths = [
        format_flux_path(model, solution, start_met, path, reaction_types, compartment_names)
        for path in paths
    ]

    return {
        "status": "success",
        "exchange_id": exchange_rxn_id,
        "exchange_flux": float(solution.fluxes[exchange_rxn_id]),
        "biomass_flux": float(solution.objective_value),
        "paths": formatted_paths,
        "num_active_reactions": len(active_flux),
        "excluded_trivial_metabolites": exclude_trivial_metabolites,
    }


def run_pathway_trace(
    model, solution, start_type, start_id, target_met,
    max_levels, max_paths, exclude_trivial,
    flux_tolerance=1e-9, reaction_types=None, compartment_names=None,
):
    """Run one pass of the general pathway trace (resolve the start point,
    build the active-flux graph, BFS to the target, format the paths)
    against `solution` -- the FBA result for `model` exactly as it's
    currently bounded. This is the one piece of logic shared by both the
    baseline trace and, when the caller has applied a knockout inside its
    own `with model:` block first, the after-KO trace, so the two are
    guaranteed to be traced the same way.

    Returns a dict with an "error" key on failure, or on success:
    "status", "start_metabolites", "num_active_reactions", "paths",
    "growth", and "active_flux" ({reaction_id: flux} for every reaction
    carrying flux in `solution` -- kept for the caller's own before/after
    comparison, not meant to be sent to the frontend as-is since it can be
    large; the endpoint pulls out just the reactions it needs).
    """
    if solution.status != "optimal":
        return {"status": solution.status, "error": "FBA not optimal"}

    if start_type == "metabolite":
        try:
            start_metabolites = [model.metabolites.get_by_id(start_id)]
        except KeyError:
            return {"error": f"Starting metabolite '{start_id}' not found in model"}
    else:
        start_metabolites, resolve_error = resolve_reaction_start_metabolites(model, start_id, solution, flux_tolerance)
        if resolve_error:
            return {"error": resolve_error}
        if not start_metabolites:
            return {"error": f"Reaction '{start_id}' has no products to trace from under its current flux direction."}

    active_flux = compute_active_flux(model, solution, flux_tolerance)

    # Never treat the target or any starting metabolite as trivial, even if
    # it's on the currency/cofactor list -- the user explicitly chose it, so
    # it must remain a usable node in the traced graph.
    trivial_ids = set()
    if exclude_trivial:
        keep_ids = {target_met.id} | {m.id for m in start_metabolites}
        trivial_ids = {
            met.id for met in model.metabolites
            if met.id not in keep_ids and is_trivial_metabolite(met)
        }

    downstream = build_active_flux_downstream_graph(model, active_flux, flux_tolerance, trivial_ids)

    def is_target(met_id):
        return met_id == target_met.id

    all_paths = []
    for start_met in start_metabolites:
        if len(all_paths) >= max_paths:
            break
        paths = bfs_flux_paths(downstream, start_met.id, is_target, max_paths - len(all_paths), max_levels)
        all_paths.extend(
            format_flux_path(model, solution, start_met, path, reaction_types, compartment_names)
            for path in paths
        )

    return {
        "status": "success",
        "start_metabolites": [
            {
                "id": m.id, "name": clean_metabolite_display_name(m),
                "compartment": m.compartment,
                "compartment_name": (compartment_names or {}).get(m.compartment, m.compartment),
                "formula": getattr(m, "formula", None),
                "charge": clean(getattr(m, "charge", None)),
            }
            for m in start_metabolites
        ],
        "num_active_reactions": len(active_flux),
        "paths": all_paths,
        "growth": safe_float(solution.objective_value),
        "active_flux": active_flux,
    }


def resolve_knockout_targets(model, raw_ids):
    """Resolve a list of user-typed ids for the Pathway Tracer's optional
    before/after-knockout comparison. Each id is looked up as a reaction
    first, then as a metabolite. A reaction resolves to itself. Knocking
    out a metabolite has no single built-in meaning in COBRApy, so it's
    approximated here as blocking every reaction the metabolite
    participates in as a reactant or product -- effectively removing it from
    the network. Returns (resolved, not_found):
      resolved: [{"input": raw_id, "type": "reaction"|"metabolite", "id": ..., "name": ..., "reactions_blocked": [rxn_id, ...]}, ...]
      not_found: [raw_id, ...] -- ids that matched neither a reaction nor a metabolite
    """
    resolved, not_found = [], []
    for raw in raw_ids:
        raw = (raw or "").strip()
        if not raw:
            continue
        try:
            rxn = model.reactions.get_by_id(raw)
        except KeyError:
            rxn = None
        if rxn is not None:
            resolved.append({
                "input": raw, "type": "reaction", "id": rxn.id, "name": rxn.name,
                "reactions_blocked": [rxn.id],
            })
            continue
        try:
            met = model.metabolites.get_by_id(raw)
        except KeyError:
            met = None
        if met is not None:
            rxn_ids = sorted(r.id for r in met.reactions)
            resolved.append({
                "input": raw, "type": "metabolite", "id": met.id, "name": clean_metabolite_display_name(met),
                "reactions_blocked": rxn_ids,
            })
            continue
        not_found.append(raw)
    return resolved, not_found


def apply_knockouts(model, resolved_targets):
    """Zero the bounds of every reaction implicated by resolve_knockout_targets
    (deduplicated across all targets). Meant to be called inside the
    caller's own `with model:` context so the change is automatically
    reverted afterwards. Returns the sorted list of reaction ids actually
    blocked."""
    rxn_ids = sorted({rid for t in resolved_targets for rid in t["reactions_blocked"]})
    for rid in rxn_ids:
        model.reactions.get_by_id(rid).knock_out()
    return rxn_ids
