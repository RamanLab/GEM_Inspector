"""Tier 1 of the gap classification: instant, topology-only (no LP).

Classifies dead-end metabolites and FVA-blocked reactions into the classes in
CLASS_LABELS, and groups them by root gap. The aim is to help inspect a model,
not to fix it: every class carries a short "what to check" note in GUIDANCE.

Method (see docs/REFERENCES.md):
  * Dead ends are found by propagation, following GapFind (Kumar et al. 2007).
    A reaction direction is allowed by the bounds; it is dead when one of its
    substrates can never be produced, or one of its products can never be
    consumed. A metabolite can never be produced (consumed) when every allowed
    direction that would produce (consume) it is dead. Repeating this until
    nothing changes gives the root gaps (found in round 0) and everything they
    cause downstream (round > 0).
  * The propagation is run four times to see what resolves a gap: the model
    as it is, with exchanges opened (medium), with internal reactions made
    reversible (directionality), and with both (structural if still dead).
  * Currency metabolites (editable list) never cause deadness, otherwise one
    cofactor would "block" half the model.
This is a purely structural test, so a cycle with no entry point is not found
(that needs flux balance; see Tier 2 and the docs).
"""
from collections import defaultdict

import numpy as np
import scipy.sparse as sp
from cobra.util import linear_reaction_coefficients

from annotation.naming import metabolite_base_id
from diagnostics.balance import analyse_all_reactions

BIG = 1e6  # "open" bound used for the relaxed runs

CLASS_LABELS = {
    # dead-end metabolites
    "rnp": "Root no-production (RNP)",
    "rnc": "Root no-consumption (RNC)",
    "rnp_rnc": "No production and no consumption (RNP + RNC)",
    "downstream": "Downstream of an RNP",
    "upstream": "Upstream of an RNC",
    "conditional": "Conditional (medium)",
    "reversibility": "Reversibility-specific",
    "mixed": "Mixed (needs more than one change)",
    "currency": "Currency-metabolite artifact",
    # blocked reactions
    "dead_end_rnp": "Dead-end-linked: RNP",
    "dead_end_rnc": "Dead-end-linked: RNC",
    "dead_end_downstream": "Dead-end-linked: downstream of RNP",
    "dead_end_upstream": "Dead-end-linked: upstream of RNC",
    "dead_end_both": "Dead-end-linked: RNP and RNC",
    "bounds_closed": "Closed by bounds (lb = ub = 0)",
    "medium": "Medium-blocked",
    "directionality": "Directionality-blocked",
    "cofactor": "Cofactor/redox-blocked",
    "transport": "Compartment/transport-blocked (inferred)",
    "unresolved": "Unresolved (stoichiometric / other)",
}

GUIDANCE = {
    "rnp": "Nothing in the model makes this metabolite. Look for a missing synthesis reaction, transporter or exchange, or a wrongly closed direction.",
    "rnc": "Nothing in the model uses this metabolite. Look for a missing consuming reaction, secretion/demand reaction or transporter.",
    "rnp_rnc": "No pair of reactions can produce and consume it: it is in no reaction, or in one reaction only. Check for a leftover, a duplicate id, or missing reactions.",
    "downstream": "Not a root cause: its producers need a metabolite that cannot be made. Fix the root gap(s) listed.",
    "upstream": "Not a root cause: its consumers lead only to a metabolite that cannot be used. Fix the root gap(s) listed.",
    "conditional": "A gap only under the current medium (a closed exchange). Open the exchange or change the diet to see whether it is real.",
    "reversibility": "A gap only because of reaction directions. Check the directionality of the reactions around it against the literature.",
    "mixed": "Only resolved by several changes together (medium, directions, cofactors). Check each of them around it.",
    "currency": "A common cofactor, listed only for completeness. Usually balanced elsewhere in the model; check only if it matters to you.",
    "dead_end_rnp": "Blocked because it consumes an RNP metabolite. Fix the root gap, not each reaction.",
    "dead_end_rnc": "Blocked because it makes an RNC metabolite. Fix the root gap, not each reaction.",
    "dead_end_downstream": "Blocked further down from a root RNP gap. Fix the root gap and re-run.",
    "dead_end_upstream": "Blocked further up from a root RNC gap. Fix the root gap and re-run.",
    "dead_end_both": "Blocked by both a root RNP and a root RNC gap. Fix the root gaps and re-run.",
    "bounds_closed": "Both bounds are zero, so it was closed on purpose or by mistake. Check whether it should be open.",
    "medium": "Becomes usable when exchanges are opened. Check which nutrient it needs (see Minimal medium / Exchange debugging).",
    "directionality": "Becomes usable when reaction directions are relaxed. Check the directionality of the reactions around it.",
    "cofactor": "Becomes usable when currency metabolites can be supplied freely. Check ATP/NAD(P)H/CoA balance and regeneration around it.",
    "transport": "Involves a metabolite with a connected twin in another compartment. Check for a missing transporter or wrong localisation.",
    "unresolved": "None of the tests explains it. Check balance, duplicates, the GPR and the literature; it may also be flux-coupled.",
}


