"""ATP maintenance in a model: NGAM and GAM.

NGAM (non-growth-associated maintenance) is a reaction that hydrolyses ATP and is
forced to run (positive lower bound), usually called ATPM or NGAM. GAM
(growth-associated maintenance) is the ATP hydrolysis written into the biomass
reaction itself: the coefficient of ATP (consumed) alongside ADP, phosphate and
H+ (produced). Both are found by their chemistry first and their names second,
so they are listed even in models with unusual ids. The values are not changed.
"""
import re

from annotation.naming import metabolite_base_id
from core.shared import safe_float

NAME_HINT = re.compile(r"maintenance|\bngam\b|^atpm$", re.IGNORECASE)


def _bases(rxn):
    """({base id: coefficient})."""
    return {metabolite_base_id(m.id): c for m, c in rxn.metabolites.items()}


def _is_atp_hydrolysis(rxn):
    b = _bases(rxn)
    return b.get("atp", 0) < 0 and b.get("h2o", 0) < 0 and b.get("adp", 0) > 0 and b.get("pi", 0) > 0


def find_maintenance(model, objective_ids):
    """{"ngam": [...], "gam": [...]} (see the module docstring)."""
    objective_ids = set(objective_ids)
    ngam = []
    for rxn in model.reactions:
        if rxn.id in objective_ids or len(rxn.metabolites) > 6:
            continue
        hydrolysis = _is_atp_hydrolysis(rxn)
        named = bool(NAME_HINT.search(rxn.id) or NAME_HINT.search(rxn.name or ""))
        if (hydrolysis and (rxn.lower_bound > 0 or named)) or (named and "atp" in _bases(rxn)):
            ngam.append({"id": rxn.id, "name": rxn.name, "equation": rxn.reaction,
                         "lower_bound": safe_float(rxn.lower_bound), "upper_bound": safe_float(rxn.upper_bound),
                         "forced": rxn.lower_bound > 0})
    gam = []
    for rid in objective_ids:
        if rid not in model.reactions:
            continue
        b = _bases(model.reactions.get_by_id(rid))
        if b.get("atp", 0) < 0 and b.get("adp", 0) > 0:
            gam.append({"reaction": rid, "coefficient": abs(b["atp"])})
    return {"ngam": ngam, "gam": gam}
