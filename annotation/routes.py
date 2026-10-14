"""Routes for the Annotation & Translation module: SEED -> VMH translation
and translation through MetaNetX of the loaded model, and downloads of the
translated model and report.
"""
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

from annotation.metanetx_translation import TARGETS, translate_via_metanetx
from annotation.seed_to_vmh import translate_seed_to_vmh
from annotation.translation_export import build_bundle, model_bytes, report_summary_text
from core.shared import EXPIRY_HOOKS, MODEL_CACHE, ORIGINAL_FILES, load_uploaded_model, touch_model_cache

annotation_bp = Blueprint("annotation", __name__)

# model_id -> {"model", "report", "base_name", "source_name"} for the most
# recent translation of each cached model, so it can be downloaded after the
# report has been shown. Dropped when the source model expires.
TRANSLATIONS = {}
MNX_TRANSLATIONS = {}  # same, for the translations through MetaNetX
EXPIRY_HOOKS.append(lambda model_id: TRANSLATIONS.pop(model_id, None))
EXPIRY_HOOKS.append(lambda model_id: MNX_TRANSLATIONS.pop(model_id, None))


def _fresh_source_model(model_id):
    """A new copy of the model to translate: reloaded from the file exactly
    as uploaded when it's still on disk (the cached model has the chosen
    diet applied), otherwise a copy of the cached one."""
    original = ORIGINAL_FILES.get(model_id)
    if original is not None and Path(original).is_file():
        return load_uploaded_model(Path(original)), Path(original).name
    cached, _ = MODEL_CACHE[model_id]
    return cached.copy(), cached.id or "model"


@annotation_bp.post("/api/translate-seed-vmh")
def api_translate_seed_vmh():
    """Translate the loaded model's ids from SEED to VMH and return the
    report (mapped / errors / no available mapping). The cached model is
    never changed; the translated copy is kept for download."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404

    touch_model_cache(model_id)
    try:
        model, source_name = _fresh_source_model(model_id)
        report = translate_seed_to_vmh(model, data.get("style", "vmh"))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if "error" in report:
        return jsonify({"status": "error", **report}), 400

    TRANSLATIONS[model_id] = {
        "model": model, "report": report, "source_name": source_name,
        "base_name": Path(source_name).name.split(".")[0] + "_vmh",
    }
    return jsonify({"status": "success", "source_name": source_name, **report})


def _download_response(store, model_id):
    """Download of the last translation kept in `store`: ?what=bundle (zip:
    model + report, default), sbml, json, or summary."""
    entry = store.get(model_id)
    if entry is None:
        return jsonify({"error": "No translation found for this model. Run the translation again."}), 404

    touch_model_cache(model_id)
    what = request.args.get("what", "bundle")
    base = entry["base_name"]
    try:
        if what == "sbml":
            body, mime, name = model_bytes(entry["model"], "sbml"), "application/xml", f"{base}.xml"
        elif what == "json":
            body, mime, name = model_bytes(entry["model"], "json"), "application/json", f"{base}.json"
        elif what == "summary":
            body = report_summary_text(entry["report"], entry["source_name"]).encode("utf-8")
            mime, name = "text/plain", "translation_summary.txt"
        else:
            body = build_bundle(entry["model"], entry["report"], base, entry["source_name"])
            mime, name = "application/zip", f"{base}_translation.zip"
    except Exception as exc:
        return jsonify({"error": f"Could not build the download: {exc}"}), 500

    return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@annotation_bp.get("/api/translate-seed-vmh/<model_id>/download")
def api_translate_seed_vmh_download(model_id):
    return _download_response(TRANSLATIONS, model_id)


@annotation_bp.post("/api/translate-metanetx")
def api_translate_metanetx():
    """Translate the loaded model's ids to another namespace through MetaNetX
    (json: model_id, target, style, pick_first) and return the report. The
    cached model is never changed; the translated copy is kept for download."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404
    target = data.get("target", "metanetx")
    if target not in TARGETS:
        return jsonify({"error": f"Unknown target namespace '{target}'."}), 400

    touch_model_cache(model_id)
    try:
        model, source_name = _fresh_source_model(model_id)
        report = translate_via_metanetx(model, target, data.get("style", "auto"), bool(data.get("pick_first")))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if "error" in report:
        return jsonify({"status": "error", **report}), 400

    MNX_TRANSLATIONS[model_id] = {
        "model": model, "report": report, "source_name": source_name,
        "base_name": Path(source_name).name.split(".")[0] + "_" + target,
    }
    return jsonify({"status": "success", "source_name": source_name, **report})


@annotation_bp.get("/api/translate-metanetx/<model_id>/download")
def api_translate_metanetx_download(model_id):
    return _download_response(MNX_TRANSLATIONS, model_id)
