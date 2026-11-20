"""The benchmark as one Excel workbook: a sheet per section, plus the full match lists."""
import io

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER = PatternFill("solid", fgColor="DCE6F5")


def _sheet(wb, title, header, rows):
    ws = wb.create_sheet(title[:31])
    ws.append(header)
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True), HEADER
    for row in rows:
        ws.append(["" if v is None else v for v in row])
    for i, col in enumerate(ws.columns, 1):
        width = max((len(str(c.value)) for c in col[:200] if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
    ws.freeze_panes = "A2"
    return ws


def build_workbook(result, details):
    names = result["names"]
    wb = Workbook()
    wb.remove(wb.active)
    n = len(names)

    notes = [["Mode", result["mode"] + (f" (reference: {result['reference']})" if result["reference"] else "")],
             ["FVA fraction of optimum", result["fva_fraction"]], [], ["Warnings"]] + [[w] for w in result["warnings"]]
    _sheet(wb, "About", ["Item", "Value"], notes)

    rows = []
    for p in result["similarity"]["pairs"]:
        for kind in ("metabolites", "reactions", "genes"):
            s = p[kind]
            rows.append([names[p["a"]], names[p["b"]], kind, s["a"], s["b"], s["matched"], s["strict_matched"], s["only_a"], s["only_b"],
                         round(s["jaccard_strict"], 4), round(s["jaccard_relaxed"], 4),
                         "; ".join(f"{m}: {c}" for m, c in s["by_method"].items())])
    _sheet(wb, "Similarity", ["Model A", "Model B", "Type", "In A", "In B", "Matched", "Matched by id/MetaNetX", "Only in A", "Only in B",
                              "Jaccard (strict)", "Jaccard (relaxed)", "Matched by"], rows)
    for key, grid in result["similarity"]["matrix"].items():
        _sheet(wb, f"Matrix {key.replace('_', ' ')}", [""] + names, [[names[i]] + [None if v is None else round(v, 4) for v in grid[i]] for i in range(n)])

    ov = result["overview"]
    labels = [("Model id", "model_id"), ("Genes", "genes"), ("Metabolites", "metabolites"), ("Reactions", "reactions"), ("Compartments", "compartments"),
              ("WT growth", "wt_growth"), ("FBA status", "wt_status"), ("Metabolite ID namespace", "namespace_metabolites"),
              ("Reaction ID namespace", "namespace_reactions"), ("Compartment convention", "compartment_convention"),
              ("Metabolites mapped to MetaNetX", "mapped_metabolites"), ("Reactions mapped to MetaNetX", "mapped_reactions"),
              ("Reactions with GPR", "with_gpr"), ("Reactions with subsystem", "with_subsystem"), ("Genes per reaction", "gene_reaction_ratio")]
    rows = [[label] + [o.get(key) for o in ov] for label, key in labels]
    rows += [[f"Reactions: {t}"] + [o["reaction_types"].get(t, 0) for o in ov] for t in sorted({t for o in ov for t in o["reaction_types"]})]
    rows += [[f"Mass/charge balance: {t}"] + [o["balance"].get(t, 0) for o in ov] for t in sorted({t for o in ov for t in o["balance"]})]
    rows += [["Medium entries applied / requested"] + [f"{m['applied']} / {m['requested']}" if m["mode"] == "custom" else "model's own" for m in result["medium"]]]
    _sheet(wb, "Overview", ["Metric"] + names, rows)

    bio = result["biomass"]
    rows = [["Biomass reaction"] + [x and x["reaction"] for x in bio["summary"]], ["Components"] + [x and x["n_components"] for x in bio["summary"]],
            ["Consumed"] + [x and x["n_consumed"] for x in bio["summary"]], ["Produced"] + [x and x["n_produced"] for x in bio["summary"]],
            ["Building-block mass (g/gDW)"] + [x and round(x["mass_g_per_gdw"], 3) for x in bio["summary"]]]
    rows += [[f"Component overlap (Jaccard) with {names[i]}"] + [None if v is None else round(v, 4) for v in bio["jaccard"][i]] for i in range(n)]
    _sheet(wb, "Biomass", ["Metric"] + names, rows)
    _sheet(wb, "Biomass components", ["Component", "Only in some models"] + [f"{x} coefficient" for x in names],
           [[c["name"], "yes" if c["differs"] else ""] + [None if v is None else round(v, 5) for v in c["coefficients"]] for c in bio["components"]])

    m = result["maintenance"]
    _sheet(wb, "Maintenance", ["Metric"] + names, [["GAM (mmol ATP/gDW)"] + [x["gam"] for x in m], ["NGAM reaction"] + [x["ngam_id"] for x in m],
                                                   ["NGAM lower bound"] + [x["ngam_lower"] for x in m], ["NGAM forced"] + [x["ngam_forced"] for x in m]])

    for key, title in (("uptake", "Uptake"), ("secretion", "Secretion")):
        _sheet(wb, title, ["Metabolite", "Name", "In some models only"] + [f"{x} rate" for x in names] + [f"{x} exchange" for x in names],
               [[r["key"], r["name"], "yes" if r["differs"] else ""] + r["rates"] + r["exchanges"] for r in result[key]])
    src = result["sources"]
    _sheet(wb, "Carbon & nitrogen source", ["Model", "Main carbon source", "Rate", "Main nitrogen source", "Rate"],
           [[names[i], s["carbon"] and s["carbon"]["name"], s["carbon"] and s["carbon"]["rate"], s["nitrogen"] and s["nitrogen"]["name"],
             s["nitrogen"] and s["nitrogen"]["rate"]] for i, s in enumerate(src)])
    _sheet(wb, "Essential exchanges", ["Metabolite", "Name", "Differs"] + names,
           [[r["key"], r["name"], "yes" if r["differs"] else ""] + r["status"] for r in result["essential"]])

    rows = []
    for r in result["core"]:
        row = [r["id"], r["group"], "; ".join(r["flags"])]
        for c in r["models"]:
            row += [None, None, None, None, None] if c is None else [c["id"], c["status"], c["min"], c["max"], c["wt_flux"]]
        rows.append(row)
    head = ["Reaction", "Pathway", "Differences"] + [f"{x} {f}" for x in names for f in ("id", "status", "FVA min", "FVA max", "FBA flux")]
    _sheet(wb, "Core carbon FVA", head, rows)

    met_rows, rxn_rows, only = [], [], []
    for d in details["pairs"]:
        a, b = names[d["a"]], names[d["b"]]
        met_rows += [[a, b, x, y, method] for x, (y, method) in d["metabolites"].items()]
        rxn_rows += [[a, b, x, y, method] for x, (y, method) in d["reactions"].items()]
        in_b = {y for y, _ in d["metabolites"].values()}
        only += [[a, b, "metabolite", m.id, f"only in {a}"] for m in details["infos"][d["a"]] if m.id not in d["metabolites"]]
        only += [[a, b, "metabolite", m.id, f"only in {b}"] for m in details["infos"][d["b"]] if m.id not in in_b]
        used_b = {y for y, _ in d["reactions"].values()}
        only += [[a, b, "reaction", r.id, f"only in {a}"] for r in details["models"][d["a"]].reactions if r.id not in d["reactions"]]
        only += [[a, b, "reaction", r.id, f"only in {b}"] for r in details["models"][d["b"]].reactions if r.id not in used_b]
    head = ["Model A", "Model B", "ID in A", "ID in B", "Matched by"]
    _sheet(wb, "Metabolite matches", head, met_rows)
    _sheet(wb, "Reaction matches", head, rxn_rows)
    _sheet(wb, "Unmatched", ["Model A", "Model B", "Type", "ID", "Where"], only)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
