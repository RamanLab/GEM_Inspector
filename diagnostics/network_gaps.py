"""Network Gaps tab (on request, in two independent steps).

  1. Dead-end metabolites: GapFind (gapfind.py), each classed as root or
     inherited no-production / no-consumption.
  2. Blocked reactions: FVA with the objective not constrained (every reaction
     that cannot carry flux under the current bounds), then split into those
     linked to a dead end and those that are not (subclasses come later).

Each step runs on its own, so the tab can show the dead ends before the FVA
starts. The FVA is the same one the FROG report can request (fraction 0), so
whichever runs first saves the other.
"""
from annotation.naming import clean_metabolite_display_name, compartment_display_name
from annotation.namespace_mapping import detect_metabolite_namespace_and_map, detect_reaction_namespace_and_map
from core.memo import not_error, remember
from core.shared import classify_reactions, safe_float, subsystem_value
from diagnostics.frog import compute_frog_fva
from diagnostics.gapfind import CLASS_LABELS, compute_dead_ends

BLOCKED_LABELS = {"dead_end_linked": "Dead-end-linked", "not_dead_end_linked": "Not dead-end-linked"}


def compute_dead_end_report(model):
    """The dead-end metabolites with their GapFind class."""
    gaps = compute_dead_ends(model)
    if "error" in gaps:
        return gaps
    compartment_names = {cid: compartment_display_name(cid, name) for cid, name in model.compartments.items()}
    _, _, _, met_to_mnx = detect_metabolite_namespace_and_map(model)
    rows = []
    for met_id, classes in gaps["classes"].items():
        met = model.metabolites.get_by_id(met_id)
        rows.append({
            "id": met.id,
            "metanetx_id": met_to_mnx.get(met.id),
            "name": clean_metabolite_display_name(met),
            "compartment": met.compartment,
            "compartment_name": compartment_names.get(met.compartment, met.compartment),
            "formula": getattr(met, "formula", None),
            "classes": classes,
            "class_label": " + ".join(CLASS_LABELS[c] for c in classes),
            "reactions": sorted(r.id for r in met.reactions),
        })
    return {
        "dead_end_metabolites": rows,
        "class_labels": CLASS_LABELS,
        "note": (
            f"{len(rows)} dead-end metabolite(s) found with GapFind (Kumar et al. 2007) with all exchange reactions "
            "opened, so these are gaps of the network itself, not of the medium. Roots are metabolites that no "
            "reaction can produce (or consume); downstream/upstream ones are inherited from a root."
        ),
    }


def compute_blocked_report(model, zero_cutoff=None):
    """Memoized per model and cutoff. Needs no earlier analysis: the dead ends
    it links to are computed (once) if they are not there yet."""
    return remember(model, ("blocked_reactions", zero_cutoff),
                    lambda: _compute_blocked_report(model, zero_cutoff), cache_if=not_error)


def _compute_blocked_report(model, zero_cutoff):
    dead_ends = compute_dead_ends(model)
    if "error" in dead_ends:
        return dead_ends
    fva = compute_frog_fva(model, 0.0)
    cutoff = model.tolerance if zero_cutoff is None else zero_cutoff
    blocked_ids = sorted(r["id"] for r in fva["reactions"]
                         if abs(r["minimum"] or 0.0) < cutoff and abs(r["maximum"] or 0.0) < cutoff)

    reaction_types = classify_reactions(model)
    _, _, _, rxn_to_mnx = detect_reaction_namespace_and_map(model)
    rows = []
    for rxn_id in blocked_ids:
        rxn = model.reactions.get_by_id(rxn_id)
        linked = sorted(m.id for m in rxn.metabolites if m.id in dead_ends["classes"])
        cls = "dead_end_linked" if linked else "not_dead_end_linked"
        rows.append({
            "id": rxn.id,
            "metanetx_id": rxn_to_mnx.get(rxn.id),
            "name": rxn.name,
            "subsystem": subsystem_value(rxn),
            "type": reaction_types.get(rxn.id, ""),
            "compartments": sorted({m.compartment for m in rxn.metabolites if m.compartment}),
            "reaction_string": rxn.reaction,
            "lower_bound": safe_float(rxn.lower_bound),
            "upper_bound": safe_float(rxn.upper_bound),
            "gene_reaction_rule": getattr(rxn, "gene_reaction_rule", ""),
            "class": cls,
            "class_label": BLOCKED_LABELS[cls],
            "dead_end_metabolites": linked,
        })
    return {
        "blocked_reactions": rows,
        "zero_cutoff": safe_float(cutoff),
        "note": (
            f"{len(rows)} blocked reaction(s): they cannot carry flux under the model's current bounds (flux "
            "variability analysis). Dead-end-linked means the reaction involves a dead-end metabolite. Blocked "
            "reactions are relative to the medium currently applied to the model."
        ),
    }


def compute_network_gaps_report(model, zero_cutoff=None):
    """Both steps together (used by the report and the model comparison)."""
    dead = compute_dead_end_report(model)
    if "error" in dead:
        return dead
    blocked = compute_blocked_report(model, zero_cutoff)
    if "error" in blocked:
        return blocked
    return {**dead, **blocked, "note": dead["note"] + " " + blocked["note"]}
