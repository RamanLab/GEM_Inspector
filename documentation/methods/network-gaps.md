# Network gaps

This page describes how dead-end metabolites and blocked reactions are identified and classified. The two steps are independent: the blocked-reaction step computes the dead-end result itself when it has not been run.

## Dead-end metabolites (GapFind)

### Definition

A metabolite is *not produced* if no flux distribution within the reaction bounds, with every metabolite at steady state or accumulating, can produce it, and *not consumed* if none can consume it. These are the gaps defined by Kumar, Dasika and Maranas (2007) in the GapFind procedure. A structural test, "no reaction produces the metabolite", finds only the simplest cases; the formulation below also finds metabolites whose only producers require a precursor that cannot itself be made, which a structural test misses.

### Formulation

Let $S$ be the stoichiometric matrix, $v$ the flux vector within bounds $\ell \le v \le u$, and $\varepsilon$ a small positive threshold (10⁻⁴ here). A metabolite $i$ is *produced* if some flux vector satisfying

```latex
\sum_j S_{kj} v_j \ge 0 \;\; \forall k, \qquad \ell \le v \le u
```

has a producing reaction entry with $\sum_{j \in P_i} S_{ij} v_j \ge \varepsilon$, where $P_i$ contains the reactions that can produce $i$ (a positive entry of an irreversible reaction, and every entry of a reversible one). Kumar, Dasika and Maranas express this as a single mixed-integer program with a binary variable per producing entry and a big-M constant. GEM Inspector solves the same definition exactly with linear programs instead, because the big-M formulation couples $\varepsilon$ to every reaction entry and its answer depends on the scale of fluxes and stoichiometric coefficients; on *E. coli* iJO1366 it reported about 115 consumption-side metabolites that an independent linear program shows to be consumable (see [Benchmarks](../benchmarks.md)).

The linear-program solution has two phases. A batch certification program maximises $\sum_i \min(p_i, \varepsilon)$ over all remaining candidates at once, where $p_i$ is the production of $i$ by one-direction-only reactions; every metabolite reaching $\varepsilon$ is certified as produced, and the step repeats on the rest. Candidates that are still uncertified are tested one at a time, one producing entry per program, with early exit at $\varepsilon$. A metabolite that no program can produce is not produced. Solving the same problem on $-S$ identifies the metabolites that are not consumed. The programs are solved with HiGHS through SciPy, independently of the solver selected for the other analyses.

### Medium independence

All exchange reactions are opened to ±1000 before the problem is solved. The gaps found therefore belong to the network itself and do not depend on the medium, so a metabolite is not reported merely because the current medium lacks a nutrient. Blocked reactions, in contrast, are reported under the medium currently applied.

### Classification

Each unproduced or unconsumed metabolite is placed in one of four classes. A metabolite can belong to more than one, for example when it is both a downstream no-production and a root no-consumption metabolite.

| Class | Meaning |
|---|---|
| Root no-production | No reaction can produce it, because none has a producing direction within its bounds. A true source of the gap. |
| Downstream no-production | Some reaction could produce it, but every such reaction requires a metabolite that is itself not produced. The gap is inherited from a root upstream. |
| Root no-consumption | No reaction can consume it. |
| Upstream no-consumption | Some reaction could consume it, but every such reaction leads only to a metabolite that is not consumed. The gap is inherited from a root downstream. |

Roots are recognised structurally from the bounds, and downstream and upstream gaps are the remaining unproduced and unconsumed metabolites. Curation effort is best directed at the roots, since resolving one root can resolve many inherited gaps.

### Computation and runtime

The two problems (production on $S$, consumption on $-S$) run in separate child processes, so an unrecoverable solver failure cannot terminate the web server, and the two run side by side on separate cores. Measured timings are given in [Benchmarks](../benchmarks.md).

## Blocked reactions

A reaction is blocked if its minimum and maximum flux are both zero (within the solver tolerance) in a flux variability analysis at 0 % of the optimal objective. This definition is identical to COBRApy's `find_blocked_reactions` and is verified against it in the [benchmarks](../benchmarks.md). Because exchanges keep the bounds of the applied medium, the result reflects the current medium.

Each blocked reaction is then assigned to one of two groups:

* **Dead-end-linked**: the reaction has at least one participant metabolite that was classified as a dead end. The dead-end metabolites responsible are listed with it.
* **Not dead-end-linked**: no participant is a dead end, so the blockage arises from something else, for example the medium, a reaction direction, a thermodynamic or loop constraint, or a dependency between several reactions.

Finer subcategories of the second group are not assigned by the tool at present.

!!! warning "Interpretation"
    A high fraction of blocked reactions or dead-end metabolites does not by itself indicate a poor model; it may reflect incomplete knowledge of the organism. The classes are intended to direct inspection, not to establish error.

## Shared computation

The flux variability analysis at 0 % of the optimum is the same computation as the FROG report with the corresponding cut-off, and is computed once per loaded model.
