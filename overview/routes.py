"""Routes for the landing page and the Overview / Exchange Essentiality
tabs: upload + diet application, quick stats, and streamed KO analysis.
"""
import tempfile
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from core.shared import ALLOWED, MODEL_CACHE, load_uploaded_model, safe_float, store_original_file, touch_model_cache
from diagnostics.diet import apply_diet_to_model, parse_diet_file
from overview import memote_jobs
from overview.analysis import analyze_model, quick_analyze, stream_ko_analysis

overview_bp = Blueprint("overview", __name__)

# Changes on every server start; appended to /static URLs so a browser never
# keeps serving an older app.js / app.css after the app is updated.
ASSET_VERSION = str(int(time.time()))


@overview_bp.get("/")
def index():
    return render_template("index.html", v=ASSET_VERSION)


@overview_bp.post("/api/analyze-quick")
def api_analyze_quick():
    """Fast endpoint that returns stats without KO analysis."""
    uploaded = request.files.get("model")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Please upload a model file."}), 400

    filename = secure_filename(uploaded.filename)
    suffixes = "".join(Path(filename).suffixes).lower()
    if not any(suffixes.endswith(ext) for ext in ALLOWED):
        return jsonify({"error": "Unsupported model format. Use SBML/XML, JSON, YAML, MATLAB .mat, or supported compressed SBML."}), 400

    diet_mode = (request.form.get("diet_mode") or "none").strip().lower()
    diet_file = request.files.get("diet_file")

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        uploaded.save(path)
        try:
            model = load_uploaded_model(path)

            diet_entries = None
            if diet_mode == "custom":
                if not diet_file or not diet_file.filename:
                    return jsonify({"error": "Custom diet selected, but no diet file was uploaded."}), 400
                try:
                    diet_entries = parse_diet_file(diet_file)
                except Exception as exc:
                    return jsonify({"error": f"Could not read the diet file: {exc}"}), 400
                if not diet_entries:
                    return jsonify({"error": "The diet file didn't contain any usable (id, flux) rows."}), 400

            diet_result = apply_diet_to_model(model, diet_mode, diet_entries)

            result = quick_analyze(model)
            result["diet"] = diet_result

            # Store model in cache for streaming
            model_id = str(uuid.uuid4())
            MODEL_CACHE[model_id] = (model, time.time())
            # Keep the untouched upload for MEMOTE (the cached model has the diet applied).
            try:
                store_original_file(model_id, path)
            except OSError:
                pass
            result["model_id"] = model_id
            ok, info = memote_jobs.memote_available()
            result["memote_available"] = ok
            result["memote_message"] = None if ok else info
            return jsonify(result)
        except Exception as exc:
            return jsonify({
                "error": str(exc),
                "hint": "For SBML, install python-libsbml. For MATLAB files, ensure the relevant COBRApy dependencies are installed."
            }), 500


@overview_bp.get("/api/analyze-ko/<model_id>")
def api_analyze_ko(model_id):
    """Stream KO analysis progress."""
    if model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired"}), 404

    model, _ = MODEL_CACHE[model_id]

    try:
        wt_solution = model.optimize()
        wt_growth = safe_float(wt_solution.objective_value) or 0.0
        fluxes = wt_solution.fluxes if hasattr(wt_solution, "fluxes") else {}

        def generate():
            try:
                for line in stream_ko_analysis(model, wt_growth, fluxes):
                    yield line
            finally:
                # Keep the model cached (refresh its TTL) instead of
                # deleting it: the user can request exchange debugging
                # right after KO analysis finishes, which needs this same
                # model object. The periodic cleanup thread reaps it after
                # MODEL_TTL_SECONDS of inactivity.
                touch_model_cache(model_id)

        return Response(generate(), mimetype='text/event-stream', headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        })
    except Exception as exc:
        if model_id in MODEL_CACHE:
            del MODEL_CACHE[model_id]
        return jsonify({"error": str(exc)}), 500


@overview_bp.post("/api/analyze")
def api_analyze():
    """Full analysis endpoint (legacy, slower)."""
    uploaded = request.files.get("model")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Please upload a model file."}), 400

    filename = secure_filename(uploaded.filename)
    suffixes = "".join(Path(filename).suffixes).lower()
    if not any(suffixes.endswith(ext) for ext in ALLOWED):
        return jsonify({"error": "Unsupported model format. Use SBML/XML, JSON, YAML, MATLAB .mat, or supported compressed SBML."}), 400

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        uploaded.save(path)
        try:
            model = load_uploaded_model(path)
            result = analyze_model(model)
            return jsonify(result)
        except Exception as exc:
            return jsonify({
                "error": str(exc),
                "hint": "For SBML, install python-libsbml. For MATLAB files, ensure the relevant COBRApy dependencies are installed."
            }), 500


# ---------------------------------------------------------------------------
# MEMOTE (run on request; see overview/memote_jobs.py)
# ---------------------------------------------------------------------------
@overview_bp.post("/api/memote/<model_id>/start")
def api_memote_start(model_id):
    if model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-analyze the model."}), 404
    job, err = memote_jobs.start_job(model_id)
    if err:
        return jsonify({"error": err}), 400
    return jsonify(memote_jobs.job_state(model_id))


@overview_bp.get("/api/memote/<model_id>/status")
def api_memote_status(model_id):
    touch_model_cache(model_id)
    return jsonify(memote_jobs.job_state(model_id))


@overview_bp.post("/api/memote/<model_id>/cancel")
def api_memote_cancel(model_id):
    return jsonify({"cancelled": memote_jobs.cancel_job(model_id)})


@overview_bp.get("/api/memote/<model_id>/report")
def api_memote_report(model_id):
    path = memote_jobs.report_path(model_id)
    if path is None:
        return jsonify({"error": "No MEMOTE report available."}), 404
    return send_file(path, mimetype="text/html", as_attachment=request.args.get("download") == "1",
                     download_name="memote_report.html")
