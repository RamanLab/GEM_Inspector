"""Dead-end metabolites by GapFind (Kumar, Suthers & Maranas 2007), the
algorithm behind COBRA Toolbox gapFind.m (see docs/REFERENCES.md).

GapFind is a MILP. Every flux v_j stays inside its bounds, every metabolite i
gets a binary x_i ("can be produced"), and each reaction entry that could
produce i gets a binary w_ij ("j produces i at a rate of at least eps"):

    sum_j S_ij v_j >= 0                 net production of every metabolite
    S_ij v_j >= eps   if w_ij = 1       (positive entries of irreversible
    S_ij v_j <= M w_ij                   reactions; every entry of reversible
    sum_j w_ij >= x_i                    ones; reversible ones also get
    maximise sum_i x_i                   S_ij v_j >= eps - M when w_ij = 0)

A metabolite left with x_i = 0 cannot be produced (no-production, NP). The same
MILP on -S finds the metabolites that cannot be consumed (no-consumption, NC).
Roots are the metabolites no reaction touches in the needed direction at all;
the rest are inherited from a root: downstream (NP) and upstream (NC).

As recommended for gapFind.m, exchange reactions are opened so that gaps are
those of the network itself and not of the medium. M is the number of reactions
and eps is 1e-4, as in the toolbox.

The two MILPs run in child processes (python -m diagnostics.gapfind), side by
side: a crash of the solver, seen with GLPK on some Windows builds, then fails
the request instead of killing the web server.
"""
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import scipy.sparse as sp

from core.memo import not_error, remember

EPSILON = 1e-4
OPEN = 1000.0
TIMEOUT_SECONDS = 3600

CLASS_LABELS = {
    "rnp": "Root no-production",
    "dnp": "Downstream no-production",
    "rnc": "Root no-consumption",
    "unc": "Upstream no-consumption",
}


def _unproduced(S, lb, ub):
    """Boolean mask of the metabolites that cannot be produced (the MILP)."""
    from optlang import glpk_interface as glpk

    S = S.tocoo()
    n_met, n_rxn = S.shape
    reversible = lb < 0
    big_m = float(n_rxn)  # as in gapFind.m

    v = [glpk.Variable(f"v{j}", lb=float(lb[j]), ub=float(ub[j])) for j in range(n_rxn)]
    net = [[] for _ in range(n_met)]       # S_ij v_j for each metabolite
    producers = [[] for _ in range(n_met)]  # the w_ij of each metabolite
    constraints = []
    for i, j, a in zip(S.row, S.col, S.data):
        term = a * v[j]
        net[i].append(term)
        if not reversible[j] and a < 0:
            continue
        w = glpk.Variable(f"w{i}_{j}", type="binary")
        producers[i].append(w)
        constraints.append(glpk.Constraint(term - big_m * w, ub=0))
        if reversible[j]:
            constraints.append(glpk.Constraint(term - big_m * w, lb=EPSILON - big_m))
        else:
            constraints.append(glpk.Constraint(term - EPSILON * w, lb=0))

    # A metabolite nothing can produce has no x_i: it is unproducible outright.
    x = {i: glpk.Variable(f"x{i}", type="binary") for i in range(n_met) if producers[i]}
    for i in range(n_met):
        if net[i]:
            constraints.append(glpk.Constraint(sum(net[i]), lb=0))
        if i in x:
            constraints.append(glpk.Constraint(sum(producers[i]) - x[i], lb=0))

    problem = glpk.Model(name="gapfind")
    problem.add(v)
    problem.add(list(x.values()))
    problem.add(constraints)
    problem.objective = glpk.Objective(sum(x.values()), direction="max")
    status = problem.optimize()
    if status != "optimal":
        raise RuntimeError(f"GapFind MILP ended with status '{status}'")

    unproduced = np.ones(n_met, dtype=bool)
    for i, var in x.items():
        unproduced[i] = var.primal < 0.5
    return unproduced


