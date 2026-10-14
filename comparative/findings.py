"""Automatic findings: flags raised by applying the QC thresholds to each
model's statistics, plus panel-wide observations."""
import math
import re
from collections import Counter

from comparative.metrics import UNANNOTATED
from comparative.settings import QCSettings

_DOUBLED_COMPARTMENT_RE = re.compile(r"\[\w+\]\[\w+\]")


def _has(value):
    return value is not None and not (isinstance(value, float) and math.isnan(value))


def _implausible(ids, settings):
    return sorted({i for i in ids if any(tok in i.lower() for tok in settings.implausible_nutrients)})


def model_findings(entry, settings):
    """List of flag strings for one model's {"metrics", "details"}."""
    m, d = entry["metrics"], entry["details"]
    flags = []

    mu = m.get("mu_per_h")
    if _has(mu):
        if mu > settings.mu_max:
            flags.append(f"growth rate {mu:.3g} /h is above the plausible ceiling ({settings.mu_max:g} /h); "
                         f"doubling time {math.log(2) / mu * 60:.3g} min")
        elif mu < settings.mu_min:
            flags.append(f"growth rate {mu:.3g} /h is below {settings.mu_min:g} /h")
    if m.get("wt_status") and m["wt_status"] != "optimal":
        flags.append(f"FBA did not solve to optimality ({m['wt_status']})")

    n_exch, n_unb = m.get("n_exchange") or 0, m.get("n_exchange_unbounded") or 0
    if n_exch and n_unb / n_exch > 0.5:
        flags.append(f"{n_unb}/{n_exch} exchanges are unbounded (LB <= {settings.unbounded_lb:.0f}); the medium is effectively unconstrained")

    for key, threshold, what in (("pct_blocked", settings.blocked_warn_pct, "of reactions are blocked"),
                                 ("pct_deadend", settings.deadend_warn_pct, "of metabolites are dead ends"),
                                 ("pct_unbalanced", settings.unbalanced_warn_pct, "of checkable reactions are mass/charge unbalanced")):
        if _has(m.get(key)) and m[key] > threshold:
            flags.append(f"{m[key]:.1f}% {what} (threshold {threshold:g}%)")

    for key, label in (("met_namespace_pct", "metabolite"), ("rxn_namespace_pct", "reaction")):
        if _has(m.get(key)) and m[key] < settings.namespace_warn_pct:
            flags.append(f"only {m[key]:.1f}% of {label} ids resolve to the detected namespace ({m.get(key.replace('_pct', ''))})")

    if m.get("charge_zero_pct") == 100:
        flags.append("charge is 0 for every metabolite: charge annotation is absent, so charge balancing is impossible")
    if _has(m.get("no_formula_pct")) and m["no_formula_pct"] > 5:
        flags.append(f"{m['no_formula_pct']:.1f}% of metabolites have no molecular formula")
    if m.get("compartments") == 1:
        flags.append("single compartment: the extracellular space is collapsed into the cytosol (unusable for community simulation)")
    if _DOUBLED_COMPARTMENT_RE.search(d.get("biomass") or ""):
        flags.append("metabolite ids carry a duplicated compartment suffix (e.g. x_c[c][c]); re-export with a single tag")

    bad = _implausible([e["id"] for e in d.get("minimal_medium", [])], settings)
    if bad:
        flags.append("minimal medium contains compounds that are not credible nutrients: " + ", ".join(bad[:8]))
    bad = _implausible(d.get("essential_exchanges", []), settings)
    if bad:
        flags.append("model is auxotrophic for compounds it should synthesise: " + ", ".join(bad[:8]))
    if m.get("n_ds_essential"):
        flags.append(f"{m['n_ds_essential']} demand/sink reaction(s) are essential: growth depends on gap-fill crutches")
    for note in d.get("notes", []):
        flags.append("analysis incomplete: " + note)
    return flags


def panel_findings(models, settings=None):
    """Per-model flags (keyed by model_key) with duplicate-content flags
    added, and a list of panel-wide observations."""
    settings = settings or QCSettings()
    findings = {e["metrics"]["model_key"]: model_findings(e, settings) for e in models}

    by_hash = {}
    for e in models:
        by_hash.setdefault(e["metrics"]["content_hash"], []).append(e["metrics"]["model_key"])
    for keys in by_hash.values():
        for key in keys if len(keys) > 1 else []:
            others = [k for k in keys if k != key]
            findings[key].insert(0, "duplicate: identical reactions, stoichiometry and bounds to " + ", ".join(others))

    distinct = [e for e in models if e["metrics"]["model_key"] == by_hash[e["metrics"]["content_hash"]][0]]
    observations = []
    n_fast = sum(1 for e in distinct if _has(e["metrics"].get("mu_per_h")) and e["metrics"]["mu_per_h"] > settings.mu_max)
    if n_fast and len(distinct) > 1:
        observations.append(f"{n_fast} of {len(distinct)} models predict growth above {settings.mu_max:g} /h; treat their flux numbers as "
                            "uninterpretable until the medium is constrained.")
    n_open = sum(1 for e in distinct if (e["metrics"].get("n_exchange") or 0) and
                 (e["metrics"].get("n_exchange_unbounded") or 0) / e["metrics"]["n_exchange"] > 0.5)
    if n_open and len(distinct) > 1:
        observations.append(f"{n_open} of {len(distinct)} models run on an effectively unconstrained medium (more than half of all exchanges unbounded).")
    totals = Counter()
    for e in distinct:
        totals.update(e["details"].get("blocked_by_subsystem", {}))
    named = [(s, n) for s, n in totals.most_common() if s != UNANNOTATED][:3]
    if named and len(distinct) > 1:
        observations.append("Blocked reactions concentrate in: " + "; ".join(f"{s} ({n})" for s, n in named) + ".")
    if len(distinct) < len(models):
        observations.append(f"{len(models) - len(distinct)} model(s) duplicate another model in the panel.")
    return findings, observations, [e["metrics"]["model_key"] for e in distinct]
