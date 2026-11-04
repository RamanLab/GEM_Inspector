# Annotation and translation

Models built by different groups use different identifier systems, which makes comparison and integration difficult. This module detects what a model uses and translates between systems.

## Identifier namespaces and annotation

For metabolites, reactions and genes the tool infers the identifier namespace (for example BiGG, ModelSEED, VMH, KEGG, MetaCyc), and summarises annotation coverage. The result is also used by the comparison and report features to decide whether two models can be matched by identifier directly.

## Translation via MetaNetX

Identifiers of any supported namespace are mapped through the MetaNetX cross-reference tables (`chem_xref`, `reac_xref`) to MetaNetX, BiGG, VMH, ModelSEED, KEGG or MetaCyc. Each entity is reported as mapped, ambiguous, or without a mapping, and the translated model can be downloaded.

## SEED to VMH

A dedicated route converts ModelSEED-namespace models to VMH identifiers with the translation tables in the `data/` folder. Entities are reported as mapped, as errors (the table is ambiguous or the new identifier would collide with an existing one) or as unmapped. The translated model, in SBML and JSON, and the report are downloaded as one archive.