def _has_neighbour(S, lb, ub):
    """Mask of metabolites some reaction can produce, ignoring everything else
    (used for the roots: no such reaction means a root no-production)."""
    S = S.tocsr()
    forward, backward = (ub > 0).astype(float), (lb < 0).astype(float)
    pos, neg = (S > 0).astype(float), (S < 0).astype(float)
    return np.asarray((pos @ forward + neg @ backward) > 0).ravel()


def _roots(S, lb, ub, no_production, no_consumption):
    """{"rnp", "dnp", "rnc", "unc"} masks: the roots are the unproducible (unconsumable)
    metabolites that no reaction could produce (consume) at all."""
    can_produce, can_consume = _has_neighbour(S, lb, ub), _has_neighbour(-S, lb, ub)
    return {
        "rnp": no_production & ~can_produce, "dnp": no_production & can_produce,
        "rnc": no_consumption & ~can_consume, "unc": no_consumption & can_consume,
    }


def _network_arrays(model):
    """S (sparse) and the bounds, with every exchange reaction opened."""
    met_index = {m.id: i for i, m in enumerate(model.metabolites)}
    rows, cols, vals = [], [], []
    for j, rxn in enumerate(model.reactions):
        for met, coeff in rxn.metabolites.items():
            rows.append(met_index[met.id])
            cols.append(j)
            vals.append(coeff)
    S = sp.csr_matrix((vals, (rows, cols)), shape=(len(model.metabolites), len(model.reactions)))
    lb = np.array([r.lower_bound for r in model.reactions], dtype=float)
    ub = np.array([r.upper_bound for r in model.reactions], dtype=float)
    exchange = np.array([r.id in {e.id for e in model.exchanges} for r in model.reactions])
    lb[exchange], ub[exchange] = np.minimum(lb[exchange], -OPEN), np.maximum(ub[exchange], OPEN)
    return S, lb, ub


def compute_dead_ends(model):
    """Memoized per model. {"met_ids": [...], "classes": {metabolite id: [class keys]}},
    or {"error": ...}. Independent of every other analysis."""
    return remember(model, "gapfind", lambda: _compute_dead_ends(model), cache_if=not_error)


def _compute_dead_ends(model):
    if not model.metabolites or not model.reactions:
        return {"classes": {}}
    S, lb, ub = _network_arrays(model)
    with tempfile.TemporaryDirectory() as tmp:
        job = Path(tmp, "job.pkl")
        job.write_bytes(pickle.dumps((S, lb, ub)))
        # The two MILPs (production on S, consumption on -S) are independent: run them side by side.
        children = [(sign, Path(tmp, f"result{sign}.pkl")) for sign in ("+", "-")]
        procs = [subprocess.Popen(
            [sys.executable, "-m", "diagnostics.gapfind", str(job), str(out), sign],
            cwd=Path(__file__).resolve().parent.parent, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
        ) for sign, out in children]
        masks = []
        for proc, (_, out) in zip(procs, children):
            try:
                _, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                for p in procs:
                    p.kill()
                return {"error": "GapFind did not finish in time."}
            if proc.returncode != 0 or not out.exists():
                return {"error": "GapFind stopped: " + (stderr.strip().splitlines() or ["the solver crashed"])[-1]}
            masks.append(pickle.loads(out.read_bytes()))
    found = _roots(S, lb, ub, *masks)

    classes = {}
    for i, met in enumerate(model.metabolites):
        keys = [key for key in CLASS_LABELS if found[key][i]]
        if keys:
            classes[met.id] = keys
    return {"classes": classes}


if __name__ == "__main__":
    job_path, out_path, sign = sys.argv[1:4]
    S, lb, ub = pickle.loads(Path(job_path).read_bytes())
    Path(out_path).write_bytes(pickle.dumps(_unproduced(S if sign == "+" else -S, lb, ub)))
