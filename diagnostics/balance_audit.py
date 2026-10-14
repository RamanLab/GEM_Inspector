"""Audit of the unbalanced reactions: why each one doesn't balance and what to
do about it.

For every unbalanced reaction (and, optionally, every reaction that can't be
checked because metabolites lack formulas) the audit
  1. looks up each metabolite's MetaNetX id and its ids in BiGG / VMH /
     ModelSEED / KEGG / MetaCyc (the "original database" mapping), and flags
     ids that don't map or that belong to a different namespace than the
     rest of the model;
  2. checks each metabolite's formula and charge: against the MetaNetX
     reference when data/chem_prop.tsv is present (see annotation.chem_reference),
     and always against the same compound in other compartments of the model;
  3. proposes fixes and verifies each one by recomputing the balance:
       - use the reference / consistent formula for a metabolite,
       - add or remove common species (H+, H2O, phosphate, CO2, ...),
       - change one metabolite's formula or charge,
       - change one metabolite's stoichiometric coefficient,
       - fill in a missing formula from the reference.
"""
from itertools import combinations, product

from cobra import Metabolite

from annotation.chem_reference import load_chem_properties
from annotation.naming import clean_metabolite_display_name, metabolite_base_id_preserve_case
from annotation.namespace_mapping import (
    CHEM_NAMESPACES,
    NS_LABELS,
    detect_metabolite_namespace_and_map,
)
from annotation.xref_index import namespaces_containing, reverse_index
from diagnostics.balance import TOL, compute_balance_report

# (label, namespace key in the xref table) shown in the mapping columns.
DATABASES = (
    ("BiGG", "bigg.metabolite"),
    ("VMH", "vmhmetabolite"),
    ("ModelSEED", "seed.compound"),
    ("KEGG", "kegg.compound"),
    ("MetaCyc", "metacyc.compound"),
)
_MAX_IDS_SHOWN = 3

# Species commonly missing from, or surplus in, an unbalanced reaction:
# (short id, name, formula, charge)
COMMON_SPECIES = (
    ("h", "proton (H+)", "H", 1),
    ("h2o", "water", "H2O", 0),
    ("pi", "phosphate", "HO4P", -2),
    ("ppi", "diphosphate", "HO7P2", -3),
    ("co2", "carbon dioxide", "CO2", 0),
    ("nh4", "ammonium", "H4N", 1),
)
_MAX_SPECIES_COEFFICIENT = 3
_MAX_FORMULA_CHANGE_ATOMS = 6
_MAX_SUGGESTIONS = 4

# Rank of each suggestion type when choosing the headline fix.
_TYPE_ORDER = {"reference": 0, "fill_formula": 0, "consistency": 1, "species": 2, "formula": 3, "coefficient": 4, "check": 9}


# --- Formulas ------------------------------------------------------------------

def elements_of(formula):
    """Element counts of a formula string, or None when it can't be used for
    balancing (empty, unparsable, or a generic group such as R / X / *)."""
    formula = (formula or "").strip()
    if not formula or "*" in formula:
        return None
    try:
        elements = Metabolite("x", formula=formula).elements
    except Exception:
        return None
    if not elements or any(el in ("R", "X") for el in elements):
        return None
    return dict(elements)


def hill(elements):
    """Formula string from element counts (C, H, then alphabetical)."""
    order = sorted(elements, key=lambda e: (e not in ("C", "H"), "CH".index(e) if e in ("C", "H") else 0, e))
    return "".join(f"{e}{int(n) if n != 1 else ''}" for e, n in ((e, elements[e]) for e in order) if n)


def _same_formula(a, b):
    ea, eb = elements_of(a), elements_of(b)
    return ea is not None and ea == eb


def _fmt_charge(charge):
    return "?" if charge is None else f"{charge:+d}" if charge else "0"


# --- Balance arithmetic -----------------------------------------------------------

def _net(items):
    """Net (products - reactants) element and charge totals for a list of
    (coefficient, elements, charge). Charge is only included when every
    metabolite has one. Returns None if any metabolite has no usable formula."""
    totals, charge_known, charge = {}, True, 0.0
    for coef, elements, ch in items:
        if elements is None:
            return None
        for el, n in elements.items():
            totals[el] = totals.get(el, 0.0) + coef * n
        if ch is None:
            charge_known = False
        else:
            charge += coef * ch
    if charge_known:
        totals["charge"] = charge
    return {k: v for k, v in totals.items() if abs(v) > TOL}


