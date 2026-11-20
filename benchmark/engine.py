"""Run a benchmark: profile every model under one medium, match them, and build the comparison.

Models are compared either against one reference ("reference" mode) or all against all. Metabolites
exchanged, essential exchanges, biomass components and core reactions are lined up across models
through the metabolite matches to the anchor model (the reference, or the first model).
"""
from benchmark.core_carbon import GROUP_OF, default_ids
from benchmark.matching import compare_pair, metabolite_infos
from benchmark.profile import build_profile
from annotation.naming import metabolite_base_id

FLUX_TOL = 1e-6


def _status(low, high):
    if low is None or high is None:
        return "not computed"
    if abs(low) <= FLUX_TOL and abs(high) <= FLUX_TOL:
        return "blocked"
    if low >= -FLUX_TOL:
        return "forward"
    if high <= FLUX_TOL:
        return "reverse"
    return "reversible"


class _Keys:
    """A comparable key for each metabolite of each model: the anchor's id without its compartment."""

    def __init__(self, to_anchor):
        self.to_anchor = to_anchor   # per model: {metabolite id: anchor metabolite id}

    def key(self, j, met_id):
        anchor_id = self.to_anchor[j].get(met_id)
        return metabolite_base_id(anchor_id or met_id)

    def canon(self, j, met_id):
        """Compartment-specific key, for orientation of reactions."""
        return self.to_anchor[j].get(met_id) or f"{j}:{met_id}"


def _rate_table(profiles, keys, field):
    table = {}
    for j, p in enumerate(profiles):
        for r in p[field]:
            row = table.setdefault(keys.key(j, r["metabolite"]),
                                   {"name": r["name"], "rates": [None] * len(profiles), "exchanges": [None] * len(profiles)})
            row["rates"][j] = (row["rates"][j] or 0.0) + r["rate"]
            row["exchanges"][j] = r["id"]
    rows = []
    for key, row in table.items():
        present = [x is not None for x in row["rates"]]
        rows.append({"key": key, **row, "differs": any(present) and not all(present)})
    rows.sort(key=lambda r: -max(x or 0.0 for x in r["rates"]))
    return rows


def _essential_table(profiles, keys):
    table = {}
    for j, p in enumerate(profiles):
        for r in p["essential_exchanges"]:
            row = table.setdefault(keys.key(j, r["metabolite"]), {"name": r["name"], "status": [None] * len(profiles)})
            row["status"][j] = "essential" if r["essential"] else "not essential"
    rows = [{"key": k, **v, "differs": len({s for s in v["status"] if s}) > 1 or (any(v["status"]) and not all(v["status"]))}
            for k, v in table.items()]
    rows = [r for r in rows if "essential" in r["status"]]   # a metabolite essential in at least one model
    rows.sort(key=lambda r: (not r["differs"], r["key"]))
    return rows


def _biomass_compare(profiles, keys):
    comps, summary = {}, []
    for j, p in enumerate(profiles):
        b = p["biomass"]
        if not b:
            summary.append(None)
            continue
        for c in b["components"]:
            row = comps.setdefault(keys.key(j, c["id"]), {"name": c["name"], "coefficients": [None] * len(profiles)})
            row["coefficients"][j] = c["coefficient"]
        summary.append({"reaction": b["reaction"], "n_consumed": b["n_consumed"], "n_produced": b["n_produced"],
                        "mass_g_per_gdw": b["mass_g_per_gdw"], "n_components": len(b["components"])})
    rows = [{"key": k, **v, "differs": any(c is None for c in v["coefficients"]) and any(c is not None for c in v["coefficients"])}
            for k, v in comps.items()]
    rows.sort(key=lambda r: (not r["differs"], r["name"].lower()))
    sets = [{k for k, v in comps.items() if v["coefficients"][j] is not None} for j in range(len(profiles))]
    jaccard = [[(len(a & b) / len(a | b)) if (a | b) else None for b in sets] for a in sets]
    return {"summary": summary, "components": rows, "jaccard": jaccard}


def _maintenance(profiles):
    out = []
    for p in profiles:
        m = p["maintenance"]
        out.append({"gam": m["gam"][0]["coefficient"] if m["gam"] else None, "ngam_id": m["ngam"][0]["id"] if m["ngam"] else None,
                    "ngam_lower": m["ngam"][0]["lower_bound"] if m["ngam"] else None,
                    "ngam_forced": any(n["forced"] for n in m["ngam"])})
    return out


def _orientation(models, keys, reaction_ids):
    """+1 / -1 per model: whether its version of a reaction runs the same way as the first model that has it."""
    base = None
    signs = []
    for j, rid in enumerate(reaction_ids):
        if rid is None:
            signs.append(1)
            continue
        coefs = {keys.canon(j, m.id): c for m, c in models[j].reactions.get_by_id(rid).metabolites.items()}
        if base is None:
            base = coefs
            signs.append(1)
            continue
        score = sum((1 if c > 0 else -1) * (1 if base[k] > 0 else -1) for k, c in coefs.items() if k in base)
        signs.append(-1 if score < 0 else 1)
    return signs


