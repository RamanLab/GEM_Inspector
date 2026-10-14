"""Routes for the model reports: the multi-model comparison started from the
landing page, and the report for the single loaded model. Both stream
progress as newline-delimited JSON and keep the finished report so its Excel
and HTML files can be downloaded."""
import json
import tempfile
import time
import uuid
from pathlib import Path

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from comparative.export_html import build_report_html
from comparative.export_xlsx import build_report_xlsx
from comparative.metrics import compute_model_metrics
from comparative.panel import build_report, for_client
from comparative.settings import QCSections, QCSettings
from core.shared import ALLOWED, EXPIRY_HOOKS, MODEL_CACHE, clean, load_uploaded_model, touch_model_cache

comparative_bp = Blueprint("comparative", __name__)

MAX_STORED_PANELS = 10
PANEL_REPORTS = {}   # run_id -> (report, created_ts), for downloads of a multi-model run
MODEL_REPORTS = {}   # model_id -> report, for the single loaded model
EXPIRY_HOOKS.append(lambda model_id: MODEL_REPORTS.pop(model_id, None))


def _options():
    """QC thresholds and the optional analyses chosen in the request form."""
    form = request.form if request.form else (request.json or {})
    sections = {name: form.get(name) for name in QCSections().__dict__ if form.get(name) is not None}
    return QCSettings.from_dict(form), QCSections.from_dict(sections)


def _event(payload):
    return json.dumps(clean(payload)) + "\n"


def _stream(generator):
    return Response(generator, mimetype="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _store_panel(report):
    run_id = str(uuid.uuid4())
    PANEL_REPORTS[run_id] = (report, time.time())
    for old in sorted(PANEL_REPORTS, key=lambda k: PANEL_REPORTS[k][1])[:-MAX_STORED_PANELS]:
        PANEL_REPORTS.pop(old, None)
    return run_id


def _file_response(report, fmt, filename_base, inline):
    if fmt == "xlsx":
        body = build_report_xlsx(report)
        mime, name = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"{filename_base}.xlsx"
    elif fmt == "html":
        body = build_report_html(report).encode("utf-8")
        mime, name = "text/html; charset=utf-8", f"{filename_base}.html"
    else:
        return jsonify({"error": "Unknown format. Use xlsx or html."}), 400
    disposition = "inline" if (inline and fmt == "html") else "attachment"
    return Response(body, mimetype=mime, headers={"Content-Disposition": f'{disposition}; filename="{name}"'})


@comparative_bp.post("/api/multi-analyze")
def api_multi_analyze():
    """Upload several models (form field "models"), compute the statistics of
    each and stream progress; the last event carries the report summary and
    the run id to download the Excel / HTML files with."""
    uploads = [f for f in request.files.getlist("models") if f and f.filename]
    if len(uploads) < 2:
        return jsonify({"error": "Choose at least two model files to compare."}), 400
    settings, sections = _options()

    folder = Path(tempfile.mkdtemp(prefix="gem_inspector_multi_"))
    saved, rejected = [], []
    for i, upload in enumerate(uploads):
        name = secure_filename(upload.filename) or f"model_{i}"
        suffixes = "".join(Path(name).suffixes).lower()
        if not any(suffixes.endswith(ext) for ext in ALLOWED):
            rejected.append({"file": upload.filename, "error": "Unsupported model format"})
            continue
        path = folder / f"{i}_{name}"
        upload.save(path)
        saved.append((name, path))

    def generate():
        import shutil
        entries, failed = [], list(rejected)
        try:
            for index, (name, path) in enumerate(saved):
                yield _event({"type": "progress", "current": index, "total": len(saved), "message": f"{name}: loading"})
                try:
                    model = load_uploaded_model(path)
                except Exception as exc:
                    failed.append({"file": name, "error": f"Could not read the model: {exc}"})
                    continue
                messages = []
                try:
                    entry = compute_model_metrics(model, name, settings, sections, progress=messages.append)
                except Exception as exc:
                    failed.append({"file": name, "error": str(exc)})
                    continue
                entries.append(entry)
                yield _event({"type": "progress", "current": index + 1, "total": len(saved), "message": f"{name}: done"})
            if len(entries) < 1:
                yield _event({"type": "error", "error": "None of the files could be analysed.", "failed": failed})
                return
            report = build_report(entries, settings, sections)
            yield _event({"type": "complete", "run_id": _store_panel(report), "report": for_client(report), "failed": failed})
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    return _stream(generate())


@comparative_bp.get("/api/multi-report/<run_id>")
def api_multi_report(run_id):
    """?format=xlsx|html (&inline=1 to open the HTML in the browser)."""
    stored = PANEL_REPORTS.get(run_id)
    if stored is None:
        return jsonify({"error": "This comparison is no longer available. Run it again."}), 404
    return _file_response(stored[0], request.args.get("format", "xlsx"), "model_comparison_report", request.args.get("inline") == "1")


@comparative_bp.post("/api/model-report")
def api_model_report():
    """Statistics and findings for the loaded model (json: model_id and
    optional thresholds / sections); streams progress like /api/multi-analyze."""
    data = request.json or {}
    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404
    settings, sections = _options()
    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]
    source_name = (model.id or "model") + ".xml"

    def generate():
        steps = []

        def note(message):
            steps.append(message)

        try:
            entry = compute_model_metrics(model, source_name, settings, sections, progress=note)
            report = build_report([entry], settings, sections)
        except Exception as exc:
            yield _event({"type": "error", "error": str(exc)})
            return
        finally:
            touch_model_cache(model_id)
        MODEL_REPORTS[model_id] = report
        yield _event({"type": "complete", "report": for_client(report)})

    return _stream(generate())


@comparative_bp.get("/api/model-report/<model_id>/download")
def api_model_report_download(model_id):
    report = MODEL_REPORTS.get(model_id)
    if report is None:
        return jsonify({"error": "No report for this model. Build the report first."}), 404
    touch_model_cache(model_id)
    return _file_response(report, request.args.get("format", "xlsx"), "model_report", request.args.get("inline") == "1")
