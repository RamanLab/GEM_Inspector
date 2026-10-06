"""Generate-report support: saving a client-assembled HTML report to disk.

The report itself is built client-side out of whichever sections/analyses
the user picks, from data already fetched via the other sections' on-request
endpoints -- this only needs to get the finished HTML onto disk, two ways:

  - /api/browse-save-path opens a native "Save As" dialog in a separate
    helper process (never inside the Flask process/thread itself) so the
    user can pick any location on their own machine. Meaningful only
    because this Flask server and the browser are expected to run on the
    same computer -- the local-desktop-use pattern this app is built for.
    Fails softly if no GUI is available (no tkinter, no display), and the
    frontend then falls back to a plain text field or a browser download.
  - /api/save-report writes a given HTML string straight to a given path.
"""
import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request
from werkzeug.utils import secure_filename

reporting_bp = Blueprint("reporting", __name__)


@reporting_bp.get("/api/browse-save-path")
def api_browse_save_path():
    """Best-effort native "Save As" dialog for the generated report, run in
    a short-lived helper subprocess so it never shares a thread or event
    loop with the Flask server itself. Returns {"path": "..."} on success,
    {"path": null} if the user cancelled, or {"path": null, "error": "..."}
    when no GUI is available here (the frontend then falls back to typing a
    path manually, or a plain browser download)."""
    default_name = (request.args.get("default_name") or "model_report.html").strip()
    default_name = secure_filename(default_name) or "model_report.html"
    if not default_name.lower().endswith((".html", ".htm")):
        default_name += ".html"

    script = (
        "import tkinter as tk\n"
        "from tkinter import filedialog\n"
        "root = tk.Tk()\n"
        "root.withdraw()\n"
        "try:\n"
        "    root.attributes('-topmost', True)\n"
        "except Exception:\n"
        "    pass\n"
        "path = filedialog.asksaveasfilename(\n"
        "    defaultextension='.html',\n"
        "    filetypes=[('HTML files', '*.html'), ('All files', '*.*')],\n"
        f"    initialfile={default_name!r},\n"
        "    title='Save model report as...',\n"
        ")\n"
        "print(path)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=180,
        )
    except Exception as exc:
        return jsonify({"path": None, "error": f"Could not open a save dialog here: {exc}"})

    if result.returncode != 0:
        stderr_lines = (result.stderr or "").strip().splitlines()
        reason = stderr_lines[-1] if stderr_lines else "unknown error"
        return jsonify({"path": None, "error": f"Save dialog unavailable here: {reason}"})

    path = (result.stdout or "").strip()
    return jsonify({"path": path or None})


@reporting_bp.post("/api/save-report")
def api_save_report():
    """Write a generated report's HTML directly to a path on this machine.
    Only meaningful when the browser and this Flask process share a
    filesystem, i.e. the local-desktop-use pattern this app assumes; the
    frontend falls back to a plain browser download when no path is given."""
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    path_str = (data.get("path") or "").strip()
    html = data.get("html")
    if not path_str:
        return jsonify({"error": "No save path given."}), 400
    if html is None:
        return jsonify({"error": "No report content given."}), 400

    path = Path(path_str).expanduser()
    if not path.is_absolute():
        return jsonify({"error": "Save path must be an absolute path (use Browse…, or type a full path)."}), 400
    if path.suffix.lower() not in (".html", ".htm"):
        path = path.with_name(path.name + ".html")

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html, encoding="utf-8")
    except Exception as exc:
        return jsonify({"error": f"Could not write the report to '{path}': {exc}"}), 500

    return jsonify({"status": "success", "path": str(path)})
