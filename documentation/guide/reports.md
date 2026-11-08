# Reports and exports

## Model report

The **Generate report** button on the results page assembles the sections chosen by the user, with figures and quality findings, into a single self-contained HTML file, optionally accompanied by an Excel workbook.  The warning thresholds set in the network-gaps tab determine which findings are flagged.

## Multiple models

The *Analyze multiple models* workflow takes two to five models (the server rejects more) and produces a side-by-side comparison of model statistics, quality control indicators and automatically raised findings, with charts, as an HTML report and an Excel workbook. Thresholds for the findings can be adjusted. The report includes the network-gap fractions computed by the same GapFind and FVA analyses as the single-model workflow. Every model is analysed in full, so genome-scale models take minutes each; the interface asks for confirmation above three models.

## CSV, Excel and clipboard

Tables across the tool can be searched, filtered and sorted by column. The principal result tables (minimal medium, dead-end metabolites, blocked reactions, demand and sink audit, balance audit, FROG, model comparison) can be copied to the clipboard or exported as CSV; the audit and comparison results are also available as Excel workbooks.
