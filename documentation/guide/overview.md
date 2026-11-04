# Overview module

The Overview module characterises a model before any diagnostic work begins. Its tabs are read-only views of the loaded model with an optional quality assessment.

## Summary

The summary presents the number of genes, metabolites, reactions and compartments, the predicted wild-type growth rate in h⁻¹ (the optimum of the model's objective by flux balance analysis), the solver in use, and the medium that was applied at upload. The growth rate is the only quantity expressed per hour; the objective value of any other objective is shown without a unit.

### MEMOTE quality assessment

On request, the tool runs [MEMOTE](https://memote.readthedocs.io) (Lieven et al., 2020) on the model and reports the total score, the section scores and a list of the areas that need attention, each linked to the tab of this tool that can investigate it. The full MEMOTE HTML report can be opened or downloaded. MEMOTE runs in a separate process, shows progress, can be cancelled, and is repeated once with an exact-arithmetic GLPK solver if the first attempt fails.

## Metabolites, reactions and genes

Searchable and sortable tables list every component. Metabolites carry compartment, formula and charge; reactions carry type (internal, transport, boundary), subsystem, flux in the current solution, genes and balance status; genes list the reactions they are associated with, those that would be lost on deletion and how many are active in the wild-type solution. Identifiers throughout the tool are hyperlinks: a click moves to the corresponding reaction, metabolite or gene, and a hover shows a summary card. Compartment codes are displayed with readable names (for example *c* as cytosol).

## Objective

The objective tab lists the objective reaction or reactions and decomposes the biomass reaction into its precursors with their stoichiometric coefficients, identifying what the model regards as the essential building blocks of growth.

## Related

[Diagnostics and comparative analyses](diagnostics.md) · [Reports and exports](reports.md)
