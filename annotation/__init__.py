"""Annotation and Translational Toolkit.

Everything concerned with a model's *identifiers* rather than its biology:

  - naming.py            friendly compartment names, cleaned metabolite/
                          reaction display names, and the currency/cofactor
                          metabolite list used to keep pathway traces readable
  - namespace_mapping.py  detecting which id namespace a model uses (BiGG,
                          VMH, ModelSEED, KEGG, MetaCyc, ...) and translating
                          every id to a MetaNetX id via the bundled xref
                          tables, plus an audit of ids that didn't translate
  - translation_tables.py bundled SEED -> VMH id tables (data/*TranslationTable.txt)
  - seed_to_vmh.py        renaming a SEED-namespace model to VMH ids and
                          reporting what was mapped, errored, or unmapped
  - translation_export.py the translated model + report as downloadable files
  - routes.py             the translation endpoints

Every other section imports from here to display and cross-reference model
identifiers consistently.
"""
