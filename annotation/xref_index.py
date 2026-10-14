"""Reverse lookups over the bundled MetaNetX xref tables: from a MetaNetX id
to the ids that refer to it in each database, and from an id to the
namespaces it appears in."""
from annotation.namespace_mapping import load_xref

_reverse_cache = {}


def reverse_index(kind, namespace):
    """{mnx_id: [ids in `namespace`]} for kind "chem" or "reac" (file order,
    no duplicates)."""
    key = (kind, namespace)
    if key not in _reverse_cache:
        index = {}
        for ident, mnx in load_xref(kind).get(namespace, {}).items():
            index.setdefault(mnx, []).append(ident)
        _reverse_cache[key] = index
    return _reverse_cache[key]


def namespaces_containing(kind, ident, namespaces):
    """Which of `namespaces` list `ident` as one of their ids."""
    xref = load_xref(kind)
    return [ns for ns in namespaces if ident in xref.get(ns, {})]
