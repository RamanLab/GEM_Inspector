"""MEMOTE job manager.

One job per cached model. A job runs overview/memote_worker.py in a child
process (crash isolation, cancellation), polls its progress file, retries
once with the exact-arithmetic GLPK solver if the worker dies, and keeps the
result in memory until the model expires.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from core.shared import BUSY_CHECKS, EXPIRY_HOOKS, ORIGINAL_FILES, touch_model_cache

PROJECT_ROOT = Path(__file__).resolve().parent.parent

JOBS = {}  # model_id -> job dict
_LOCK = threading.Lock()


def memote_available():
    """(True, version) or (False, plain-language explanation).

    The explanation names the exact Python interpreter the app is running
    under, because the usual cause is memote being installed into a
    different Python (e.g. the global one) than the app's own .venv."""
    try:
        import memote  # noqa: F401
        return True, getattr(memote, "__version__", None)
    except Exception as exc:  # ImportError or a broken install
        return False, (
            f"MEMOTE could not be imported by the Python that runs this app ({type(exc).__name__}: {exc}). "
            f"Install it into that same Python with:  \"{sys.executable}\" -m pip install memote  "
            "then click Run MEMOTE again (no restart needed)."
        )


def _read_json(path):
    import json
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _tail(text, n=1500):
    text = (text or "").strip()
    return text[-n:]


def _run_worker(job, solver_mode):
    """Run one worker process; returns (returncode, stderr_tail)."""
    out_dir = job["dir"]
    progress = os.path.join(out_dir, "progress.json")
    if os.path.exists(progress):
        os.remove(progress)
    env = dict(os.environ)
    env["MEMOTE_PROGRESS_FILE"] = progress
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    err_path = os.path.join(out_dir, "worker.log")
    with open(err_path, "w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            [sys.executable, "-m", "overview.memote_worker", str(job["model_path"]), out_dir, solver_mode],
            cwd=str(PROJECT_ROOT), env=env, stdout=err, stderr=subprocess.STDOUT,
        )
    job["proc"] = proc
    while proc.poll() is None:
        data = _read_json(progress)
        if data:
            job["progress"] = data
        touch_model_cache(job["model_id"])
        time.sleep(0.5)
    data = _read_json(progress)
    if data:
        job["progress"] = data
    try:
        log = open(err_path, encoding="utf-8", errors="replace").read()
    except OSError:
        log = ""
    return proc.returncode, _tail(log)


def _job_thread(job):
    try:
        job["status"] = "running"
        code, log = _run_worker(job, "default")
        if job.get("cancelled"):
            job["status"] = "cancelled"
            return
        if code != 0:
            job["retried"] = True
            job["progress"] = {"stage": "retrying", "done": 0, "total": 0, "current": ""}
            code, log = _run_worker(job, "glpk_exact")
            if job.get("cancelled"):
                job["status"] = "cancelled"
                return
        if code != 0:
            job["status"] = "error"
            job["error"] = "MEMOTE did not finish." + (" Details:\n" + log if log else "")
            return
        import json
        with open(os.path.join(job["dir"], "result.json"), encoding="utf-8") as fh:
            job["result"] = json.load(fh)
        job["status"] = "done"
        job["finished"] = time.time()
    except Exception as exc:
        job["status"] = "error"
        job["error"] = str(exc)


def start_job(model_id):
    """Start (or return the running/finished) MEMOTE job for this model."""
    ok, info = memote_available()
    if not ok:
        return None, info
    path = ORIGINAL_FILES.get(model_id)
    if path is None or not Path(path).exists():
        return None, "The uploaded model file is no longer available. Please re-analyze the model."
    with _LOCK:
        job = JOBS.get(model_id)
        if job and job["status"] in ("queued", "running", "done"):
            return job, None
        job = {
            "model_id": model_id, "status": "queued", "started": time.time(),
            "dir": tempfile.mkdtemp(prefix="gem_inspector_memote_"),
            "model_path": str(path), "progress": {"stage": "loading", "done": 0, "total": 0, "current": ""},
            "result": None, "error": None, "retried": False, "cancelled": False, "proc": None,
        }
        JOBS[model_id] = job
    threading.Thread(target=_job_thread, args=(job,), daemon=True).start()
    return job, None


def cancel_job(model_id):
    job = JOBS.get(model_id)
    if not job or job["status"] not in ("queued", "running"):
        return False
    job["cancelled"] = True
    proc = job.get("proc")
    if proc and proc.poll() is None:
        proc.terminate()
    return True


def job_state(model_id):
    job = JOBS.get(model_id)
    if not job:
        return {"status": "none"}
    prog = job["progress"] or {}
    total = prog.get("total") or 0
    done = prog.get("done") or 0
    out = {
        "status": job["status"],
        "stage": prog.get("stage"),
        "done": done, "total": total,
        "percent": round(100.0 * done / total) if total else 0,
        "current": prog.get("current", ""),
        "elapsed": round(time.time() - job["started"]),
        "retried": job["retried"],
        "error": job["error"],
    }
    if job["status"] == "done":
        out["result"] = job["result"]
    return out


def report_path(model_id):
    job = JOBS.get(model_id)
    if job and job["status"] == "done":
        p = Path(job["dir"]) / "report.html"
        if p.exists():
            return p
    return None


def _is_running(model_id):
    job = JOBS.get(model_id)
    return bool(job and job["status"] in ("queued", "running"))


def _forget(model_id):
    cancel_job(model_id)
    job = JOBS.pop(model_id, None)
    if job:
        shutil.rmtree(job["dir"], ignore_errors=True)


BUSY_CHECKS.append(_is_running)
EXPIRY_HOOKS.append(_forget)
