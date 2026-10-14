"""Bundled SEED -> VMH id translation tables.

data/MetaboliteTranslationTable.txt and data/ReactionTranslationTable.txt are
tab-separated, one header row, two columns: the ModelSEED id (cpd#####,
rxn#####) and its VMH id. Both directions are many-to-one in places (several
SEED ids share one VMH id), and a SEED id can occasionally list more than one
VMH id -- those are kept as a list so the caller can flag them as ambiguous.
"""
from pathlib import Path

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

TABLE_FILES = {
    "metabolite": "MetaboliteTranslationTable.txt",
    "reaction": "ReactionTranslationTable.txt",
}

_table_cache = {}


def _read_table(path):
    """{seed_id: [vmh_id, ...]} with VMH ids de-duplicated, in file order."""
    table = {}
    with open(path, encoding="utf-8-sig") as f:
        next(f, None)  # header row
        for line in f:
            cells = [c.strip() for c in line.rstrip("\r\n").split("\t")]
            if len(cells) < 2 or not cells[0] or not cells[1]:
                continue
            targets = table.setdefault(cells[0], [])
            if cells[1] not in targets:
                targets.append(cells[1])
    return table


def load_translation_table(kind):
    """Lazily load and cache the "metabolite" or "reaction" table. Returns
    None when the data file is missing, so callers can report that cleanly."""
    if kind in _table_cache:
        return _table_cache[kind]
    path = _DATA_DIR / TABLE_FILES[kind]
    table = _read_table(path) if path.is_file() else None
    _table_cache[kind] = table
    return table
