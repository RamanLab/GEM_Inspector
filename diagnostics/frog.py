"""FROG report (on-request, its own tab): the reproducibility-check
standard used across the SBML/COMBINE community for genome-scale metabolic
models -- F(lux variability analysis), R(eaction deletions), O(bjective
value), and G(ene deletions), all run against the model's current bounds
(whatever diet was applied at upload). Any other FBA tool analyzing the
same model + medium can be cross-checked against these same four results,
which is the whole point of the standard.

F/R/G can each be individually skipped -- for a large genome-scale model
they're the slow parts (one LP solve per reaction for F's minimize +
maximize, one per reaction for R, one per gene for G), whereas O is a
single, near-instant solve. FVA's growth cutoff (fraction_of_optimum) is
configurable, same as the Minimal Medium tab's cutoff.

All the actual LP solving reuses cobra's own bulk analysis functions,
forced to processes=1 (Windows "spawn" multiprocessing is fragile/slow to
invoke from inside a live Flask request) and wrapped in
run_with_exact_solver -- this class of repeated-solve computation is
exactly what has been observed to crash GLPK's default solver on some
Windows builds (see solver_utils.run_with_exact_solver).
"""
import json

from cobra.flux_analysis import flux_variability_analysis, single_gene_deletion, single_reaction_deletion

from core.memo import remember
from core.shared import find_biomass_reaction, safe_float, wt_solution as solve_wt
from diagnostics.solver_utils import run_with_exact_solver


def compute_frog_objective(model):
    """The 'O' in FROG: a single FBA optimum under the model's current
    bounds (whatever diet was applied at upload)."""
    solution = solve_wt(model)
    return {
        "objective_reaction": find_biomass_reaction(model),
        "status": str(solution.status),
        "value": safe_float(solution.objective_value),
    }


def compute_frog_fva(model, fraction_of_optimum=1.0):
    """Memoized per model and fraction; see _compute_frog_fva."""
    return remember(model, ("frog_fva", str(fraction_of_optimum)), lambda: _compute_frog_fva(model, fraction_of_optimum))


def _compute_frog_fva(model, fraction_of_optimum=1.0):
    """The 'F' in FROG: flux variability analysis on every reaction in the
    model at the given fraction_of_optimum (1.0 = fixed at the model's own
    maximum growth; lower values allow more flux variability)."""
    try:
        fraction_of_optimum = float(fraction_of_optimum)
    except (TypeError, ValueError):
        fraction_of_optimum = 1.0
    fraction_of_optimum = max(0.0, min(1.0, fraction_of_optimum))

    df = run_with_exact_solver(
        model,
        lambda: flux_variability_analysis(
            model, reaction_list=None, fraction_of_optimum=fraction_of_optimum, processes=1,
        ),
    )
    rows = [
        {"id": rxn_id, "minimum": safe_float(row["minimum"]), "maximum": safe_float(row["maximum"])}
        for rxn_id, row in df.iterrows()
    ]
    rows.sort(key=lambda r: r["id"])
    return {"fraction_of_optimum": fraction_of_optimum, "reactions": rows}


def compute_frog_reaction_deletions(model):
    return remember(model, "frog_reaction_deletions", lambda: _compute_frog_reaction_deletions(model))


def _compute_frog_reaction_deletions(model):
    """The 'R' in FROG: single-reaction-deletion objective value for every
    reaction in the model (not just exchanges -- unlike the Exchange
    Essentiality tab, this is every reaction, per the FROG standard)."""
    if not model.reactions:
        return {"reactions": []}
    df = run_with_exact_solver(model, lambda: single_reaction_deletion(model, processes=1))
    rows = []
    for _, row in df.iterrows():
        ids = row["ids"]
        rxn_id = next(iter(ids)) if ids else None
        rows.append({"id": rxn_id, "growth": safe_float(row["growth"]), "status": str(row["status"])})
    rows.sort(key=lambda r: (r["id"] is None, r["id"]))
    return {"reactions": rows}


def compute_frog_gene_deletions(model):
    return remember(model, "frog_gene_deletions", lambda: _compute_frog_gene_deletions(model))


def _compute_frog_gene_deletions(model):
    """The 'G' in FROG: single-gene-deletion objective value for every gene
    in the model."""
    if not model.genes:
        return {"genes": []}
    df = run_with_exact_solver(model, lambda: single_gene_deletion(model, processes=1))
    rows = []
    for _, row in df.iterrows():
        ids = row["ids"]
        gene_id = next(iter(ids)) if ids else None
        rows.append({"id": gene_id, "growth": safe_float(row["growth"]), "status": str(row["status"])})
    rows.sort(key=lambda r: (r["id"] is None, r["id"]))
    return {"genes": rows}


def stream_frog_report(model, fva_fraction, include_fva, include_reaction_deletions, include_gene_deletions):
    """Generator that yields FROG-report progress over SSE, one stage at a
    time. O is computed first (near-instant, and needed regardless), then
    F/R/G in that order, each skippable by the caller. Yields a final
    "complete" event carrying every computed piece, or an "error" event
    (and stops) if any stage raises."""
    yield "data: " + json.dumps({"type": "info", "message": "Computing objective value (O)…"}) + "\n\n"
    try:
        objective = compute_frog_objective(model)
    except Exception as exc:
        yield "data: " + json.dumps({"type": "error", "message": f"Objective computation failed: {exc}"}) + "\n\n"
        return

    fva_result = None
    if include_fva:
        yield "data: " + json.dumps({
            "type": "info",
            "message": f"Running flux variability analysis (F) on {len(model.reactions)} reaction(s)…",
        }) + "\n\n"
        try:
            fva_result = compute_frog_fva(model, fva_fraction)
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "message": f"FVA failed: {exc}"}) + "\n\n"
            return

    reaction_deletions = None
    if include_reaction_deletions:
        yield "data: " + json.dumps({
            "type": "info",
            "message": f"Running single-reaction deletions (R) on {len(model.reactions)} reaction(s)…",
        }) + "\n\n"
        try:
            reaction_deletions = compute_frog_reaction_deletions(model)
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "message": f"Reaction deletions failed: {exc}"}) + "\n\n"
            return

    gene_deletions = None
    if include_gene_deletions:
        yield "data: " + json.dumps({
            "type": "info",
            "message": f"Running single-gene deletions (G) on {len(model.genes)} gene(s)…",
        }) + "\n\n"
        try:
            gene_deletions = compute_frog_gene_deletions(model)
        except Exception as exc:
            yield "data: " + json.dumps({"type": "error", "message": f"Gene deletions failed: {exc}"}) + "\n\n"
            return

    note = (
        "FROG: a model-reproducibility check standard used in the SBML/COMBINE community -- Flux variability "
        "analysis, Reaction deletions, Objective value, Gene deletions -- computed against this model's current "
        "bounds, so it can be cross-checked against any other FBA tool analyzing the same model and medium."
    )
    yield "data: " + json.dumps({
        "type": "complete",
        "objective": objective,
        "fva": fva_result,
        "reaction_deletions": reaction_deletions,
        "gene_deletions": gene_deletions,
        "note": note,
    }) + "\n\n"