class _Network:
    """Sparse incidence of the model: Apos/Aneg are (metabolites x reactions)
    0/1 matrices of positive/negative stoichiometric coefficients."""

    def __init__(self, model):
        met_index = {m.id: i for i, m in enumerate(model.metabolites)}
        rows, cols, vals = [], [], []
        for j, rxn in enumerate(model.reactions):
            for met, coeff in rxn.metabolites.items():
                rows.append(met_index[met.id])
                cols.append(j)
                vals.append(coeff)
        shape = (len(model.metabolites), len(model.reactions))
        vals = np.asarray(vals, dtype=float)
        self.Apos = sp.csr_matrix(((vals > 0).astype(float), (rows, cols)), shape=shape)
        self.Aneg = sp.csr_matrix(((vals < 0).astype(float), (rows, cols)), shape=shape)
        self.Atouch = self.Apos + self.Aneg
        self.PosT, self.NegT = self.Apos.T.tocsr(), self.Aneg.T.tocsr()
        self.rxn_index = {r.id: j for j, r in enumerate(model.reactions)}


class _Run:
    """Result of one propagation: which metabolites cannot be produced /
    consumed (and in which round that was found), and which reaction
    directions are dead."""

    def __init__(self, net, lb, ub, ignore):
        n_met, n_rxn = net.Apos.shape
        self.net, self.ignore = net, ignore
        self.allowed_f, self.allowed_r = ub > 0, lb < 0
        self.np_round = np.full(n_met, -1)
        self.nc_round = np.full(n_met, -1)
        self.dead_f = ~self.allowed_f
        self.dead_r = ~self.allowed_r
        self._propagate()

    @property
    def no_production(self):
        return self.np_round >= 0

    @property
    def no_consumption(self):
        return self.nc_round >= 0

    @property
    def dead_end(self):
        return self.no_production | self.no_consumption

    @property
    def dead_reaction(self):
        return self.dead_f & self.dead_r

    def _propagate(self):
        net = self.net
        rnd = 0
        while True:
            cause_p = (self.no_production & ~self.ignore).astype(float)
            cause_c = (self.no_consumption & ~self.ignore).astype(float)
            self.dead_f = ~self.allowed_f | (net.NegT @ cause_p > 0) | (net.PosT @ cause_c > 0)
            self.dead_r = ~self.allowed_r | (net.PosT @ cause_p > 0) | (net.NegT @ cause_c > 0)
            live_f, live_r = (~self.dead_f).astype(float), (~self.dead_r).astype(float)
            n_producers = net.Apos @ live_f + net.Aneg @ live_r
            n_consumers = net.Aneg @ live_f + net.Apos @ live_r
            n_reactions = net.Atouch @ np.maximum(live_f, live_r)
            # A single reversible reaction cannot both produce and consume a
            # metabolite at steady state, so it still counts as a dead end.
            single = (n_producers > 0) & (n_consumers > 0) & (n_reactions < 2)
            no_prod, no_cons = (n_producers == 0) | single, (n_consumers == 0) | single
            new_p, new_c = no_prod & ~self.no_production, no_cons & ~self.no_consumption
            if not (new_p.any() or new_c.any()):
                return
            self.np_round[new_p] = rnd
            self.nc_round[new_c] = rnd
            rnd += 1


