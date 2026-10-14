"""Key statistics for one model: size, growth, namespaces, formula coverage,
biomass, exchanges and their essentiality, minimal medium, network gaps,
demand/sink reactions and mass balance.

compute_model_metrics() returns {"metrics": {...flat numbers/strings...},
"details": {...lists behind them...}}. Every optional analysis is switched by
QCSections and isolated, so one that fails is noted and the rest still run.
"""
import hashlib
import math
import re
from collections import Counter
from pathlib import Path

from annotation.namespace_mapping import (
    NS_LABELS,
    detect_metabolite_namespace_and_map,
    detect_reaction_namespace_and_map,
)
from annotation.naming import metabolite_base_id
from comparative.settings import QCSections, QCSettings
from core.memo import recall
from core.shared import find_biomass_reaction, safe_float, subsystem_value, wt_solution
from diagnostics.balance import compute_balance_report
from diagnostics.demand_sink import compute_demand_sink_audit
from diagnostics.minimal_medium import compute_minimal_medium_report
from diagnostics.network_gaps import compute_network_gaps_report

UNANNOTATED = "other / unannotated"
_PLACEHOLDER_NAMES = {"", "model", "cobramodel", "model exported from cobra toolbox"}
_ARCHIVE_SUFFIXES = re.compile(r"(\.(xml|sbml|json|ya?ml|mat|gz|zip|bz2))+$", re.I)


def model_key(source_name):
    """File name without its model extensions."""
    return _ARCHIVE_SUFFIXES.sub("", Path(source_name).name) or Path(source_name).name


def display_name(model, source_name):
    for candidate in (getattr(model, "name", None), model.id):
        candidate = (candidate or "").strip()
        if candidate.lower() not in _PLACEHOLDER_NAMES:
            return candidate
    return model_key(source_name)


def _pct(part, whole):
    return round(part / whole * 100, 1) if whole else None


def _content_hash(model):
    """Hash of the reactions, their stoichiometry and bounds, to spot duplicate models."""
    digest = hashlib.md5()
    for rxn in sorted(model.reactions, key=lambda r: r.id):
        digest.update(f"{rxn.id}|{rxn.lower_bound:g}|{rxn.upper_bound:g}|".encode())
        for met, coeff in sorted(rxn.metabolites.items(), key=lambda kv: kv[0].id):
            digest.update(f"{met.id}:{coeff:g};".encode())
    return digest.hexdigest()


def _namespace(model, detect):
    ns, coverage, _, mapping = detect(model)
    return NS_LABELS.get(ns, "Unrecognized") if ns else "Unrecognized", round(coverage * 100, 1), sum(v is None for v in mapping.values())


def _basic(model, source_name, metrics, details):
    n_genes, n_mets, n_rxns = len(model.genes), len(model.metabolites), len(model.reactions)
    metrics.update({
        "model_key": model_key(source_name), "source_file": Path(source_name).name,
        "display_name": display_name(model, source_name),
        "model_id": model.id, "model_name": getattr(model, "name", None) or "",
        "genes": n_genes, "metabolites": n_mets, "reactions": n_rxns,
        "gene_reaction_ratio": round(n_genes / n_rxns, 3) if n_rxns else None,
        "compartments": len(model.compartments),
        "objective_direction": str(model.objective.direction),
        "solver": str(model.solver.interface.__name__).split(".")[-1],
        "content_hash": _content_hash(model),
    })
    for kind, detect, prefix in (("metabolite", detect_metabolite_namespace_and_map, "met"),
                                 ("reaction", detect_reaction_namespace_and_map, "rxn")):
        label, pct, unmapped = _namespace(model, detect)
        metrics[f"{prefix}_namespace"], metrics[f"{prefix}_namespace_pct"], metrics[f"{prefix}_unmapped"] = label, pct, unmapped
    formulas = sum(not (m.formula or "").strip() for m in model.metabolites)
    metrics["no_formula_pct"] = _pct(formulas, n_mets)
    metrics["charge_zero_pct"] = _pct(sum(not m.charge for m in model.metabolites), n_mets)
    metrics["group"] = ("single-compartment export" if metrics["compartments"] == 1
                        else metrics["met_namespace"].split(" (")[0])


def _growth(model, metrics):
    solution = wt_solution(model)
    metrics["wt_status"] = str(solution.status)
    mu = safe_float(solution.objective_value)
    metrics["mu_per_h"] = mu
    metrics["doubling_time_min"] = round(math.log(2) / mu * 60, 2) if mu and mu > 0 else None
    return solution


def _biomass(model, metrics, details):
    rxn_id = find_biomass_reaction(model)
    metrics.update({"biomass_reaction": rxn_id, "biomass_atp_coeff": None, "biomass_n_metabolites": None})
    details["biomass"] = None
    if rxn_id is None:
        return
    rxn = model.reactions.get_by_id(rxn_id)
    details["biomass"] = rxn.build_reaction_string()
    metrics["biomass_n_metabolites"] = len(rxn.metabolites)
    for met, coeff in rxn.metabolites.items():
        if metabolite_base_id(met.id) == "atp" and coeff < 0:
            metrics["biomass_atp_coeff"] = abs(safe_float(coeff))
            break


