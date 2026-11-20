"""Which LP/MILP solver and how many cores the app uses -- one place.

Settings come from the environment so that child processes (GapFind, MEMOTE)
and gunicorn workers see the same choice:

  GEM_SOLVER      auto (default) | gurobi | cplex | glpk | scipy
                  (scipy = HiGHS: LP only, so MILP steps use another solver)
  GEM_THREADS     threads per solver call            (default: up to 4)
  GEM_PROCESSES   worker processes for FVA / gene deletions (default: 1 on
                  Windows, where spawning is slow; up to 4 elsewhere)

`python app.py --solver gurobi --threads 8` sets them; see app.py.
"""
import os

# Best first. Only these can solve integer programs (GapFind, minimal components).
PREFERENCE = ["gurobi", "cplex", "glpk", "scipy"]
MILP_SOLVERS = ["gurobi", "cplex", "glpk"]


def _cores():
    return os.cpu_count() or 1


def _int_env(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def threads():
    return _int_env("GEM_THREADS", min(4, _cores()))


def processes():
    return _int_env("GEM_PROCESSES", 1 if os.name == "nt" else min(4, _cores()))


FAILURES = {}   # solver name -> why it was rejected, shown at startup


def _works(name):
    """True when the solver imports AND solves a tiny problem (this also
    catches a missing or expired licence, which only fails at first use)."""
    try:
        from cobra.util.solver import solvers
        if name not in solvers:
            if name == "gurobi":
                FAILURES[name] = "COBRApy/optlang could not load it (is gurobipy installed in this same Python environment?)"
            return False
        iface = solvers[name]
        # Gurobi and CPLEX free (size-limited) licences solve small problems but refuse genome-scale
        # ones, so those two are tested with a problem larger than their limits (2000 / 1000).
        size = 2100 if name in ("gurobi", "cplex") else 1
        problem = iface.Model()
        xs = [iface.Variable(f"x{i}", lb=0, ub=1) for i in range(size)]
        problem.add(xs)
        problem.add([iface.Constraint(xs[i] + xs[(i + 1) % size], ub=1.5, name=f"c{i}") for i in range(size)] if size > 1 else [])
        problem.objective = iface.Objective(sum(xs), direction="max")
        status = problem.optimize()
        if status != "optimal":
            FAILURES[name] = f"a test problem returned status '{status}'"
        return status == "optimal"
    except Exception as exc:
        FAILURES[name] = f"{type(exc).__name__}: {exc}" + (
            " (a free, size-limited licence cannot solve genome-scale models; use a full or academic licence)"
            if name in ("gurobi", "cplex") else "")
        return False


_available = None


def available_solvers():
    """Usable solvers, best first (checked once)."""
    global _available
    if _available is None:
        _available = [s for s in PREFERENCE if _works(s)]
    return _available


def solver_name():
    """The solver for LP work: GEM_SOLVER if usable, else the best available."""
    wanted = os.environ.get("GEM_SOLVER", "auto").lower()
    usable = available_solvers()
    return wanted if wanted in usable else (usable[0] if usable else "glpk")


def milp_solver_name():
    """The solver for integer programs: the chosen one when it supports them."""
    name = solver_name()
    if name in MILP_SOLVERS:
        return name
    return next((s for s in MILP_SOLVERS if s in available_solvers()), "glpk")


def milp_interface():
    """optlang module (gurobi_interface, glpk_interface, ...) for MILPs."""
    from cobra.util.solver import solvers
    return solvers[milp_solver_name()]


def set_threads(problem):
    """Apply the thread count to an optlang model (Gurobi / CPLEX only)."""
    n = threads()
    try:
        if milp_solver_name() == "gurobi":
            problem.problem.setParam("Threads", n)
        elif milp_solver_name() == "cplex":
            problem.problem.parameters.threads.set(n)
    except Exception:
        pass


def apply():
    """Make newly created cobra models use the chosen solver."""
    import cobra
    cobra.Configuration().solver = solver_name()


def configure(solver=None, threads_=None, processes_=None):
    """Set the choices (None leaves one unchanged) and apply them."""
    for key, value in (("GEM_SOLVER", solver), ("GEM_THREADS", threads_), ("GEM_PROCESSES", processes_)):
        if value is not None:
            os.environ[key] = str(value)
    apply()


def describe():
    """One-line startup summary."""
    return (f"solver={solver_name()} (MILP: {milp_solver_name()}), threads={threads()}, "
            f"processes={processes()}; available: {', '.join(available_solvers()) or 'none'}"
            + "".join(f"\n  {n} not used: {FAILURES[n]}" for n in ("gurobi", "cplex") if n in FAILURES and n not in available_solvers()))


def prompt_choice():
    """Ask which solver to use when several are available (terminal only)."""
    usable = available_solvers()
    if len(usable) < 2:
        return None
    print("Solvers found:", ", ".join(usable))
    for name in PREFERENCE:
        if name in FAILURES and name not in usable and name in ("gurobi", "cplex"):
            print(f"  {name} was not used: {FAILURES[name]}")
    answer = input(f"Solver to use [auto = {usable[0]}; or {'/'.join(usable)}]: ").strip().lower()
    return answer if answer in usable else None