def _met_items(rxn_info, overrides=None, coefficient_override=None):
    overrides = overrides or {}
    items = []
    for m in rxn_info["metabolites"]:
        formula, charge = overrides.get(m["id"], (m["formula"], m["charge"]))
        coef = m["coefficient"] + (coefficient_override[1] if coefficient_override and coefficient_override[0] == m["id"] else 0)
        items.append((coef, elements_of(formula), charge))
    return items


# --- Metabolite checks --------------------------------------------------------------

class _Context:
    """Per-model lookups shared by all reactions."""

    def __init__(self, model):
        self.model = model
        met_ns, _, _, self.met_to_mnx = detect_metabolite_namespace_and_map(model)
        self.model_namespace = met_ns
        self.reference = load_chem_properties()
        self.by_mnx = {}
        self.by_base = {}
        for met in model.metabolites:
            mnx = self.met_to_mnx.get(met.id)
            if mnx:
                self.by_mnx.setdefault(mnx, []).append(met)
            self.by_base.setdefault(metabolite_base_id_preserve_case(met.id).lower(), []).append(met)
        self.species_index = {}
        for met in model.metabolites:
            elements = elements_of(met.formula)
            if elements is not None:
                self.species_index.setdefault((tuple(sorted(elements.items())), met.charge, met.compartment), met.id)

    def databases(self, mnx):
        """{database label: [ids]} for an MNX id."""
        found = {}
        for label, namespace in DATABASES:
            ids = reverse_index("chem", namespace).get(mnx, []) if mnx else []
            if ids:
                found[label] = ids
        return found

    def mapping_check(self, met, mnx):
        base = metabolite_base_id_preserve_case(met.id)
        if not mnx:
            return "No MetaNetX id: this id is not in any bundled namespace"
        namespaces = namespaces_containing("chem", base, CHEM_NAMESPACES)
        if self.model_namespace and namespaces and self.model_namespace not in namespaces:
            labels = sorted({NS_LABELS.get(n, n) for n in namespaces})
            return (f"Id is not in the model's namespace ({NS_LABELS.get(self.model_namespace, self.model_namespace)}); "
                    f"found in {', '.join(labels)}")
        return "OK"

    def formula_check(self, met, mnx):
        """(status text, reference dict or None, consistent-alternative or None)."""
        issues, ref = [], None
        elements = elements_of(met.formula)
        if not (met.formula or "").strip():
            issues.append("no formula")
        elif elements is None:
            issues.append(f"formula '{met.formula}' can't be used (generic group or unparsable)")

        if self.reference is not None and mnx and mnx in self.reference:
            ref = self.reference[mnx]
            ref_elements = elements_of(ref["formula"])
            if elements is not None and ref_elements is not None and elements != ref_elements:
                issues.append(f"formula {met.formula} differs from MetaNetX reference {ref['formula']}")
            if met.charge is not None and ref["charge"] is not None and met.charge != ref["charge"]:
                issues.append(f"charge {_fmt_charge(met.charge)} differs from MetaNetX reference {_fmt_charge(ref['charge'])}")

        alternative = None
        peers = [p for p in self.by_mnx.get(mnx, []) if p.id != met.id] if mnx else []
        if peers and elements is not None:
            peer_formulas = {(hill(e), p.charge) for p in peers if (e := elements_of(p.formula)) is not None}
            if peer_formulas and (hill(elements), met.charge) not in peer_formulas:
                alternative = sorted(peer_formulas, key=lambda x: str(x))[0]
                issues.append(f"differs from the same compound in another compartment ({alternative[0]}, charge {_fmt_charge(alternative[1])})")
        return ("; ".join(issues) if issues else "OK"), ref, alternative


# --- Suggestions ------------------------------------------------------------------------

def _imbalance_text(imbalance):
    return ", ".join(f"{k} {v:+g}" for k, v in sorted(imbalance.items())) or "balanced"


def _verify(rxn_info, **kwargs):
    return _net(_met_items(rxn_info, **kwargs))


