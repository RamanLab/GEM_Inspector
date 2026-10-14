"""The Overview tab's analysis: model-wide stats, reaction/metabolite
tables, objective breakdown, and exchange essentiality (KO) testing.
"""
import json

from cobra.util import linear_reaction_coefficients

from annotation.naming import (
    clean_metabolite_display_name,
    clean_reaction_display_name,
    compartment_display_name,
    detect_compartment_convention,
    metabolite_base_id,
)
from annotation.namespace_mapping import (
    NS_LABELS,
    compute_unmapped_id_audit,
    detect_metabolite_namespace_and_map,
    detect_reaction_namespace_and_map,
)
from core.memo import recall, store_value
from core.shared import classify_reactions, clean, safe_float, subsystem_value, wt_solution as solve_wt
from diagnostics.balance import analyse_all_reactions, short_text as balance_short_text

ESSENTIALITY_RULE = "Exchange reaction is essential when reaction KO gives growth < 5% of WT growth."
TRANSPORT_RULE = (
    "Transport is shown using a simple heuristic: reaction metabolites span more than one "
    "compartment and the reaction is not classified by COBRApy as exchange/demand/sink."
)


def compute_metabolite_reaction_stats(model):
    """For every metabolite, count its reaction roles.

    Categories are mutually exclusive:
      - produced_count: irreversible reactions where the metabolite has a
        positive stoichiometric coefficient
      - consumed_count: irreversible reactions where the metabolite has a
        negative stoichiometric coefficient
      - reversible_count: reactions that can carry flux in both directions

    So reaction_count = produced_count + consumed_count + reversible_count.
    A reversible reaction's actual role depends on the flux direction, which
    isn't known here, so it isn't classified as produced/consumed.

    Returns {met_id: {"reaction_count", "produced_count", "consumed_count", "reversible_count"}}.
    """
    stats = {}
    for rxn in model.reactions:
        reversible = rxn.lower_bound < 0 and rxn.upper_bound > 0
        for met, coeff in rxn.metabolites.items():
            entry = stats.setdefault(met.id, {
                "reaction_count": 0, "produced_count": 0,
                "consumed_count": 0, "reversible_count": 0,
            })
            entry["reaction_count"] += 1
            if reversible:
                entry["reversible_count"] += 1
            elif coeff > 0:
                entry["produced_count"] += 1
            elif coeff < 0:
                entry["consumed_count"] += 1
    return stats


def stoich_rows(reaction):
    """Reactant/product rows for a reaction, with clean display names."""
    rows = []
    for met, coeff in reaction.metabolites.items():
        rows.append({
            "id": met.id,
            "name": clean_metabolite_display_name(met),
            "compartment": met.compartment,
            "coefficient": safe_float(coeff),
            "side": "reactant" if coeff < 0 else "product",
        })
    return rows


def gene_rows(model, fluxes):
    """One row per gene: its reactions and basic attributes.

    `lost_on_ko` counts the reactions that cannot be catalysed any more when
    this gene alone is deleted (its GPR rule evaluates to False without it).
    """
    rows = []
    for gene in model.genes:
        rxns = sorted(gene.reactions, key=lambda r: r.id)
        lost = [r.id for r in rxns if not r.gpr.eval(knockouts={gene.id})]
        active = 0
        for r in rxns:
            flux = safe_float(fluxes.get(r.id)) if hasattr(fluxes, "get") else None
            if flux is not None and abs(flux) > 1e-9:
                active += 1
        annotation = []
        for key, value in sorted((gene.annotation or {}).items()):
            for v in (value if isinstance(value, (list, tuple)) else [value]):
                annotation.append(f"{key}:{v}")
        rows.append({
            "id": gene.id,
            "name": gene.name or "",
            "functional": bool(gene.functional),
            "reaction_count": len(rxns),
            "reactions": [r.id for r in rxns],
            "lost_on_ko": lost,
            "active_count": active,
            "subsystems": sorted({subsystem_value(r) for r in rxns if subsystem_value(r)}),
            "annotation": annotation,
        })
    return rows


