"""Curated media (LB, M9 and variants), from data/media.csv.

The file lists, per medium, the compounds it contains. The compound ids are
bare metabolite ids (e.g. glc__D); they are matched to the model's exchange
reactions when the diet is applied (diagnostics/diet.py), so the same medium
works across id conventions. Defaults: uptake lower bound -1000, secretion
upper bound 1000. The user can edit every bound before the model is loaded.
"""
import csv
from pathlib import Path

MEDIA_FILE = Path(__file__).resolve().parent.parent / "data" / "media.csv"
DEFAULT_LOWER, DEFAULT_UPPER = -1000.0, 1000.0

_cache = None


def _load():
    global _cache
    if _cache is None:
        media = {}
        with open(MEDIA_FILE, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                medium = media.setdefault(row["medium"], {"key": row["medium"], "description": row["description"], "compounds": []})
                medium["compounds"].append({"id": row["compound"], "name": row["name"],
                                            "lower_bound": DEFAULT_LOWER, "upper_bound": DEFAULT_UPPER})
        _cache = media
    return _cache


def list_media():
    """[{key, description, size}] for the diet dropdown."""
    return [{"key": m["key"], "description": m["description"], "size": len(m["compounds"])} for m in _load().values()]


def get_medium(key):
    return _load().get(key)
