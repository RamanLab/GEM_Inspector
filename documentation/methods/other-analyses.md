# Other analyses

| Analysis | Method | Verification |
|---|---|---|
| Minimal medium | `cobra.medium.minimal_medium` with the target growth set slightly below the model's own optimum (by 10⁻⁶ relative) to avoid infeasibility from round-off. The LP minimises total uptake; the MILP variant minimises the number of components. | Uses the model's own growth as target, not an artificially opened model. |
| Exchange essentiality | Each exchange is knocked out in turn with the shared knockout routine; essential if growth falls below 5 % of wild type. | Shares results with the FROG and demand and sink analyses. |
| Reaction balance | Sum of element counts weighted by stoichiometry (products minus reactants) with a tolerance of 10⁻⁶, plus charge where defined. Boundary and biomass reactions are not applicable. | Fix suggestions are verified by recomputing the balance. |
| Biomass precursors | A temporary demand per precursor, biomass switched off, maximal demand flux under the applied medium and with all exchanges open. | Performed in a temporary context. |
| FROG | Flux variability, single reaction deletion, objective value, single gene deletion, on the exact-arithmetic GLPK solver where the default solver is GLPK. | Deletion results equal COBRApy's `single_reaction_deletion`; see [Benchmarks](../benchmarks.md). |
| MEMOTE | The MEMOTE test suite run in a child process. | Not shared with other analyses because it solves its own copy of the model. |

## Numerical robustness

Repeated LP solves on badly scaled genome-scale models (for example with exchanges opened to ±1000) can abort plain GLPK on some builds, taking the host process with it. When the model uses GLPK, the repeated-solve analyses run on GLPK's exact-arithmetic interface instead, which avoids floating-point scaling at some cost in speed. Gurobi, CPLEX and HiGHS do not need this and are used as they are.

## Infeasible knockouts

A knockout that leaves the model infeasible is reported as *infeasible* and is treated as zero growth where a growth value is needed, rather than being reported as an error. This matches COBRApy's reaction-deletion output.