def _core_compare(models, profiles, keys, wanted):
    rows = []
    for wid in wanted:
        entries = [p["core"].get(wid) for p in profiles]
        signs = _orientation(models, keys, [e["id"] if e else None for e in entries])
        cells, flags = [], []
        for e, s in zip(entries, signs):
            if e is None:
                cells.append(None)
                continue
            low, high, wt = e["min"], e["max"], e["wt_flux"]
            if s < 0:
                low, high, wt = (None if high is None else -high), (None if low is None else -low), (None if wt is None else -wt)
            cells.append({"id": e["id"], "wt_flux": wt, "min": low, "max": high, "status": _status(low, high), "flipped": s < 0})
        present = [c for c in cells if c]
        if 0 < len(present) < len(cells):
            flags.append("missing in some models")
        states = {c["status"] for c in present if c["status"] != "not computed"}
        if "blocked" in states and len(states) > 1:
            flags.append("blocked in some, active in others")
        if "forward" in states and "reverse" in states:
            flags.append("opposite directions")
        spans = [(c["min"], c["max"]) for c in present if c["min"] is not None]
        if any(a[1] < b[0] - FLUX_TOL for a in spans for b in spans):
            flags.append("flux ranges do not overlap")
        rows.append({"id": wid, "group": GROUP_OF.get(wid, "Custom"), "models": cells, "flags": flags})
    return rows


def run_benchmark(entries, medium, reference=None, core_ids=None, fva_fraction=1.0, progress=lambda message: None):
    """entries: [(name, model)]. reference: index of the model the others are benchmarked against, or
    None for all against all. Returns (result for the page, details for the report files)."""
    names, models = [n for n, _ in entries], [m for _, m in entries]
    core_ids = core_ids or default_ids()
    profiles = [build_profile(n, m, medium, core_ids, fva_fraction, progress) for n, m in entries]
    infos = [metabolite_infos(m) for m in models]
    anchor = reference if reference is not None else 0
    count = len(models)
    wanted_pairs = [(anchor, j) for j in range(count) if j != anchor] if reference is not None \
        else [(i, j) for i in range(count) for j in range(i + 1, count)]

    pairs, details = [], []
    to_anchor = [dict() for _ in range(count)]
    for a, b in wanted_pairs:
        progress(f"Matching {names[a]} with {names[b]}")
        summary, met_pairs, rxn_pairs = compare_pair(models[a], models[b], infos[a], infos[b])
        pairs.append({"a": a, "b": b, **summary})
        details.append({"a": a, "b": b, "metabolites": met_pairs, "reactions": rxn_pairs})
        if a == anchor:
            to_anchor[b] = {bid: aid for aid, (bid, _) in met_pairs.items()}
    to_anchor[anchor] = {m.id: m.id for m in infos[anchor]}
    keys = _Keys(to_anchor)

    matrix = {}
    for kind in ("metabolites", "reactions"):
        for flavour in ("jaccard_strict", "jaccard_relaxed"):
            grid = [[1.0 if i == j else None for j in range(count)] for i in range(count)]
            for p in pairs:
                grid[p["a"]][p["b"]] = grid[p["b"]][p["a"]] = p[kind][flavour]
            matrix[f"{kind}_{flavour[8:]}"] = grid

    warnings = []
    for p in profiles:
        if (p["overview"]["wt_growth"] or 0) <= 1e-9:
            warnings.append(f"{p['name']} does not grow on this medium, so essential exchanges and flux ranges are empty for it.")
        miss = p["medium"]["unmatched"]
        if miss:
            warnings.append(f"{p['name']}: {len(miss)} of {p['medium']['requested']} medium entries have no exchange reaction in this model ({', '.join(miss[:8])}{'…' if len(miss) > 8 else ''}).")
        absent = sum(1 for v in p["core"].values() if v is None)
        if absent:
            warnings.append(f"{p['name']}: {absent} of {len(core_ids)} core carbon reactions were not found.")

    result = {
        "names": names, "mode": "reference" if reference is not None else "all", "reference": names[reference] if reference is not None else None,
        "anchor": anchor, "fva_fraction": fva_fraction, "warnings": warnings,
        "medium": [p["medium"] for p in profiles], "overview": [p["overview"] for p in profiles],
        "similarity": {"pairs": pairs, "matrix": matrix},
        "biomass": _biomass_compare(profiles, keys), "maintenance": _maintenance(profiles),
        "sources": [{"carbon": p["carbon_main"], "nitrogen": p["nitrogen_main"]} for p in profiles],
        "uptake": _rate_table(profiles, keys, "uptake"), "secretion": _rate_table(profiles, keys, "secretion"),
        "essential": _essential_table(profiles, keys), "core": _core_compare(models, profiles, keys, core_ids),
    }
    return result, {"pairs": details, "names": names, "infos": infos, "models": models}
