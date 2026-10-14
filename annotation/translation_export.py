"""Files for a finished id translation (SEED -> VMH or via MetaNetX): the translated model (SBML
and JSON) and the report (summary plus one TSV per group), plus a zip of all
of them."""
import csv
import io
import tempfile
import zipfile
from pathlib import Path

from cobra.io import save_json_model, write_sbml_model

REPORT_GROUPS = (
    ("mapped", "mapped.tsv", "Mapped"),
    ("errors", "errors.tsv", "Errors"),
    ("unmapped", "unmapped.tsv", "No available mapping"),
)


def report_tsv(rows, columns):
    out = io.StringIO()
    writer = csv.writer(out, delimiter="\t", lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([row.get(c, "") for c in columns])
    return out.getvalue()


def report_summary_text(report, source_name):
    lines = [
        report.get("title", "Id translation report"),
        f"Source model: {source_name}",
        f"Id style: {report['style']}",
        "",
    ]
    for kind in ("metabolites", "reactions"):
        c = report["counts"][kind]
        lines.append(f"{kind.capitalize()}: {c['total']} total, {c['mapped']} mapped, "
                     f"{c['errors']} errors, {c['unmapped']} no available mapping")
    after = report["after"]
    lines += [
        "",
        f"Namespace after translation: metabolites {after['metabolites']['label']} "
        f"({after['metabolites']['coverage'] * 100:.1f}%), reactions {after['reactions']['label']} "
        f"({after['reactions']['coverage'] * 100:.1f}%)",
    ]
    if report.get("source_check", {}).get("warning"):
        lines += ["", "Warning: " + report["source_check"]["warning"]]
    lines += [""] + report["notes"]
    return "\n".join(lines) + "\n"


def model_bytes(model, fmt):
    """The model serialized as "sbml" or "json"."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"model.{'xml' if fmt == 'sbml' else 'json'}"
        if fmt == "sbml":
            write_sbml_model(model, str(path))
        else:
            save_json_model(model, str(path))
        return path.read_bytes()


def build_bundle(model, report, base_name, source_name):
    """Zip with the translated model (SBML + JSON) and the full report."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base_name}.xml", model_bytes(model, "sbml"))
        zf.writestr(f"{base_name}.json", model_bytes(model, "json"))
        zf.writestr("translation_summary.txt", report_summary_text(report, source_name))
        for key, filename, _ in REPORT_GROUPS:
            zf.writestr(filename, report_tsv(report[key], report["columns"]))
    return buffer.getvalue()
