"""Match the metabolites and reactions of one model to those of another.

Metabolites are matched in passes, most certain first, each metabolite used once:
  id                identical id, same compartment
  mnx               same MetaNetX id, same compartment
  formula+charge    same formula and charge, same compartment (when one candidate each side,
                    or told apart by name)
  name              same normalised name, same compartment
Reactions, using the metabolite matches to write one model's reactions in the other's terms:
  id, mnx, stoichiometry (direction and scale ignored), and stoichiometry ignoring H+ / H2O.

"Strict" similarity counts only the id and mnx matches; "relaxed" counts every match.
"""
import re
from collections import defaultdict

from annotation.namespace_mapping import detect_metabolite_namespace_and_map, detect_reaction_namespace_and_map
from annotation.naming import clean_metabolite_display_name, clean_reaction_display_name

STRICT = {"id", "mnx"}
_KEYWORDS = [("extra", "e"), ("exter", "e"), ("peri", "p"), ("cyto", "c"), ("mito", "m"), ("nucle", "n"),
             ("endoplasm", "r"), ("golgi", "g"), ("lysos", "l"), ("peroxi", "x"), ("vacuol", "v"),
             ("chloro", "h"), ("plast", "h"), ("thylak", "u")]


def compartment_class(model, code):
    """One letter for a compartment however the model names it (c, c0, cytosol -> c)."""
    name = str(model.compartments.get(code, "") or "").lower()
    for word, letter in _KEYWORDS:
        if word in name:
            return letter
    plain = re.sub(r"\d+", "", (code or "").lower())
    return plain[:1] or "?"


