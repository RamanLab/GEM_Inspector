"""Every metabolite and reaction of a model with its ids in all the databases
the bundled MetaNetX tables cover (BiGG, VMH, ModelSEED, KEGG, MetaCyc), as two
tab-separated tables.

The model id is matched to a MetaNetX id (annotation.namespace_mapping); each
database column then lists every id that MetaNetX gives for that same compound
or reaction, separated by ";". Metabolites are matched by the id without its
compartment tag, so the cytosolic and extracellular copies share one row's
worth of mapping. When MetaNetX's chem_prop table is in the data folder, its
reference name, formula and charge are added for comparison with the model's.
"""
import csv
import io
import zipfile

from annotation.chem_reference import load_chem_properties
from annotation.namespace_mapping import detect_metabolite_namespace_and_map, detect_reaction_namespace_and_map
from annotation.naming import clean_metabolite_display_name, clean_reaction_display_name, metabolite_base_id_preserve_case
from annotation.xref_index import reverse_index

CHEM_DATABASES = [("BiGG", "bigg.metabolite"), ("VMH", "vmhmetabolite"), ("ModelSEED", "seed.compound"),
                  ("KEGG", "kegg.compound"), ("MetaCyc", "metacyc.compound")]
REAC_DATABASES = [("BiGG", "bigg.reaction"), ("VMH", "vmhreaction"), ("ModelSEED", "seed.reaction"),
                  ("KEGG", "kegg.reaction"), ("MetaCyc", "metacyc.reaction")]


def _join(values, legacy_prefix):
    """The ids joined by ";", leaving out the legacy-prefixed twin (R_ACALD) of an id that is also listed (ACALD)."""
    present = set(values)
    return ";".join(v for v in values if not (v.startswith(legacy_prefix) and v[len(legacy_prefix):] in present))


def metabolite_rows(model):
    _, _, _, to_mnx = detect_metabolite_namespace_and_map(model)
    indexes = {label: reverse_index("chem", ns) for label, ns in CHEM_DATABASES}
    reference = load_chem_properties()
    rows = []
    for met in model.metabolites:
        mnx = to_mnx.get(met.id) or ""
        row = {
            "model_id": met.id, "base_id": metabolite_base_id_preserve_case(met.id),
            "name": clean_metabolite_display_name(met), "compartment": met.compartment or "",
            "formula": getattr(met, "formula", "") or "", "charge": "" if met.charge is None else met.charge,
            "metanetx_id": mnx,
        }
        for label, _ in CHEM_DATABASES:
            row[label] = _join(indexes[label].get(mnx, []), "M_") if mnx else ""
        if reference is not None:
            ref = reference.get(mnx) or {}
            row.update(reference_name=ref.get("name", ""), reference_formula=ref.get("formula", ""),
                       reference_charge="" if ref.get("charge") is None else ref.get("charge"))
        rows.append(row)
    return rows


def reaction_rows(model):
    _, _, _, to_mnx = detect_reaction_namespace_and_map(model)
    indexes = {label: reverse_index("reac", ns) for label, ns in REAC_DATABASES}
    rows = []
    for rxn in model.reactions:
        mnx = to_mnx.get(rxn.id) or ""
        row = {
            "model_id": rxn.id, "name": clean_reaction_display_name(rxn), "equation": rxn.reaction,
            "subsystem": getattr(rxn, "subsystem", "") or "", "gene_reaction_rule": rxn.gene_reaction_rule or "",
            "metanetx_id": mnx,
        }
        for label, _ in REAC_DATABASES:
            row[label] = _join(indexes[label].get(mnx, []), "R_") if mnx else ""
        rows.append(row)
    return rows


def to_tsv(rows, columns=None):
    columns = columns or (list(rows[0]) if rows else [])
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, delimiter="\t", lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def mapping_files(model):
    """{"metabolite_id_mapping.tsv": text, "reaction_id_mapping.tsv": text}."""
    return {"metabolite_id_mapping.tsv": to_tsv(metabolite_rows(model)),
            "reaction_id_mapping.tsv": to_tsv(reaction_rows(model))}


def mapping_zip(model):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in mapping_files(model).items():
            archive.writestr(name, text)
    return buffer.getvalue()
