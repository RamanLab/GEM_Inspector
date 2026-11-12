"""Routes for the Debugging Toolkit: Exchange Debugging, the
general-purpose Pathway Tracer, and Compare Models.
"""
import tempfile
from pathlib import Path

from flask import Blueprint, Response, jsonify, request
from werkzeug.utils import secure_filename

from annotation.naming import clean_metabolite_display_name, compartment_display_name, currency_bases, is_trivial_metabolite
from core.shared import (
    ALLOWED,
    EXPIRY_HOOKS,
    MODEL_CACHE,
    classify_reactions,
    clean,
    find_biomass_reaction,
    load_uploaded_model,
    safe_float,
    touch_model_cache,
    wt_solution as solve_wt,
)
from debugging.compare_export import build_html, build_xlsx
from debugging.exchange_map import build_exchange_map
from debugging.model_compare import compare_models
from debugging.explore import expand, test_metabolites
from debugging.trace_map import trace_map
from debugging.tracing import apply_knockouts, debug_exchange_to_biomass, resolve_knockout_targets

debugging_bp = Blueprint("debugging", __name__)

MAX_HOPS = 3  # beyond this the neighbourhood is too large to read

# model_id -> the latest Compare Models result, kept so its Excel/HTML report
# can be downloaded after the comparison is shown. Dropped when the model expires.
COMPARISONS = {}
EXPIRY_HOOKS.append(lambda model_id: COMPARISONS.pop(model_id, None))


@debugging_bp.post("/api/debug-exchange-map")
def api_debug_exchange_map():
    """Map one exchange: the active-flux route from its metabolite to biomass
    plus the reactions and metabolites within `hops` steps of that route, with
    the flux before and after knocking the exchange out."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    exchange_id = data.get("exchange_id")
    hops = min(max(int(data.get("hops", 1)), 0), MAX_HOPS)
    hide_trivial = bool(data.get("exclude_trivial_metabolites", True))
    currency = currency_bases(data.get("currency_metabolites"))

    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404
    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]

    try:
        exch = model.reactions.get_by_id(exchange_id)
    except KeyError:
        return jsonify({"error": f"Exchange reaction '{exchange_id}' not found in model"}), 404
    if not exch.metabolites:
        return jsonify({"error": "No metabolites found in exchange"}), 400
    biomass_id = find_biomass_reaction(model)
    if not biomass_id:
        return jsonify({"error": "Could not identify biomass reaction"}), 400

    try:
        wt = solve_wt(model)
        wt_growth = max(0.0, safe_float(wt.objective_value) or 0.0)
        met = list(exch.metabolites)[0]
        compartment_names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}
        before = debug_exchange_to_biomass(
            model, exchange_id, met.id, biomass_id, solution=wt,
            max_flux_paths=5, max_flux_path_depth=15, exclude_trivial_metabolites=hide_trivial,
            reaction_types=classify_reactions(model), compartment_names=compartment_names, currency=currency,
        )
        with model:
            exch.knock_out()
            ko = model.optimize()
        ko_growth = max(0.0, safe_float(ko.objective_value) or 0.0) if ko.status == "optimal" else 0.0
        # With growth lost the solver returns an arbitrary feasible flux vector, so none is shown.
        ko_flux = ko if ko_growth > 1e-9 else None

        return jsonify({
            "status": "success",
            "exchange_id": exchange_id,
            "exchange_name": exch.name,
            "internal_metabolite": {"id": met.id, "name": clean_metabolite_display_name(met)},
            "biomass_reaction": biomass_id,
            "growth_impact": {
                "wt_growth": wt_growth, "ko_growth": ko_growth,
                "ko_growth_fraction": (ko_growth / wt_growth) if wt_growth > 0 else None,
            },
            "paths": before.get("paths", []),
            "map": build_exchange_map(model, exchange_id, biomass_id, before.get("paths", []), wt, ko_flux,
                                      currency, hide_trivial, hops, compartment_names),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


def _endpoint(data, key):
    """(kind, id) from {"type": "metabolite"|"reaction", "id": ...} or None."""
    item = data.get(key) or {}
    kind = str(item.get("type", "")).strip().lower()
    ident = str(item.get("id", "")).strip()
    return (kind, ident) if kind in ("metabolite", "reaction") and ident else None


def _id_list(raw):
    if isinstance(raw, str):
        raw = raw.split(",")
    return [str(x).strip() for x in (raw or []) if str(x).strip()]


def _bounded_int(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


@debugging_bp.post("/api/trace-map")
def api_trace_map():
    """Pathway tracer. Routes from a start (metabolite or reaction) to a target
    (metabolite or reaction), either only through reactions carrying flux
    ("active") or through any reaction the bounds allow ("all"), drawn with
    their `hops` neighbourhood. Optional "knockouts" (reaction/metabolite ids)
    add the flux after the knockout; the model itself is never changed."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    model_id = data.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404
    start, target = _endpoint(data, "start"), _endpoint(data, "target")
    if not start or not target:
        return jsonify({"error": "Choose both a start and a target (metabolite or reaction)."}), 400
    mode = "all" if data.get("mode") == "all" else "active"
    hops = _bounded_int(data.get("hops"), 1, 0, MAX_HOPS)
    max_levels = _bounded_int(data.get("max_levels"), 15, 1, 100)
    max_paths = _bounded_int(data.get("max_paths"), 10, 1, 100)
    hide_trivial = bool(data.get("exclude_trivial_metabolites", True))
    currency = currency_bases(data.get("currency_metabolites"))

    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]
    extra_mets = [m.id for m in (model.metabolites.get_by_id(i) for i in _id_list(data.get("extra_metabolites"))
                                 if i in model.metabolites)]
    extra_rxns = [i for i in _id_list(data.get("extra_reactions")) if i in model.reactions]
    ko_ids = _id_list(data.get("knockouts"))
    compartment_names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}

    try:
        wt = solve_wt(model)
        wt_growth = max(0.0, safe_float(wt.objective_value) or 0.0)
        ko, ko_info = None, None
        if ko_ids:
            targets, not_found = resolve_knockout_targets(model, ko_ids)
            if not targets:
                ko_info = {"error": "None of the knockout ids were found: " + ", ".join(not_found),
                           "not_found": not_found}
            else:
                with model:
                    blocked = apply_knockouts(model, targets)
                    sol = model.optimize()
                ko_growth = max(0.0, safe_float(sol.objective_value) or 0.0) if sol.status == "optimal" else 0.0
                # With growth lost the solver returns an arbitrary flux vector, so none is shown.
                ko = sol if ko_growth > 1e-9 else None
                ko_info = {"targets": targets, "not_found": not_found, "blocked_reactions": blocked,
                           "growth_impact": {"wt_growth": wt_growth, "ko_growth": ko_growth,
                                             "ko_growth_fraction": (ko_growth / wt_growth) if wt_growth > 0 else None}}
        result = trace_map(model, wt, ko, start, target, mode, hops, max_levels, max_paths, currency,
                           hide_trivial, extra_mets, extra_rxns, compartment_names, find_biomass_reaction(model))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    if "error" in result:
        return jsonify(result), 400
    result.update({
        "status": "success", "mode": mode, "growth": wt_growth, "knockout": ko_info,
        "start": {"type": start[0], "id": start[1]}, "target": {"type": target[0], "id": target[1]},
    })
    return jsonify(result)


