"""Background analyses: dead ends, FVA, FROG and MEMOTE run for a model without
the user opening each tab.

Each task fills the per-model memo (core.memo), which is what the tabs, the
generated report and the tracer read, so nothing is computed twice. The work is
done on a copy of the cached model that shares that memo, so it never collides
with a request that temporarily changes the cached model's bounds.

Tasks run one after another in one thread. MEMOTE runs in its own process
(overview/memote_jobs.py): it starts at once when there are at least four cores
and after the others otherwise. Time estimates are rough: they scale the time of
one LP by the number of LPs each task needs.
"""
import os
import threading
import time

from core.memo import recall
from core.shared import BUSY_CHECKS, EXPIRY_HOOKS, MODEL_CACHE
from core.solver_config import processes
from diagnostics.frog import (compute_frog_fva, compute_frog_gene_deletions, compute_frog_objective,
                              compute_frog_reaction_deletions)
from diagnostics.gapfind import CLASS_LABELS, compute_dead_ends
from diagnostics.network_gaps import compute_blocked_report
from overview import memote_jobs

TASKS = {
    "dead_ends": "Dead-end metabolites",
    "fva": "FVA (blocked reactions and flux ranges)",
    "frog": "FROG report (FVA at optimum, deletions)",
    "memote": "MEMOTE",
}
ORDER = ["dead_ends", "fva", "frog"]  # in-process tasks, in the order they run
JOBS = {}  # model_id -> {"tasks": {name: state}, "queue": [...], "thread": Thread|None, "stop": bool}
_LOCK = threading.Lock()


def _lp_seconds(model):
    """Typical time of one LP on this model (best of three warm solves)."""
    model.slim_optimize()
    best = None
    for _ in range(3):
        t = time.perf_counter()
        model.slim_optimize()
        best = min(best or 1e9, time.perf_counter() - t)
    return best


def estimates(model):
    """Rough seconds per task."""
    t, n, p = _lp_seconds(model), len(model.reactions), max(1, processes())
    return {
        "dead_ends": max(2.0, 4 * len(model.metabolites) * t / 20),
        "fva": 2 * n * t / p + 1,
        "frog": (2 * n * t / p) + n * t + len(model.genes) * t / p + 1,
        "memote": 30 + n * 0.05 + 60 * (n / 3000),
    }


def _run_task(name, model):
    if name == "dead_ends":
        result = compute_dead_ends(model)
    elif name == "fva":
        compute_frog_fva(model, 0.0)
        result = compute_blocked_report(model)
    else:  # frog
        compute_frog_objective(model)
        compute_frog_fva(model, 1.0)
        compute_frog_reaction_deletions(model)
        result = compute_frog_gene_deletions(model)
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(result["error"])


def _worker(model_id, job):
    entry = MODEL_CACHE.get(model_id)
    if entry is None:
        return
    entry[0].__dict__.setdefault("_gi_memo", {})  # the copy shares this dict, so its results land on the cached model
    work = entry[0].copy()
    job["estimates"] = estimates(work)
    while True:
        with _LOCK:
            queue = [t for t in ORDER if t in job["queue"]]
            if not queue or job["stop"]:
                job["queue"] = []
                job["thread"] = None
                return
            name = queue[0]
            job["queue"].remove(name)
        state = job["tasks"][name]
        state.update(status="running", started=time.time())
        try:
            _run_task(name, work)
            state["status"] = "done"
        except Exception as exc:
            state.update(status="error", error=str(exc))
        state["finished"] = time.time()


def _start_memote(model_id, state):
    job, err = memote_jobs.start_job(model_id)
    if err:
        state.update(status="error", error=err, finished=time.time())
    else:
        state.update(status="running", started=time.time())


