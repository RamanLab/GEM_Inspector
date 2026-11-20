"""Routes for Benchmark / compare models: run on several uploaded models (streamed progress), download
the Excel report, and download the stand-alone script for runs that are too big for the page."""
import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request, send_file
from werkzeug.utils import secure_filename

from benchmark.core_carbon import CORE_REACTIONS, parse_ids
from benchmark.engine import run_benchmark
from benchmark.export import build_workbook
from core.shared import ALLOWED, MODEL_CACHE, clean, load_uploaded_model, touch_model_cache

benchmark_bp = Blueprint("benchmark", __name__)
MAX_MODELS = 6          # keep in step with static/benchmark.js
MAX_STORED_RUNS = 3
RUNS = {}               # run id -> (result, details, created)
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "benchmark_models.py"


def _event(payload):
    return json.dumps(clean(payload)) + "\n"


@benchmark_bp.get("/api/benchmark/defaults")
def api_benchmark_defaults():
    return jsonify({"core": CORE_REACTIONS, "max_models": MAX_MODELS})


@benchmark_bp.get("/api/benchmark/script")
def api_benchmark_script():
    return send_file(SCRIPT, as_attachment=True, download_name="benchmark_models.py", mimetype="text/x-python")


@benchmark_bp.post("/api/benchmark/run")
def api_benchmark_run():
    uploads = [f for f in request.files.getlist("models") if f and f.filename]
    # Optionally model A is the model already loaded in the app (Debugging Toolkit > Compare Models).
    loaded_id = request.form.get("model_id")
    if loaded_id:
        if loaded_id not in MODEL_CACHE:
            return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404
        touch_model_cache(loaded_id)
    if len(uploads) + (1 if loaded_id else 0) < 2:
        return jsonify({"error": "Choose at least two model files."}), 400
    if len(uploads) + (1 if loaded_id else 0) > MAX_MODELS:
        return jsonify({"error": f"At most {MAX_MODELS} models can be benchmarked on this page. Use the stand-alone script for more."}), 400
    try:
        medium = {"mode": request.form.get("medium_mode", "own"), "rows": json.loads(request.form.get("medium_rows") or "[]")}
        fraction = min(max(float(request.form.get("fva_fraction", 1.0)), 0.0), 1.0)
    except (ValueError, TypeError):
        return jsonify({"error": "The medium or the FVA fraction could not be read."}), 400
    if medium["mode"] == "custom" and not medium["rows"]:
        return jsonify({"error": "The medium table is empty. Add uptakes, or use each model's own medium."}), 400
    core_ids = parse_ids(request.form.get("core_ids"))
    reference = request.form.get("reference", "")
    reference = int(reference) if reference.isdigit() and int(reference) < len(uploads) + (1 if loaded_id else 0) else None

    folder = Path(tempfile.mkdtemp(prefix="gem_inspector_bench_"))
    saved = []
    for i, upload in enumerate(uploads):
        name = secure_filename(upload.filename) or f"model_{i}"
        if not any("".join(Path(name).suffixes).lower().endswith(ext) for ext in ALLOWED):
            shutil.rmtree(folder, ignore_errors=True)
            return jsonify({"error": f"{upload.filename}: unsupported model format."}), 400
        path = folder / f"{i}_{name}"
        upload.save(path)
        saved.append((name, path))

    def generate():
        try:
            entries = []
            if loaded_id:
                loaded = MODEL_CACHE[loaded_id][0]
                entries.append((f"{loaded.id or 'model'} (loaded)", loaded.copy()))   # a copy: the medium is applied to it
            for i, (name, path) in enumerate(saved):
                yield _event({"type": "progress", "message": f"Loading {name}", "current": i, "total": len(saved)})
                try:
                    entries.append((name, load_uploaded_model(path)))
                except Exception as exc:
                    yield _event({"type": "error", "error": f"Could not read {name}: {exc}"})
                    return
            messages = []
            yield _event({"type": "progress", "message": "Analysing the models (this can take a few minutes)", "current": 0, "total": len(saved)})
            result, details = run_benchmark(entries, medium, reference, core_ids, fraction, progress=messages.append)
            run_id = str(uuid.uuid4())
            RUNS[run_id] = (result, details, time.time())
            for old in sorted(RUNS, key=lambda k: RUNS[k][2])[:-MAX_STORED_RUNS]:
                RUNS.pop(old, None)
            yield _event({"type": "complete", "run_id": run_id, "result": result})
        except Exception as exc:
            yield _event({"type": "error", "error": str(exc)})
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return Response(generate(), mimetype="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@benchmark_bp.get("/api/benchmark/<run_id>/download")
def api_benchmark_download(run_id):
    stored = RUNS.get(run_id)
    if stored is None:
        return jsonify({"error": "This benchmark is no longer available. Run it again."}), 404
    body = build_workbook(stored[0], stored[1])
    return Response(body, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="model_benchmark.xlsx"'})
