"""Core carbon metabolism: a fixed list of central reactions (BiGG ids) found in each model by
id, then by MetaNetX id; the flux ranges are then computed with FVA for just these reactions."""
import re

from annotation.namespace_mapping import detect_reaction_namespace_and_map, load_xref

CORE_REACTIONS = {
    "Glycolysis / gluconeogenesis": ["HEX1", "PGI", "PFK", "FBP", "FBA", "TPI", "GAPD", "PGK", "PGM", "ENO", "PYK", "PPS"],
    "Pyruvate and acetyl-CoA": ["PDH", "PFL", "LDH_D", "ACALD", "ALCD2x", "PTAr", "ACKr"],
    "Pentose phosphate pathway": ["G6PDH2r", "PGL", "GND", "RPE", "RPI", "TKT1", "TKT2", "TALA"],
    "TCA cycle": ["CS", "ACONTa", "ACONTb", "ICDHyr", "AKGDH", "SUCOAS", "SUCDi", "FUM", "MDH"],
    "Anaplerotic and glyoxylate": ["PPC", "PPCK", "ME1", "ME2", "ICL", "MALS"],
    "Energy": ["ATPS4r", "NADH16", "CYTBD", "THD2", "ATPM"],
}
GROUP_OF = {rid: group for group, ids in CORE_REACTIONS.items() for rid in ids}


def default_ids():
    return [rid for ids in CORE_REACTIONS.values() for rid in ids]


def parse_ids(text):
    """Reaction ids from a comma / space / line separated text; None when empty."""
    ids = [i for i in re.split(r"[\s,;]+", text or "") if i]
    return list(dict.fromkeys(ids)) or None


def find_core_reactions(model, wanted):
    """{wanted BiGG id: model reaction id or None}: the model's own id first, then the reaction with
    the same MetaNetX id."""
    bigg = load_xref("reac").get("bigg.reaction", {})
    _, _, _, to_mnx = detect_reaction_namespace_and_map(model)
    by_mnx = {}
    for rid, mnx in to_mnx.items():
        if mnx and not model.reactions.get_by_id(rid).boundary:
            by_mnx.setdefault(mnx, rid)
    ids = {r.id for r in model.reactions}
    found = {}
    for rid in wanted:
        hit = rid if rid in ids else f"R_{rid}" if f"R_{rid}" in ids else None
        if hit is None and bigg.get(rid):
            hit = by_mnx.get(bigg[rid])
        found[rid] = hit
    return found
