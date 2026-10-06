"""MEMOTE worker -- runs in its own process, never inside the Flask server.

Usage (done for you by overview/memote_jobs.py):

    python -m overview.memote_worker <model_file> <out_dir> <solver_mode>

solver_mode is "default" (the model's own solver) or "glpk_exact". Two files
are written to <out_dir> on success:

    result.json   a compact summary the Overview tab renders
    report.html   MEMOTE's own full, self-contained snapshot report

Why a separate process: MEMOTE re-solves the same LP many times (flux
variability for blocked reactions, balanced cycles, ...). On some GLPK
builds -- seen on Windows -- that can abort the whole process from inside
GLPK's C code, which Python cannot catch. In a worker process the abort only
ends the worker, and the job manager can retry with the exact-arithmetic
solver. It also lets the user cancel a long run.

Progress is written by overview/memote_progress.py (loaded as a pytest
plugin) to the file named in MEMOTE_PROGRESS_FILE.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path


def _write_progress(stage, **extra):
    path = os.environ.get("MEMOTE_PROGRESS_FILE")
    if not path:
        return
    payload = {"stage": stage, "done": 0, "total": 0, "current": ""}
    payload.update(extra)
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except OSError:
        pass


# Tests that describe the model (counts, lists, matrix properties) rather
# than flag a defect. Their "metric" is non-zero by nature, so they are shown
# as information, not as problems.
INFO_TESTS = {
    "test_metabolites_presence", "test_reactions_presence", "test_genes_presence",
    "test_metabolic_coverage", "test_find_unique_metabolites", "test_find_medium_metabolites",
    "test_find_pure_metabolic_reactions", "test_find_constrained_pure_metabolic_reactions",
    "test_find_transport_reactions", "test_find_reactions_with_identical_genes",
    "test_number_independent_conservation_relations", "test_matrix_rank",
    "test_degrees_of_freedom", "test_sbml_level",
}


def _first(value):
    """MEMOTE stores one value per biomass reaction as a dict; flatten it."""
    if isinstance(value, dict):
        return list(value.values())
    return [value]


def _sample(data, limit=30):
    """(count, first `limit` items as strings) for whatever a test stored."""
    if data is None:
        return None, []
    if isinstance(data, dict):
        items = [f"{k}: {v}" for k, v in data.items()]
        return len(items), items[:limit]
    if isinstance(data, (list, tuple, set)):
        items = [str(x) for x in data]
        return len(items), items[:limit]
    if isinstance(data, bool):
        return None, [str(data)]
    return None, [str(data)]


def _summarise_case(name, case, weight):
    result_flat = [str(r) for r in _first(case.get("result"))]
    metric_raw = case.get("metric")
    metric_vals = [m for m in _first(metric_raw) if isinstance(m, (int, float))]
    metric = max(metric_vals) if metric_vals else None

    if result_flat and all(r == "skipped" for r in result_flat):
        status = "skipped"
    elif metric is not None:
        # MEMOTE's own score is 1 - metric, and its pass/fail flag is not
        # reliable for every test (a few assert against a list instead of a
        # count), so the metric is what we classify on.
        status = "ok" if metric <= 1e-9 else ("info" if name in INFO_TESTS else "issue")
    else:
        status = "ok" if all(r == "passed" for r in result_flat) else "issue"

    messages = [str(m) for m in _first(case.get("message")) if m]
    count, sample = _sample(case.get("data"))
    return {
        "name": name,
        "title": case.get("title") or name,
        "summary": (case.get("summary") or "").strip(),
        "status": status,
        "metric": metric,
        "score": None if metric is None else max(0.0, 1.0 - metric),
        "weight": weight,
        "impact": (metric or 0.0) * weight if status == "issue" else 0.0,
        "message": " ".join(" ".join(messages).split())[:600],
        "format_type": case.get("format_type"),
        "data_count": count,
        "data_sample": sample,
    }


def build_summary(report_json, duration, meta_extra):
    tests_raw = report_json.get("tests", {})
    weights = report_json.get("weights", {})
    cards_raw = report_json.get("cards", {})
    score = report_json.get("score", {})

    tests = {
        name: _summarise_case(name, case, float(weights.get(name, 1.0)))
        for name, case in tests_raw.items()
    }

    section_titles = {}
    section_weights = {}
    cards = []
    scored_tests = set()
    for card_id, card in cards_raw.items():
        entry = {"id": card_id, "title": card.get("title", card_id), "sections": []}
        if "sections" in card:
            for sec_id, sec in card["sections"].items():
                section_titles[sec_id] = sec.get("title", sec_id)
                section_weights[sec_id] = sec.get("weight", 1.0)
                names = [n for n in sec.get("cases", []) if n in tests]
                scored_tests.update(names)
                entry["sections"].append({"id": sec_id, "title": sec.get("title", sec_id), "tests": names})
        else:
            names = [n for n in card.get("cases", []) if n in tests]
            entry["sections"].append({"id": card_id, "title": card.get("title", card_id), "tests": names})
        if any(s["tests"] for s in entry["sections"]):
            cards.append(entry)

    for name, t in tests.items():
        t["scored"] = name in scored_tests

    sections = [
        {
            "id": s["section"],
            "title": section_titles.get(s["section"], s["section"]),
            "score": s["score"],
            "weight": section_weights.get(s["section"], 1.0),
        }
        for s in score.get("sections", [])
    ]

    counts = {"ok": 0, "issue": 0, "info": 0, "skipped": 0}
    for t in tests.values():
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    counts["total"] = len(tests)

    import memote  # noqa: WPS433 (imported late: keeps module import cheap)

    meta = {
        "memote_version": getattr(memote, "__version__", None),
        "duration_seconds": round(duration, 1),
        "timestamp": report_json.get("meta", {}).get("timestamp"),
    }
    meta.update(meta_extra)

    return {
        "total_score": score.get("total_score"),
        "sections": sections,
        "cards": cards,
        "tests": tests,
        "counts": counts,
        "meta": meta,
    }


def main(argv):
    model_path = Path(argv[1])
    out_dir = Path(argv[2])
    solver_mode = argv[3] if len(argv) > 3 else "default"
    out_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()
    _write_progress("loading")

    from core.shared import load_uploaded_model

    sbml_version = None
    model = None
    suffixes = "".join(model_path.suffixes).lower()
    if suffixes.endswith((".xml", ".sbml", ".xml.gz", ".xml.zip", ".xml.bz2")):
        # MEMOTE's own loader also reports the SBML level/version/FBC use,
        # which a few of its checks want.
        try:
            from memote.suite.api import validate_model

            model, sbml_version, _ = validate_model(str(model_path))
        except Exception:
            model = None
    if model is None:
        model = load_uploaded_model(model_path)

    if solver_mode == "glpk_exact":
        model.solver = "glpk_exact"

    from memote.suite.api import snapshot_report, test_model
    from memote.suite.reporting import ReportConfiguration

    _write_progress("testing")
    code, result = test_model(
        model,
        sbml_version=sbml_version,
        results=True,
        pytest_args=["-q", "--no-header", "-p", "no:cacheprovider", "-p", "overview.memote_progress"],
    )
    # `code` is pytest's exit status: it is 1 whenever any individual test
    # fails, which for a model-quality report is normal, not an error.

    _write_progress("rendering", done=1, total=1)
    config = ReportConfiguration.load()
    report_json = json.loads(snapshot_report(result, config, html=False))
    html = snapshot_report(result, config, html=True)

    summary = build_summary(
        report_json,
        time.time() - started,
        {"solver": solver_mode, "model_id": getattr(model, "id", None)},
    )
    (out_dir / "report.html").write_text(html, encoding="utf-8")
    (out_dir / "result.json").write_text(json.dumps(summary), encoding="utf-8")
    _write_progress("done", done=1, total=1)


if __name__ == "__main__":
    try:
        main(sys.argv)
    except Exception:
        # The job manager shows the tail of this to the user.
        traceback.print_exc()
        sys.exit(2)
