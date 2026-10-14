"""Shared machinery for renaming metabolite and reaction ids in place.

Used by the SEED -> VMH translation and the MetaNetX translations. A caller
builds one "outcome" per object (see new_outcome), fills in new_id/status,
then runs resolve_collisions and apply_renames. Every outcome ends in one of
three statuses:

  mapped    renamed to its new id
  error     had a candidate but could not be renamed safely (ambiguous, or the
            new id would collide with another id); the original id is kept
  unmapped  no candidate at all; the original id is kept
"""


def new_outcome(kind, obj, **extra):
    """Blank outcome for one metabolite or reaction (status "unmapped")."""
    outcome = {"kind": kind, "obj": obj, "original_id": obj.id, "new_id": obj.id,
               "name": "", "status": "unmapped", "reason": ""}
    outcome.update(extra)
    return outcome


def resolve_collisions(outcomes, label="new"):
    """Turn any mapped outcome whose new id would clash with another id in
    the model into an error that keeps its original id. Repeats until stable,
    since keeping one original id can create a new clash for another."""
    for _ in range(len(outcomes) + 1):
        holder = {}
        for o in outcomes:
            if o["status"] != "mapped" or o["new_id"] == o["original_id"]:
                holder[o["original_id"]] = o["original_id"]
        changed = False
        for o in outcomes:
            if o["status"] != "mapped" or o["new_id"] == o["original_id"]:
                continue
            if o["new_id"] in holder:
                o["status"] = "error"
                o["reason"] = f"{label} id '{o['new_id']}' is already used by '{holder[o['new_id']]}'"
                o["new_id"] = o["original_id"]
                changed = True
            else:
                holder[o["new_id"]] = o["original_id"]
        if not changed:
            return


def apply_renames(outcomes):
    """Rename in two phases (to temporary ids, then to the final ones) so a
    new id that equals another object's old id can't collide mid-way."""
    todo = [o for o in outcomes if o["status"] == "mapped" and o["new_id"] != o["original_id"]]
    for i, o in enumerate(todo):
        o["obj"].id = f"__rename_tmp_{i}__"
    for o in todo:
        o["obj"].id = o["new_id"]


def count_outcomes(outcomes, kind):
    rows = [o for o in outcomes if o["kind"] == kind]
    return {
        "total": len(rows),
        "mapped": sum(o["status"] == "mapped" for o in rows),
        "errors": sum(o["status"] == "error" for o in rows),
        "unmapped": sum(o["status"] == "unmapped" for o in rows),
    }
