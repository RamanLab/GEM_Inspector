"""Id-namespace detection and MetaNetX cross-referencing.

On "Analyze model", before anything else is shown, this works out:
  (a) which id namespace the uploaded model's metabolites/reactions use
      (BiGG, VMH, ModelSEED, KEGG, MetaCyc, ...), and
  (b) a MetaNetX (MNX) id for every metabolite/reaction, via a bundled,
      filtered copy of MetaNetX's own chem_xref/reac_xref cross-reference
      tables (data/chem_xref.tsv.gz, data/reac_xref.tsv.gz -- three
      columns: namespace, id-in-that-namespace, mnx-id).

Namespace detection is itself data-driven off these same tables (rather
than hand-written per-vendor regexes): whichever namespace's id set matches
the most ids in this model is the detected namespace.
"""
import gzip
import re
from pathlib import Path

from annotation.naming import (
    clean_metabolite_display_name,
    clean_reaction_display_name,
    metabolite_base_id_preserve_case,
)

CHEM_NAMESPACES = [
    "bigg.metabolite", "biggM",
    "vmhmetabolite", "vmhM",
    "seed.compound", "seedM",
    "kegg.compound",
    "metacyc.compound", "metacycM",
]
REAC_NAMESPACES = [
    "bigg.reaction", "biggR",
    "vmhreaction", "vmhR",
    "seed.reaction", "seedR",
    "kegg.reaction",
    "metacyc.reaction", "metacycR",
]
NS_LABELS = {
    "bigg.metabolite": "BiGG", "biggM": "BiGG (legacy M_-prefixed)",
    "vmhmetabolite": "VMH", "vmhM": "VMH (legacy M_-prefixed)",
    "seed.compound": "ModelSEED", "seedM": "ModelSEED (legacy M_-prefixed)",
    "kegg.compound": "KEGG",
    "metacyc.compound": "MetaCyc", "metacycM": "MetaCyc (legacy M_-prefixed)",
    "bigg.reaction": "BiGG", "biggR": "BiGG (legacy R_-prefixed)",
    "vmhreaction": "VMH", "vmhR": "VMH (legacy R_-prefixed)",
    "seed.reaction": "ModelSEED", "seedR": "ModelSEED (legacy R_-prefixed)",
    "kegg.reaction": "KEGG",
    "metacyc.reaction": "MetaCyc", "metacycR": "MetaCyc (legacy R_-prefixed)",
}

_MNX_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_xref_cache = {"chem": None, "reac": None}
_detect_cache = {}


def _load_xref(kind):
    """Lazily load and cache the bundled MetaNetX xref table for "chem" or
    "reac" into {namespace: {id: mnx_id}}. Loaded once per process, on
    first use, and kept in memory for the life of the server."""
    if _xref_cache[kind] is not None:
        return _xref_cache[kind]
    fname = "chem_xref.tsv.gz" if kind == "chem" else "reac_xref.tsv.gz"
    path = _MNX_DATA_DIR / fname
    xref = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) != 3:
                    continue
                ns, ident, mnx_id = parts
                xref.setdefault(ns, {})[ident] = mnx_id
    except FileNotFoundError:
        xref = {}
    _xref_cache[kind] = xref
    return xref


def load_xref(kind):
    """The bundled MetaNetX xref table for "chem" or "reac" as
    {namespace: {id: mnx_id}} (empty if the data file is missing)."""
    return _load_xref(kind)


def detect_namespace_and_map(id_pairs, xref, ns_list):
    """id_pairs: list of (original_id, lookup_key) tuples. xref: the loaded
    {namespace: {id: mnx_id}} table. ns_list: namespaces to consider, most
    specific first.

    Finds whichever namespace's id set matches the most lookup_keys in this
    model (the model's detected/dominant namespace), then builds a full
    original_id -> mnx_id map for every id, trying that namespace first and
    falling back to any other known namespace per-id (handles models that
    mix conventions, or a handful of ids the dominant namespace misses).

    Returns (detected_namespace_or_None, coverage_fraction,
    example_original_id_or_None, {original_id: mnx_id_or_None}).
    """
    total = len(id_pairs)
    if total == 0:
        return None, 0.0, None, {}

    best_ns, best_count, best_example = None, 0, None
    for ns in ns_list:
        idset = xref.get(ns)
        if not idset:
            continue
        count = 0
        example = None
        for orig, key in id_pairs:
            if key in idset:
                count += 1
                if example is None:
                    example = orig
        if count > best_count:
            best_ns, best_count, best_example = ns, count, example

    coverage = (best_count / total) if total else 0.0

    id_to_mnx = {}
    primary_map = xref.get(best_ns, {}) if best_ns else {}
    fallback_namespaces = [ns for ns in ns_list if ns != best_ns]
    for orig, key in id_pairs:
        mnx = primary_map.get(key)
        if mnx is None:
            for ns in fallback_namespaces:
                mnx = xref.get(ns, {}).get(key)
                if mnx is not None:
                    break
        id_to_mnx[orig] = mnx
    return best_ns, coverage, best_example, id_to_mnx