def quick_analyze(model):
    """Fast initial analysis without KO tests."""
    wt_solution = solve_wt(model)
    wt_status = str(wt_solution.status)
    wt_growth = safe_float(wt_solution.objective_value)

    if wt_growth is None:
        wt_growth = 0.0

    # Namespace detection + MetaNetX mapping, done once up front so both the
    # Overview stats and the per-row metabolite/reaction tables below can
    # use the results (see annotation.namespace_mapping).
    met_ns, met_ns_coverage, met_ns_example, met_to_mnx = detect_metabolite_namespace_and_map(model)
    rxn_ns, rxn_ns_coverage, rxn_ns_example, rxn_to_mnx = detect_reaction_namespace_and_map(model)
    compartment_convention = detect_compartment_convention(model)

    # Which metabolites/reactions never matched any bundled MetaNetX
    # namespace, plus a same-model, same-name check for each one.
    namespace_audit = compute_unmapped_id_audit(model, met_to_mnx, rxn_to_mnx)

    n_genes = len(model.genes)
    n_reactions = len(model.reactions)

    stats = {
        "model_id": model.id,
        "model_name": getattr(model, "name", None),
        "genes": len(model.genes),
        "metabolites": len(model.metabolites),
        "reactions": len(model.reactions),
        "compartments": len(model.compartments),
        "compartment_details": [
            {"id": cid, "name": compartment_display_name(cid, name), "raw_name": str(name)}
            for cid, name in model.compartments.items()
        ],
        "solver": str(model.solver.interface.__name__).split(".")[-1],
        "objective_direction": str(model.objective.direction),
        "wt_status": wt_status,
        "wt_growth": wt_growth,
        "namespace_metabolites": {
            "key": met_ns,
            "label": NS_LABELS.get(met_ns, met_ns) if met_ns else "Unrecognized (not in bundled BiGG/VMH/SEED/KEGG/MetaCyc reference)",
            "example": met_ns_example,
            "coverage": met_ns_coverage,
        },
        "namespace_reactions": {
            "key": rxn_ns,
            "label": NS_LABELS.get(rxn_ns, rxn_ns) if rxn_ns else "Unrecognized (not in bundled BiGG/VMH/SEED/KEGG/MetaCyc reference)",
            "example": rxn_ns_example,
            "coverage": rxn_ns_coverage,
        },
        "compartment_convention": compartment_convention,
        "gene_reaction_ratio": (n_genes / n_reactions) if n_reactions else None,
        "reaction_gene_ratio": (n_reactions / n_genes) if n_genes else None,
        "unmapped_metabolite_count": namespace_audit["unmapped_metabolite_count"],
        "mapped_metabolite_count": namespace_audit["mapped_metabolite_count"],
        "unmapped_reaction_count": namespace_audit["unmapped_reaction_count"],
        "mapped_reaction_count": namespace_audit["mapped_reaction_count"],
    }

    # Metabolite -> single-metabolite exchange lookup, built once rather
    # than scanned per objective metabolite below. Keyed by the
    # compartment-stripped *base* id (e.g. "pyr", not "pyr_c"): a biomass
    # component is essentially always intracellular ("pyr_c"), while its
    # exchange reaction is essentially always on the extracellular form
    # ("pyr_e") -- matching by base id answers the useful question, "does
    # this biomass building block have a same-compound exchange reaction
    # somewhere in the model?"
    direct_exchange_by_met = {}
    for exch in model.exchanges:
        if len(exch.metabolites) == 1:
            (met,) = exch.metabolites.keys()
            direct_exchange_by_met.setdefault(metabolite_base_id(met.id), exch.id)

    # Per-metabolite reaction-role stats, shared by both the Metabolites
    # table and the Objective tab below.
    met_reaction_stats = compute_metabolite_reaction_stats(model)
    _empty_met_stats = {"reaction_count": 0, "produced_count": 0, "consumed_count": 0, "reversible_count": 0}

    # Objective components
    objective_components = []
    objective_metabolites = []
    try:
        coefficients = linear_reaction_coefficients(model)

        # Collect metabolites from objective reactions, excluding the same
        # currency/cofactor metabolites filtered out of exchange-debugging
        # traces (see annotation.naming.TRIVIAL_METABOLITES).
        met_coeff_map = {}

        for rxn, coeff in coefficients.items():
            try:
                reaction_string_names = rxn.build_reaction_string(use_metabolite_names=True)
            except Exception:
                reaction_string_names = None
            objective_components.append({
                "reaction_id": rxn.id,
                "reaction_name": rxn.name,
                "coefficient": safe_float(coeff),
                "reaction": rxn.reaction,
                "reaction_string_names": reaction_string_names,
                "subsystem": subsystem_value(rxn),
                "reactants": stoich_rows(rxn),
                "products": stoich_rows(rxn),
            })

            for met, met_coeff in rxn.metabolites.items():
                key = met.id
                if key not in met_coeff_map:
                    met_coeff_map[key] = {"met": met, "total_coeff": 0.0, "rxn_count": 0}
                met_coeff_map[key]["total_coeff"] += safe_float(met_coeff) * coeff if coeff else 0
                met_coeff_map[key]["rxn_count"] += 1

        for met_id, met_info in sorted(met_coeff_map.items()):
            met = met_info["met"]
            total_coeff = safe_float(met_info["total_coeff"])
            m_stats = met_reaction_stats.get(met.id, _empty_met_stats)
            objective_metabolites.append({
                "metabolite_id": met.id,
                "metabolite_metanetx_id": met_to_mnx.get(met.id),
                "metabolite_name": clean_metabolite_display_name(met),
                "compartment": met.compartment,
                "coefficient": total_coeff,
                # Net role of this metabolite in the objective/biomass
                # reaction(s) -- not to be confused with produced_count/
                # consumed_count below, which count every reaction in the
                # model this metabolite appears in.
                "biomass_role": "produced" if (total_coeff or 0) > 0 else ("consumed" if (total_coeff or 0) < 0 else "neutral"),
                "direct_exchange": direct_exchange_by_met.get(metabolite_base_id(met.id)),
                "appears_in_reactions": met_info["rxn_count"],
                "reaction_count": m_stats["reaction_count"],
                "produced_count": m_stats["produced_count"],
                "consumed_count": m_stats["consumed_count"],
                "reversible_count": m_stats["reversible_count"],
            })
    except Exception as exc:
        objective_components = [{
            "error": f"Objective could not be reduced to linear reaction coefficients: {exc}"
        }]

    # Reaction table + WT flux
    fluxes = wt_solution.fluxes if hasattr(wt_solution, "fluxes") else {}
    reaction_types = classify_reactions(model)
    reactions = []
    balance_by_id = analyse_all_reactions(model)
    for rxn in model.reactions:
        flux = safe_float(fluxes.get(rxn.id)) if hasattr(fluxes, "get") else None
        balance = balance_by_id[rxn.id]
        reactions.append({
            "balance": balance["status"],
            "balance_detail": balance_short_text(balance),
            "id": rxn.id,
            "metanetx_id": rxn_to_mnx.get(rxn.id),
            "name": clean_reaction_display_name(rxn),
            "type": reaction_types.get(rxn.id, "internal"),
            "subsystem": subsystem_value(rxn),
            "compartments": sorted({m.compartment for m in rxn.metabolites if m.compartment}),
            "lower_bound": safe_float(rxn.lower_bound),
            "upper_bound": safe_float(rxn.upper_bound),
            "reversible": bool(rxn.lower_bound < 0 and rxn.upper_bound > 0),
            "wt_flux": flux,
            "gene_reaction_rule": getattr(rxn, "gene_reaction_rule", ""),
        })

    # Metabolite table
    metabolites = []
    for met in model.metabolites:
        m_stats = met_reaction_stats.get(met.id, _empty_met_stats)
        metabolites.append({
            "id": met.id,
            "metanetx_id": met_to_mnx.get(met.id),
            "name": clean_metabolite_display_name(met),
            "compartment": met.compartment,
            "formula": getattr(met, "formula", None),
            "charge": clean(getattr(met, "charge", None)),
            "reaction_count": m_stats["reaction_count"],
            "produced_count": m_stats["produced_count"],
            "consumed_count": m_stats["consumed_count"],
            "reversible_count": m_stats["reversible_count"],
        })

    return {
        "stats": stats,
        "reactions": reactions,
        "metabolites": metabolites,
        "genes": gene_rows(model, fluxes),
        "objective": objective_components,
        "objective_metabolites": objective_metabolites,
        "namespace_audit": namespace_audit,
        "wt_growth": wt_growth,
        "fluxes": dict(fluxes),
        "essentiality_rule": ESSENTIALITY_RULE,
        "transport_rule": TRANSPORT_RULE,
    }


