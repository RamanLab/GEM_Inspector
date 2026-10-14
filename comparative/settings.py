"""Thresholds and options for the model quality-control reports."""
from dataclasses import dataclass, field


@dataclass
class QCSettings:
    """Acceptance thresholds used for the automatic findings."""

    # Biologically plausible growth-rate window (1/h).
    mu_min: float = 0.05
    mu_max: float = 2.0
    # Share of the network allowed to be blocked / dead-end before warning (%).
    blocked_warn_pct: float = 15.0
    deadend_warn_pct: float = 10.0
    # Minimum share of ids that must resolve to the detected namespace (%).
    namespace_warn_pct: float = 90.0
    # An exchange is "essential" when closing it leaves less than this fraction of growth.
    essential_retained_max: float = 0.05
    # An exchange counts as unbounded when its lower bound is at or below this.
    unbounded_lb: float = -999.0
    # Reactions that fail mass/charge balance above this share of the checkable ones (%).
    unbalanced_warn_pct: float = 10.0
    # Compounds that are never a genuine nutrient requirement for a free-living bacterium.
    implausible_nutrients: tuple = (
        "12dgr", "dag", "aacp", "apoacp", "2fe2s", "4fe4s", "udcpp",
        "gcald", "26dap_m", "amylose", "starch", "tet", "6apa", "2pglyc",
        "pe160", "pg160", "clpn", "peptido", "lipoteichoic",
    )
    band_label: str = "plausible range"

    @classmethod
    def from_dict(cls, data):
        """Settings from a (possibly partial) dict of user-supplied numbers."""
        settings = cls()
        for name in ("mu_min", "mu_max", "blocked_warn_pct", "deadend_warn_pct", "namespace_warn_pct",
                     "essential_retained_max", "unbalanced_warn_pct"):
            try:
                if data.get(name) not in (None, ""):
                    setattr(settings, name, float(data[name]))
            except (TypeError, ValueError):
                pass
        return settings

    def as_rows(self):
        """(label, value) pairs for the report's thresholds table."""
        return [
            ("Plausible growth rate (1/h)", f"{self.mu_min:g} - {self.mu_max:g}"),
            ("Blocked reactions warn above (% of reactions)", f"{self.blocked_warn_pct:g}"),
            ("Dead-end metabolites warn above (% of metabolites)", f"{self.deadend_warn_pct:g}"),
            ("Namespace coverage warn below (% of ids)", f"{self.namespace_warn_pct:g}"),
            ("Unbalanced reactions warn above (% of checkable)", f"{self.unbalanced_warn_pct:g}"),
            ("Exchange is essential when closing it leaves less than", f"{self.essential_retained_max:.0%} of growth"),
        ]


# Which (slower) analyses to include. Quick statistics are always computed.
@dataclass
class QCSections:
    essentiality: bool = True      # close each exchange and re-solve
    minimal_medium: bool = True    # smallest nutrient set for full growth
    network_gaps: bool = True      # blocked reactions (FVA) and dead-end metabolites
    demand_sink: bool = True       # demand / sink reactions and their essentiality
    balance: bool = True           # mass / charge balance of every reaction

    @classmethod
    def from_dict(cls, data):
        sections = cls()
        for name in sections.__dict__:
            if name in (data or {}):
                setattr(sections, name, str(data[name]).lower() not in ("0", "false", "no", ""))
        return sections
