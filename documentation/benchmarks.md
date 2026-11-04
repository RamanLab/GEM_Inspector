# Benchmarks

This page reports how GEM Inspector's results compare with the implementations it builds on or overlaps with, and how long the analyses take. All numbers were produced by one script on one machine and can be reproduced; the setup is given at the end.

## Models

| Model | Reactions | Metabolites | Genes |
|---|---|---|---|
| e_coli_core | 95 | 72 | 137 |
| iJO1366 | 2583 | 1805 | 1367 |
| STM_v1_0 | 3357 | 2436 | 1707 |
| iML1515 | 2712 | 1877 | 1516 |

*e_coli_core* is the textbook model; *iJO1366* and *iML1515* are *E. coli* models and *STM_v1_0* is a *Salmonella* model. Models other than *e_coli_core* were loaded without changes, with the media defined in the files.

## Agreement with existing implementations

| Model | Blocked reactions equal to COBRApy | FROG deletion mismatches vs COBRApy | Flagged metabolites that are not strict gaps | Unflagged sample that are strict gaps |
|---|---|---|---|---|
| e_coli_core | yes | 0 of 95 | 0 of 0 | 24 of 144 |
| iJO1366 | yes | 0 of 2583 | 0 of 217 | 9 of 300 |
| STM_v1_0 | yes | 0 of 3357 | 0 of 330 | 10 of 300 |
| iML1515 | yes | 0 of 2712 | 1 of 239 | 22 of 300 |

Blocked reactions and the FROG-style single-reaction deletion results were compared with COBRApy 0.32.1 (`find_blocked_reactions` and `single_reaction_deletion`) on every model. The blocked-reaction sets are identical and the growth rates agree to 10⁻⁶ for every reaction, which is expected because the tool reuses these definitions; the comparison guards against regressions in the shared caches.

For GapFind there is no reference implementation to compare with directly, so two checks were made. First, each metabolite reported as not produced or not consumed was tested with an independent linear program at strict steady state (a drain or source for that metabolite on its own); a flagged metabolite that the strict test could still produce would be a false positive. Second, a random sample of 150 unflagged metabolites per direction was tested the other way. Unflagged metabolites that are strict gaps are expected: they are conserved moieties (ATP/ADP, NAD(P)H pairs, CoA, quinones), which cannot be net-produced at steady state but are not gaps in the GapFind sense, which allows accumulation. Table above gives the counts. Where a flagged metabolite was not a strict gap, we did not investigate the cause; it may be a difference in tolerance between the threshold of 10⁻⁴ and the strict test.

### GapFind: linear programs and the original mixed-integer program

The GapFind mixed-integer program ties the threshold ε to every reaction entry through a big-M constant, and its answer therefore depends on the scale of fluxes and stoichiometric coefficients. On iJO1366 the toolbox formulation, implemented with the same threshold and big-M, reported about 115 consumption-side metabolites for which a flux distribution that consumes them exists, according to the independent linear program. GEM Inspector therefore solves the same definition exactly with linear programs; the MILP run took 265 to 360 s on the same machine and the linear-program solution about 80 s. We note that this comparison concerns our implementation of the published formulation, not the COBRA Toolbox run in MATLAB.

## Comparison with MACAW on dead ends

MACAW identifies dead-end metabolites with a structural test that uses the bounds of the model as they are. Table below compares it with GEM Inspector in two settings: with the bounds as they are, and with all exchanges opened, which is how GEM Inspector reports gaps.

| Model | MACAW, as-is bounds: shared | only GEM Inspector | only MACAW | MACAW, exchanges opened: GEM Inspector found | shared | only MACAW |
|---|---|---|---|---|---|---|
| e_coli_core | 4 | 0 | 0 | 0 | 0 | 4 |
| iJO1366 | 603 | 18 | 24 | 155 | 153 | 474 |
| STM_v1_0 | 694 | 47 | 15 | 219 | 196 | 513 |
| iML1515 | 636 | 30 | 46 | 178 | 177 | 505 |

With the bounds as they are, the two methods largely agree and differ in a small number of metabolites in both directions; on *e_coli_core* GEM Inspector reproduces MACAW's four metabolites exactly. With exchanges opened, GEM Inspector reports far fewer metabolites, because many metabolites that look like dead ends are only so because the medium lacks the corresponding uptake; the metabolites found by both methods are the ones that remain gaps of the network itself. The remaining differences were not examined individually.

## Reported counts

| Model | Dead-end metabolites | Root NP | Downstream NP | Root NC | Upstream NC | Blocked reactions | Dead-end-linked |
|---|---|---|---|---|---|---|---|
| e_coli_core | 0 | 0 | 0 | 0 | 0 | 8 | 0 |
| iJO1366 | 155 | 50 | 50 | 60 | 57 | 878 | 158 |
| STM_v1_0 | 219 | 64 | 75 | 84 | 107 | 983 | 209 |
| iML1515 | 178 | 45 | 50 | 63 | 81 | 968 | 182 |

## Runtime

| Model | GapFind | Blocked reactions (incl. GapFind) | COBRApy blocked | FROG reaction deletions | COBRApy reaction deletions |
|---|---|---|---|---|---|
| e_coli_core | 1.0 | 0.5 | 0.0 | 0.3 | 0.0 |
| iJO1366 | 82 | 141 | 30 | 84 | 14 |
| STM_v1_0 | 71 | 128 | 71 | 152 | 34 |
| iML1515 | 49 | 92 | 37 | 104 | 16 |

Times are in seconds, on two virtual CPUs with GLPK and one process per analysis. GapFind uses HiGHS in two processes. The blocked-reaction time includes the dead-end analysis when it has not been run, so the two are not independent. For flux variability and reaction deletions, the numbers show that GEM Inspector is slower than the COBRApy calls it is compared with, by about a factor of two to six in these runs; we did not investigate the cause in detail. The values are the cost of the single-process default, and the tool can use more cores (see [Solvers](getting-started/solvers.md)). Because the results are cached per model, each analysis is paid for once per loaded model.

## Reproducing

Setup: Python 3.13.18, COBRApy 0.32.1, 2 virtual CPUs, GLPK as the LP solver, a single run per model (no repetitions, so timings carry run-to-run variation). The script is `docs/benchmarks/run_benchmark.py` in the repository (it contains local file paths for the models that must be adjusted).

## What the comparison does not show

The benchmarks are on published models and compare results and run times with other implementations. They do not measure usability, and they do not show that the reported gaps correspond to errors in the models.