def stream_ko_analysis(model, wt_growth, fluxes):
    """Generator that yields exchange-essentiality (KO) results with
    progress updates, over SSE."""
    exchanges = list(model.exchanges)
    total = len(exchanges)
    _, _, _, met_to_mnx = detect_metabolite_namespace_and_map(model)
    _, _, _, rxn_to_mnx = detect_reaction_namespace_and_map(model)

    yield "data: " + json.dumps({"type": "info", "message": f"Starting KO analysis for {total} exchanges..."}) + "\n\n"

    essentiality = []
    for idx, rxn in enumerate(exchanges):
        yield "data: " + json.dumps({"type": "progress", "current": idx + 1, "total": total, "message": f"Testing {rxn.id}..."}) + "\n\n"

        ko_growth = None
        ko_status = "not tested"
        if wt_growth > 0:
            # Temporary bounds instead of copying the model, for speed.
            old_lb = rxn.lower_bound
            old_ub = rxn.upper_bound
            try:
                rxn.lower_bound = 0
                rxn.upper_bound = 0

                # slim_optimize() skips building a full Solution object
                # (fluxes/reduced costs/shadow prices for every reaction)
                # and just returns the objective value, which is all a
                # knockout screen needs -- avoids thousands of unnecessary
                # Solution constructions for a model with many exchanges.
                value = model.slim_optimize(error_value=None)
                if value is None:
                    ko_status = "infeasible"
                else:
                    ko_status = "optimal"
                    ko_growth = max(0.0, safe_float(value) or 0.0)
            except Exception as exc:
                ko_status = f"error: {exc}"
            finally:
                rxn.lower_bound = old_lb
                rxn.upper_bound = old_ub

        ratio = None
        essential = False
        if ko_growth is not None and wt_growth > 0:
            ratio = ko_growth / wt_growth
            essential = ratio < 0.05
        if wt_growth > 0:
            # Shared with the model report so it does not repeat these knockouts.
            store_value(model, ("exchange_ko_retained", rxn.id), ratio)

        met_ids = [m.id for m in rxn.metabolites]
        met_names = [clean_metabolite_display_name(m) for m in rxn.metabolites]
        met_metanetx_ids = [met_to_mnx.get(m.id) for m in rxn.metabolites]

        essentiality.append({
            "id": rxn.id,
            "metanetx_id": rxn_to_mnx.get(rxn.id),
            "name": rxn.name,
            "metabolites": met_ids,
            "metabolite_metanetx_ids": met_metanetx_ids,
            "metabolite_names": met_names,
            "lower_bound": safe_float(rxn.lower_bound),
            "upper_bound": safe_float(rxn.upper_bound),
            "wt_flux": safe_float(fluxes.get(rxn.id)) if hasattr(fluxes, "get") else None,
            "uptake_allowed": bool(rxn.lower_bound < 0),
            "secretion_allowed": bool(rxn.upper_bound > 0),
            "reversible": bool(rxn.lower_bound < 0 and rxn.upper_bound > 0),
            "ko_growth": ko_growth,
            "ko_growth_fraction": ratio,
            "essential": essential,
            "ko_status": ko_status,
            # Extra context for a hover tooltip on the essentiality table.
            "reaction_string": rxn.reaction,
            "subsystem": subsystem_value(rxn),
            "gene_reaction_rule": getattr(rxn, "gene_reaction_rule", ""),
        })

    yield "data: " + json.dumps({
        "type": "complete", "exchanges": essentiality,
        "essentiality_rule": ESSENTIALITY_RULE, "transport_rule": TRANSPORT_RULE,
    }) + "\n\n"


def analyze_model(model):
    """Legacy, non-streaming full analysis (quick stats + KO analysis in one
    call). Kept for /api/analyze; the frontend normally uses quick_analyze
    plus the streaming KO endpoint instead."""
    quick_data = quick_analyze(model)
    fluxes = quick_data["fluxes"]
    wt_growth = quick_data["wt_growth"]

    essentiality = []
    for result in stream_ko_analysis(model, wt_growth, fluxes):
        try:
            data = json.loads(result.strip())
            if data.get("type") == "complete":
                essentiality = data.get("exchanges", [])
        except Exception:
            pass

    return {
        "stats": quick_data["stats"],
        "reactions": quick_data["reactions"],
        "metabolites": quick_data["metabolites"],
        "exchanges": essentiality,
        "objective": quick_data["objective"],
        "objective_metabolites": quick_data["objective_metabolites"],
        "essentiality_rule": ESSENTIALITY_RULE,
        "transport_rule": TRANSPORT_RULE,
    }
