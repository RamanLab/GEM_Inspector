#!/usr/bin/env python
"""Benchmark any number of models from the command line and write the same Excel report as the
"Benchmark / compare models" page.

Run it from a copy of the GEM Inspector repository (it uses the repository's own code), with its
requirements installed (pip install -r requirements.txt):

    python scripts/benchmark_models.py model_a.xml model_b.json model_c.xml
    python scripts/benchmark_models.py *.xml --reference model_a.xml --medium M9 --out m9_benchmark.xlsx
    python scripts/benchmark_models.py *.xml --medium-file my_medium.csv --fva-fraction 0.95

Medium: by default every model keeps its own. Use --medium KEY for a curated one (LB, LB[-O2], M9,
M9[-O2], M9[glyc]) or --medium-file for your own CSV/TSV with the columns
    id, lower_bound, upper_bound   (id = exchange reaction or metabolite id; lower bound negative = uptake)
Run all models on the SAME medium, or the comparison mostly shows the medium differences.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.core_carbon import parse_ids  # noqa: E402
from benchmark.engine import run_benchmark  # noqa: E402
from benchmark.export import build_workbook  # noqa: E402
from core import solver_config  # noqa: E402
from core.shared import load_uploaded_model  # noqa: E402
from diagnostics.media import get_medium  # noqa: E402


def medium_from_file(path):
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        for row in csv.reader(handle, dialect):
            if len(row) < 3:
                continue
            try:
                lower, upper = float(row[1]), float(row[2])
            except ValueError:
                continue   # header or a bad line
            rows.append({"id": row[0].strip(), "name": row[3].strip() if len(row) > 3 else "", "lower_bound": lower, "upper_bound": upper})
    return rows


def main():
    parser = argparse.ArgumentParser(description="Benchmark / compare genome-scale models.")
    parser.add_argument("models", nargs="+", help="model files (SBML, JSON, YAML, MAT)")
    parser.add_argument("--reference", help="benchmark the others against this file (default: all against all)")
    parser.add_argument("--medium", help="curated medium key: LB, LB[-O2], M9, M9[-O2], M9[glyc]")
    parser.add_argument("--medium-file", help="your own medium: CSV/TSV with id, lower_bound, upper_bound")
    parser.add_argument("--core", help="reaction ids for the core carbon FVA (comma separated); default: the built-in list")
    parser.add_argument("--fva-fraction", type=float, default=1.0, help="fraction of optimal growth kept in FVA (default 1.0)")
    parser.add_argument("--solver", choices=["auto", "gurobi", "cplex", "glpk", "scipy"], default="auto")
    parser.add_argument("--out", default="model_benchmark.xlsx", help="output Excel file")
    args = parser.parse_args()
    if len(args.models) < 2:
        parser.error("give at least two models")

    solver_config.configure(args.solver if args.solver != "auto" else None)
    medium = {"mode": "own", "rows": []}
    if args.medium_file:
        medium = {"mode": "custom", "rows": medium_from_file(args.medium_file)}
    elif args.medium:
        found = get_medium(args.medium)
        if not found:
            parser.error(f"unknown medium '{args.medium}'")
        medium = {"mode": "custom", "rows": found["compounds"]}
    else:
        print("Note: each model keeps its own medium. Use --medium or --medium-file to put them all on the same one.")

    entries = []
    for path in args.models:
        print(f"Loading {path}")
        entries.append((Path(path).name, load_uploaded_model(Path(path))))
    names = [n for n, _ in entries]
    reference = names.index(Path(args.reference).name) if args.reference else None
    result, details = run_benchmark(entries, medium, reference, parse_ids(args.core), args.fva_fraction, progress=print)
    Path(args.out).write_bytes(build_workbook(result, details))
    for warning in result["warnings"]:
        print("Warning:", warning)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
