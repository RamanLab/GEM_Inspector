"""Routes for the Debugging Toolkit: Exchange Debugging and the
general-purpose Pathway Tracer.
"""
from flask import Blueprint, jsonify, request

from annotation.naming import clean_metabolite_display_name, compartment_display_name
from core.shared import MODEL_CACHE, classify_reactions, clean, find_biomass_reaction, safe_float, touch_model_cache
from debugging.tracing import (
    apply_knockouts,
    debug_exchange_to_biomass,
    resolve_knockout_targets,
    run_pathway_trace,
)

debugging_bp = Blueprint("debugging", __name__)


@debugging_bp.post("/api/debug-exchanges")
def api_debug_exchanges():
    """Debug selected essential exchanges by tracing external metabolite ->
    biomass, both with the exchange active (before KO) and with it
    reversibly knocked out (after KO), so the two flux traces can be
    compared side by side."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    exchange_ids = data.get("exchange_ids", [])
    exclude_trivial = bool(data.get("exclude_trivial_metabolites", True))

    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404

    if not exchange_ids:
        return jsonify({"error": "No exchanges selected"}), 400

    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]

    try:
        biomass_rxn = find_biomass_reaction(model)
        if not biomass_rxn:
            return jsonify({"error": "Could not identify biomass reaction"}), 400

        wt_solution = model.optimize()
        wt_growth = max(0.0, safe_float(wt_solution.objective_value) or 0.0)

        # Computed once and reused across every selected exchange's
        # before/after trace below -- both depend only on model structure,
        # not on which exchange is knocked out, so recomputing them inside
        # the loop would waste an O(n) pass per exchange for nothing.
        reaction_types = classify_reactions(model)
        compartment_names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}

        results = {}
        for exch_id in exchange_ids:
            try:
                exch = model.reactions.get_by_id(exch_id)
            except KeyError:
                results[exch_id] = {"error": f"Exchange reaction '{exch_id}' not found in model"}
                continue

            internal_mets = list(exch.metabolites.keys())
            if not internal_mets:
                results[exch_id] = {"error": "No metabolites found in exchange"}
                continue
            int_met = internal_mets[0]

            try:
                # Before KO: trace on the model exactly as analyzed.
                before = debug_exchange_to_biomass(
                    model, exch_id, int_met.id, biomass_rxn,
                    max_flux_paths=5, max_flux_path_depth=15,
                    exclude_trivial_metabolites=exclude_trivial,
                    reaction_types=reaction_types, compartment_names=compartment_names,
                )

                # After KO: knock the exchange out inside a model context so
                # the bound change is automatically reverted afterwards, then
                # re-trace on the perturbed steady state (flux may reroute
                # through an alternate pathway, or vanish entirely).
                with model:
                    exch.knock_out()
                    after = debug_exchange_to_biomass(
                        model, exch_id, int_met.id, biomass_rxn,
                        max_flux_paths=5, max_flux_path_depth=15,
                        exclude_trivial_metabolites=exclude_trivial,
                        reaction_types=reaction_types, compartment_names=compartment_names,
                    )

                ko_growth = 0.0
                if after.get("status") == "success":
                    ko_growth = max(0.0, safe_float(after.get("biomass_flux")) or 0.0)
                ratio = (ko_growth / wt_growth) if wt_growth > 0 else None

                results[exch_id] = {
                    "exchange_id": exch_id,
                    "exchange_name": exch.name,
                    "internal_metabolite": {"id": int_met.id, "name": clean_metabolite_display_name(int_met)},
                    "biomass_reaction": biomass_rxn,
                    "before_ko": before,
                    "after_ko": after,
                    "growth_impact": {
                        "wt_growth": wt_growth,
                        "ko_growth": ko_growth,
                        "ko_growth_fraction": ratio,
                    },
                }
            except Exception as exc:
                results[exch_id] = {"error": str(exc)}

        return jsonify({
            "status": "success",
            "biomass_reaction": biomass_rxn,
            "results": results,
            "excluded_trivial_metabolites": exclude_trivial,
            "trivial_metabolite_rule": (
                "Currency/cofactor metabolites (H+, water, ATP/ADP/AMP and other "
                "nucleotides, NAD(H)/NADP(H), FAD(H2), CoA, phosphate/diphosphate, "
                "quinones) are excluded from traced paths so they don't obscure the "
                "pathway-specific route to biomass."
                if exclude_trivial else
                "Currency/cofactor metabolites are included in traced paths."
            ),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@debugging_bp.post("/api/trace-pathway")
def api_trace_pathway():
    """General-purpose pathway tracer (a separate module the user runs on
    request -- never triggered automatically). Unlike the biomass-specific
    exchange debugger, the start can be any reaction or metabolite and the
    target can be any metabolite; "levels" is the BFS depth cap. Reuses the
    exact same active-flux tracing helpers as debug_exchange_to_biomass.

    Optionally accepts "knockouts": a list of reaction/metabolite ids (or a
    comma-separated string). When given, the same start->target trace is
    run a second time with those reaction(s)/metabolite(s) blocked (inside
    a `with model:` context, so the uploaded model is never permanently
    changed), and the result is returned under "knockout" alongside the
    baseline ("before KO") trace at the top level -- so a single request
    gives the frontend everything it needs to toggle between the two and
    highlight what changed.
    """
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    model_id = data.get("model_id")
    start_type = (data.get("start_type") or "metabolite").strip().lower()
    start_id = (data.get("start_id") or "").strip()
    target_metabolite_id = (data.get("target_metabolite_id") or "").strip()
    exclude_trivial = bool(data.get("exclude_trivial_metabolites", True))

    knockout_raw = data.get("knockouts") or []
    if isinstance(knockout_raw, str):
        knockout_raw = knockout_raw.split(",")
    knockout_ids = [str(x).strip() for x in knockout_raw if str(x).strip()]

    if not model_id or model_id not in MODEL_CACHE:
        return jsonify({"error": "Model not found or expired. Please re-run the initial analysis."}), 404
    if start_type not in ("metabolite", "reaction"):
        return jsonify({"error": "start_type must be 'metabolite' or 'reaction'"}), 400
    if not start_id:
        return jsonify({"error": "A starting reaction or metabolite id is required"}), 400
    if not target_metabolite_id:
        return jsonify({"error": "A target metabolite id is required"}), 400

    try:
        max_levels = max(1, min(100, int(data.get("max_levels", 15))))
    except (TypeError, ValueError):
        max_levels = 15
    try:
        max_paths = max(1, min(100, int(data.get("max_paths", 10))))
    except (TypeError, ValueError):
        max_paths = 10

    touch_model_cache(model_id)
    model, _ = MODEL_CACHE[model_id]

    try:
        target_met = model.metabolites.get_by_id(target_metabolite_id)
    except KeyError:
        return jsonify({"error": f"Target metabolite '{target_metabolite_id}' not found in model"}), 400

    flux_tolerance = 1e-9
    # Computed once and reused for both the baseline and (if requested) the
    # after-KO trace below -- both depend only on model structure, not on
    # which reactions are knocked out.
    reaction_types = classify_reactions(model)
    compartment_names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}

    try:
        baseline_solution = model.optimize()
    except Exception as exc:
        return jsonify({"error": f"FBA failed: {exc}"}), 500

    try:
        before = run_pathway_trace(
            model, baseline_solution, start_type, start_id, target_met,
            max_levels, max_paths, exclude_trivial, flux_tolerance,
            reaction_types, compartment_names,
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    if "error" in before:
        return jsonify({"error": before["error"]}), 400

    before_active_flux = before.pop("active_flux", {})

    response = {
        "status": "success",
        "start_type": start_type,
        "start_id": start_id,
        "start_metabolites": before["start_metabolites"],
        "target_metabolite": {
            "id": target_met.id, "name": clean_metabolite_display_name(target_met),
            "compartment": target_met.compartment,
            "compartment_name": compartment_names.get(target_met.compartment, target_met.compartment),
            "formula": getattr(target_met, "formula", None),
            "charge": clean(getattr(target_met, "charge", None)),
        },
        "num_active_reactions": before["num_active_reactions"],
        "paths": before["paths"],
        "growth": before["growth"],
        "excluded_trivial_metabolites": exclude_trivial,
        "max_levels": max_levels,
        "max_paths": max_paths,
    }

    # Optional comparative knockout: trace the same start->target again with
    # the requested reaction(s)/metabolite(s) blocked, so the two can be
    # toggled side by side in the UI.
    if knockout_ids:
        resolved_targets, not_found = resolve_knockout_targets(model, knockout_ids)
        if not resolved_targets:
            response["knockout"] = {
                "error": f"None of the requested knockout id(s) were found in the model: {', '.join(not_found)}",
                "not_found": not_found,
            }
        else:
            try:
                with model:
                    blocked_rxn_ids = apply_knockouts(model, resolved_targets)
                    try:
                        ko_solution = model.optimize()
                        ko_fba_error = None
                    except Exception as exc:
                        ko_solution = None
                        ko_fba_error = f"FBA failed after knockout: {exc}"

                    if ko_solution is not None:
                        after = run_pathway_trace(
                            model, ko_solution, start_type, start_id, target_met,
                            max_levels, max_paths, exclude_trivial, flux_tolerance,
                            reaction_types, compartment_names,
                        )
                    else:
                        after = {"error": ko_fba_error}

                    after_active_flux = after.pop("active_flux", {}) if "error" not in after else {}

                    # Flux comparison, limited to reactions that actually
                    # appear on the traced paths (before and/or after) --
                    # this is "the subset that it got", not the whole
                    # model's flux table, so the payload stays small and
                    # directly answers "did this KO affect this path".
                    path_rxn_ids = {r["id"] for p in response["paths"] for r in p["reactions"]}
                    if "error" not in after:
                        path_rxn_ids |= {r["id"] for p in after.get("paths", []) for r in p["reactions"]}

                    flux_comparison = {
                        rid: {
                            "before_flux": float(before_active_flux.get(rid, 0.0)),
                            "after_flux": float(after_active_flux.get(rid, 0.0)),
                            "active_before": rid in before_active_flux,
                            "active_after": rid in after_active_flux,
                        }
                        for rid in sorted(path_rxn_ids)
                    }
            except Exception as exc:
                response["knockout"] = {"error": str(exc), "not_found": not_found}
            else:
                if "error" in after:
                    response["knockout"] = {
                        "targets": resolved_targets,
                        "not_found": not_found,
                        "blocked_reactions": blocked_rxn_ids,
                        "after_ko": after,
                    }
                else:
                    # Clamp near-zero floating-point solver noise (a lethal
                    # knockout can solve to e.g. -1e-15 instead of exactly 0)
                    # up to 0, matching how the rest of the app already
                    # treats KO growth. Without this, a fully lethal
                    # knockout could display as "-0%" retained.
                    wt_growth = max(0.0, safe_float(before["growth"]) or 0.0)
                    ko_growth = max(0.0, safe_float(after.get("growth")) or 0.0)
                    response["knockout"] = {
                        "targets": resolved_targets,
                        "not_found": not_found,
                        "blocked_reactions": blocked_rxn_ids,
                        "after_ko": after,
                        "growth_impact": {
                            "wt_growth": wt_growth,
                            "ko_growth": ko_growth,
                            "ko_growth_fraction": (ko_growth / wt_growth) if wt_growth > 0 else None,
                        },
                        "flux_comparison": flux_comparison,
                    }

    return jsonify(response)
