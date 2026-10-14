"""Assemble the report for one model or a panel of models: labels, column
definitions, ranges across models, the subsystem table and the
essential-exchange matrix, plus findings. Both the Excel and HTML builders
work from this structure."""
import re
from collections import Counter
from datetime import datetime

from comparative.findings import panel_findings
from comparative.metrics import UNANNOTATED
from comparative.settings import QCSections, QCSettings

# (metric key, column header) in the order shown in the summary table / sheet.
SUMMARY_COLUMNS = [
    ("display_name", "Model"), ("source_file", "File"), ("model_id", "Model ID"),
    ("genes", "Genes"), ("metabolites", "Metabolites"), ("reactions", "Reactions"),
    ("gene_reaction_ratio", "Gene : reaction ratio"), ("compartments", "Compartments"),
    ("objective_direction", "Objective direction"), ("wt_status", "FBA status"),
    ("mu_per_h", "Growth rate (1/h)"), ("doubling_time_min", "Doubling time (min)"), ("solver", "Solver"),
    ("met_namespace", "Metabolite namespace"), ("met_namespace_pct", "Metabolite ids resolved (%)"), ("met_unmapped", "Metabolites without MetaNetX id"),
    ("rxn_namespace", "Reaction namespace"), ("rxn_namespace_pct", "Reaction ids resolved (%)"), ("rxn_unmapped", "Reactions without MetaNetX id"),
    ("no_formula_pct", "Metabolites without formula (%)"), ("charge_zero_pct", "Metabolites with charge 0 or missing (%)"),
    ("n_unbalanced", "Unbalanced reactions"), ("n_balance_unknown", "Reactions that can't be balance-checked"), ("pct_unbalanced", "Unbalanced (% of checkable)"),
    ("biomass_reaction", "Biomass reaction"), ("biomass_n_metabolites", "Biomass metabolites"), ("biomass_atp_coeff", "Biomass ATP coefficient"),
    ("n_exchange", "Exchanges"), ("n_uptake_allowed", "Exchanges allowing uptake"), ("n_exchange_unbounded", "Unbounded exchanges"),
    ("n_essential_exchange", "Essential exchanges"), ("min_medium_n", "Minimal medium size"),
    ("blocked_reactions", "Blocked reactions"), ("pct_blocked", "Blocked (% of reactions)"),
    ("deadend_metabolites", "Dead-end metabolites"), ("pct_deadend", "Dead-end (% of metabolites)"),
    ("n_demand", "Demand reactions"), ("n_sink", "Sink reactions"), ("n_ds_no_flux", "Demand/sink with no flux"), ("n_ds_essential", "Essential demand/sink"),
    ("group", "Group"),
]

# Columns of the compact table shown in the app and at the top of the HTML report.
KEY_COLUMNS = ["display_name", "source_file", "genes", "reactions", "metabolites", "compartments", "mu_per_h", "doubling_time_min", "met_namespace",
               "rxn_namespace_pct", "n_unbalanced", "n_exchange_unbounded", "n_essential_exchange", "min_medium_n", "pct_blocked", "pct_deadend"]

# Ranges shown in the panel overview: (key, label, decimals)
RANGE_ROWS = [("genes", "Genes", 0), ("reactions", "Reactions", 0), ("metabolites", "Metabolites", 0),
              ("mu_per_h", "Growth rate (1/h)", 3), ("doubling_time_min", "Doubling time (min)", 1),
              ("pct_blocked", "Blocked reactions (%)", 1), ("pct_deadend", "Dead-end metabolites (%)", 1),
              ("rxn_namespace_pct", "Reaction ids resolved (%)", 1), ("n_exchange_unbounded", "Unbounded exchanges", 0)]

_BOILERPLATE_RE = re.compile(r"^(genome[- ]scale metabolic model of|metabolic model of|model report|cobramodel report|"
                             r"model exported from cobra toolbox)\s*", re.I)
_BINOMIAL_RE = re.compile(r"\b([A-Z])[a-z]{3,}\s+([a-z]{3,})")


def short_label(name, maxlen=32):
    """Compact a model name for a chart label: drop boilerplate, abbreviate the genus."""
    s = _BOILERPLATE_RE.sub("", (name or "").strip()).strip(" .")
    s = re.sub(r"\bsubsp\.?\s+\S+\s*", "", s)
    s = _BINOMIAL_RE.sub(lambda m: f"{m.group(1)}. {m.group(2)}", s, count=1)
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= maxlen else s[: maxlen - 1] + "…"


def unique_labels(entries, maxlen=32):
    """Short labels, disambiguated with the file name where two collide."""
    base = [short_label(e["metrics"]["display_name"], maxlen) for e in entries]
    counts = Counter(base)
    return [f"{b} [{short_label(e['metrics']['model_key'], 14)}]" if counts[b] > 1 else b for b, e in zip(base, entries)]


def _range(values, decimals):
    values = [v for v in values if v is not None]
    if not values:
        return "n/a"
    lo, hi = min(values), max(values)
    fmt = f"{{:.{decimals}f}}" if decimals else "{:.0f}"
    return fmt.format(lo) if lo == hi else f"{fmt.format(lo)} - {fmt.format(hi)}"


def build_report(entries, settings=None, sections=None):
    """The full report structure for a list of {"metrics", "details"} entries."""
    settings = settings or QCSettings()
    sections = sections or QCSections()
    findings, observations, distinct_keys = panel_findings(entries, settings)
    labels = unique_labels(entries)
    for entry, label in zip(entries, labels):
        entry["metrics"]["label"] = label
        entry["findings"] = findings[entry["metrics"]["model_key"]]

    distinct = [e for e in entries if e["metrics"]["model_key"] in distinct_keys]
    subsystem_totals = Counter()
    for e in distinct:
        subsystem_totals.update(e["details"].get("blocked_by_subsystem", {}))
    subsystem_columns = [s for s, _ in subsystem_totals.most_common() if s != UNANNOTATED]
    if UNANNOTATED in subsystem_totals:
        subsystem_columns.append(UNANNOTATED)

    essential_counts = Counter()
    for e in entries:
        essential_counts.update(set(e["details"].get("essential_exchanges", [])))

    return {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "n_models": len(entries), "n_distinct": len(distinct),
        "models": entries,
        "settings_rows": settings.as_rows(),
        "settings": {"mu_min": settings.mu_min, "mu_max": settings.mu_max, "band_label": settings.band_label,
                     "blocked_warn_pct": settings.blocked_warn_pct, "deadend_warn_pct": settings.deadend_warn_pct},
        "sections": sections.__dict__.copy(),
        "ranges": [(label, _range([e["metrics"].get(k) for e in distinct], d)) for k, label, d in RANGE_ROWS],
        "observations": observations,
        "subsystem_columns": subsystem_columns,
        "essential_exchange_ids": [i for i, _ in sorted(essential_counts.items(), key=lambda kv: (-kv[1], kv[0]))],
        "summary_columns": SUMMARY_COLUMNS,
        "key_columns": KEY_COLUMNS,
    }


def for_client(report):
    """A trimmed, JSON-friendly view for the app (no large detail lists)."""
    return {
        "generated": report["generated"], "n_models": report["n_models"], "n_distinct": report["n_distinct"],
        "observations": report["observations"], "ranges": report["ranges"], "settings_rows": report["settings_rows"],
        "columns": [{"key": k, "label": dict(SUMMARY_COLUMNS)[k]} for k in KEY_COLUMNS],
        "models": [{"metrics": e["metrics"], "findings": e["findings"], "notes": e["details"]["notes"]} for e in report["models"]],
    }