def _norm_name(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _formula_key(met):
    formula = (getattr(met, "formula", None) or "").strip()
    if not formula or "*" in formula:
        return None
    try:
        elements = met.elements
    except Exception:
        return None
    if not elements or any(e in ("R", "X") for e in elements):
        return None
    return tuple(sorted(elements.items()))


class Met:
    """What matching needs to know about one metabolite."""
    __slots__ = ("id", "name", "comp", "mnx", "formula", "charge")

    def __init__(self, met, model, mnx):
        self.id, self.name = met.id, _norm_name(clean_metabolite_display_name(met))
        self.comp, self.mnx = compartment_class(model, met.compartment), mnx or None
        self.formula = _formula_key(met)
        self.charge = None if met.charge is None else int(round(float(met.charge)))


def metabolite_infos(model):
    _, _, _, to_mnx = detect_metabolite_namespace_and_map(model)
    return [Met(m, model, to_mnx.get(m.id)) for m in model.metabolites]


def match_metabolites(a_list, b_list):
    """{a id: (b id, method)} between two lists of Met."""
    pairs, used = {}, set()

    def take(a, b, method):
        pairs[a.id] = (b.id, method)
        used.add(b.id)

    by_id = {b.id: b for b in b_list}
    for a in a_list:
        b = by_id.get(a.id)
        if b and b.comp == a.comp:
            take(a, b, "id")

    def passes(key_of, method, tie_name=True):
        pool = defaultdict(list)
        for b in b_list:
            if b.id not in used and key_of(b) is not None:
                pool[key_of(b)].append(b)
        todo = defaultdict(list)
        for a in a_list:
            if a.id not in pairs and key_of(a) is not None:
                todo[key_of(a)].append(a)
        for key, group_a in todo.items():
            group_b = pool.get(key, [])
            if not group_b:
                continue
            if len(group_a) == 1 and len(group_b) == 1:
                take(group_a[0], group_b[0], method)
            elif tie_name:   # isomers share a formula: only pair those told apart by name
                for a in group_a:
                    same = [b for b in group_b if b.id not in used and b.name and b.name == a.name]
                    if len(same) == 1:
                        take(a, same[0], method)
            else:
                for a in group_a:
                    free = [b for b in group_b if b.id not in used]
                    if free:
                        take(a, free[0], method)

    passes(lambda m: (m.mnx, m.comp) if m.mnx else None, "mnx", tie_name=False)
    passes(lambda m: (m.formula, m.charge, m.comp) if m.formula else None, "formula+charge")
    passes(lambda m: (m.name, m.comp) if m.name else None, "name", tie_name=False)
    return pairs


# ---- reactions ---------------------------------------------------------------

_IGNORED = {(("H", 1),), (("H", 2), ("O", 1))}   # H+ and H2O


def _signature(rxn, canon, ignore):
    """The reaction in terms of canonical metabolite ids: direction and scale removed."""
    terms = {}
    for met, coef in rxn.metabolites.items():
        key = canon(met.id)
        if key is None:
            return None
        if key in ignore:
            continue
        terms[key] = terms.get(key, 0.0) + coef
    items = sorted((k, c) for k, c in terms.items() if abs(c) > 1e-9)
    if not items:
        return None
    scale = abs(items[0][1]) * (1 if items[0][1] < 0 else -1)
    return tuple((k, round(c / scale, 5)) for k, c in items)


def match_reactions(model_a, model_b, met_pairs, a_infos, b_infos):
    """{a reaction id: (b reaction id, method)}; met_pairs is {a met id: (b met id, method)}."""
    _, _, _, a_mnx = detect_reaction_namespace_and_map(model_a)
    _, _, _, b_mnx = detect_reaction_namespace_and_map(model_b)
    b_to_a = {b: a for a, (b, _) in met_pairs.items()}
    pairs, used = {}, set()

    def take(ra, rb_id, method):
        pairs[ra.id] = (rb_id, method)
        used.add(rb_id)

    strip = lambda i: re.sub(r"^R_", "", i)
    by_id = {strip(r.id): r.id for r in model_b.reactions}
    for ra in model_a.reactions:
        rb = by_id.get(strip(ra.id))
        if rb and rb not in used:
            take(ra, rb, "id")

    by_mnx = defaultdict(list)
    for rb in model_b.reactions:
        if rb.id not in used and b_mnx.get(rb.id):
            by_mnx[b_mnx[rb.id]].append(rb.id)
    for ra in model_a.reactions:
        if ra.id not in pairs and a_mnx.get(ra.id):
            free = [i for i in by_mnx.get(a_mnx[ra.id], []) if i not in used]
            if free:
                take(ra, free[0], "mnx")

    a_formula = {m.id: m.formula for m in a_infos}
    ignorable = {mid for mid, f in a_formula.items() if f in _IGNORED}
    for method, ignore in (("stoichiometry", set()), ("stoichiometry (no H+/H2O)", ignorable)):
        index = defaultdict(list)
        for rb in model_b.reactions:
            if rb.id in used:
                continue
            sig = _signature(rb, lambda mid: b_to_a.get(mid), ignore)
            if sig:
                index[sig].append(rb.id)
        for ra in model_a.reactions:
            if ra.id in pairs:
                continue
            sig = _signature(ra, lambda mid: mid if mid in a_formula else None, ignore)
            free = [i for i in index.get(sig, []) if i not in used] if sig else []
            if free:
                take(ra, free[0], method)
    return pairs


# ---- similarity ---------------------------------------------------------------

def _overlap(n_a, n_b, pairs):
    matched = len(pairs)
    strict = sum(1 for _, m in pairs.values() if m in STRICT)
    union = lambda k: n_a + n_b - k
    return {"a": n_a, "b": n_b, "matched": matched, "strict_matched": strict,
            "only_a": n_a - matched, "only_b": n_b - matched,
            "jaccard_strict": strict / union(strict) if union(strict) else 0.0,
            "jaccard_relaxed": matched / union(matched) if union(matched) else 0.0,
            "by_method": {m: sum(1 for _, x in pairs.values() if x == m) for m in sorted({x for _, x in pairs.values()})}}


def compare_pair(model_a, model_b, a_infos, b_infos):
    """Similarity of two models plus the full match lists (details) for the report files."""
    met_pairs = match_metabolites(a_infos, b_infos)
    rxn_pairs = match_reactions(model_a, model_b, met_pairs, a_infos, b_infos)
    gene_pairs = {g.id: (g.id, "id") for g in model_a.genes if g.id in {x.id for x in model_b.genes}}
    summary = {"metabolites": _overlap(len(a_infos), len(b_infos), met_pairs),
               "reactions": _overlap(len(model_a.reactions), len(model_b.reactions), rxn_pairs),
               "genes": _overlap(len(model_a.genes), len(model_b.genes), gene_pairs)}
    return summary, met_pairs, rxn_pairs