def start(model_id, names):
    """Queue the named tasks that have not run (or are not running) yet."""
    names = [n for n in names if n in TASKS]
    with _LOCK:
        job = JOBS.setdefault(model_id, {"tasks": {}, "queue": [], "thread": None, "stop": False, "estimates": {}})
        job["stop"] = False
        for name in names:
            old = job["tasks"].get(name)
            if old and old["status"] in ("queued", "running", "done"):
                continue
            job["tasks"][name] = {"label": TASKS[name], "status": "queued", "started": None, "finished": None, "error": None}
            if name != "memote":
                job["queue"].append(name)
        if any(n in job["queue"] for n in ORDER) and job["thread"] is None:
            job["thread"] = threading.Thread(target=_worker, args=(model_id, job), daemon=True)
            job["thread"].start()
        memote_state = job["tasks"].get("memote")
        busy_elsewhere = job["thread"] is not None
    if memote_state and memote_state["status"] == "queued":
        if (os.cpu_count() or 1) >= 4 or not busy_elsewhere:
            _start_memote(model_id, memote_state)
        else:
            job["memote_after"] = True
    return state(model_id)


def stop(model_id):
    job = JOBS.get(model_id)
    if job:
        job["stop"] = True
        for name in list(job["queue"]):
            job["tasks"][name]["status"] = "stopped"
        memote_jobs.cancel_job(model_id)
        if "memote" in job["tasks"] and job["tasks"]["memote"]["status"] in ("queued", "running"):
            job["tasks"]["memote"]["status"] = "stopped"
    return state(model_id)


def state(model_id):
    job = JOBS.get(model_id)
    cores = os.cpu_count() or 1
    if not job:
        return {"tasks": {}, "cores": cores, "processes": processes(), "running": False}
    memote = job["tasks"].get("memote")
    if memote:
        if memote["status"] == "queued" and job.get("memote_after") and job["thread"] is None:
            _start_memote(model_id, memote)  # the others have finished
        if memote["status"] == "running":
            m = memote_jobs.job_state(model_id)
            if m["status"] == "done":
                memote.update(status="done", finished=time.time())
            elif m["status"] in ("error", "none"):
                memote.update(status="error", error=m.get("error") or "MEMOTE stopped", finished=time.time())
            elif m["status"] == "cancelled":
                memote.update(status="stopped", finished=time.time())
    now = time.time()
    out = {}
    for name, st in job["tasks"].items():
        end = st["finished"] or now
        out[name] = {
            "label": st["label"], "status": st["status"], "error": st["error"],
            "elapsed": round(end - st["started"], 1) if st["started"] else 0,
            "estimate": round((job["estimates"] or {}).get(name, 0)) or None,
        }
    running = any(s["status"] in ("queued", "running") for s in out.values())
    return {"tasks": out, "cores": cores, "processes": processes(), "running": running}


def estimate_for(model_id):
    """Estimates before any task has started (for the upload-time boxes)."""
    entry = MODEL_CACHE.get(model_id)
    return {k: round(v) for k, v in estimates(entry[0].copy()).items()} if entry else {}


def results(model):
    """What the tables and the tracer need, from whatever is already computed:
    FVA ranges (any growth), which reactions are blocked, and each dead-end
    metabolite's class."""
    out = {}
    fva = recall(model, ("frog_fva", 0.0))
    if fva:
        cutoff = model.tolerance
        ranges = {r["id"]: [r["minimum"], r["maximum"]] for r in fva["reactions"]}
        out["fva"] = {
            "ranges": ranges,
            "blocked": [i for i, (lo, hi) in ranges.items() if abs(lo or 0.0) < cutoff and abs(hi or 0.0) < cutoff],
        }
    gaps = recall(model, "gapfind")
    if gaps and "classes" in gaps:
        out["dead_ends"] = {m: " + ".join(CLASS_LABELS[c] for c in cls) for m, cls in gaps["classes"].items()}
    return out


BUSY_CHECKS.append(lambda mid: bool(JOBS.get(mid) and JOBS[mid]["thread"] is not None))
EXPIRY_HOOKS.append(lambda mid: JOBS.pop(mid, None))
