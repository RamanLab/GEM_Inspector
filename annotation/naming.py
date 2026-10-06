"""Compartment codes and display-name cleanup.

Model exports use several different conventions for tagging a metabolite's
or reaction's compartment onto its id or name (trailing "_c", "[c]", "(c)",
optionally with a numeric index like "_c0"). This module normalizes all of
that for display purposes only -- ids themselves are never touched anywhere
in this app, only the human-readable name/compartment shown next to them.
"""
import re

# "Currency"/cofactor metabolites that shuttle through almost every pathway
# (energy carriers, redox carriers, protons, water, phosphate...) and tend to
# clutter a pathway trace without adding pathway-specific information.
# Matched against a metabolite's compartment-stripped *base* id, so "atp_c",
# "atp_c0", and "atp_e" all match the single entry "atp" below regardless of
# which compartment they're in. Edit this set to taste.
TRIVIAL_METABOLITES = {
    "h", "h2o", "pi", "ppi",
    "atp", "adp", "amp",
    "gtp", "gdp", "gmp",
    "utp", "udp", "ump",
    "ctp", "cdp", "cmp",
    "itp", "idp", "imp",
    "nad", "nadh", "nadp", "nadph",
    "fad", "fadh2",
    "coa", "co_a",
    "co2",
    "q8", "q8h2", "mqn8", "mql8",
}

# A trailing compartment tag can appear in any of several conventions
# depending on how the model was built: "_c", "_e0", "[c]", "[e0]", "(c)",
# "(e0)". This matches whichever one is present at the very end of an id and
# captures (compartment_code, numeric_index_or_empty) separately, e.g.
# "atp_c0" -> ("c", "0"), "glc_D[e]" -> ("e", ""), "EX_thm(e)" -> ("e", "").
_COMPARTMENT_SUFFIX_RE = re.compile(
    r"(?:_([A-Za-z]+)(\d*)|\[([A-Za-z]+)(\d*)\]|\(([A-Za-z]+)(\d*)\))$"
)


def parse_compartment_suffix(raw_id):
    """Split a trailing compartment tag off an id, in whichever convention
    it uses. Returns (base_id, compartment_code_lower_or_None). The
    numeric index, if any, is discarded here -- see compartment_display_name
    for where it's used for display disambiguation.
    """
    match = _COMPARTMENT_SUFFIX_RE.search(raw_id)
    if not match:
        return raw_id, None
    groups = [g for g in match.groups() if g]
    code = groups[0].lower() if groups else None
    base = raw_id[: match.start()]
    return base, code


def metabolite_base_id(met_id):
    """Strip a trailing compartment tag from a metabolite id so it can be
    matched against a compartment-agnostic name list, e.g. "atp_c0", "atp_c",
    "atp[c]", and "atp(c)" all reduce to "atp"."""
    base, _ = parse_compartment_suffix(met_id)
    return base.lower()


def metabolite_base_id_preserve_case(met_id):
    """Like metabolite_base_id, but keeps the original casing -- needed for
    MetaNetX lookups, since KEGG ("C00031") and MetaCyc ids are
    case-sensitive."""
    base, _ = parse_compartment_suffix(met_id)
    return base


def is_trivial_metabolite(met, trivial_bases=TRIVIAL_METABOLITES):
    return metabolite_base_id(met.id) in trivial_bases


# Base compartment code -> friendly display name. Codes are matched after
# stripping any trailing numeric index (see parse_compartment_suffix), so
# "c", "c0", "c1", ... all map to the same entry. Extend this to taste.
COMPARTMENT_NAME_MAP = {
    "c": "Cytosol",
    "e": "Extracellular space",
    "p": "Periplasm",
    "m": "Mitochondria",
    "mm": "Mitochondrial membrane",
    "im": "Mitochondrial intermembrane space",
    "r": "Endoplasmic reticulum",
    "g": "Golgi apparatus",
    "n": "Nucleus",
    "x": "Peroxisome",
    "v": "Vacuole",
    "l": "Lysosome",
    "w": "Cell wall",
    "u": "Thylakoid lumen",
    "cm": "Cytoplasmic membrane",
    "cx": "Carboxysome",
    "flag": "Flagellum",
    "per": "Periplasm",
}


def compartment_display_name(comp_id, model_provided_name=None):
    """Best-effort friendly name for a compartment id/code.

    Prefers the model's own compartment name if it's meaningfully set (not
    blank and not just a repeat of the code). Otherwise looks up the base
    code in COMPARTMENT_NAME_MAP, falling back to the raw id, title-cased,
    if the code isn't recognized. A non-zero numeric index (multi-instance
    compartments, e.g. community models with "c0"/"c1" per organism) is
    appended for disambiguation.
    """
    comp_id = comp_id or ""
    if model_provided_name:
        name = str(model_provided_name).strip()
        if name and name.lower() != comp_id.lower():
            return name

    match = re.match(r"^([A-Za-z]+)(\d*)$", comp_id)
    if not match:
        return comp_id.title() if comp_id else "Unknown compartment"
    base, index = match.group(1).lower(), match.group(2)

    friendly = COMPARTMENT_NAME_MAP.get(base, base.title())
    if index and index != "0":
        friendly = f"{friendly} {index}"
    return friendly