def _reference_suggestions(rxn_info, mets_checked, imbalance):
    """Replace formulas/charges with the MetaNetX reference (or the formula used for the
    same compound elsewhere in the model)."""
    out = []
    fixes = {}
    for m in rxn_info["metabolites"]:
        check = mets_checked[m["id"]]
        for kind, source in (("reference", check["reference"]), ("consistency", check["alternative"])):
            if kind == "reference" and source and elements_of(source["formula"]) is not None:
                fixes.setdefault(kind, {})[m["id"]] = (source["formula"], source["charge"] if source["charge"] is not None else m["charge"])
            if kind == "consistency" and source:
                fixes.setdefault(kind, {})[m["id"]] = (source[0], source[1])
    for kind, overrides in fixes.items():
        overrides = {k: v for k, v in overrides.items() if v != (next(x["formula"] for x in rxn_info["metabolites"] if x["id"] == k), next(x["charge"] for x in rxn_info["metabolites"] if x["id"] == k))}
        if not overrides:
            continue
        source_text = "the MetaNetX reference" if kind == "reference" else "the same compound in another compartment"
        # Try each metabolite alone first, then all together.
        candidates = [({k: v}, [k]) for k, v in overrides.items()]
        if len(overrides) > 1:
            candidates.append((overrides, list(overrides)))
        for subset, ids in candidates:
            remaining = _verify(rxn_info, overrides=subset)
            if remaining == {}:
                changes = "; ".join(f"{i}: {next(x['formula'] for x in rxn_info['metabolites'] if x['id'] == i) or '(none)'} "
                                    f"({_fmt_charge(next(x['charge'] for x in rxn_info['metabolites'] if x['id'] == i))}) -> {subset[i][0]} ({_fmt_charge(subset[i][1])})" for i in ids)
                out.append({"type": "reference" if kind == "reference" else "consistency", "balances": True,
                            "text": f"Use the formula/charge from {source_text}: {changes}. The reaction then balances.",
                            "metabolites": ids})
                break
    return out


def _species_vectors():
    species = []
    for short, name, formula, charge in COMMON_SPECIES:
        species.append((short, name, formula, charge, elements_of(formula)))
    return species


_SPECIES = _species_vectors()


def _species_suggestions(rxn_info, imbalance, ctx):
    """Combinations of common species whose addition zeroes the imbalance."""
    if not imbalance:
        return []
    has_charge = "charge" in imbalance or all(m["charge"] is not None for m in rxn_info["metabolites"])
    keys = set(imbalance)
    results = []
    for size in (1, 2):
        for combo in combinations(_SPECIES, size):
            for coefficients in product([c for c in range(-_MAX_SPECIES_COEFFICIENT, _MAX_SPECIES_COEFFICIENT + 1) if c], repeat=size):
                total = dict(imbalance)
                for (short, name, formula, charge, elements), a in zip(combo, coefficients):
                    for el, n in elements.items():
                        total[el] = total.get(el, 0.0) + a * n
                    if has_charge:
                        total["charge"] = total.get("charge", 0.0) + a * charge
                if all(abs(v) <= TOL for v in total.values()):
                    results.append((size, sum(abs(a) for a in coefficients), combo, coefficients))
        if results:
            break
    results.sort(key=lambda r: (r[0], r[1]))
    compartment = _main_compartment(rxn_info)
    suggestions = []
    for _, _, combo, coefficients in results[:2]:
        parts, found = [], []
        for (short, name, formula, charge, elements), a in zip(combo, coefficients):
            side = "products" if a > 0 else "reactants"
            met_id = ctx.species_index.get((tuple(sorted(elements.items())), charge, compartment))
            label = f"{abs(a):g} x {name}" + (f" ({met_id})" if met_id else f" ({short}_{compartment or 'c'}: not found in the model, would need adding)")
            parts.append(f"{label} to the {side}")
            found.append(met_id or "")
        suggestions.append({"type": "species", "balances": True,
                            "text": "Add " + " and ".join(parts) + ".", "metabolites": [f for f in found if f]})
    return suggestions


def _main_compartment(rxn_info):
    counts = {}
    for m in rxn_info["metabolites"]:
        counts[m["compartment"]] = counts.get(m["compartment"], 0) + 1
    return max(counts, key=counts.get) if counts else None