def _bounds(model):
    lb = np.array([r.lower_bound for r in model.reactions], dtype=float)
    ub = np.array([r.upper_bound for r in model.reactions], dtype=float)
    return lb, ub


def _four_runs(model, net, ignore):
    """Propagation as-is, with exchanges opened, with internal reactions made
    reversible, and with both."""
    lb, ub = _bounds(model)
    exch_ids = {r.id for r in model.exchanges}
    is_exch = np.array([r.id in exch_ids for r in model.reactions])
    objective = {r.id for r in linear_reaction_coefficients(model)}
    # The objective (biomass) reaction is never relaxed: running it backwards means nothing.
    is_internal = np.array([not r.boundary and r.id not in objective for r in model.reactions])

    def relaxed(open_exchanges, relax_internal):
        l, u = lb.copy(), ub.copy()
        for mask, wanted in ((is_exch, open_exchanges), (is_internal, relax_internal)):
            if wanted:
                l[mask], u[mask] = -BIG, BIG
        return _Run(net, l, u, ignore)

    return {"now": _Run(net, lb, ub, ignore), "medium": relaxed(True, False),
            "direction": relaxed(False, True), "both": relaxed(True, True)}


def _resolved_by(alive_in):
    """Which single relaxations remove a gap: [] means neither alone (maybe both)."""
    return [name for name in ("medium", "direction") if alive_in[name]]


class _Roots:
    """Root gaps behind every dead metabolite / reaction in one run."""

    def __init__(self, model, run):
        self.model, self.run = model, run
        self.mets = list(model.metabolites)
        self.met_index = {m.id: i for i, m in enumerate(self.mets)}
        # (metabolite index, "p"|"c") -> set of (root metabolite index, "p"|"c"): the roots
        # behind that metabolite's missing production ("p") or consumption ("c"), and which
        # kind of gap each root is.
        self.of_met = {}
        order = sorted(
            [(run.np_round[i], i, "p") for i in np.flatnonzero(run.no_production)] +
            [(run.nc_round[i], i, "c") for i in np.flatnonzero(run.no_consumption)])
        for rnd, i, side in order:
            self.of_met[(i, side)] = {(i, side)} if rnd == 0 else self._causes_of_metabolite(i, side, rnd)

    def _causes(self, rxn, forward, before):
        """Root metabolites behind one dead direction of a reaction, using only
        gaps found before round `before`."""
        run, found = self.run, set()
        for met, coeff in rxn.metabolites.items():
            i = self.met_index[met.id]
            if run.ignore[i]:
                continue
            substrate = (coeff < 0) == forward
            side, rnd = ("p", run.np_round[i]) if substrate else ("c", run.nc_round[i])
            if 0 <= rnd < before:
                found |= self.of_met[(i, side)]
        return found

    def _causes_of_metabolite(self, i, side, rnd):
        found = set()
        for rxn in self.mets[i].reactions:
            j = self.run.net.rxn_index[rxn.id]
            coeff = rxn.metabolites[self.mets[i]]
            # direction that produces (side "p") or consumes (side "c") this metabolite
            forward = (coeff > 0) == (side == "p")
            allowed = self.run.allowed_f[j] if forward else self.run.allowed_r[j]
            if allowed:
                found |= self._causes(rxn, forward, rnd)
        return found

    def of_reaction(self, rxn, j):
        found = set()
        for forward, allowed in ((True, self.run.allowed_f[j]), (False, self.run.allowed_r[j])):
            if allowed:
                found |= self._causes(rxn, forward, np.inf)
        return found

    @staticmethod
    def root_ids(pairs):
        return {root for root, _ in pairs}

    def root_type(self, i):
        p, c = self.run.np_round[i] == 0, self.run.nc_round[i] == 0
        return "RNP+RNC" if p and c else "RNP" if p else "RNC"

    def met_roots(self, i):
        return self.of_met.get((i, "p"), set()) | self.of_met.get((i, "c"), set())


