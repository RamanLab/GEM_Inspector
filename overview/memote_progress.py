"""Tiny pytest plugin that reports MEMOTE's progress to a JSON file.

MEMOTE runs its ~70 tests through pytest. `memote.suite.api.test_model` does
not expose a progress callback, but pytest can load extra plugins by import
name (`-p overview.memote_progress`), so the worker passes this module that
way. The path of the progress file comes from the MEMOTE_PROGRESS_FILE
environment variable, set by the job manager (overview/memote_jobs.py).

Only the standard library is used here on purpose: this module is imported
inside the worker process, before any of the app's own code is needed.
"""
import json
import os

_PATH = os.environ.get("MEMOTE_PROGRESS_FILE")
_state = {"stage": "testing", "done": 0, "total": 0, "current": ""}


def _write():
    if not _PATH:
        return
    tmp = _PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_state, fh)
        os.replace(tmp, _PATH)
    except OSError:
        # The reader may have the file open for a moment (Windows); the next
        # update will go through, so skipping one is harmless.
        pass


def pytest_collection_finish(session):
    _state["total"] = len(session.items)
    _write()


def pytest_runtest_logreport(report):
    # Every test emits exactly one "teardown" report, whether it passed,
    # failed or was skipped, so counting those gives a clean progress figure.
    if report.when == "teardown":
        _state["done"] += 1
        _state["current"] = report.nodeid.split("::")[-1]
        _write()
