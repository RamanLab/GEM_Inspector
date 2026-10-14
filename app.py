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

Run directly (`python app.py`) for local development, or serve with
gunicorn using `app:app` (see Dockerfile).
"""
from flask import Flask

from annotation.routes import annotation_bp
from comparative.routes import comparative_bp
from core.reporting import reporting_bp
from core.shared import start_model_cache_cleanup
from debugging.routes import debugging_bp
from diagnostics.routes import diagnostics_bp
from overview.routes import overview_bp

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
    app.run(host="127.0.0.1", port=5000, debug=True)
