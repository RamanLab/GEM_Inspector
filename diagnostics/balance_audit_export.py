"""Excel workbook for a balance audit: a summary, one row per problem reaction
with its suggested fix, and one row per reaction-metabolite pair with the
formula check and the ids in each database."""
from datetime import datetime

from core.xlsx_helpers import new_workbook, title_cell, workbook_bytes, write_table

REACTION_COLUMNS = [
    ("Reaction id", "id"), ("Name", "name"), ("Status", "status"), ("Imbalance", "imbalance"),
    ("Suggested fix", "suggestion"), ("Fix type", "suggestion_type"), ("Fix verified", "verified"),
    ("Other suggestions", "other_suggestions"), ("Metabolites to check", "metabolites_to_check"),
    ("Metabolite mapping (id -> MetaNetX -> databases)", "metabolite_mapping"), ("Reaction", "reaction"),
]


def metabolite_columns(databases):
    return [
        ("Reaction id", "reaction_id"), ("Metabolite id", "metabolite_id"), ("Name", "name"),
        ("Coefficient", "coefficient"), ("Compartment", "compartment"), ("Formula", "formula"), ("Charge", "charge"),
        ("MetaNetX id", "metanetx_id"), ("Reference formula", "reference_formula"), ("Reference charge", "reference_charge"),
        ("Formula check", "formula_check"), ("Mapping check", "mapping_check"),
    ] + [(label, label) for label in databases]


def build_audit_xlsx(report):
    wb = new_workbook()
    ws = wb.active
    ws.title = "Summary"
    title_cell(ws, "A1", "Unbalanced reaction audit")
    ws["A2"], ws["B2"] = "Generated", datetime.now().strftime("%Y-%m-%d %H:%M")
    counts = report["counts"]
    lines = [("Reactions in the model", counts["total"]), ("Balanced", counts["balanced"]), ("Unbalanced", counts["unbalanced"]),
             ("Can't be checked (missing formulas)", counts["unknown"]), ("Audited here", counts["audited"]),
             ("With a fix that balances the reaction", counts["with_verified_fix"])]
    for i, (label, value) in enumerate(lines, start=4):
        ws.cell(row=i, column=1, value=label)
        ws.cell(row=i, column=2, value=value)
    ws.cell(row=len(lines) + 5, column=1, value=report["note"])
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 18

    ws = wb.create_sheet("Reactions")
    write_table(ws, [h for h, _ in REACTION_COLUMNS],
                [[r.get(k) if k != "verified" else ("yes" if r[k] else "no") for _, k in REACTION_COLUMNS] for r in report["reactions"]],
                widths_cap=70, wrap_columns=("Suggested fix", "Other suggestions", "Metabolite mapping (id -> MetaNetX -> databases)"))

    columns = metabolite_columns(report["databases"])
    ws = wb.create_sheet("Metabolites")
    write_table(ws, [h for h, _ in columns], [[m.get(k) for _, k in columns] for m in report["metabolites"]], widths_cap=50)
    return workbook_bytes(wb)