def _detect_cached(kind, id_pairs, xref_kind, namespaces):
    """Detection depends only on the ids, so identical id lists (the same model
    analysed by several tabs, or a translated copy that kept its ids) reuse one result."""
    key = (kind, tuple(id_pairs))
    if key not in _detect_cache:
        if len(_detect_cache) >= 8:
            _detect_cache.pop(next(iter(_detect_cache)))
        _detect_cache[key] = detect_namespace_and_map(id_pairs, _load_xref(xref_kind), namespaces)
    ns, coverage, example, mapping = _detect_cache[key]
    return ns, coverage, example, dict(mapping)


def detect_metabolite_namespace_and_map(model):
    id_pairs = [(met.id, metabolite_base_id_preserve_case(met.id)) for met in model.metabolites]
    return _detect_cached("chem", id_pairs, "chem", CHEM_NAMESPACES)


def detect_reaction_namespace_and_map(model):
    # Reaction ids keep their compartment tag as part of the id itself
    # (e.g. "EX_glc__D_e"), so -- unlike metabolites -- they're looked up
    # as-is, with no compartment-suffix stripping.
    id_pairs = [(rxn.id, rxn.id) for rxn in model.reactions]
    return _detect_cached("reac", id_pairs, "reac", REAC_NAMESPACES)


def _normalize_name_for_match(name):
    """Loosely normalize a metabolite/reaction display name for same-model
    name matching: lowercase, collapse anything that isn't a letter/digit
    into a single space.

    Used only to compare names WITHIN a single uploaded model. The bundled
    MetaNetX cross-reference tables are id <-> id only and carry no names,
    so there's no external name database to check an unmapped id against.
    The next best signal is whether the same name already appears on a
    different, already-mapped id elsewhere in this model -- the signature
    of a namespace mix-up (e.g. a couple of VMH-style ids added into an
    otherwise-BiGG model under different ids than the rest of the model
    would have used for the same compound).
    """
    if not name:
        return None
    n = re.sub(r"[^a-z0-9]+", " ", name.strip().lower()).strip()
    return n or None


def compute_unmapped_id_audit(model, met_to_mnx, rxn_to_mnx):
    """Find metabolites/reactions that didn't map to any MetaNetX id under
    any of the bundled namespaces, and for each one, look for other ids in
    THIS model that share its (normalized) display name and DID map -- see
    _normalize_name_for_match for why this is a same-model check rather
    than a lookup against an external name table.

    Returns a dict with per-kind lists of unmapped entries (each carrying
    any same-name "likely_duplicate_of" candidates found elsewhere in the
    model) plus mapped/unmapped counts.
    """
    met_name_index = {}
    for met in model.metabolites:
        norm = _normalize_name_for_match(clean_metabolite_display_name(met))
        if norm:
            met_name_index.setdefault(norm, []).append(met.id)

    unmapped_metabolites = []
    mapped_metabolite_count = 0
    for met in model.metabolites:
        mnx = met_to_mnx.get(met.id)
        if mnx:
            mapped_metabolite_count += 1
            continue
        name = clean_metabolite_display_name(met)
        norm = _normalize_name_for_match(name)
        candidates = []
        if norm:
            for other_id in met_name_index.get(norm, []):
                if other_id == met.id:
                    continue
                other_mnx = met_to_mnx.get(other_id)
                if other_mnx:
                    candidates.append({"id": other_id, "metanetx_id": other_mnx})
        unmapped_metabolites.append({
            "id": met.id,
            "name": name,
            "compartment": met.compartment,
            "likely_duplicate_of": candidates,
        })

    rxn_name_index = {}
    for rxn in model.reactions:
        norm = _normalize_name_for_match(clean_reaction_display_name(rxn))
        if norm:
            rxn_name_index.setdefault(norm, []).append(rxn.id)

    unmapped_reactions = []
    mapped_reaction_count = 0
    for rxn in model.reactions:
        mnx = rxn_to_mnx.get(rxn.id)
        if mnx:
            mapped_reaction_count += 1
            continue
        name = clean_reaction_display_name(rxn)
        norm = _normalize_name_for_match(name)
        candidates = []
        if norm:
            for other_id in rxn_name_index.get(norm, []):
                if other_id == rxn.id:
                    continue
                other_mnx = rxn_to_mnx.get(other_id)
                if other_mnx:
                    candidates.append({"id": other_id, "metanetx_id": other_mnx})
        unmapped_reactions.append({
            "id": rxn.id,
            "name": name,
            "likely_duplicate_of": candidates,
        })

    return {
        "unmapped_metabolites": unmapped_metabolites,
        "unmapped_reactions": unmapped_reactions,
        "unmapped_metabolite_count": len(unmapped_metabolites),
        "mapped_metabolite_count": mapped_metabolite_count,
        "unmapped_reaction_count": len(unmapped_reactions),
        "mapped_reaction_count": mapped_reaction_count,
    }