def _exchanges(model, solution, settings, sections, metrics, details):
    wt = safe_float(solution.objective_value) or 0.0
    fluxes = solution.fluxes if solution.status == "optimal" else {}
    rows = []
    for rxn in model.exchanges:
        row = {"id": rxn.id, "name": rxn.name or "", "lb": safe_float(rxn.lower_bound), "ub": safe_float(rxn.upper_bound),
               "wt_flux": safe_float(fluxes.get(rxn.id)) if hasattr(fluxes, "get") else None,
               "uptake_allowed": rxn.lower_bound < 0, "retained": None}
        known = recall(model, ("exchange_ko_retained", rxn.id), "unknown")
        if sections.essentiality and wt > 0 and known != "unknown":
            row["retained"] = known  # already tested by the Exchange essentiality analysis
        elif sections.essentiality and wt > 0:
            old = rxn.bounds
            try:
                rxn.bounds = (0, 0)
                value = model.slim_optimize(error_value=None)
                row["retained"] = None if value is None else max(0.0, safe_float(value) or 0.0) / wt
            except Exception:
                row["retained"] = None
            finally:
                rxn.bounds = old
        rows.append(row)
    essential = [r["id"] for r in rows if r["retained"] is not None and r["retained"] < settings.essential_retained_max]
    metrics.update({
        "n_exchange": len(rows),
        "n_uptake_allowed": sum(r["uptake_allowed"] for r in rows),
        "n_exchange_unbounded": sum((r["lb"] if r["lb"] is not None else -math.inf) <= settings.unbounded_lb for r in rows),
        "n_essential_exchange": len(essential) if sections.essentiality else None,
    })
    details["exchanges"] = rows
    details["essential_exchanges"] = essential


def _minimal_medium(model, metrics, details):
    report = compute_minimal_medium_report(model, 1.0)
    if "error" in report:
        metrics["min_medium_n"] = None
        details["minimal_medium"] = []
        details["notes"].append("minimal medium: " + report["error"])
        return
    details["minimal_medium"] = [{"id": c["exchange_id"], "name": c["metabolite_name"] or c["exchange_name"], "uptake_flux": c["uptake_flux"]}
                                 for c in report["components"]]
    metrics["min_medium_n"] = len(details["minimal_medium"])


def _network_gaps(model, metrics, details):
    report = compute_network_gaps_report(model)
    if "error" in report:
        details["notes"].append("network gaps: " + report["error"])
        return
    blocked, dead = report["blocked_reactions"], report["dead_end_metabolites"]
    by_subsystem = Counter((r["subsystem"] or UNANNOTATED) for r in blocked)
    metrics.update({
        "blocked_reactions": len(blocked), "deadend_metabolites": len(dead),
        "pct_blocked": _pct(len(blocked), metrics["reactions"]), "pct_deadend": _pct(len(dead), metrics["metabolites"]),
    })
    details["blocked"] = [{"id": r["id"], "name": r["name"], "subsystem": r["subsystem"], "type": r["type"],
                           "lb": r["lower_bound"], "ub": r["upper_bound"]} for r in blocked]
    details["dead_end"] = [{"id": d["id"], "name": d["name"], "compartment": d["compartment"], "reason": d["reason"]} for d in dead]
    details["blocked_by_subsystem"] = dict(by_subsystem)


def _demand_sink(model, metrics, details):
    report = compute_demand_sink_audit(model)
    if "error" in report:
        details["notes"].append("demand & sink: " + report["error"])
        return
    rows = report["rows"]
    metrics.update({
        "n_demand": sum(r["kind"] == "demand" for r in rows), "n_sink": sum(r["kind"] == "sink" for r in rows),
        "n_ds_no_flux": sum(not r["used_in_wt_solution"] for r in rows), "n_ds_essential": sum(r["essential"] for r in rows),
    })
    details["demand_sink"] = [{"id": r["id"], "kind": r["kind"], "metabolite": r["metabolite_id"], "wt_flux": r["wt_flux"],
                               "essential": r["essential"]} for r in rows]


def _balance(model, metrics, details):
    report = compute_balance_report(model)
    counts = report["counts"]
    checkable = counts["balanced"] + counts["unbalanced"]
    metrics.update({"n_unbalanced": counts["unbalanced"], "n_balance_unknown": counts["unknown"],
                    "pct_unbalanced": _pct(counts["unbalanced"], checkable)})
    details["unbalanced"] = [{"id": r["id"], "name": r["name"], "status": r["status"], "problem": r["problem"]}
                             for r in report["reactions"]]


def compute_model_metrics(model, source_name, settings=None, sections=None, progress=None):
    """Statistics and detail lists for one model. `progress(message)` is
    called before each analysis."""
    settings = settings or QCSettings()
    sections = sections or QCSections()
    step = progress or (lambda message: None)
    metrics, details = {}, {"notes": []}

    step("Basic statistics")
    _basic(model, source_name, metrics, details)
    step("Growth (FBA)")
    solution = _growth(model, metrics)
    _biomass(model, metrics, details)
    step("Exchanges" + (" and their essentiality" if sections.essentiality else ""))
    _exchanges(model, solution, settings, sections, metrics, details)

    optional = [
        (sections.minimal_medium and (metrics["mu_per_h"] or 0) > 0, "Minimal medium", _minimal_medium),
        (sections.network_gaps, "Network gaps (blocked reactions)", _network_gaps),
        (sections.demand_sink and (metrics["mu_per_h"] or 0) > 0, "Demand & sink reactions", _demand_sink),
        (sections.balance, "Mass / charge balance", _balance),
    ]
    for enabled, label, fn in optional:
        if not enabled:
            continue
        step(label)
        try:
            fn(model, metrics, details)
        except Exception as exc:  # one failing analysis must not lose the rest
            details["notes"].append(f"{label.lower()}: {exc}")
    return {"metrics": metrics, "details": details}
