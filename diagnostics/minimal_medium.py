"""On-request Minimal Medium tab.

Separate from the diet applied at upload time (diet.py's mode == "minimal",
which permanently constrains the analyzed model to that computed medium):
this is a read-only, repeatable report the user can (re)run for any growth
cutoff after the model is loaded, without ever changing the cached model's
bounds. Shares the same underlying cobra.medium.minimal_medium call and the
same "target is the model's own growth, not an artificially opened one" fix
as diet.py.
"""
from cobra.medium import minimal_medium

from annotation.naming import clean_metabolite_display_name
from annotation.namespace_mapping import detect_metabolite_namespace_and_map, detect_reaction_namespace_and_map
from core.memo import not_error, remember
from core.shared import safe_float
from diagnostics.solver_utils import run_with_exact_solver


def compute_minimal_medium_report(model, growth_cutoff_fraction=1.0, minimize_components=False):
    """Memoized per model and settings; see _compute_minimal_medium_report."""
    key = ("minimal_medium", str(growth_cutoff_fraction), bool(minimize_components))
    return remember(model, key,
                    lambda: _compute_minimal_medium_report(model, growth_cutoff_fraction, minimize_components),
                    cache_if=not_error)


def _compute_minimal_medium_report(model, growth_cutoff_fraction=1.0, minimize_components=False):
    """Compute the minimal medium needed to sustain growth_cutoff_fraction of
    the model's own maximum growth rate (under its own original bounds).
    cobra's minimal_medium() already manages open_exchanges internally and
    leaves the model's own bounds completely unchanged when it returns, so
    this never permanently changes the cached model -- and deliberately does
    NOT wrap its own extra `with model:` around that call, since nesting a
    redundant context manager around minimal_medium's own reentrant
    optimize() calls can corrupt the GLPK solver's internal memory and crash
    the whole process. growth_cutoff_fraction is clamped to (0, 1] -- 1.0
    means the model's full own maximum growth, 0.5 means half of it, etc.

    Returns a dict with wt_growth, growth_cutoff_fraction, target_growth,
    components (a list of {exchange_id, exchange_name, metabolite_id,
    metabolite_name, uptake_flux}, sorted by exchange id), and a note; or an
    "error" key (alongside wt_growth, when known) on failure.
    """
    wt_growth = safe_float(model.slim_optimize(error_value=0.0)) or 0.0
    if wt_growth <= 1e-9:
        return {
            "error": "Model cannot grow under its own original bounds; a minimal medium is undefined.",
            "wt_growth": wt_growth,
        }

    _, _, _, met_to_mnx = detect_metabolite_namespace_and_map(model)
    _, _, _, rxn_to_mnx = detect_reaction_namespace_and_map(model)

    try:
        growth_cutoff_fraction = float(growth_cutoff_fraction)
    except (TypeError, ValueError):
        growth_cutoff_fraction = 1.0
    growth_cutoff_fraction = max(1e-6, min(1.0, growth_cutoff_fraction))
    target_growth = wt_growth * growth_cutoff_fraction

    try:
        medium = run_with_exact_solver(
            model,
            lambda: minimal_medium(model, target_growth, minimize_components=minimize_components, open_exchanges=True),
        )
    except Exception as exc:
        return {"error": f"Could not compute a minimal medium: {exc}", "wt_growth": wt_growth}
    if medium is None:
        return {
            "error": f"Minimal-medium computation was infeasible at a {growth_cutoff_fraction * 100:.4g}% growth cutoff.",
            "wt_growth": wt_growth,
        }

    components = []
    for rxn_id, flux in medium.items():
        if flux <= 0:
            continue
        rxn = model.reactions.get_by_id(rxn_id)
        met = next(iter(rxn.metabolites.keys()), None)
        components.append({
            "exchange_id": rxn_id,
            "exchange_metanetx_id": rxn_to_mnx.get(rxn_id),
            "exchange_name": rxn.name,
            "metabolite_id": met.id if met else None,
            "metabolite_metanetx_id": met_to_mnx.get(met.id) if met else None,
            "metabolite_name": clean_metabolite_display_name(met) if met else None,
            "uptake_flux": abs(safe_float(flux) or 0.0),
        })
    components.sort(key=lambda c: c["exchange_id"])

    return {
        "wt_growth": wt_growth,
        "growth_cutoff_fraction": growth_cutoff_fraction,
        "target_growth": target_growth,
        "components": components,
        "note": (
            f"Smallest set of {len(components)} nutrient(s) sustaining "
            f"{growth_cutoff_fraction * 100:.4g}% of the model's own maximum growth rate "
            f"({target_growth:.4g} of {wt_growth:.4g})."
        ),
    }
