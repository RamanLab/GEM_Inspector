# Comparison with existing tools

Several mature tools address parts of the same problem. This page states what each provides, as described in its own publication or documentation, and where GEM Inspector overlaps with it, complements it or does not attempt the task. The statements about other tools were checked against their publications and repositories on the date of writing; capabilities change, so consult the sources.

## Capability overview

| Capability | GEM Inspector | MEMOTE | MACAW | ModelExplorer | COBRApy | COBRA Toolbox | FROG (fbc_curation) |
|---|---|---|---|---|---|---|---|
| Interface | Web GUI, local | Web and CLI reports | Python and R scripts | Desktop GUI | Python library | MATLAB library | CLI, web, REST |
| Annotation and SBO checks | Namespace detection, coverage | **Yes** | – | – | – | – | – |
| Mass and charge balance | Per reaction, with cause and verified fix suggestions | Counts and checks | – | – | – | – | – |
| Dead-end metabolites | GapFind definition solved by LP; root and downstream classes | Reported in consistency analysis | Structural test with dead-end networks | Blocked metabolites | – | `detectDeadEnds`, `gapFind` | – |
| Blocked reactions | FVA, grouped by dead-end linkage | Reported | Via dead-end test | Via ExtraFastCC | `find_blocked_reactions` | Consistency functions | – |
| Dilution, duplicate and loop tests | – | Energy-generating cycles | **Yes** | – | – | – | – |
| Reproducibility reference data | FROG-style quantities (CSV, HTML) | – | – | – | – | – | **Yes** (standard files) |
| Active-flux pathway tracing | **Yes**, with knockout comparison | – | Network of flagged reactions | Neighbour views | – | – | – |
| Interactive network view | Cytoscape.js, compartment lanes | – | Export for Cytoscape | **Yes** (own renderer) | – | – | – |
| Identifier translation | MetaNetX | – | – | – | – | – | – |
| Multi-model comparison | Statistics, findings, pairwise comparison | Diff report | – | – | – | – | – |
| Version history and continuous integration | – | **Yes** | – | – | – | – | – |
| Model editing and repair | Suggestions only | – | Suggestions | Manual editing | **Yes** (API) | **Yes** | – |
| Gap-filling | – | – | – | – | `gapfill` | `gapFill`, `fastGapFill` | – |

*Sources: Lieven et al. (2020); Moyer et al. (2025); Martyushenko and Almaas (2019); Ebrahim et al. (2013); Heirendt et al. (2019); Raman et al. (2024) and the fbc_curation documentation.* A dash means the tool does not advertise the capability, not that it cannot be scripted.

## Relationship to each tool

**MEMOTE** is the community standard for model quality testing, with annotation, SBO, stoichiometric-consistency and biomass tests, snapshot, diff and history reports and continuous-integration support. GEM Inspector does not replace it; it runs MEMOTE on request and links the areas that need attention to tools that can investigate them. What it adds is interactive follow-up: MEMOTE reports that a model has blocked reactions or unbalanced reactions, and GEM Inspector shows which dead ends are responsible, which metabolites or formulas explain an imbalance, and what a fix would do.

**MACAW** detects errors that arise from groups of reactions: dead-end pathways, dilution-constrained inconsistencies, duplicates (including redox duplicates) and flux loops. These tests are outside the scope of GEM Inspector. The two overlap on dead ends, where MACAW applies a structural test and GEM Inspector uses the GapFind definition with a root and inherited classification; the [benchmarks](benchmarks.md) compare their results on the same models. MACAW is a scripting library, whereas GEM Inspector is used through a browser.

**FROG** analysis defines standardised reference data (flux variability, reaction deletion, objective and gene deletion) for reproducibility. GEM Inspector computes the same four quantities and exports them as CSV and HTML, but it does not generate the standardised FROG files or validate SBML-FBC; use `fbc_curation` for submission to BioModels.

**ModelExplorer** shares the aim of visual inspection and offers fast rendering and manual editing of large networks. GEM Inspector is browser-based, makes no changes to the model, and concentrates on classification and tracing along active flux rather than on editing.

**COBRApy and the COBRA Toolbox** supply the underlying computations (and, in the Toolbox, `gapFind`). GEM Inspector is built on COBRApy and reimplements the GapFind formulation of the Toolbox in Python (through the optlang solver interface), with the classification described in [Network gaps](methods/network-gaps.md).

**RAVEN** is a MATLAB toolbox for semi-automated reconstruction that also contains gap-filling and quality-control functions. It is aimed at building models rather than inspecting finished ones, and is complementary: a model reconstructed with RAVEN can be inspected here.

## What GEM Inspector does

* Classifies dead-end metabolites into root and inherited classes, independently of the medium.
* Groups FVA-blocked reactions by linkage to those dead ends.
* Explains balance failures by identifier mapping and formula comparison, and verifies each suggested fix.
* Traces flux-carrying routes between any two metabolites, with before and after knockout comparison, user-editable cofactors, extra metabolites and a compartment view.
* Converts between identifier namespaces and compares models.
* Produces reports and exports without requiring programming.

## What GEM Inspector does not do

* It does not repair or gap-fill models, and it does not edit them. Suggestions are shown for the curator to apply elsewhere.
* It does not test for dilution-constrained errors, duplicate reactions or flux loops.
* It does not test annotation against SBO terms or provide MEMOTE's version history and continuous-integration workflow.
* It does not generate the standardised FROG files.
* It does not further subdivide blocked reactions that are not linked to dead ends (for example by medium, direction or loop constraints).
* It is a single-user, in-memory application. It has no persistent storage or accounts, and models expire after ten minutes of inactivity.
* Models far beyond a few thousand reactions make GapFind slow under GLPK; a commercial solver is advisable.