def _is_extracellular(model, met):
    name = (model.compartments.get(met.compartment) or "").lower()
    return (met.compartment or "").lower() in {"e", "e0"} or "extracell" in name or "external" in name


def _classify_metabolites(model, runs, roots_by_run, ignore):
    """One row per dead-end metabolite (dead under the model's current bounds)."""
    now = runs["now"]
    mets = list(model.metabolites)
    live_by_base = defaultdict(list)
    for i, met in enumerate(mets):
        if not now.dead_end[i]:
            live_by_base[metabolite_base_id(met.id)].append(met)

    rows = []
    for i in np.flatnonzero(now.dead_end):
        met = mets[i]
        alive = {k: not runs[k].dead_end[i] for k in ("medium", "direction", "both")}
        tags = _resolved_by(alive)
        if ignore[i]:
            cls, run_key = "currency", "now"
        elif tags:
            cls, run_key = ("conditional" if "medium" in tags else "reversibility"), "now"
        elif alive["both"]:
            cls, run_key = "mixed", "now"
        else:
            run_key = "both"
            p0, c0 = runs["both"].np_round[i] == 0, runs["both"].nc_round[i] == 0
            cls = ("rnp_rnc" if p0 and c0 else "rnp" if p0 else "rnc" if c0 else
                   "downstream" if runs["both"].no_production[i] else "upstream")
        run = runs[run_key]
        roots = {mets[r].id for r in roots_by_run[run_key].root_ids(roots_by_run[run_key].met_roots(i))} - {met.id}

        p, c = now.no_production[i], now.no_consumption[i]
        if not met.reactions:
            reason = "no_reactions"
        else:
            reason = "fully_blocked" if p and c else "no_producing_reaction" if p else "no_consuming_reaction"
        rows.append({
            "id": met.id, "class": cls, "resolved_by": tags, "roots": sorted(roots),
            "reason": reason, "reactions": sorted(r.id for r in met.reactions),
            "transport_hint": _transport_hint(model, met, live_by_base),
        })
    return rows


def _transport_hint(model, met, live_by_base):
    twins = [m for m in live_by_base.get(metabolite_base_id(met.id), []) if m.compartment != met.compartment]
    if _is_extracellular(model, met) and not any(r.boundary for r in met.reactions):
        return "Extracellular, with no exchange reaction."
    if twins:
        return "Connected in " + ", ".join(sorted({m.compartment or "?" for m in twins})) + ": check for a missing transporter."
    return None


def _reaction_flags(rxn, signature_counts, balance):
    flags = []
    if balance[rxn.id]["status"] == "unbalanced":
        flags.append("unbalanced")
    if not rxn.boundary and not (rxn.gene_reaction_rule or "").strip():
        flags.append("no GPR")
    if signature_counts[_signature(rxn)] > 1:
        flags.append("duplicate")
    return flags


def _signature(rxn):
    return frozenset((m.id, c) for m, c in rxn.metabolites.items())


