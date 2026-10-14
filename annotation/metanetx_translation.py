"""Translate a model's metabolite and reaction ids between namespaces by going
through MetaNetX instead of a direct table.

Every id is first mapped to its MetaNetX (MNX) id using the bundled xref
tables (whichever namespace the model is in is detected automatically), and
the MNX id is then mapped to the chosen target namespace:

  metanetx  MNXM... / MNXR... ids
  bigg, vmh, seed, kegg, metacyc  the ids of that database

Every id ends up as mapped / error / unmapped (see id_renaming). An MNX id can
have several ids in the target namespace; such a metabolite or reaction is an
error ("ambiguous") unless pick_first is set, in which case the first id in
the xref file is used and the alternatives are listed in the report.

Boundary reactions (EX_/DM_/SK_ + metabolite) are renamed from their
metabolite's new id, so "EX_glc__D_e" becomes e.g. "EX_glc_D(e)". Gene ids and
compartment ids are not translated.

Compartment tags (id style):
  keep        the model's own tags ("_c0" stays "_c0")
  underscore  glc__D_c, EX_glc__D_e
  bracket     glc_D[c], EX_glc_D(e)
  auto        the target's own convention (VMH: bracket, BiGG/MetaNetX: underscore, others: keep)
"""
import re

from annotation.id_renaming import apply_renames, count_outcomes, new_outcome, resolve_collisions
from annotation.naming import clean_metabolite_display_name, parse_compartment_suffix
from annotation.namespace_mapping import (
    NS_LABELS,
    detect_metabolite_namespace_and_map,
    detect_reaction_namespace_and_map,
    load_xref,
)
from annotation.xref_index import reverse_index

# target key -> (label, metabolite namespace, reaction namespace) in the xref tables
TARGETS = {
    "metanetx": ("MetaNetX", None, None),
    "bigg": ("BiGG", "bigg.metabolite", "bigg.reaction"),
    "vmh": ("VMH", "vmhmetabolite", "vmhreaction"),
    "seed": ("ModelSEED", "seed.compound", "seed.reaction"),
    "kegg": ("KEGG", "kegg.compound", "kegg.reaction"),
    "metacyc": ("MetaCyc", "metacyc.compound", "metacyc.reaction"),
}

STYLES = ("auto", "keep", "underscore", "bracket")
_AUTO_STYLE = {"vmh": "bracket", "bigg": "underscore", "metanetx": "underscore"}

BOUNDARY_PREFIXES = ("EX_", "DM_", "SK_", "sink_")
REPORT_COLUMNS = ["kind", "original_id", "mnx_id", "target_id", "new_id", "name", "reason"]

_COMPARTMENT_BASE_RE = re.compile(r"^([A-Za-z]+)\d*$")
_MAX_LISTED = 8


def _target_ids(kind, target, mnx):
    """All ids in the target namespace for an MNX id."""
    if target == "metanetx":
        return [mnx]
    namespace = TARGETS[target][1 if kind == "metabolite" else 2]
    return reverse_index("chem" if kind == "metabolite" else "reac", namespace).get(mnx, [])


def _compartment_code(met, parsed_code):
    if parsed_code:
        return parsed_code
    match = _COMPARTMENT_BASE_RE.match(met.compartment or "")
    return match.group(1).lower() if match else None


def _tag(style, code, original_tail):
    if style == "keep":
        return original_tail
    if not code:
        return ""
    return f"_{code}" if style == "underscore" else (f"[{code}]" if style == "bracket" else f"({code})")


def _choose(outcome, candidates, source_base, pick_first):
    """Pick the single target id for an outcome, recording why not when
    there isn't one. Returns the id or None."""
    outcome["target_id"] = " | ".join(candidates[:_MAX_LISTED]) + (" | ..." if len(candidates) > _MAX_LISTED else "")
    if not candidates:
        outcome["reason"] = "MetaNetX id has no entry in the target namespace"
        return None
    if len(candidates) == 1:
        return candidates[0]
    if source_base in candidates:  # the id is already valid in the target namespace
        return source_base
    if pick_first:
        outcome["reason"] = f"{len(candidates)} ids in the target namespace; the first was used"
        return candidates[0]
    outcome["status"] = "error"
    outcome["reason"] = f"Ambiguous: MetaNetX id has {len(candidates)} ids in the target namespace"
    return None


def _plan_metabolites(model, target, style, pick_first, met_to_mnx):
    outcomes = []
    for met in model.metabolites:
        base, code = parse_compartment_suffix(met.id)
        out = new_outcome("metabolite", met, mnx_id=met_to_mnx.get(met.id) or "", target_id="", new_base=None)
        out["name"] = clean_metabolite_display_name(met)
        if not out["mnx_id"]:
            out["reason"] = "No MetaNetX id for this id"
        else:
            chosen = _choose(out, _target_ids("metabolite", target, out["mnx_id"]), base, pick_first)
            if chosen:
                code = _compartment_code(met, code)
                out["new_base"] = chosen
                out["new_id"] = chosen + _tag(style, code, met.id[len(base):])
                out["status"] = "mapped"
        outcomes.append(out)
    return outcomes


