"""Genome-scale Model Inspector -- Flask application entry point.

Wires together the app's four functional areas (see README.md for the full
feature list):

  - overview     model upload/diet application, quick stats, and the
                 Exchange Essentiality tab           (overview/)
  - diagnostics  Minimal Medium, Network Gaps, Demand & Sink Audit, and
                 FROG Report -- on-request, comparative/what-if analyses
                 that never permanently change the model  (diagnostics/)
  - debugging    Exchange Debugging and the general-purpose Pathway
                 Tracer -- active-flux tracing toward a target  (debugging/)
  - annotation   id-namespace detection/MetaNetX mapping, translation
                 between namespaces, and display-name cleanup shared by
                 every section above  (annotation/)
  - comparative  model statistics and quality-control reports for one
                 model or several side by side, as Excel and HTML
                 (comparative/)

Plus "Generate report" save/browse support (core/reporting.py).

Run directly (`python app.py [--solver gurobi|cplex|glpk|scipy|auto]
[--threads N] [--processes N]`) for local development, or serve with gunicorn
using `app:app` and the GEM_SOLVER / GEM_THREADS / GEM_PROCESSES environment
variables (one worker: the model cache lives in process memory).
"""
from flask import Flask

from annotation.routes import annotation_bp
from comparative.routes import comparative_bp
from core.reporting import reporting_bp
from core import solver_config
from core.shared import start_model_cache_cleanup
from debugging.routes import debugging_bp
from diagnostics.routes import diagnostics_bp
from overview.routes import overview_bp

solver_config.apply()  # GEM_SOLVER / GEM_THREADS / GEM_PROCESSES, see core/solver_config.py

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB

app.register_blueprint(overview_bp)
app.register_blueprint(diagnostics_bp)
app.register_blueprint(debugging_bp)
app.register_blueprint(annotation_bp)
app.register_blueprint(comparative_bp)
app.register_blueprint(reporting_bp)

start_model_cache_cleanup()

if __name__ == "__main__":
    import argparse
    import os
    import sys

    parser = argparse.ArgumentParser(description="Genome-scale Model Inspector")
    parser.add_argument("--solver", choices=["auto", "gurobi", "cplex", "glpk", "scipy"],
                        help="LP/MILP solver (default: GEM_SOLVER or auto = best installed)")
    parser.add_argument("--threads", type=int, help="threads per solver call")
    parser.add_argument("--processes", type=int, help="worker processes for FVA / gene deletions")
    args = parser.parse_args()

    # Ask once (not again in the debug reloader's child) when no choice was given.
    if not (args.solver or os.environ.get("GEM_SOLVER")) and sys.stdin.isatty() \
            and not os.environ.get("WERKZEUG_RUN_MAIN"):
        args.solver = solver_config.prompt_choice()
    solver_config.configure(args.solver, args.threads, args.processes)
    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        print("Inspector:", solver_config.describe())
    app.run(host="127.0.0.1", port=5000, debug=True)
