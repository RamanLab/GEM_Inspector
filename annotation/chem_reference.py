"""Optional reference formulas/charges for metabolites, from MetaNetX's
chem_prop table.

Put MetaNetX's `chem_prop.tsv` (or `chem_prop.tsv.gz`) in the data folder to
enable the formula checks in the balance audit. It is not required: without
it the audit still works from the model's own formulas, it just cannot
compare them with a reference. Only the MetaNetX ids that appear in the
bundled xref table are kept in memory.

chem_prop columns: ID, name, reference, formula, charge, mass, InChI, InChIKey, SMILES
(lines starting with "#" are comments / the header).
"""
import gzip
from pathlib import Path

from annotation.namespace_mapping import load_xref

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CANDIDATE_FILES = ("chem_prop.tsv", "chem_prop.tsv.gz")
_cache = {"loaded": False, "table": None}


def _open(path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else open(path, encoding="utf-8")


def load_chem_properties():
    """{mnx_id: {"name", "formula", "charge"}} for the metabolites known to
    the xref table, or None when no chem_prop file is in the data folder."""
    if _cache["loaded"]:
        return _cache["table"]
    _cache["loaded"] = True
    path = next((_DATA_DIR / n for n in _CANDIDATE_FILES if (_DATA_DIR / n).is_file()), None)
    if path is None:
        return None
    wanted = {mnx for ns_map in load_xref("chem").values() for mnx in ns_map.values()}
    table = {}
    with _open(path) as handle:
        for line in handle:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5 or parts[0] not in wanted:
                continue
            charge = parts[4].strip()
            try:
                charge = int(float(charge)) if charge else None
            except ValueError:
                charge = None
            table[parts[0]] = {"name": parts[1], "formula": parts[3].strip(), "charge": charge}
    _cache["table"] = table
    return table
