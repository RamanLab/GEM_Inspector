"""What the wild-type solution takes up and secretes, and which uptake is the
carbon source and which the nitrogen source.

An exchange reaction with one metabolite and coefficient c carries net flow
c * flux into the model (positive = uptake, negative = secretion). Carbon and
nitrogen atoms come from the metabolite formula. The main source is the uptake
that brings in the most carbon (nitrogen) atoms per hour; CO2 and carbonate
are listed as inorganic carbon and not picked as the carbon source when an
organic one exists.
"""
from annotation.naming import clean_metabolite_display_name
from core.shared import safe_float

TOLERANCE = 1e-9
INORGANIC_CARBON = {"CO2", "CH2O3", "CHO3", "CO3", "CH3O3"}


def _row(rxn, met, net):
    elements = getattr(met, "elements", None) or {}
    formula = getattr(met, "formula", None) or ""
    n_c, n_n = elements.get("C", 0), elements.get("N", 0)
    return {
        "id": rxn.id, "metabolite": met.id, "name": clean_metabolite_display_name(met), "formula": formula,
        "rate": abs(net), "lower_bound": safe_float(rxn.lower_bound), "upper_bound": safe_float(rxn.upper_bound),
        "c_atoms": n_c, "n_atoms": n_n, "carbon": abs(net) * n_c, "nitrogen": abs(net) * n_n,
        "inorganic": formula.replace(" ", "") in INORGANIC_CARBON,
    }


def _sources(rows, key):
    """Uptakes that bring in the element, largest first, each with its share."""
    found = sorted((r for r in rows if r[key] > TOLERANCE), key=lambda r: -r[key])
    total = sum(r[key] for r in found)
    for r in found:
        r["share"] = r[key] / total if total else 0.0
    return found


def uptake_secretion(model, solution):
    fluxes = solution.fluxes
    uptake, secretion, no_formula = [], [], 0
    for rxn in model.exchanges:
        if len(rxn.metabolites) != 1:
            continue
        met, coeff = next(iter(rxn.metabolites.items()))
        net = coeff * float(fluxes[rxn.id])
        if abs(net) <= TOLERANCE:
            continue
        row = _row(rxn, met, net)
        if not row["formula"]:
            no_formula += 1
        (uptake if net > 0 else secretion).append(row)
    uptake.sort(key=lambda r: -r["rate"])
    secretion.sort(key=lambda r: -r["rate"])

    carbon = _sources(uptake, "carbon")
    organic = [r for r in carbon if not r["inorganic"]]
    nitrogen = _sources(uptake, "nitrogen")
    for r in carbon:
        r["share"] = r["carbon"] / sum(x["carbon"] for x in organic) if organic and not r["inorganic"] else None
    return {
        "uptake": uptake, "secretion": secretion, "carbon": carbon, "nitrogen": nitrogen,
        "carbon_main": (organic or carbon or [None])[0], "nitrogen_main": (nitrogen or [None])[0],
        "no_formula": no_formula,
    }
