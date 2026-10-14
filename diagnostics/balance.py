"""Reaction mass/charge balance checks (the "Balance" column of the Reactions
table and the Diagnostics > Reaction Balance tab).

Status values:
  balanced    every element (and charge, where metabolites have charges) sums to zero
  unbalanced  at least one element or the charge does not balance
  unknown     one or more metabolites has no usable chemical formula, so it can't be checked
  n/a         boundary reactions (exchange/demand/sink) and the biomass/objective reaction,
              which are not expected to balance
"""
from cobra.util import linear_reaction_coefficients

from core.memo import remember

TOL = 1e-6


def _is_not_applicable(rxn, objective_ids):
    return rxn.boundary or rxn.id in objective_ids or "biomass" in rxn.id.lower()


def analyse_reaction(rxn, objective_ids=frozenset()):
    """Return {status, imbalance{element: net}, missing_formula[ids], missing_charge[ids]}.

    imbalance is (products - reactants) per element, so a positive value means the
    product side has more of that element than the reactant side.
    """
    if _is_not_applicable(rxn, objective_ids):
        return {"status": "n/a", "imbalance": {}, "missing_formula": [], "missing_charge": []}

    mets = list(rxn.metabolites)
    missing_formula = [m.id for m in mets if not (getattr(m, "formula", None) or "").strip()]
    missing_charge = [m.id for m in mets if getattr(m, "charge", None) is None]
    if missing_formula:
        return {"status": "unknown", "imbalance": {}, "missing_formula": missing_formula,
                "missing_charge": missing_charge}

    totals = {}
    try:
        for met, coef in rxn.metabolites.items():
            for el, n in met.elements.items():
                totals[el] = totals.get(el, 0.0) + coef * n
    except Exception:
        return {"status": "unknown", "imbalance": {}, "missing_formula": [m.id for m in mets],
                "missing_charge": missing_charge}
    if not missing_charge:
        totals["charge"] = sum(coef * (met.charge or 0) for met, coef in rxn.metabolites.items())

    imbalance = {k: v for k, v in totals.items() if abs(v) > TOL}
    return {"status": "unbalanced" if imbalance else "balanced", "imbalance": imbalance,
            "missing_formula": [], "missing_charge": missing_charge}


def short_text(info):
    """One-line summary for the table cell tooltip."""
    if info["status"] == "unbalanced":
        return ", ".join(f"{k} {v:+g}" for k, v in sorted(info["imbalance"].items()))
    if info["status"] == "unknown":
        return "No formula for: " + ", ".join(info["missing_formula"][:6])
    return ""


def objective_reaction_ids(model):
    try:
        return {r.id for r in linear_reaction_coefficients(model)}
    except Exception:
        return set()


def problem_sentence(info):
    if info["status"] == "unknown":
        return ("Cannot be checked: these metabolites have no chemical formula — "
                + ", ".join(info["missing_formula"]) + ". Add formulas (e.g. from a database) to test the reaction.")
    parts = []
    for el, v in sorted(info["imbalance"].items()):
        n = f"{abs(v):g}"
        if el == "charge":
            parts.append(f"net charge differs by {n} (products {'more positive' if v > 0 else 'more negative'} than reactants)")
        elif v > 0:
            parts.append(f"{n} {el} appear on the product side with no matching source ({n} {el} missing from the reactants)")
        else:
            parts.append(f"{n} {el} on the reactant side do not end up in any product ({n} {el} missing from the products)")
    text = "; ".join(parts) + "."
    hints = []
    if set(info["imbalance"]) <= {"H", "charge"}:
        hints.append("Often a missing proton (H+) or a wrong protonation state/charge on one metabolite.")
    if set(info["imbalance"]) <= {"H", "O", "charge"} and "O" in info["imbalance"]:
        hints.append("A missing water (H2O) is a common cause.")
    if "P" in info["imbalance"]:
        hints.append("A missing phosphate (Pi/PPi) is a common cause.")
    if not hints:
        hints.append("Check the stoichiometric coefficients and the formulas of the metabolites involved.")
    return text + " " + " ".join(hints)


def analyse_all_reactions(model):
    """{reaction id: analyse_reaction result} for the whole model, computed once."""
    def compute():
        objective_ids = objective_reaction_ids(model)
        return {rxn.id: analyse_reaction(rxn, objective_ids) for rxn in model.reactions}
    return remember(model, "balance_by_reaction", compute)


def compute_balance_report(model):
    return remember(model, "balance_report", lambda: _compute_balance_report(model))


def _compute_balance_report(model):
    analysed = analyse_all_reactions(model)
    counts = {"balanced": 0, "unbalanced": 0, "unknown": 0, "n/a": 0}
    problems = []
    for rxn in model.reactions:
        info = analysed[rxn.id]
        counts[info["status"]] += 1
        if info["status"] in ("unbalanced", "unknown"):
            problems.append({
                "id": rxn.id,
                "name": rxn.name or "",
                "status": info["status"],
                "imbalance": info["imbalance"],
                "problem": problem_sentence(info),
                "missing_formula": info["missing_formula"],
                "missing_charge": info["missing_charge"],
                "reaction": rxn.build_reaction_string(use_metabolite_names=False),
                "metabolites": [
                    {"id": m.id, "name": m.name or "", "formula": getattr(m, "formula", None) or "",
                     "charge": getattr(m, "charge", None), "coefficient": c,
                     "compartment": m.compartment}
                    for m, c in rxn.metabolites.items()
                ],
            })
    return {"counts": counts, "reactions": problems, "total": len(model.reactions)}
