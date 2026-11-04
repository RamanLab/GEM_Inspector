"""Dead-end metabolites by the GapFind definition (Kumar, Dasika & Maranas 2007;
COBRA Toolbox gapFind.m -- see docs/REFERENCES.md).

A metabolite i is *not produced* (NP) when no flux distribution within the
bounds, in which no metabolite is consumed faster than it is made
(sum_j S_ij v_j >= 0 for every metabolite), has a reaction producing it at a
rate of at least eps. Solving the same problem on -S finds the metabolites that
are *not consumed* (NC). Roots are the metabolites no reaction touches in the
needed direction at all; the rest are inherited from a root: downstream (NP)
and upstream (NC).

GapFind states this as one MILP (a binary per metabolite and per producing
reaction entry, with a big M). That MILP ties eps to every reaction entry, so
its answer depends on the scale of the flux and of the stoichiometric
coefficients, and it reported about half of the no-consumption metabolites of
iJO1366 although the flux distributions that consume them exist (verified, see
docs/TODO.md). The conditions are linear and homogeneous, so the same
definition is solved here exactly by linear programs, in two phases:

  1. one LP certifies many metabolites at once (maximise sum_i min(P_i, eps),
     P_i = production through reactions that run in one direction only);
  2. each metabolite left over is tested on its own: for every reaction entry
     that could produce it, maximise S_ij v_j and stop at the first >= eps.

As recommended for gapFind.m, exchange reactions are opened so that gaps are
those of the network itself and not of the medium.

The two problems (production on S, consumption on -S) run in child processes
(python -m diagnostics.gapfind), side by side, so a crash of a native solver
library fails the request instead of killing the web server.
"""
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog

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


def _solve(c, A_ub, lb, ub):
    """min c.x s.t. A_ub x <= 0, lb <= x <= ub (HiGHS). Raises when infeasible."""
    result = linprog(c, A_ub=A_ub, b_ub=np.zeros(A_ub.shape[0]), bounds=np.column_stack([lb, ub]), method="highs")
    if result.status != 0:
        raise RuntimeError(f"GapFind LP ended with status {result.status}: {result.message}")
    return result.x


def _batch_certify(S, lb, ub, candidates):
    """Metabolites among `candidates` that one flux vector can produce through
    reactions running in one direction only (production = S_ij v_j >= 0 there)."""
    n_met, n_rxn = S.shape
    forward, backward = lb >= 0, ub <= 0
    coo = S.tocoo()
    keep = (forward[coo.col] & (coo.data > 0)) | (backward[coo.col] & (coo.data < 0))
    P = sp.csr_matrix((coo.data[keep], (coo.row[keep], coo.col[keep])), shape=S.shape)[candidates]
    k = len(candidates)
    # variables: v (n_rxn), z (k); z_i <= P_i v and z_i <= eps
    A = sp.vstack([sp.hstack([-S, sp.csr_matrix((n_met, k))]),
                   sp.hstack([-P, sp.identity(k)])]).tocsr()
    c = np.concatenate([np.zeros(n_rxn), -np.ones(k)])
    x = _solve(c, A, np.concatenate([lb, np.zeros(k)]), np.concatenate([ub, np.full(k, EPSILON)]))
    return x[n_rxn:] >= 0.999 * EPSILON


def _entry_produces(S, A_ub, lb, ub, i):
    """True when some reaction entry of metabolite i can produce it at >= eps."""
    row = S.getrow(i)
    for j, a in zip(row.indices, row.data):
        if (a > 0 and ub[j] <= 0) or (a < 0 and lb[j] >= 0):
            continue
        c = np.zeros(S.shape[1])
        c[j] = -a
        if -c @ _solve(c, A_ub, lb, ub) >= EPSILON:
            return True
    return False


def _unproduced(S, lb, ub):
    """Boolean mask of the metabolites that cannot be produced."""
    S = S.tocsr()
    produced = np.zeros(S.shape[0], dtype=bool)
    todo = np.flatnonzero(np.diff(S.indptr) > 0)
    while len(todo):
        certified = _batch_certify(S, lb, ub, todo)
        if not certified.any():
            break
        produced[todo[certified]] = True
        todo = todo[~certified]
    A_ub = -S
    for i in todo:
        produced[i] = _entry_produces(S, A_ub, lb, ub, i)
    return ~produced


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
    exchange_ids = {e.id for e in model.exchanges}
    exchange = np.array([r.id in exchange_ids for r in model.reactions])
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
        # The two LP problems (production on S, consumption on -S) are independent: run them side by side.
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
