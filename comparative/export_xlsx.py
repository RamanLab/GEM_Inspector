"""Excel workbook for a model report: a summary row per model, the findings,
panel overview, blocked-reaction subsystem table, essential-exchange matrix,
minimal media and biomass equations. For a single model it also has the
detail lists (exchanges, blocked reactions, dead ends, unbalanced reactions,
demand/sink reactions)."""
from comparative.metrics import UNANNOTATED
from core.xlsx_helpers import new_workbook, title_cell, workbook_bytes, write_table


def _summary_sheet(wb, report):
    ws = wb.active
    ws.title = "Summary"
    columns = report["summary_columns"]
    rows = [[e["metrics"].get(k) for k, _ in columns] for e in report["models"]]
    write_table(ws, [h for _, h in columns], rows, widths_cap=40)
    ws.freeze_panes = "B2"


def _findings_sheet(wb, report):
    ws = wb.create_sheet("Findings")
    rows = []
    for e in report["models"]:
        flags = e["findings"] or ["No threshold violations"]
        rows += [[e["metrics"]["display_name"], e["metrics"]["source_file"], i, flag] for i, flag in enumerate(flags, 1)]
    write_table(ws, ["Model", "File", "#", "Finding"], rows, widths_cap=110, wrap_columns=("Finding",))


def _overview_sheet(wb, report):
    ws = wb.create_sheet("Panel overview")
    title_cell(ws, "A1", "Model quality report")
    ws["A2"], ws["B2"] = "Generated", report["generated"]
    ws["A3"], ws["B3"] = "Models", f"{report['n_models']} ({report['n_distinct']} distinct)"
    row = 5
    ws.cell(row=row, column=1, value="Thresholds applied")
    for label, value in report["settings_rows"]:
        row += 1
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=2, value=value)
    row += 2
    ws.cell(row=row, column=1, value="Range across distinct models")
    for label, value in report["ranges"]:
        row += 1
        ws.cell(row=row, column=1, value=label)
        ws.cell(row=row, column=2, value=value)
    if report["observations"]:
        row += 2
        ws.cell(row=row, column=1, value="Panel-wide observations")
        for text in report["observations"]:
            row += 1
            ws.cell(row=row, column=1, value=text)
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 30


def _subsystem_sheet(wb, report):
    columns = report["subsystem_columns"]
    if not columns:
        return
    ws = wb.create_sheet("Blocked by subsystem")
    rows = [[e["metrics"]["display_name"]] + [e["details"].get("blocked_by_subsystem", {}).get(c, 0) for c in columns]
            for e in report["models"]]
    write_table(ws, ["Model"] + columns, rows, widths_cap=30)


def _essential_sheet(wb, report):
    ids = report["essential_exchange_ids"]
    if not ids:
        return
    ws = wb.create_sheet("Essential exchanges")
    rows = [[e["metrics"]["display_name"]] + [1 if i in set(e["details"].get("essential_exchanges", [])) else 0 for i in ids]
            for e in report["models"]]
    write_table(ws, ["Model"] + ids, rows, widths_cap=18)


def _minimal_medium_sheet(wb, report):
    rows = [[e["metrics"]["display_name"], c["id"], c["name"], c["uptake_flux"]]
            for e in report["models"] for c in e["details"].get("minimal_medium", [])]
    if rows:
        write_table(wb.create_sheet("Minimal media"), ["Model", "Exchange id", "Metabolite", "Uptake flux"], rows, widths_cap=50)


def _biomass_sheet(wb, report):
    rows = [[e["metrics"]["display_name"], e["metrics"].get("biomass_reaction"), e["details"].get("biomass")] for e in report["models"]]
    write_table(wb.create_sheet("Biomass"), ["Model", "Reaction", "Equation"], rows, widths_cap=140, wrap_columns=("Equation",))


def _detail_sheets(wb, report):
    """Per-reaction / per-metabolite lists, for a report on one model."""
    details = report["models"][0]["details"]
    sheets = [
        ("Exchanges", ["Exchange id", "Name", "Lower bound", "Upper bound", "WT flux", "Uptake allowed", "Growth kept when closed"],
         [[r["id"], r["name"], r["lb"], r["ub"], r["wt_flux"], "yes" if r["uptake_allowed"] else "no", r["retained"]] for r in details.get("exchanges", [])]),
        ("Blocked reactions", ["Reaction id", "Name", "Subsystem", "Type", "Lower bound", "Upper bound"],
         [[r["id"], r["name"], r["subsystem"] or UNANNOTATED, r["type"], r["lb"], r["ub"]] for r in details.get("blocked", [])]),
        ("Dead-end metabolites", ["Metabolite id", "Name", "Compartment", "Reason"],
         [[r["id"], r["name"], r["compartment"], r["reason"]] for r in details.get("dead_end", [])]),
        ("Unbalanced reactions", ["Reaction id", "Name", "Status", "Problem"],
         [[r["id"], r["name"], r["status"], r["problem"]] for r in details.get("unbalanced", [])]),
        ("Demand & sink", ["Reaction id", "Kind", "Metabolite", "WT flux", "Essential"],
         [[r["id"], r["kind"], r["metabolite"], r["wt_flux"], "yes" if r["essential"] else "no"] for r in details.get("demand_sink", [])]),
    ]
    for title, headers, rows in sheets:
        if rows:
            write_table(wb.create_sheet(title), headers, rows, widths_cap=60)


def build_report_xlsx(report):
    wb = new_workbook()
    _summary_sheet(wb, report)
    _findings_sheet(wb, report)
    _overview_sheet(wb, report)
    _subsystem_sheet(wb, report)
    _essential_sheet(wb, report)
    _minimal_medium_sheet(wb, report)
    _biomass_sheet(wb, report)
    if report["n_models"] == 1:
        _detail_sheets(wb, report)
    return workbook_bytes(wb)
