"""Compare two models component by component.

For genes, metabolites, reactions and the biomass reaction's components,
reports what the two models share and what is only in one of them, after
first reporting the id naming conventions of each model and whether they
agree. Every listed item carries its MetaNetX id (where one is known) so the
lists can be cross-referenced outside this app.

Items are matched in passes, most exact first, and each id is used once:
  1. identical id
  2. same MetaNetX id (and the same compartment, for metabolites)
  3. same id once the compartment tag is stripped and case is ignored
     (metabolites only), which catches "glc_D_c" vs "glc_D[c]"
"""
import re

from annotation.naming import (
    clean_metabolite_display_name,
    detect_compartment_convention,
    metabolite_base_id,
)
from annotation.namespace_mapping import (
    NS_LABELS,
    detect_metabolite_namespace_and_map,
    detect_reaction_namespace_and_map,
)
from core.shared import find_biomass_reaction, safe_float

_COMPARTMENT_BASE_RE = re.compile(r"^([A-Za-z]+)\d*$")
_UNRECOGNIZED = "Unrecognized (not in bundled BiGG/VMH/SEED/KEGG/MetaCyc reference)"


def _compartment_group(met):
    """Compartment code with any numeric index dropped ("c0" -> "c")."""
    match = _COMPARTMENT_BASE_RE.match(met.compartment or "")
    return match.group(1).lower() if match else (met.compartment or "").lower()


def _item(obj_id, name, mnx, group=None, coefficient=None):
    return {"id": obj_id, "name": name, "mnx": mnx, "group": group, "coefficient": coefficient}


# --- Naming conventions ------------------------------------------------------

def describe_naming(model):
    """Namespace/compartment conventions of one model plus its id -> MetaNetX
    maps. Returns (summary, met_to_mnx, rxn_to_mnx)."""
    met_ns, met_cov, met_ex, met_to_mnx = detect_metabolite_namespace_and_map(model)
    rxn_ns, rxn_cov, rxn_ex, rxn_to_mnx = detect_reaction_namespace_and_map(model)
    conv = detect_compartment_convention(model)
    summary = {
        "metabolites": {"key": met_ns, "label": NS_LABELS.get(met_ns, _UNRECOGNIZED), "example": met_ex, "coverage": met_cov},
        "reactions": {"key": rxn_ns, "label": NS_LABELS.get(rxn_ns, _UNRECOGNIZED), "example": rxn_ex, "coverage": rxn_cov},
        "compartments": {"key": conv["style"], "label": conv["label"], "example": conv["example"], "coverage": conv["coverage"]},
    }
    return summary, met_to_mnx, rxn_to_mnx


def _consistency(a, b):
    """True/False when both sides were recognized, None when neither could be."""
    if a["key"] is None and b["key"] is None:
        return None
    return a["key"] == b["key"]


def compare_naming(summary_a, summary_b):
    rows = []
    for key, title in (("metabolites", "Metabolite id namespace"),
                       ("reactions", "Reaction id namespace"),
                       ("compartments", "Compartment tag convention")):
        a, b = summary_a[key], summary_b[key]
        rows.append({"aspect": title, "model_a": a, "model_b": b, "consistent": _consistency(a, b)})
    verdicts = [r["consistent"] for r in rows]
    return {
        "rows": rows,
        "all_consistent": all(v is True for v in verdicts),
        "any_inconsistent": any(v is False for v in verdicts),
    }


# --- Matching ----------------------------------------------------------------

def _key_by_id(item):
    return item["id"]


def _key_by_mnx(item):
    return (item["mnx"], item["group"]) if item["mnx"] else None


def _key_by_normalized_id(item):
    base = metabolite_base_id(item["id"])
    return (base, item["group"]) if item["group"] else base


def match_items(items_a, items_b, passes):
    """Pair items from the two models. `passes` is a list of (label, key_fn);
    an item is matched at the first pass where both sides yield the same key.
    Returns (shared, only_a, only_b), each a list of row dicts."""
    unmatched_a = list(items_a)
    unmatched_b = list(items_b)
    shared = []

    for label, key_fn in passes:
        index_b = {}
        for item in unmatched_b:
            key = key_fn(item)
            if key is not None:
                index_b.setdefault(key, []).append(item)
        used_b, still_a = set(), []
        for item in unmatched_a:
            key = key_fn(item)
            candidates = index_b.get(key) if key is not None else None
            partner = next((c for c in candidates if id(c) not in used_b), None) if candidates else None
            if partner is None:
                still_a.append(item)
                continue
            used_b.add(id(partner))
            shared.append(_shared_row(item, partner, label))
        unmatched_a = still_a
        unmatched_b = [i for i in unmatched_b if id(i) not in used_b]

    return shared, [_single_row(i, "a") for i in unmatched_a], [_single_row(i, "b") for i in unmatched_b]


