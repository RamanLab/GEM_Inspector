"""Self-contained HTML page for a model report. Opens in any browser, needs
no server, and has a light/dark switch (light by default)."""
from html import escape

from comparative import charts
from comparative.metrics import UNANNOTATED
from comparative.panel import SUMMARY_COLUMNS

_LABELS = dict(SUMMARY_COLUMNS)

_STYLE = """
:root{color-scheme:light;--surface:#fcfcfb;--page:#f4f5f7;--ink:#0b0b0b;--muted:#52514e;--grid:#e3e2de;--line:#dcdbd6;
--band:#e9e8e4;--cell:#eceae5;--good:#0d7a4f;--warn:#a05a00;--bad:#b42318;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s5:#e87ba4;--s6:#008300;--s-other:#8f8e88}
[data-theme="dark"]{color-scheme:dark;--surface:#1a1a19;--page:#121211;--ink:#f0efec;--muted:#c3c2b7;--grid:#34332f;--line:#3a3935;
--band:#262522;--cell:#2a2926;--good:#3fbf8a;--warn:#e0a040;--bad:#f2766b;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s5:#d55181;--s6:#008300;--s-other:#8f8e88}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);font:14px/1.5 -apple-system,"Segoe UI",Arial,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
h1{margin:0 0 4px;font-size:24px}h2{margin:34px 0 10px;font-size:18px;border-bottom:1px solid var(--line);padding-bottom:6px}
h3{margin:0 0 6px;font-size:15px}
.meta,.muted{color:var(--muted)}.sm{font-size:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.scroll{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{padding:6px 10px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top;white-space:nowrap}
td.wrap{white-space:normal}
th{position:sticky;top:0;background:var(--surface);font-weight:600}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:0}
.ok{color:var(--good)}.warn{color:var(--warn)}.bad{color:var(--bad)}
ul.flags{margin:6px 0 0;padding-left:20px}ul.flags li{margin:3px 0}
details{background:var(--surface);border:1px solid var(--line);border-radius:10px;margin:8px 0;padding:8px 14px}
summary{cursor:pointer;font-weight:600}
code{font:12px ui-monospace,Menlo,Consolas,monospace;word-break:break-word}
svg text{fill:var(--muted);font:12px -apple-system,"Segoe UI",Arial,sans-serif}svg text.sm{font-size:11px}
svg .grid{stroke:var(--grid);stroke-width:1}svg .stem{stroke:var(--grid);stroke-width:1.5}
svg .band{fill:var(--band)}svg .dot{stroke:var(--surface);stroke-width:2}
svg .cell{fill:var(--cell)}svg .cell.on{fill:var(--s1)}
.legend{display:flex;flex-wrap:wrap;gap:6px 16px;margin:6px 0 8px;color:var(--muted);font-size:12px}
.lg i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.figure{margin:14px 0}.figure h3{margin-bottom:2px}
nav a{margin-right:14px;color:var(--s1)}
.toggle{position:fixed;top:12px;right:14px;border:1px solid var(--line);background:var(--surface);color:var(--ink);border-radius:999px;padding:5px 12px;font-size:12px;cursor:pointer}
@media print{.toggle{display:none}body{background:#fff}details{break-inside:avoid}}
"""


