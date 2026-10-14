"""Translate a ModelSEED-namespace model to the VMH namespace.

Metabolite and reaction ids are looked up (compartment tag stripped) in the
bundled translation tables and renamed in place. Every id ends up in exactly
one of three groups:

  mapped    renamed to its VMH id
  error     has a table entry but couldn't be renamed safely: the table lists
            several VMH ids for it (ambiguous), or the new id would collide
            with another id in the model. The original id is kept.
  unmapped  no entry in the table. The original id is kept.

Boundary reactions (EX_/DM_/SK_ + a metabolite id) aren't in the reaction
table, so they are translated through the metabolite table instead. Gene ids
and compartment ids are left untouched.

Output id styles:
  "vmh"   VMH conventions: metabolites "h2o[c]", exchanges "EX_h2o(e)"
  "keep"  the model's own compartment tags: "h2o_c0", "EX_h2o_e0"
"""
import re

from annotation.id_renaming import apply_renames, count_outcomes, new_outcome, resolve_collisions
from annotation.naming import clean_metabolite_display_name, parse_compartment_suffix
from annotation.namespace_mapping import (
    NS_LABELS,
    detect_metabolite_namespace_and_map,
    detect_reaction_namespace_and_map,
)
from annotation.translation_tables import load_translation_table

STYLE_VMH = "vmh"
STYLE_KEEP = "keep"

REPORT_COLUMNS = ["kind", "original_id", "seed_id", "vmh_id", "new_id", "name", "reason"]

BOUNDARY_PREFIXES = ("EX_", "DM_", "SK_", "sink_")

_SEED_METABOLITE_RE = re.compile(r"^cpd\d{5}$")
_SEED_REACTION_RE = re.compile(r"^rxn\d{5}$")
_COMPARTMENT_BASE_RE = re.compile(r"^([A-Za-z]+)\d*$")

# Fraction of ids that must look like SEED ids before a model is treated as
# a ModelSEED model rather than one that's already in another namespace.
SEED_LIKE_THRESHOLD = 0.5


def _outcome(kind, obj, seed_id):
    return new_outcome(kind, obj, seed_id=seed_id, vmh_id="")


def _compartment_code(met, parsed_code):
    """Compartment code for a VMH-style tag: the id's own tag, else the
    metabolite's compartment with any numeric index dropped."""
    if parsed_code:
        return parsed_code
    match = _COMPARTMENT_BASE_RE.match(met.compartment or "")
    return match.group(1).lower() if match else None


def _lookup(table, seed_id, outcome, missing_reason):
    """Look seed_id up in a table, recording the outcome. Returns the VMH id
    when there is exactly one."""
    targets = table.get(seed_id)
    if not targets:
        outcome["reason"] = missing_reason
        return None
    outcome["vmh_id"] = " | ".join(targets)
    if len(targets) > 1:
        outcome["status"] = "error"
        outcome["reason"] = "Ambiguous: the table lists several VMH ids for this SEED id"
        return None
    return targets[0]


def _plan_metabolites(model, table, style):
    outcomes = []
    for met in model.metabolites:
        base, code = parse_compartment_suffix(met.id)
        out = _outcome("metabolite", met, base)
        out["name"] = clean_metabolite_display_name(met)
        vmh = _lookup(table, base, out, "Not in the metabolite translation table")
        if vmh:
            if style == STYLE_VMH:
                code = _compartment_code(met, code)
                out["new_id"] = f"{vmh}[{code}]" if code else vmh
            else:
                out["new_id"] = vmh + met.id[len(base):]
            out["status"] = "mapped"
        outcomes.append(out)
    return outcomes


def _plan_reactions(model, met_table, rxn_table, style):
    outcomes = []
    for rxn in model.reactions:
        out = _outcome("reaction", rxn, rxn.id)
        out["name"] = rxn.name or ""
        prefix = next((p for p in BOUNDARY_PREFIXES if rxn.id.startswith(p)), None)

        if prefix:
            rest = rxn.id[len(prefix):]
            base, code = parse_compartment_suffix(rest)
            out["seed_id"] = base
            vmh = _lookup(met_table, base, out, "Boundary reaction: metabolite not in the metabolite translation table")
            if vmh:
                if style == STYLE_VMH:
                    out["new_id"] = f"{prefix}{vmh}({code})" if code else prefix + vmh
                else:
                    out["new_id"] = prefix + vmh + rest[len(base):]
                out["status"] = "mapped"
        else:
            base, _ = parse_compartment_suffix(rxn.id)
            out["seed_id"] = base
            vmh = _lookup(rxn_table, base, out, "Not in the reaction translation table")
            if vmh:
                out["new_id"] = vmh if style == STYLE_VMH else vmh + rxn.id[len(base):]
                out["status"] = "mapped"
        outcomes.append(out)
    return outcomes