def _shared_row(a, b, matched_by):
    row = {
        "id_a": a["id"], "id_b": b["id"], "name": a["name"] or b["name"],
        "metanetx_id": a["mnx"] or b["mnx"] or "", "matched_by": matched_by,
    }
    if a["coefficient"] is not None or b["coefficient"] is not None:
        row["coefficient_a"], row["coefficient_b"] = a["coefficient"], b["coefficient"]
    return row


def _single_row(item, side):
    row = {
        "id_a": item["id"] if side == "a" else "", "id_b": item["id"] if side == "b" else "",
        "name": item["name"], "metanetx_id": item["mnx"] or "", "matched_by": "",
    }
    if item["coefficient"] is not None:
        row["coefficient_a" if side == "a" else "coefficient_b"] = item["coefficient"]
    return row


def _section(shared, only_a, only_b):
    return {
        "shared": shared, "only_a": only_a, "only_b": only_b,
        "counts": {"shared": len(shared), "only_a": len(only_a), "only_b": len(only_b),
                   "total_a": len(shared) + len(only_a), "total_b": len(shared) + len(only_b)},
    }


METABOLITE_PASSES = [("id", _key_by_id), ("MetaNetX id", _key_by_mnx), ("id without compartment tag", _key_by_normalized_id)]
REACTION_PASSES = [("id", _key_by_id), ("MetaNetX id", _key_by_mnx)]
GENE_PASSES = [("id", _key_by_id)]


# --- Components --------------------------------------------------------------

def _metabolite_items(mets, met_to_mnx):
    return [_item(m.id, clean_metabolite_display_name(m), met_to_mnx.get(m.id), _compartment_group(m)) for m in mets]


def compare_genes(model_a, model_b):
    items = lambda model: [_item(g.id, g.name or "", None) for g in model.genes]
    return _section(*match_items(items(model_a), items(model_b), GENE_PASSES))


def compare_metabolites(model_a, model_b, mnx_a, mnx_b):
    return _section(*match_items(
        _metabolite_items(model_a.metabolites, mnx_a), _metabolite_items(model_b.metabolites, mnx_b), METABOLITE_PASSES))


def compare_reactions(model_a, model_b, mnx_a, mnx_b):
    items = lambda model, mnx: [_item(r.id, r.name or "", mnx.get(r.id)) for r in model.reactions]
    return _section(*match_items(items(model_a, mnx_a), items(model_b, mnx_b), REACTION_PASSES))


def _biomass_info(model, met_to_mnx):
    """The biomass reaction's identity and its components (every metabolite
    in the reaction, with its coefficient), or None when there isn't one."""
    rxn_id = find_biomass_reaction(model)
    if rxn_id is None:
        return None
    rxn = model.reactions.get_by_id(rxn_id)
    items = [
        _item(m.id, clean_metabolite_display_name(m), met_to_mnx.get(m.id), _compartment_group(m), safe_float(coeff))
        for m, coeff in rxn.metabolites.items()
    ]
    return {"id": rxn.id, "name": rxn.name or "", "n_components": len(items), "items": items}


def compare_biomass(model_a, model_b, mnx_a, mnx_b):
    info_a, info_b = _biomass_info(model_a, mnx_a), _biomass_info(model_b, mnx_b)
    result = {
        "reaction_a": {k: info_a[k] for k in ("id", "name", "n_components")} if info_a else None,
        "reaction_b": {k: info_b[k] for k in ("id", "name", "n_components")} if info_b else None,
    }
    if info_a is None or info_b is None:
        result["error"] = "A biomass/objective reaction could not be identified in " + (
            "both models." if info_a is None and info_b is None else ("model A." if info_a is None else "model B."))
        return result
    result.update(_section(*match_items(info_a["items"], info_b["items"], METABOLITE_PASSES)))
    return result


# --- Entry point -------------------------------------------------------------

def compare_models(model_a, model_b):
    """Full comparison report for the Compare Models tab."""
    naming_a, met_mnx_a, rxn_mnx_a = describe_naming(model_a)
    naming_b, met_mnx_b, rxn_mnx_b = describe_naming(model_b)
    return {
        "labels": {"a": model_a.id or "Model A", "b": model_b.id or "Model B"},
        "naming": compare_naming(naming_a, naming_b),
        "genes": compare_genes(model_a, model_b),
        "metabolites": compare_metabolites(model_a, model_b, met_mnx_a, met_mnx_b),
        "reactions": compare_reactions(model_a, model_b, rxn_mnx_a, rxn_mnx_b),
        "biomass": compare_biomass(model_a, model_b, met_mnx_a, met_mnx_b),
    }
