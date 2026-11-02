"""Tier 2 of the gap classification: LP tests on demand.

For every blocked reaction not already explained by a dead end, re-run the
FVA blocked-reaction check with one thing relaxed at a time (all inside a
temporary change that is always undone, so the cached model never changes):

  medium          exchanges opened
  directionality  internal reactions made reversible
  cofactor        a temporary two-way sink for every currency metabolite

A reaction that becomes active in exactly one of them gets that class; in
several, the first in the order above plus all tags; in none alone but in all
three together, "mixed"; in nothing, it stays unresolved (or "transport" if
Tier 1 inferred that). An "unblocked" result is evidence, not proof: relaxing
directions can open thermodynamically infeasible loops, so check it.
"""
from contextlib import contextmanager

from cobra.flux_analysis import find_blocked_reactions
from cobra.util import linear_reaction_coefficients

from annotation.naming import metabolite_base_id
from core.memo import not_error, remember
from diagnostics.solver_utils import run_with_exact_solver

OPEN = 1000.0
TESTS = ("medium", "direction", "cofactor")  # priority order for the primary class
CLASS_OF_TEST = {"medium": "medium", "direction": "directionality", "cofactor": "cofactor"}
NOT_TESTED = {"bounds_closed"}


@contextmanager
def _relaxed(model, tests, currency):
    """Apply the named relaxations to the model, and always undo them."""
    saved, sinks = {}, []
    objective = {r.id for r in linear_reaction_coefficients(model)}
    try:
        targets = []
        if "medium" in tests:
            targets += list(model.exchanges)
        if "direction" in tests:
            targets += [r for r in model.reactions if not r.boundary and r.id not in objective]
        for rxn in targets:
            saved.setdefault(rxn.id, rxn.bounds)
            rxn.bounds = (min(rxn.lower_bound, -OPEN), max(rxn.upper_bound, OPEN))
        if "cofactor" in tests:
            for met in model.metabolites:
                if metabolite_base_id(met.id) in currency:
                    sinks.append(model.add_boundary(met, type="sink", reaction_id=f"__gap_sink_{met.id}",
                                                    lb=-OPEN, ub=OPEN))
        yield
    finally:
        if sinks:
            model.remove_reactions(sinks, remove_orphans=False)
        for rid, bounds in saved.items():
            model.reactions.get_by_id(rid).bounds = bounds


def _still_blocked(model, candidates, tests, currency):
    reactions = [model.reactions.get_by_id(rid) for rid in candidates]
    with _relaxed(model, tests, currency):
        return set(find_blocked_reactions(model, reaction_list=reactions, open_exchanges=False, processes=1))


def _classify(unblocked_by, rid, tier1_class):
    tags = [t for t in TESTS if rid in unblocked_by[t]]
    if tags:
        return {"class": CLASS_OF_TEST[tags[0]], "resolved_by": tags}
    if rid in unblocked_by["all"]:
        return {"class": "mixed", "resolved_by": []}
    return {"class": "transport" if tier1_class == "transport" else "unresolved", "resolved_by": []}


def compute_gap_lp_tests(model, blocked_rows, currency):
    """Memoized per model and currency list; see _compute_gap_lp_tests."""
    return remember(model, ("gap_lp_tests", tuple(sorted(currency))),
                    lambda: _compute_gap_lp_tests(model, blocked_rows, currency), cache_if=not_error)


def _compute_gap_lp_tests(model, blocked_rows, currency):
    tier1 = {r["id"]: r["class"] for r in blocked_rows}
    candidates = [rid for rid, cls in tier1.items() if cls not in NOT_TESTED and not cls.startswith("dead_end")]
    if not candidates:
        return {"updates": {}, "tested": 0}

    def run_tests():
        blocked_after = {t: _still_blocked(model, candidates, (t,), currency) for t in TESTS}
        unblocked = {t: set(candidates) - blocked_after[t] for t in TESTS}
        left = [rid for rid in candidates if not any(rid in unblocked[t] for t in TESTS)]
        unblocked["all"] = set(left) - _still_blocked(model, left, TESTS, currency) if left else set()
        return unblocked

    try:
        unblocked_by = run_with_exact_solver(model, run_tests)
    except Exception as exc:
        return {"error": f"Could not run the LP tests: {exc}"}

    updates = {rid: {**_classify(unblocked_by, rid, tier1[rid]), "basis": "LP"} for rid in candidates}
    return {"updates": updates, "tested": len(candidates)}
