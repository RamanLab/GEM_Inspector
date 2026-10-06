"""Annotation and Translational Toolkit.

Everything concerned with a model's *identifiers* rather than its biology:

  - naming.py            friendly compartment names, cleaned metabolite/
                          reaction display names, and the currency/cofactor
                          metabolite list used to keep pathway traces readable
  - namespace_mapping.py  detecting which id namespace a model uses (BiGG,
                          VMH, ModelSEED, KEGG, MetaCyc, ...) and translating
                          every id to a MetaNetX id via the bundled xref
                          tables, plus an audit of ids that didn't translate

Every other section imports from here to display and cross-reference model
identifiers consistently.
"""