def _fmt(value):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _table(headers, rows, numeric=()):
    head = "".join(f'<th class="{"num" if i in numeric else ""}">{escape(h)}</th>' for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td class="{"num" if i in numeric else ""}">{escape(_fmt(v))}</td>' for i, v in enumerate(row)) + "</tr>" for row in rows)
    return f'<div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def _key_table(report):
    keys = report["key_columns"]
    rows = [[e["metrics"].get(k) for k in keys] for e in report["models"]]
    numeric = {i for i, k in enumerate(keys) if k not in ("display_name", "source_file", "met_namespace")}
    return _table([_LABELS[k] for k in keys], rows, numeric)


def _findings_html(entry):
    flags = entry["findings"]
    if not flags:
        return '<p class="ok">No threshold violations.</p>'
    return '<ul class="flags">' + "".join(f"<li>{escape(f)}</li>" for f in flags) + "</ul>"


def _model_card(entry, index):
    m, d = entry["metrics"], entry["details"]
    summary = (f"{_fmt(m['genes'])} genes, {_fmt(m['reactions'])} reactions, {_fmt(m['metabolites'])} metabolites, "
               f"{_fmt(m['compartments'])} compartment(s); growth {_fmt(m['mu_per_h'])} /h")
    parts = [f'<p class="muted sm"><code>{escape(m["source_file"])}</code> &middot; {escape(summary)}</p>', _findings_html(entry)]
    if d.get("biomass"):
        parts.append(f'<h3>Biomass equation ({escape(str(m["biomass_reaction"]))})</h3><p class="sm"><code>{escape(d["biomass"])}</code></p>')
    if d.get("essential_exchanges"):
        parts.append(f'<h3>Essential exchanges ({len(d["essential_exchanges"])})</h3><p class="sm"><code>{escape(", ".join(d["essential_exchanges"]))}</code></p>')
    if d.get("minimal_medium"):
        parts.append(f'<h3>Minimal medium ({len(d["minimal_medium"])})</h3><p class="sm"><code>{escape(", ".join(c["id"] for c in d["minimal_medium"]))}</code></p>')
    return f'<details id="m{index}"{" open" if index == 0 else ""}><summary>{escape(m["display_name"])} <span class="muted sm">({len(entry["findings"])} finding(s))</span></summary>{"".join(parts)}</details>'


def _figures(report):
    models = [e for e in report["models"]]
    metrics = [e["metrics"] for e in models]
    groups = charts.group_colors([m["group"] for m in metrics])
    legend = charts.legend_html(groups)
    out = []
    growth = charts.growth_chart(metrics, report["settings"], groups)
    if growth:
        out.append(f'<div class="figure"><h3>Predicted growth rate</h3><p class="muted sm">Shaded band: the plausible range. Colour: namespace group.</p>{legend}{growth}</div>')
    scatter = charts.blocked_scatter(metrics, groups)
    if scatter:
        out.append(f'<div class="figure"><h3>Share of each network that cannot carry flux</h3><p class="muted sm">Lower is better.</p>{legend}{scatter}</div>')
    sub_models = [{"label": e["metrics"]["label"], "name": e["metrics"]["display_name"], "totals": e["details"].get("blocked_by_subsystem", {})} for e in models]
    svg, sub_legend = charts.subsystem_chart(sub_models, report["subsystem_columns"])
    if svg and (len(models) > 1 or True):
        swatches = "".join(f'<span class="lg"><i style="background:{c}"></i>{escape(s)}</span>' for s, c in sub_legend)
        out.append(f'<div class="figure"><h3>Blocked reactions by subsystem</h3><div class="legend">{swatches}</div>{svg}</div>')
    heat_models = [{"label": e["metrics"]["label"], "name": e["metrics"]["display_name"], "essential": e["details"].get("essential_exchanges", []),
                    "mu": e["metrics"].get("mu_per_h")} for e in models]
    heat = charts.essential_heatmap(heat_models, report["essential_exchange_ids"])
    if heat:
        out.append(f'<div class="figure"><h3>Uptakes required for growth, shared across models</h3><p class="muted sm">Filled: closing this exchange abolishes growth.</p><div class="scroll" style="padding:8px">{heat}</div></div>')
    return "".join(out)


def _single_details(report):
    d = report["models"][0]["details"]
    parts = []
    lists = [
        ("Blocked reactions", ["Reaction", "Name", "Subsystem", "Type"], [[r["id"], r["name"], r["subsystem"] or UNANNOTATED, r["type"]] for r in d.get("blocked", [])]),
        ("Dead-end metabolites", ["Metabolite", "Name", "Compartment", "Reason"], [[r["id"], r["name"], r["compartment"], r["reason"]] for r in d.get("dead_end", [])]),
        ("Unbalanced reactions", ["Reaction", "Name", "Status", "Problem"], [[r["id"], r["name"], r["status"], r["problem"]] for r in d.get("unbalanced", [])]),
        ("Exchanges", ["Exchange", "Lower bound", "Upper bound", "WT flux", "Growth kept when closed"],
         [[r["id"], r["lb"], r["ub"], r["wt_flux"], r["retained"]] for r in d.get("exchanges", [])]),
        ("Demand & sink reactions", ["Reaction", "Kind", "Metabolite", "WT flux", "Essential"],
         [[r["id"], r["kind"], r["metabolite"], r["wt_flux"], r["essential"]] for r in d.get("demand_sink", [])]),
    ]
    for title, headers, rows in lists:
        if rows:
            cap = 500
            note = f'<p class="muted sm">Showing the first {cap} of {len(rows)}; the Excel report has all of them.</p>' if len(rows) > cap else ""
            parts.append(f"<details><summary>{title} ({len(rows)})</summary>{_table(headers, rows[:cap])}{note}</details>")
    return "<h2>Details</h2>" + "".join(parts) if parts else ""


def build_report_html(report):
    single = report["n_models"] == 1
    title = report["models"][0]["metrics"]["display_name"] if single else f"{report['n_models']} models compared"
    toc = '<nav><a href="#summary">Summary</a><a href="#figures">Figures</a><a href="#findings">Findings</a></nav>'
    observations = ("<ul>" + "".join(f"<li>{escape(o)}</li>" for o in report["observations"]) + "</ul>") if report["observations"] else ""
    ranges = "" if single else f'<h3>Range across distinct models</h3>{_table(["Metric", "Range"], report["ranges"])}'
    thresholds = _table(["Threshold", "Value"], report["settings_rows"])
    figures = _figures(report)
    cards = "".join(_model_card(e, i) for i, e in enumerate(report["models"]))
    sections_off = [name.replace("_", " ") for name, on in report["sections"].items() if not on]
    skipped = f'<p class="muted sm">Not included in this report: {escape(", ".join(sections_off))}.</p>' if sections_off else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Model report: {escape(title)}</title><style>{_STYLE}</style></head><body><button class="toggle" type="button" onclick="var r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark';this.textContent=r.dataset.theme==='dark'?'Light theme':'Dark theme'">Dark theme</button><main>
<h1>{'Model report' if single else 'Model comparison report'}</h1>
<div class="meta">{escape(title)} &middot; generated {escape(report['generated'])}{'' if single else f" &middot; {report['n_distinct']} distinct model(s)"}</div>
{toc}
<h2 id="summary">Summary</h2>
{observations}{_key_table(report)}{skipped}
{ranges}
<h3 style="margin-top:18px">Thresholds applied</h3>{thresholds}
<h2 id="figures">Figures</h2>{figures or '<p class="muted">Not enough data for figures.</p>'}
<h2 id="findings">Findings{' per model' if not single else ''}</h2>{cards}
{_single_details(report) if single else ''}
</main></body></html>"""
