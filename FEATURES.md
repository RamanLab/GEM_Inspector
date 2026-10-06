# Genome-scale Model Inspector — Feature Summary

This tool lets you upload a metabolic model of a cell (a file listing all the genes, chemical reactions, and molecules the cell can use) and explore it in a web browser, without writing any code. It runs entirely on your own computer — nothing is uploaded anywhere else.

## Getting started

You upload a model file (the common formats are supported: SBML/XML, JSON, YAML, MATLAB, or a compressed SBML file). Before the analysis runs, you can also choose what "food" the model is allowed to use — its original settings, unlimited food, a computed minimal diet, or your own custom list of nutrients uploaded as a spreadsheet-style file. Once you click Analyze, the tool loads the model and shows you a set of tabs, each covering a different question you might have about it.

## Overview tab

A quick snapshot: how many genes, molecules, and reactions the model contains, how many compartments it's divided into (like the inside vs. outside of the cell), how fast the model predicts the cell can grow, and a note on which diet was used and whether any of your custom diet entries couldn't be matched.

## Metabolites tab

A searchable, sortable list of every molecule in the model — its name, ID, which compartment it's in, its chemical formula, and its charge. You can filter down to one compartment or search by name.

## Reactions tab

A searchable, sortable list of every reaction in the model — its name, what category it falls into (an internal reaction, a transport step between compartments, or a boundary reaction), which pathway/subsystem it belongs to, how fast it's predicted to run, and which genes are behind it. You can filter by category or pathway, or search by name.

## Objective tab

Shows what the model is actually trying to maximize — normally, growth — broken down into the individual ingredients (molecules) that growth depends on, with how much of each is needed. This is useful for understanding what the model considers "essential building blocks" for the cell to grow.

## Minimal Medium tab

Answers the question: "what is the smallest set of nutrients this cell needs to grow?" You choose how much growth you want to guarantee (anywhere from a sliver of the model's maximum growth rate up to its full potential), and the tool works out the shortest shopping list of nutrients that achieves it — each one listed with how much of it is needed. The result can be exported to a spreadsheet (CSV) file.

## Exchange Essentiality tab

For every nutrient the model can take in or release, this tab tests what happens if that nutrient is cut off entirely. It reports whether the cell can still grow, how much growth is lost, and flags the nutrient as "essential" if removing it drops growth to almost nothing. This is the fastest way to see which foods a cell truly cannot live without.

## Exchange Debugging tab

Once you know which nutrients are essential, this tab lets you dig into *why*. For any essential nutrient you pick, it traces the actual chemical path that nutrient takes, step by step, all the way through to growth — both with the nutrient available and with it removed, so you can see exactly which route disappears (or reroutes) when it's taken away.

## Pathway Tracer tab

A more general, flexible version of the tracing above: pick any starting point (a molecule, or a reaction) and any destination molecule, and the tool finds the chemical paths connecting them, regardless of whether nutrients or growth are involved. You can view the result as a simple step-by-step description, or as an interactive diagram you can zoom, filter, and search. You can also compare "before and after" by removing a reaction or molecule from the network and seeing what changes.

## Network Gaps & Audits tab

Three checks aimed at spotting problems or leftover clutter in the model itself, rather than testing specific nutrients:

- **Blocked reactions** — reactions that are simply incapable of ever being used, given the model's current settings — often a sign of a gap or missing connection in the model.
- **Dead-end molecules** — molecules that can only ever be produced, or only ever be consumed, but never both — a common underlying cause of blocked reactions.
- **Demand & sink audit** — a review of a special category of "helper" reactions that modelers sometimes add by hand (distinct from normal nutrient exchanges). This flags ones that appear to be doing nothing, and ones that are quietly propping up the model's growth prediction and may deserve a second look.

All three results can be exported to CSV.

## Other conveniences

- **Diet / media options** — before running the analysis, you can simulate the model on its own default nutrient settings, on unlimited nutrients, on a computed minimal diet, or on your own custom nutrient list (uploaded as a simple two-column file).
- **Readable compartment names** — internal compartment codes (like "c" or "e0") are automatically shown with friendly names (like "Cytosol" or "Extracellular space") wherever they appear.
- **Search, filter, and sort** — every table in the tool can be searched, filtered, and sorted by clicking a column header.
- **CSV export** — the Minimal Medium and Network Gaps & Audits tables can each be exported as a spreadsheet file for use elsewhere.
- **Nothing is changed permanently** — every "what if" test (removing a nutrient, blocking a reaction, trying a different diet) is temporary and only affects that one calculation; the model you uploaded is never permanently altered.

## Added: Overview batch
- Module navigation (4 modules + References) with sub-tabs; Overview is the default page.
- On-request MEMOTE run: background process, progress bar, cancel, auto-retry with `glpk_exact`, score and section scores, "needs attention" list linking to the relevant tab, full MEMOTE HTML report (open/download).
- References tab: MEMOTE, COBRApy, Thiele & Palsson 2010, FROG/COMBINE, MetaNetX, libSBML, Cytoscape.js, GLPK.
- ID namespace / annotation cards moved to Annotation & Translation > ID namespaces & annotation.
