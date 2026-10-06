"""Numerical-robustness helper shared by every repeated-solve diagnostic
(minimal medium, blocked reactions, FROG's F/R/G) -- see run_with_exact_solver.
"""


def run_with_exact_solver(model, fn):
    """Run fn() with the model's solver temporarily switched to GLPK's
    exact-arithmetic interface ("glpk_exact"), then always switch back to
    whatever interface the model was using before -- even if fn() raises.

    Why: cobra.medium.minimal_medium's open_exchanges=True path force-opens
    every exchange reaction to (-1000, 1000), which for a genome-scale model
    with a wide range of stoichiometric coefficients can produce a very
    poorly scaled LP. The default GLPK solver runs a floating-point
    scaling/factorization step for problems like that, and on some GLPK
    builds (seen on Windows) a badly-scaled problem can trigger a fatal,
    unrecoverable crash in GLPK's own memory allocator ("glp_free: memory
    allocation error") -- a C-level abort that takes the whole Python
    process down with it, so no amount of try/except around the call can
    catch it. glpk_exact uses exact rational arithmetic and skips
    floating-point scaling entirely, avoiding that failure mode (cobra's own
    minimal_medium docs list "switching to a different solver" as the
    recommended remedy for numerical instability here). It's slower, so
    it's only used for the specific computation passed in, not globally.
    """
    try:
        original = model.solver.interface.__name__.split(".")[-1].split("_interface")[0]
    except Exception:
        original = None

    if original == "glpk_exact":
        return fn()

    switched = False
    if original is not None:
        try:
            model.solver = "glpk_exact"
            switched = True
        except Exception:
            switched = False  # glpk_exact unavailable -- fall back to running as-is

    try:
        return fn()
    finally:
        if switched:
            try:
                model.solver = original
            except Exception:
                pass
