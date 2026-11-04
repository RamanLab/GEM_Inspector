"""Numerical-robustness helper shared by every repeated-solve diagnostic
(minimal medium, blocked reactions, FROG's F/R/G) -- see run_with_exact_solver.
"""


def _current_solver(model):
    try:
        return model.solver.interface.__name__.split(".")[-1].split("_interface")[0]
    except Exception:
        return None


def _with_solver(model, name, fn):
    """Run fn() with the model on solver `name`, then restore the original
    (even if fn raises). Runs as-is when `name` is unavailable."""
    original = _current_solver(model)
    switched = False
    if original is not None and original != name:
        try:
            model.solver = name
            switched = True
        except Exception:
            pass
    try:
        return fn()
    finally:
        if switched:
            try:
                model.solver = original
            except Exception:
                pass


def run_with_exact_solver(model, fn):
    """Run fn() on GLPK's exact-arithmetic interface when the model uses
    plain GLPK, otherwise unchanged.

    Why: on badly scaled genome-scale LPs (e.g. exchanges opened to +-1000)
    some GLPK builds (seen on Windows) abort inside glp_free, taking the whole
    Python process down, which no try/except can catch. glpk_exact skips the
    floating-point scaling and avoids this, at some cost in speed. Gurobi,
    CPLEX and HiGHS do not have this problem, so they are left alone.
    """
    if _current_solver(model) != "glpk":
        return fn()
    return _with_solver(model, "glpk_exact", fn)


def run_with_milp_solver(model, fn):
    """Run fn() on a solver that can handle integer variables (the chosen
    one if it can, else the best available)."""
    from core.solver_config import milp_solver_name
    return _with_solver(model, milp_solver_name(), fn)


# A target equal to the model's own optimum sits exactly on the solver's
# feasibility tolerance, so a 100% cutoff can come back "infeasible" through
# round-off alone. Asking for this fraction less is indistinguishable
# biologically and removes that failure.
GROWTH_TOLERANCE = 1e-6


def solve_minimal_medium(model, target_growth, minimize_components=False):
    """cobra.medium.minimal_medium with the robustness fixes in one place.

    - target_growth is relaxed by GROWTH_TOLERANCE (see above).
    - The LP (minimize total flux) runs on the exact GLPK solver; the MILP
      (minimize_components=True) runs on a MILP-capable solver, because
      glpk_exact (and HiGHS via scipy) have no integer variables.
    Returns cobra's Series, or None when infeasible.
    """
    from cobra.medium import minimal_medium

    def solve():
        return minimal_medium(model, target_growth * (1 - GROWTH_TOLERANCE),
                              minimize_components=minimize_components, open_exchanges=True)

    return run_with_milp_solver(model, solve) if minimize_components else run_with_exact_solver(model, solve)
