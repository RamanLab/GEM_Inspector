"""Pathway tracer: find routes between a start and a target and map them.

A route follows reactions in a direction they can run. With mode "active" only
reactions carrying flux in the current FBA solution are used, in the direction of
that flux; with mode "all" every reaction whose bounds allow the direction is
used, whether or not it carries flux, so alternative routes show up too.
"""
from collections import deque

from annotation.naming import clean_metabolite_display_name, is_trivial_metabolite
from core.shared import classify_reactions
from debugging.map_graph import FLUX_TOLERANCE, build_map
from debugging.tracing import build_active_flux_downstream_graph, compute_active_flux, format_flux_path


def _directions(rxn, flux, mode):
    """The directions (True = forward) in which the reaction may be used."""
    if mode == "active":
        return [flux > 0] if abs(flux) > FLUX_TOLERANCE else []
    out = []
    if rxn.upper_bound > FLUX_TOLERANCE:
        out.append(True)
    if rxn.lower_bound < -FLUX_TOLERANCE:
        out.append(False)
    return out


def downstream_graph(model, wt, trivial_ids, mode):
    """{substrate id: [(reaction id, product id), ...]} for the allowed directions."""
    if mode == "active":
        return build_active_flux_downstream_graph(model, compute_active_flux(model, wt, FLUX_TOLERANCE),
                                                  FLUX_TOLERANCE, trivial_ids)
    graph = {}
    for rxn in model.reactions:
        for forward in _directions(rxn, 0.0, mode):
            subs = [m.id for m, c in rxn.metabolites.items() if (c < 0) == forward and m.id not in trivial_ids]
            prods = [m.id for m, c in rxn.metabolites.items() if (c > 0) == forward and m.id not in trivial_ids]
            for s in subs:
                graph.setdefault(s, []).extend((rxn.id, p) for p in prods)
    return graph


def _distances(adjacency, sources):
    dist = {s: 0 for s in sources}
    queue = deque(sources)
    while queue:
        node = queue.popleft()
        for nxt in adjacency.get(node, ()):
            if nxt not in dist:
                dist[nxt] = dist[node] + 1
                queue.append(nxt)
    return dist


def find_routes(graph, starts, targets, max_levels, max_paths, slack=3):
    """Up to max_paths routes, shortest first: every route no longer than the
    shortest one plus `slack` reactions, never reusing a reaction or metabolite.
    The shortest routes are kept when more exist.
    Returns [(start id, [(reaction id, next metabolite id), ...]), ...]."""
    forward = {m: [p for _, p in edges] for m, edges in graph.items()}
    reverse = {}
    for m, edges in forward.items():
        for p in edges:
            reverse.setdefault(p, []).append(m)
    to_target = _distances(reverse, list(targets))
    from_start = _distances(forward, list(starts))
    reachable = [d for t, d in from_start.items() if t in targets]
    if not reachable:
        return []
    limit = min(max_levels, min(reachable) + slack)
    routes, seen = [], set()

    def walk(origin, node, path, used):
        if len(routes) >= 5 * max_paths:
            return
        if path and node in targets:
            seq = tuple(r for r, _ in path)
            if seq not in seen:
                seen.add(seq)
                routes.append((origin, list(path)))
            return
        for rxn_id, nxt in graph.get(node, ()):
            if nxt in used or any(rxn_id == r for r, _ in path):
                continue
            if len(path) + 1 + to_target.get(nxt, 10 ** 6) > limit:
                continue
            walk(origin, nxt, path + [(rxn_id, nxt)], used | {nxt})

    for origin in starts:
        if origin not in targets:
            walk(origin, origin, [], {origin})
    routes.sort(key=lambda r: len(r[1]))
    return routes[:max_paths]


def resolve_endpoint(model, kind, ident, role, wt, mode, trivial_ids):
    """(metabolite ids, reaction id or None, error). A reaction start gives the
    metabolites it can produce; a reaction target the ones it can consume."""
    if kind == "metabolite":
        try:
            return [model.metabolites.get_by_id(ident).id], None, None
        except KeyError:
            return [], None, f"Metabolite '{ident}' not found in model"
    try:
        rxn = model.reactions.get_by_id(ident)
    except KeyError:
        return [], None, f"Reaction '{ident}' not found in model"
    flux = float(wt.fluxes[rxn.id])
    dirs = _directions(rxn, flux, mode)
    if not dirs:
        why = "carries no active flux in the current solution (try “all possible routes”)" if mode == "active" \
            else "is blocked by its bounds"
        return [], rxn.id, f"Reaction '{ident}' {why}."
    wanted = (lambda c, fwd: (c > 0) == fwd) if role == "start" else (lambda c, fwd: (c < 0) == fwd)
    mets = {m.id for m, c in rxn.metabolites.items() for fwd in dirs if wanted(c, fwd) and m.id not in trivial_ids}
    if not mets:
        return [], rxn.id, f"Reaction '{ident}' has no non-cofactor {'products' if role == 'start' else 'substrates'}."
    return sorted(mets), rxn.id, None


def trace_map(model, wt, ko, start, target, mode, hops, max_levels, max_paths, currency, hide_trivial,
              extra_mets, extra_rxns, compartment_names, biomass_id):
    """start/target: (kind, id). Returns the response body or {"error": ...}."""
    keep = set(extra_mets)
    explicit = {i for k, i in (start, target) if k == "metabolite"}
    trivial_ids = {m.id for m in model.metabolites
                   if hide_trivial and m.id not in keep and m.id not in explicit and is_trivial_metabolite(m, currency)}
    starts, start_rxn, err = resolve_endpoint(model, *start, "start", wt, mode, trivial_ids)
    if err:
        return {"error": err}
    targets, target_rxn, err = resolve_endpoint(model, *target, "target", wt, mode, trivial_ids)
    if err:
        return {"error": err}

    graph = downstream_graph(model, wt, trivial_ids, mode)
    found = find_routes(graph, starts, set(targets), max_levels, max_paths)
    paths = [format_flux_path(model, wt, model.metabolites.get_by_id(s), route, None, compartment_names)
             for s, route in found]

    primary_rxns = {r["id"] for p in paths for r in p["reactions"]} | {x for x in (start_rxn, target_rxn) if x}
    primary_mets = {m["id"] for p in paths for m in p["metabolites"]}
    graph_body = build_map(
        model, classify_reactions(model), wt, ko, compartment_names, trivial_ids, primary_rxns, primary_mets,
        start_ids=set(starts), target_ids=set(targets), extra_rxns=extra_rxns, biomass_id=biomass_id, hops=hops)
    return {
        "paths": paths,
        "map": graph_body,
        "start_metabolites": [{"id": m, "name": clean_metabolite_display_name(model.metabolites.get_by_id(m))} for m in starts],
        "target_metabolites": [{"id": m, "name": clean_metabolite_display_name(model.metabolites.get_by_id(m))} for m in targets],
    }