def clean_metabolite_display_name(met):
    """Metabolite display name with any embedded compartment tag stripped.

    Some model exports bake the compartment into the metabolite *name*
    field itself (e.g. name="Thiamine[c]" or "Pyruvate_e"), which is
    redundant with the compartment already shown next to it. The
    metabolite *id* is left untouched -- only this display name is cleaned.

    Bracket/paren tags ("[c]", "(e)") are always stripped, since a real
    chemical name essentially never ends that way. An underscore tag
    ("_c", "_e0") is only stripped when the code is a recognized
    compartment (this metabolite's own compartment, or a known key in
    COMPARTMENT_NAME_MAP), which avoids mangling a name that legitimately
    ends in "_D"/"_L" etc. (e.g. "glc__D").
    """
    name = (met.name or met.id or "").strip()
    if not name:
        return name

    match = _COMPARTMENT_SUFFIX_RE.search(name)
    if not match:
        return name

    is_bracket_or_paren = match.group(3) is not None or match.group(5) is not None
    code = next((g for g in (match.group(1), match.group(3), match.group(5)) if g), "").lower()
    own_compartment_base = None
    met_compartment = getattr(met, "compartment", None)
    if met_compartment:
        comp_match = re.match(r"^([A-Za-z]+)\d*$", met_compartment)
        own_compartment_base = comp_match.group(1).lower() if comp_match else met_compartment.lower()

    if is_bracket_or_paren or code == own_compartment_base or code in COMPARTMENT_NAME_MAP:
        cleaned = name[: match.start()].rstrip(" _-")
        if cleaned:
            return cleaned
    return name


def clean_reaction_display_name(rxn):
    """Reaction display name with an embedded compartment tag stripped --
    the reaction-side counterpart of clean_metabolite_display_name, for
    exports that bake a compartment into the reaction *name* itself (e.g.
    name="ATP synthase, mitochondrial [m]"). The reaction *id* is left
    untouched -- only this display name is cleaned.
    """
    name = (rxn.name or rxn.id or "").strip()
    if not name:
        return name

    match = _COMPARTMENT_SUFFIX_RE.search(name)
    if not match:
        return name

    is_bracket_or_paren = match.group(3) is not None or match.group(5) is not None
    code = next((g for g in (match.group(1), match.group(3), match.group(5)) if g), "").lower()

    own_compartment_bases = set()
    for met in rxn.metabolites:
        comp = getattr(met, "compartment", None)
        if comp:
            comp_match = re.match(r"^([A-Za-z]+)\d*$", comp)
            own_compartment_bases.add((comp_match.group(1) if comp_match else comp).lower())

    if is_bracket_or_paren or code in own_compartment_bases or code in COMPARTMENT_NAME_MAP:
        cleaned = name[: match.start()].rstrip(" _-")
        if cleaned:
            return cleaned
    return name


_COMPARTMENT_STYLE_LABELS = {
    "underscore": "Underscore suffix (e.g. _c)",
    "underscore_indexed": "Underscore suffix with numeric index (e.g. _c0)",
    "bracket": "Bracketed suffix (e.g. [c])",
    "bracket_indexed": "Bracketed suffix with numeric index (e.g. [c0])",
    "paren": "Parenthesized suffix (e.g. (c))",
    "paren_indexed": "Parenthesized suffix with numeric index (e.g. (c0))",
}


def detect_compartment_convention(model):
    """Scan every metabolite id for its trailing compartment tag and report
    whichever tagging convention is dominant across the model, with a real
    example."""
    style_counts = {}
    example_by_style = {}
    for met in model.metabolites:
        mid = met.id
        match = _COMPARTMENT_SUFFIX_RE.search(mid)
        if not match:
            continue
        if match.group(1) is not None:
            code, idx = match.group(1), match.group(2)
            style = "underscore_indexed" if idx else "underscore"
            suffix = f"_{code}{idx}"
        elif match.group(3) is not None:
            code, idx = match.group(3), match.group(4)
            style = "bracket_indexed" if idx else "bracket"
            suffix = f"[{code}{idx}]"
        else:
            code, idx = match.group(5), match.group(6)
            style = "paren_indexed" if idx else "paren"
            suffix = f"({code}{idx})"
        style_counts[style] = style_counts.get(style, 0) + 1
        if style not in example_by_style:
            example_by_style[style] = {"id": mid, "suffix": suffix}

    if not style_counts:
        return {
            "style": None,
            "label": "No compartment suffix detected on metabolite ids",
            "example": None,
            "suffix": None,
            "coverage": 0.0,
        }

    best_style = max(style_counts, key=style_counts.get)
    total = len(model.metabolites)
    ex = example_by_style[best_style]
    return {
        "style": best_style,
        "label": _COMPARTMENT_STYLE_LABELS.get(best_style, best_style),
        "example": ex["id"],
        "suffix": ex["suffix"],
        "coverage": (style_counts[best_style] / total) if total else 0.0,
    }
