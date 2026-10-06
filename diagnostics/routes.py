"""Routes for the on-request Diagnostics & Comparative Analyses tabs:
Minimal Medium, Network Gaps, Demand & Sink Audit, and FROG Report. None of
these ever permanently change the cached model.
"""
from flask import Blueprint, Response, jsonify, request

from core.shared import MODEL_CACHE, touch_model_cache
from diagnostics.balance import compute_balance_report
from diagnostics.biomass_precursors import compute_biomass_precursor_report
from diagnostics.demand_sink import compute_demand_sink_audit
from diagnostics.frog import stream_frog_report
from diagnostics.minimal_medium import compute_minimal_medium_report
from diagnostics.network_gaps import compute_network_gaps_report

diagnostics_bp = Blueprint("diagnostics", __name__)


@diagnostics_bp.post("/api/minimal-medium")
def api_minimal_medium():
    """On-request report for the Minimal Medium tab: the smallest nutrient
    set sustaining a user-chosen fraction of the model's own maximum growth
    rate. Independent of the diet chosen at upload time, and never changes
    the cached model (see compute_minimal_medium_report)."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404

    try:
        growth_cutoff_fraction = float(data.get("growth_cutoff_fraction", 1.0))
    except (TypeError, ValueError):
        growth_cutoff_fraction = 1.0

    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]

    try:
        report = compute_minimal_medium_report(model, growth_cutoff_fraction)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if "error" in report:
        return jsonify({"status": "error", **report}), 400
    return jsonify({"status": "success", **report})


@diagnostics_bp.post("/api/network-gaps")
def api_network_gaps():
    """On-request report for the Network Gaps tab: reactions that can't
    carry any flux under the model's current bounds, plus structurally
    dead-end metabolites. Independent of every other tab; never changes
    the cached model (see compute_network_gaps_report)."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404

    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]

    try:
        report = compute_network_gaps_report(model)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if "error" in report:
        return jsonify({"status": "error", **report}), 400
    return jsonify({"status": "success", **report})


@diagnostics_bp.post("/api/demand-sink-audit")
def api_demand_sink_audit():
    """On-request report for the Demand & Sink Audit section: every demand
    and sink reaction's metabolite, bounds, WT usage, and knockout
    essentiality. Independent of every other tab; never permanently changes
    the cached model (see compute_demand_sink_audit)."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404

    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]

    try:
        report = compute_demand_sink_audit(model)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if "error" in report:
        return jsonify({"status": "error", **report}), 400
    return jsonify({"status": "success", **report})


@diagnostics_bp.get("/api/frog-report/<model_id>")
def api_frog_report(model_id):
    """Stream the FROG report (see stream_frog_report) for an already-cached
    model. GET + EventSource, same pattern as /api/analyze-ko. Query args:
    fva_fraction (default 1.0), include_fva/include_reaction_deletions/
    include_gene_deletions (each "0"/"false"/"no" to skip, default on)."""
    if model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired"}), 404

    model, _ = MODEL_CACHE[model_id]

    def parse_bool(name, default=True):
        raw = request.args.get(name)
        if raw is None:
            return default
        return raw.strip().lower() not in ("0", "false", "no", "")

    try:
        fva_fraction = float(request.args.get("fva_fraction", 1.0))
    except (TypeError, ValueError):
        fva_fraction = 1.0
    include_fva = parse_bool("include_fva", True)
    include_reaction_deletions = parse_bool("include_reaction_deletions", True)
    include_gene_deletions = parse_bool("include_gene_deletions", True)

    def generate():
        try:
            for line in stream_frog_report(
                model, fva_fraction, include_fva, include_reaction_deletions, include_gene_deletions
            ):
                yield line
        finally:
            touch_model_cache(model_id)

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
    })


def _cached_model_from_request():
    data = request.json or {}
    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return None, (jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404)
    touch_model_cache(model_id)
    return MODEL_CACHE[model_id][0], None


@diagnostics_bp.post("/api/balance-diagnostics")
def api_balance_diagnostics():
    """Which reactions are mass/charge-unbalanced (or can't be checked), and why."""
    model, err = _cached_model_from_request()
    if err:
        return err
    try:
        return jsonify({"status": "success", **compute_balance_report(model)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@diagnostics_bp.post("/api/biomass-precursors")
def api_biomass_precursors():
    """Can each biomass precursor be produced on its own? (see diagnostics/biomass_precursors.py)"""
    model, err = _cached_model_from_request()
    if err:
        return err
    try:
        report = compute_biomass_precursor_report(model)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if "error" in report:
        return jsonify({"status": "error", **report}), 400
    return jsonify({"status": "success", **report})