def check_seed_source(model):
    """How SEED-like the model's ids are (cpd#####/rxn##### once the
    compartment tag is stripped), so a model that is already in another
    namespace can be flagged before translating."""
    met_ids = [parse_compartment_suffix(m.id)[0] for m in model.metabolites]
    rxn_ids = [parse_compartment_suffix(r.id)[0] for r in model.reactions]
    met_like = sum(bool(_SEED_METABOLITE_RE.match(i)) for i in met_ids)
    rxn_like = sum(bool(_SEED_REACTION_RE.match(i)) for i in rxn_ids)
    met_frac = met_like / len(met_ids) if met_ids else 0.0
    rxn_frac = rxn_like / len(rxn_ids) if rxn_ids else 0.0
    looks_like_seed = met_frac >= SEED_LIKE_THRESHOLD or rxn_frac >= SEED_LIKE_THRESHOLD
    return {
        "metabolites": {"seed_like": met_like, "total": len(met_ids), "fraction": met_frac},
        "reactions": {"seed_like": rxn_like, "total": len(rxn_ids), "fraction": rxn_frac},
        "looks_like_seed": looks_like_seed,
        "warning": None if looks_like_seed else (
            "Few ids in this model look like ModelSEED ids (cpd##### / rxn#####), "
            "so it may not be a SEED-namespace model. Most ids will probably be unmapped."
        ),
    }


def _namespace_after(model):
    met_ns, met_cov, _, _ = detect_metabolite_namespace_and_map(model)
    rxn_ns, rxn_cov, _, _ = detect_reaction_namespace_and_map(model)
    return {
        "metabolites": {"label": NS_LABELS.get(met_ns, "Unrecognized"), "coverage": met_cov},
        "reactions": {"label": NS_LABELS.get(rxn_ns, "Unrecognized"), "coverage": rxn_cov},
    }


def translate_seed_to_vmh(model, style=STYLE_VMH):
    """Rename the model's metabolite and reaction ids from SEED to VMH, in
    place, and return the report. Returns {"error": ...} (model untouched)
    when a translation table is missing from the data folder."""
    met_table = load_translation_table("metabolite")
    rxn_table = load_translation_table("reaction")
    if met_table is None or rxn_table is None:
        return {"error": "Translation tables not found in the data folder (MetaboliteTranslationTable.txt, ReactionTranslationTable.txt)."}
    if style not in (STYLE_VMH, STYLE_KEEP):
        style = STYLE_VMH

    source_check = check_seed_source(model)

    met_outcomes = _plan_metabolites(model, met_table, style)
    rxn_outcomes = _plan_reactions(model, met_table, rxn_table, style)
    resolve_collisions(met_outcomes, "VMH")
    resolve_collisions(rxn_outcomes, "VMH")
    apply_renames(met_outcomes)
    apply_renames(rxn_outcomes)

    outcomes = met_outcomes + rxn_outcomes
    rows = {"mapped": [], "error": [], "unmapped": []}
    for o in outcomes:
        rows[o["status"]].append({k: o[k] for k in ("kind", "original_id", "seed_id", "vmh_id", "new_id", "name", "reason")})

    return {
        "title": "SEED -> VMH translation report",
        "columns": REPORT_COLUMNS,
        "style": style,
        "source_check": source_check,
        "counts": {"metabolites": count_outcomes(outcomes, "metabolite"), "reactions": count_outcomes(outcomes, "reaction")},
        "mapped": rows["mapped"],
        "errors": rows["error"],
        "unmapped": rows["unmapped"],
        "after": _namespace_after(model),
        "notes": [
            "Gene ids and compartment ids are not translated.",
            "Errors and unmapped ids keep their original ids in the translated model.",
        ],
    }