def _plan_reactions(model, target, style, pick_first, rxn_to_mnx, met_outcomes):
    by_met_id = {o["original_id"]: o for o in met_outcomes}
    outcomes = []
    for rxn in model.reactions:
        out = new_outcome("reaction", rxn, mnx_id=rxn_to_mnx.get(rxn.id) or "", target_id="")
        out["name"] = rxn.name or ""
        prefix = next((p for p in BOUNDARY_PREFIXES if rxn.id.startswith(p)), None)
        mets = list(rxn.metabolites)

        if prefix and rxn.boundary and len(mets) == 1 and by_met_id[mets[0].id]["status"] == "mapped":
            met_out = by_met_id[mets[0].id]
            rest = rxn.id[len(prefix):]
            base, code = parse_compartment_suffix(rest)
            code = _compartment_code(mets[0], code)
            tag = _tag("underscore" if style == "underscore" else "bracket" if style == "bracket" else "keep", code, rest[len(base):])
            if style == "bracket" and code:
                tag = f"({code})"
            out["mnx_id"] = met_out["mnx_id"]
            out["target_id"] = met_out["new_base"]
            out["new_id"] = prefix + met_out["new_base"] + tag
            out["status"] = "mapped"
        elif not out["mnx_id"]:
            out["reason"] = ("Boundary reaction: its metabolite has no mapping and the reaction has no MetaNetX id"
                             if prefix else "No MetaNetX id for this id")
        else:
            chosen = _choose(out, _target_ids("reaction", target, out["mnx_id"]), rxn.id, pick_first)
            if chosen:
                out["new_id"] = chosen
                out["status"] = "mapped"
        outcomes.append(out)
    return outcomes


def _namespace_summary(model):
    met_ns, met_cov, _, _ = detect_metabolite_namespace_and_map(model)
    rxn_ns, rxn_cov, _, _ = detect_reaction_namespace_and_map(model)
    unknown = "Unrecognized"
    return {
        "metabolites": {"key": met_ns, "label": NS_LABELS.get(met_ns, unknown), "coverage": met_cov},
        "reactions": {"key": rxn_ns, "label": NS_LABELS.get(rxn_ns, unknown), "coverage": rxn_cov},
    }


def _metanetx_summary(model):
    """Share of ids that are MetaNetX ids (MNXM... / MNXR...) after translating to MetaNetX."""
    def share(objects, pattern):
        ids = [parse_compartment_suffix(o.id)[0] for o in objects]
        ids = [i[3:] if i[:3] in BOUNDARY_PREFIXES else i for i in ids]
        return sum(bool(pattern.match(i)) for i in ids) / len(ids) if ids else 0.0
    met_re, rxn_re = re.compile(r"^MNXM\d+$"), re.compile(r"^MNXR\d+$")
    return {"metabolites": {"key": "metanetx", "label": "MetaNetX", "coverage": share(model.metabolites, met_re)},
            "reactions": {"key": "metanetx", "label": "MetaNetX", "coverage": share(model.reactions, rxn_re)}}


def translate_via_metanetx(model, target, style="auto", pick_first=False):
    """Rename the model's metabolite and reaction ids to the target
    namespace through MetaNetX, in place, and return the report. Returns
    {"error": ...} (model untouched) for an unknown target or when the bundled
    MetaNetX tables are missing."""
    if target not in TARGETS:
        return {"error": f"Unknown target namespace '{target}'."}
    if not load_xref("chem") or not load_xref("reac"):
        return {"error": "MetaNetX cross-reference tables not found in the data folder (chem_xref.tsv.gz, reac_xref.tsv.gz)."}
    if style not in STYLES:
        style = "auto"
    if style == "auto":
        style = _AUTO_STYLE.get(target, "keep")

    before = _namespace_summary(model)
    _, _, _, met_to_mnx = detect_metabolite_namespace_and_map(model)
    _, _, _, rxn_to_mnx = detect_reaction_namespace_and_map(model)

    met_outcomes = _plan_metabolites(model, target, style, pick_first, met_to_mnx)
    rxn_outcomes = _plan_reactions(model, target, style, pick_first, rxn_to_mnx, met_outcomes)
    label = TARGETS[target][0]
    resolve_collisions(met_outcomes, label)
    resolve_collisions(rxn_outcomes, label)
    apply_renames(met_outcomes)
    apply_renames(rxn_outcomes)

    outcomes = met_outcomes + rxn_outcomes
    rows = {"mapped": [], "error": [], "unmapped": []}
    for o in outcomes:
        rows[o["status"]].append({k: o.get(k, "") for k in REPORT_COLUMNS})

    already = target != "metanetx" and before["metabolites"]["label"].split(" (")[0] == label
    return {
        "title": f"Translation to {label} via MetaNetX",
        "columns": REPORT_COLUMNS,
        "target": target,
        "target_label": label,
        "style": style,
        "pick_first": bool(pick_first),
        "source_check": {"warning": f"The model's metabolite ids already look like {label} ids; the translation mostly re-derives them." if already else None},
        "before": before,
        "after": _metanetx_summary(model) if target == "metanetx" else _namespace_summary(model),
        "counts": {"metabolites": count_outcomes(outcomes, "metabolite"), "reactions": count_outcomes(outcomes, "reaction")},
        "mapped": rows["mapped"],
        "errors": rows["error"],
        "unmapped": rows["unmapped"],
        "notes": [
            "Each id is mapped to its MetaNetX id first, then to the target namespace.",
            "Gene ids and compartment ids are not translated.",
            "Errors and unmapped ids keep their original ids in the translated model.",
        ],
    }
