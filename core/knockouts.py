"""Reaction knockouts, computed once per model and reaction.

Exchange essentiality, the demand/sink audit and the FROG reaction deletions
all need "growth with this reaction knocked out". They share this cache, so
whichever runs first saves the others the solves, and none needs another to
have run before it.
"""
import math

from core.memo import recall, store_value
from core.shared import safe_float


def reaction_knockout(model, rxn):
    """(objective value or None, status) with the reaction knocked out; the
    model's own bounds are restored afterwards."""
    key = ("reaction_knockout", rxn.id)
    cached = recall(model, key)
    if cached is not None:
        return cached

    original = rxn.bounds
    try:
        rxn.bounds = (0, 0)
        # slim_optimize() skips building a full Solution (fluxes, reduced
        # costs, shadow prices), which is all a knockout screen can do without.
        value = model.slim_optimize(error_value=float("nan"))
        result = (None, "infeasible") if math.isnan(value) else (safe_float(value), "optimal")
    except Exception as exc:
        return None, f"error: {exc}"
    finally:
        rxn.bounds = original
    store_value(model, key, result)
    return result