def _formula_change_suggestions(rxn_info, imbalance):
    """A single metabolite whose formula/charge would have to change to balance the reaction."""
    suggestions = []
    for m in rxn_info["metabolites"]:
        elements = elements_of(m["formula"])
        if elements is None or not m["coefficient"]:
            continue
        delta = {k: -v / m["coefficient"] for k, v in imbalance.items()}
        new = dict(elements)
        ok = True
        for el, d in delta.items():
            if el == "charge":
                continue
            value = new.get(el, 0) + d
            if abs(value - round(value)) > TOL or value < -TOL:
                ok = False
                break
            new[el] = int(round(value))
        new_charge = None
        if "charge" in delta and m["charge"] is not None:
            charge = m["charge"] + delta["charge"]
            if abs(charge - round(charge)) > TOL:
                ok = False
            new_charge = int(round(charge))
        elif m["charge"] is not None:
            new_charge = m["charge"]
        atoms = sum(abs(d) for el, d in delta.items() if el != "charge")
        if not ok or atoms > _MAX_FORMULA_CHANGE_ATOMS:
            continue
        new = {k: v for k, v in new.items() if v}
        change = f"{hill(elements)} ({_fmt_charge(m['charge'])}) -> {hill(new)} ({_fmt_charge(new_charge)})"
        suggestions.append((atoms, {"type": "formula", "balances": True,
                                    "text": f"Check the formula/charge of {m['id']}: changing it {change} would balance the reaction.",
                                    "metabolites": [m["id"]]}))
    suggestions.sort(key=lambda s: s[0])
    return [s for _, s in suggestions[:2]]


def _coefficient_suggestions(rxn_info, imbalance):
    """A single stoichiometric coefficient that would balance the reaction."""
    suggestions = []
    for m in rxn_info["metabolites"]:
        elements = elements_of(m["formula"])
        if not elements:
            continue
        vector = dict(elements)
        if "charge" in imbalance and m["charge"] is not None:
            vector["charge"] = m["charge"]
        keys = set(imbalance) | {k for k, v in vector.items() if v}
        ratios = []
        for k in keys:
            v, i = vector.get(k, 0), imbalance.get(k, 0)
            if abs(v) < TOL:
                if abs(i) > TOL:
                    ratios = None
                    break
                continue
            ratios.append(-i / v)
        if not ratios or ratios is None or max(ratios) - min(ratios) > 1e-6:
            continue
        d = ratios[0]
        if abs(d) < TOL or _verify(rxn_info, coefficient_override=(m["id"], d)) != {}:
            continue
        new_coef = m["coefficient"] + d
        suggestions.append((abs(d), {"type": "coefficient", "balances": True,
                                     "text": f"Check the stoichiometric coefficient of {m['id']}: {m['coefficient']:g} -> {new_coef:g} would balance the reaction.",
                                     "metabolites": [m["id"]]}))
    suggestions.sort(key=lambda s: s[0])
    return [s for _, s in suggestions[:2]]


def _fill_formula_suggestions(rxn_info, mets_checked):
    """For a reaction that can't be checked: the reference formulas for the metabolites that lack one."""
    missing = rxn_info["missing_formula"]
    overrides, unresolved = {}, []
    for mid in missing:
        ref = mets_checked[mid]["reference"]
        if ref and elements_of(ref["formula"]) is not None:
            overrides[mid] = (ref["formula"], ref["charge"])
        else:
            unresolved.append(mid)
    suggestions = []
    if overrides:
        filled = {m["id"]: overrides.get(m["id"], (m["formula"], m["charge"])) for m in rxn_info["metabolites"]}
        remaining = _verify(rxn_info, overrides=filled)
        text = "Set the formula from the MetaNetX reference: " + "; ".join(f"{i} = {f} ({_fmt_charge(c)})" for i, (f, c) in overrides.items()) + "."
        if remaining is None:
            text += " Metabolites still without a formula: " + ", ".join(unresolved) + "."
        elif remaining:
            text += f" With these formulas the reaction is still unbalanced ({_imbalance_text(remaining)})."
        else:
            text += " The reaction then balances."
        suggestions.append({"type": "fill_formula", "balances": remaining == {}, "text": text, "metabolites": list(overrides)})
    if unresolved:
        suggestions.append({"type": "check", "balances": False,
                            "text": "No formula available for " + ", ".join(unresolved) + ": add one (look the compound up through its MetaNetX id) so the reaction can be checked.",
                            "metabolites": unresolved})
    return suggestions


# --- Report ----------------------------------------------------------------------------------

def _metabolite_rows(rxn_info, ctx, mets_checked):
    rows = []
    for m in rxn_info["metabolites"]:
        check = mets_checked[m["id"]]
        databases = check["databases"]
        ref = check["reference"]
        row = {
            "reaction_id": rxn_info["id"], "metabolite_id": m["id"], "name": m["name"],
            "coefficient": m["coefficient"], "compartment": m["compartment"],
            "formula": m["formula"], "charge": m["charge"],
            "metanetx_id": check["mnx"] or "",
            "reference_formula": ref["formula"] if ref else "", "reference_charge": ref["charge"] if ref else None,
            "formula_check": check["formula_status"], "mapping_check": check["mapping_status"],
        }
        for label, _ in DATABASES:
            row[label] = " | ".join(databases.get(label, [])[:_MAX_IDS_SHOWN])
        rows.append(row)
    return rows