def _explore_model(data):
    """(model, error response) for the Explorer endpoints."""
    model_id = (data or {}).get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return None, (jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404)
    touch_model_cache(model_id)
    return MODEL_CACHE[model_id][0], None


@debugging_bp.post("/api/explore-expand")
def api_explore_expand():
    """Explorer: one step up and/or down from a metabolite or reaction."""
    data = request.json
    model, error = _explore_model(data)
    if error:
        return error
    kind, ident = str(data.get("type", "")), str(data.get("id", ""))
    direction = data.get("direction") if data.get("direction") in ("up", "down", "both") else "both"
    pool = model.metabolites if kind == "metabolite" else model.reactions if kind == "reaction" else None
    if pool is None or ident not in pool:
        return jsonify({"error": f"'{ident}' was not found in the model."}), 400
    currency = currency_bases(data.get("currency_metabolites"))
    trivial = {m.id for m in model.metabolites if data.get("exclude_trivial_metabolites", True) and is_trivial_metabolite(m, currency)}
    try:
        names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}
        return jsonify(expand(model, solve_wt(model), kind, ident, direction, trivial, names,
                              classify_reactions(model), find_biomass_reaction(model)))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@debugging_bp.post("/api/explore-test")
def api_explore_test():
    """Explorer: can the network make / use each of these metabolites?"""
    data = request.json
    model, error = _explore_model(data)
    if error:
        return error
    ids = [i for i in (data.get("metabolites") or [])[:200] if i in model.metabolites]
    try:
        return jsonify({"results": test_metabolites(model, ids)})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@debugging_bp.post("/api/compare-models")
def api_compare_models():
    """Compare the loaded model (A) with a second uploaded model (B):
    naming conventions, then genes, metabolites, reactions and biomass
    components -- shared vs only in one. Model B is loaded for this request
    only; neither model is changed."""
    model_id = request.form.get("model_id")
    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404

    uploaded = request.files.get("model_b")
    if not uploaded or not uploaded.filename:
        return jsonify({"error": "Please choose a second model file to compare with."}), 400
    filename = secure_filename(uploaded.filename)
    suffixes = "".join(Path(filename).suffixes).lower()
    if not any(suffixes.endswith(ext) for ext in ALLOWED):
        return jsonify({"error": "Unsupported model format. Use SBML/XML, JSON, YAML, MATLAB .mat, or supported compressed SBML."}), 400

    touch_model_cache(model_id)
    model_a, _ = MODEL_CACHE[model_id]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        uploaded.save(path)
        try:
            model_b = load_uploaded_model(path)
        except Exception as exc:
            return jsonify({"error": f"Could not read the second model: {exc}"}), 400

    try:
        report = compare_models(model_a, model_b)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    report["labels"]["b"] = report["labels"]["b"] if model_b.id else Path(filename).stem
    report["file_b"] = filename
    COMPARISONS[model_id] = report
    return jsonify({"status": "success", **report})


@debugging_bp.get("/api/compare-models/<model_id>/report")
def api_compare_models_report(model_id):
    """Download the latest comparison as a report: ?format=xlsx or html."""
    report = COMPARISONS.get(model_id)
    if report is None:
        return jsonify({"error": "No comparison found for this model. Run the comparison again."}), 404

    touch_model_cache(model_id)
    try:
        if request.args.get("format") == "html":
            body, mime, ext = build_html(report).encode("utf-8"), "text/html; charset=utf-8", "html"
        else:
            body, mime, ext = build_xlsx(report), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    except Exception as exc:
        return jsonify({"error": f"Could not build the report: {exc}"}), 500

    name = f"model_comparison.{ext}"
    return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})