def _classify_blocked(model, blocked_ids, runs, roots_by_run, met_rows):
    """One entry per FVA-blocked reaction, keyed by reaction id."""
    net_index = runs["now"].net.rxn_index
    mets = list(model.metabolites)
    signature_counts = defaultdict(int)
    for rxn in model.reactions:
        signature_counts[_signature(rxn)] += 1
    balance = analyse_all_reactions(model)
    hinted = {row["id"] for row in met_rows if row["transport_hint"]}
    both, now = runs["both"], runs["now"]
    structural_roots = roots_by_run["both"]

    out = {}
    for rid in blocked_ids:
        rxn, j = model.reactions.get_by_id(rid), net_index[rid]
        entry = {"class": "unresolved", "resolved_by": [], "roots": [], "basis": "topology",
                 "flags": _reaction_flags(rxn, signature_counts, balance)}
        if rxn.lower_bound == 0 and rxn.upper_bound == 0:
            entry["class"] = "bounds_closed"
        elif both.dead_reaction[j]:
            entry.update(_dead_end_entry(structural_roots, rxn, j))
            entry["roots"] = sorted(mets[r].id for r in structural_roots.root_ids(structural_roots.of_reaction(rxn, j)))
        elif now.dead_reaction[j]:
            alive = {k: not runs[k].dead_reaction[j] for k in ("medium", "direction")}
            tags = _resolved_by(alive)
            entry["resolved_by"] = tags
            entry["class"] = ("medium" if "medium" in tags else "directionality") if tags else "mixed"
        elif _is_transport(rxn) or any(m.id in hinted for m in rxn.metabolites):
            entry["class"] = "transport"
        out[rid] = entry
    return out


def _dead_end_entry(roots, rxn, j):
    found = roots.of_reaction(rxn, j)
    direct = any(roots.mets[r] in rxn.metabolites for r in roots.root_ids(found))
    has_p, has_c = any(side == "p" for _, side in found), any(side == "c" for _, side in found)
    if has_p and has_c:
        return {"class": "dead_end_both"}
    if has_p:
        return {"class": "dead_end_rnp" if direct else "dead_end_downstream"}
    return {"class": "dead_end_rnc" if direct else "dead_end_upstream"}


def _is_transport(rxn):
    return len({m.compartment for m in rxn.metabolites if m.compartment}) > 1 and not rxn.boundary


def _root_gaps(model, runs, roots, blocked, met_rows):
    """Structural root gaps, with how many metabolites and blocked reactions
    each one causes: the "fix this, not every reaction" summary."""
    run, mets = runs["both"], roots.mets
    affected_mets, affected_rxns = defaultdict(set), defaultdict(set)
    for row in met_rows:
        for root in row["roots"]:
            affected_mets[root].add(row["id"])
    for rid, entry in blocked.items():
        for root in entry["roots"]:
            affected_rxns[root].add(rid)
    gaps = []
    for i in np.flatnonzero(run.dead_end & ((run.np_round == 0) | (run.nc_round == 0)) & ~run.ignore):
        met = mets[i]
        gaps.append({
            "id": met.id, "name": met.name, "compartment": met.compartment, "type": roots.root_type(i),
            "metabolites_affected": len(affected_mets[met.id]),
            "reactions_affected": len(affected_rxns[met.id]),
        })
    gaps.sort(key=lambda g: (-g["reactions_affected"], -g["metabolites_affected"], g["id"]))
    return gaps


def classify_gaps(model, blocked_ids, currency):
    """Tier 1 classification.

    Returns {"dead_end": [rows], "blocked": {reaction id: entry}, "root_gaps": [rows]};
    see _classify_metabolites / _classify_blocked for the fields."""
    net = _Network(model)
    ignore = np.array([metabolite_base_id(m.id) in currency for m in model.metabolites])
    runs = _four_runs(model, net, ignore)
    roots_by_run = {key: _Roots(model, runs[key]) for key in ("now", "both")}

    met_rows = _classify_metabolites(model, runs, roots_by_run, ignore)
    blocked = _classify_blocked(model, blocked_ids, runs, roots_by_run, met_rows)
    return {"dead_end": met_rows, "blocked": blocked,
            "root_gaps": _root_gaps(model, runs, roots_by_run["both"], blocked, met_rows)}