def _mapping_text(rxn_info, mets_checked):
    parts = []
    for m in rxn_info["metabolites"]:
        check = mets_checked[m["id"]]
        dbs = "; ".join(f"{label} {', '.join(ids[:_MAX_IDS_SHOWN])}" for label, ids in check["databases"].items())
        parts.append(f"{m['id']} -> {check['mnx'] or 'no MetaNetX id'}" + (f" ({dbs})" if dbs else ""))
    return " | ".join(parts)


def _rank(suggestions):
    return sorted(suggestions, key=lambda s: _TYPE_ORDER.get(s["type"], 9))


def audit_unbalanced_reactions(model, include_unknown=True):
    """Full audit report: counts, one entry per problem reaction (with its
    ranked suggestions) and one row per reaction-metabolite pair."""
    balance = compute_balance_report(model)
    ctx = _Context(model)
    reaction_rows, metabolite_rows = [], []
    cache = {}

    for rxn_info in balance["reactions"]:
        if rxn_info["status"] == "unknown" and not include_unknown:
            continue
        mets_checked = {}
        for m in rxn_info["metabolites"]:
            if m["id"] not in cache:
                met = model.metabolites.get_by_id(m["id"])
                mnx = ctx.met_to_mnx.get(met.id)
                status, ref, alternative = ctx.formula_check(met, mnx)
                cache[m["id"]] = {"mnx": mnx, "databases": ctx.databases(mnx), "reference": ref, "alternative": alternative,
                                  "formula_status": status, "mapping_status": ctx.mapping_check(met, mnx)}
            mets_checked[m["id"]] = cache[m["id"]]

        imbalance = rxn_info["imbalance"]
        if rxn_info["status"] == "unbalanced":
            suggestions = (_reference_suggestions(rxn_info, mets_checked, imbalance)
                           + _species_suggestions(rxn_info, imbalance, ctx)
                           + _formula_change_suggestions(rxn_info, imbalance)
                           + _coefficient_suggestions(rxn_info, imbalance))
        else:
            suggestions = _fill_formula_suggestions(rxn_info, mets_checked)
        suggestions = _rank(suggestions)[:_MAX_SUGGESTIONS]
        if not suggestions:
            suggestions = [{"type": "check", "balances": False, "metabolites": [],
                            "text": "No single, simple fix found. Check the stoichiometric coefficients and the formulas/charges of the metabolites listed below."}]

        flagged = [mid for mid, c in mets_checked.items() if c["formula_status"] != "OK" or c["mapping_status"] != "OK"]
        reaction_rows.append({
            "id": rxn_info["id"], "name": rxn_info["name"], "status": rxn_info["status"],
            "imbalance": _imbalance_text(imbalance) if rxn_info["status"] == "unbalanced" else "",
            "reaction": rxn_info["reaction"],
            "suggestion": suggestions[0]["text"], "suggestion_type": suggestions[0]["type"],
            "verified": bool(suggestions[0]["balances"]),
            "other_suggestions": " || ".join(s["text"] for s in suggestions[1:]),
            "metabolites_to_check": " | ".join(flagged),
            "metabolite_mapping": _mapping_text(rxn_info, mets_checked),
            "suggestions": suggestions,
        })
        metabolite_rows.extend(_metabolite_rows(rxn_info, ctx, mets_checked))

    return {
        "counts": {**balance["counts"], "total": balance["total"],
                   "audited": len(reaction_rows), "with_verified_fix": sum(r["verified"] for r in reaction_rows)},
        "reference_available": ctx.reference is not None,
        "reactions": reaction_rows,
        "metabolites": metabolite_rows,
        "databases": [label for label, _ in DATABASES],
        "note": ("Formulas were compared with the MetaNetX reference (data/chem_prop.tsv)." if ctx.reference is not None else
                 "No data/chem_prop.tsv found, so formulas could not be compared with the MetaNetX reference; "
                 "checks use the model's own formulas and the same compound in other compartments. "
                 "Download MetaNetX's chem_prop.tsv into the data folder to enable the reference comparison."),
    }
