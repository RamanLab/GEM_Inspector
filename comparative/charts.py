"""Inline-SVG charts for the HTML model report. Colours come from CSS custom
properties (--s1.. series colours, --ink / --muted / --grid / --surface) set
by the page, so the charts follow its light and dark themes. Each mark has a
<title> that shows its values on hover."""
import math
from html import escape

from comparative.metrics import UNANNOTATED

MAX_SERIES = 6  # the 7th and later groups share one "other" colour
_ROW = 22


def _text(x, y, s, cls="t", anchor="start", extra=""):
    return f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" text-anchor="{anchor}" {extra}>{escape(str(s))}</text>'


def _svg(width, height, body, label):
    return (f'<svg viewBox="0 0 {width} {height}" width="100%" style="max-width:{width}px" role="img" '
            f'aria-label="{escape(label)}" xmlns="http://www.w3.org/2000/svg">{body}</svg>')


def group_colors(groups):
    """{group: css colour}: slots in a fixed order, the rest folded into one colour."""
    colors = {}
    for i, g in enumerate(sorted(set(groups))):
        colors[g] = f"var(--s{i + 1})" if i < MAX_SERIES else "var(--s-other)"
    return colors


def legend_html(colors):
    seen = {}
    for g, c in colors.items():
        seen.setdefault(c, []).append(g)
    items = []
    for c, groups in seen.items():
        name = groups[0] if len(groups) == 1 else "other groups"
        items.append(f'<span class="lg"><i style="background:{c}"></i>{escape(name)}</span>')
    return f'<div class="legend">{"".join(items)}</div>' if len(items) > 1 else ""


def _log_ticks(lo, hi):
    ticks, p = [], math.floor(math.log10(lo))
    while 10 ** p <= hi * 1.0001:
        if 10 ** p >= lo * 0.9999:
            ticks.append(10 ** p)
        p += 1
    return ticks


# --- (a) growth rate -------------------------------------------------------------

def growth_chart(models, settings, colors):
    rows = sorted((m for m in models if (m.get("mu_per_h") or 0) > 0), key=lambda m: m["mu_per_h"])
    if len(rows) < 2:
        return ""
    left, right, top, bottom, width = 210, 36, 34, 44, 760
    lo = min(settings["mu_min"], rows[0]["mu_per_h"]) / 3
    hi = rows[-1]["mu_per_h"] * 4
    plot_w = width - left - right
    xs = lambda v: left + (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo)) * plot_w
    height = top + len(rows) * _ROW + bottom
    body = [f'<rect x="{xs(settings["mu_min"]):.1f}" y="{top - 6}" width="{xs(settings["mu_max"]) - xs(settings["mu_min"]):.1f}" '
            f'height="{len(rows) * _ROW + 6}" class="band"/>']
    body.append(_text((xs(settings["mu_min"]) + xs(settings["mu_max"])) / 2, top - 12,
                      f'{settings["band_label"]} ({settings["mu_min"]:g}-{settings["mu_max"]:g} /h)', "t sm", "middle"))
    for tick in _log_ticks(lo, hi):
        x = xs(tick)
        body.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{top - 6}" y2="{height - bottom + 2}" class="grid"/>')
        body.append(_text(x, height - bottom + 18, f"{tick:g}", "t sm", "middle"))
    body.append(_text(left + plot_w / 2, height - 8, "Predicted maximum growth rate (1/h, log scale)", "t sm", "middle"))
    for i, m in enumerate(rows):
        y = top + i * _ROW + _ROW / 2
        body.append(_text(left - 10, y + 4, m["label"], "t", "end"))
        body.append(f'<line x1="{left}" x2="{xs(m["mu_per_h"]):.1f}" y1="{y}" y2="{y}" class="stem"/>')
        body.append(f'<circle cx="{xs(m["mu_per_h"]):.1f}" cy="{y}" r="5.5" class="dot" style="fill:{colors[m["group"]]}">'
                    f'<title>{escape(m["display_name"])}: {m["mu_per_h"]:.4g} /h (doubling {m.get("doubling_time_min") or 0:.4g} min)</title></circle>')
    return _svg(width, height, "".join(body), "Predicted growth rate per model")


# --- (b) blocked vs dead-end ------------------------------------------------------------

def blocked_scatter(models, colors):
    pts = [m for m in models if m.get("pct_blocked") is not None and m.get("pct_deadend") is not None]
    if len(pts) < 2:
        return ""
    width, height, left, right, top, bottom = 560, 380, 56, 24, 20, 48
    xmax = max(5.0, max(m["pct_blocked"] for m in pts)) * 1.15
    ymax = max(5.0, max(m["pct_deadend"] for m in pts)) * 1.15
    xs = lambda v: left + v / xmax * (width - left - right)
    ys = lambda v: height - bottom - v / ymax * (height - top - bottom)
    body = []
    for i in range(5):
        for v, scale, axis in ((xmax * i / 4, xs, "x"), (ymax * i / 4, ys, "y")):
            if axis == "x":
                body.append(f'<line x1="{scale(v):.1f}" x2="{scale(v):.1f}" y1="{top}" y2="{height - bottom}" class="grid"/>')
                body.append(_text(scale(v), height - bottom + 16, f"{v:.3g}", "t sm", "middle"))
            else:
                body.append(f'<line x1="{left}" x2="{width - right}" y1="{scale(v):.1f}" y2="{scale(v):.1f}" class="grid"/>')
                body.append(_text(left - 8, scale(v) + 4, f"{v:.3g}", "t sm", "end"))
    body.append(_text((left + width - right) / 2, height - 8, "Blocked reactions (% of all reactions)", "t sm", "middle"))
    body.append(_text(14, (top + height - bottom) / 2, "Dead-end metabolites (% of all metabolites)", "t sm", "middle",
                      f'transform="rotate(-90 14 {(top + height - bottom) / 2})"'))
    extremes = {id(m): m for m in sorted(pts, key=lambda m: -m["pct_blocked"])[:2] + sorted(pts, key=lambda m: m["pct_blocked"])[:2]
                + sorted(pts, key=lambda m: -m["pct_deadend"])[:1]}
    for m in pts:
        body.append(f'<circle cx="{xs(m["pct_blocked"]):.1f}" cy="{ys(m["pct_deadend"]):.1f}" r="6" class="dot" style="fill:{colors[m["group"]]}">'
                    f'<title>{escape(m["display_name"])}: {m["pct_blocked"]}% blocked, {m["pct_deadend"]}% dead-end</title></circle>')
    for m in extremes.values():
        x = xs(m["pct_blocked"])
        anchor = "end" if x > width * 0.7 else "start"
        body.append(_text(x + (-9 if anchor == "end" else 9), ys(m["pct_deadend"]) - 8, m["label"], "t sm", anchor))
    return _svg(width, height, "".join(body), "Blocked reactions versus dead-end metabolites")


# --- (c) blocked reactions by subsystem ---------------------------------------------------

def subsystem_chart(models, columns):
    rows = [m for m in models if m["totals"]]
    if not rows or not columns:
        return "", []
    named = [c for c in columns if c != UNANNOTATED][:5]
    series = named + ["other / unannotated"]
    rows = sorted(rows, key=lambda m: sum(m["totals"].values()))
    width, left, right, top, bottom = 760, 210, 40, 12, 44
    xmax = max(sum(m["totals"].values()) for m in rows)
    height = top + len(rows) * _ROW + bottom
    xs = lambda v: left + v / xmax * (width - left - right)
    body = []
    for i in range(5):
        v = xmax * i / 4
        body.append(f'<line x1="{xs(v):.1f}" x2="{xs(v):.1f}" y1="{top}" y2="{height - bottom}" class="grid"/>')
        body.append(_text(xs(v), height - bottom + 16, f"{v:.0f}", "t sm", "middle"))
    body.append(_text((left + width - right) / 2, height - 8, "Blocked reactions (count)", "t sm", "middle"))
    for i, m in enumerate(rows):
        y = top + i * _ROW + 3
        body.append(_text(left - 10, y + _ROW / 2 + 1, m["label"], "t", "end"))
        x0 = 0
        counts = [m["totals"].get(c, 0) for c in named]
        counts.append(sum(m["totals"].values()) - sum(counts))
        for j, n in enumerate(counts):
            if n <= 0:
                continue
            color = f"var(--s{j + 1})" if j < len(named) else "var(--s-other)"
            body.append(f'<rect x="{xs(x0) + (1 if x0 else 0):.1f}" y="{y}" width="{max(xs(x0 + n) - xs(x0) - (1 if x0 else 0), 1):.1f}" height="{_ROW - 8}" '
                        f'rx="2" style="fill:{color}"><title>{escape(m["name"])} / {escape(series[j])}: {n}</title></rect>')
            x0 += n
    legend = [(s, f"var(--s{j + 1})" if j < len(named) else "var(--s-other)") for j, s in enumerate(series)]
    return _svg(width, height, "".join(body), "Blocked reactions by subsystem"), legend


# --- (d) shared essential exchanges ------------------------------------------------------------

def essential_heatmap(models, essential_ids):
    sets = [(m, set(m["essential"])) for m in models]
    counts = {i: sum(i in s for _, s in sets) for i in essential_ids}
    ids = [i for i in sorted(counts, key=lambda k: (-counts[k], k)) if counts[i] >= 2][:14]
    if not ids or len(models) < 2:
        return ""
    cell, left, top, right = 22, 190, 150, 150
    order = sorted(sets, key=lambda p: p[0]["mu"] or 0)
    width = left + len(order) * cell + right
    height = top + len(ids) * cell + 16
    body = []
    for j, (m, s) in enumerate(order):
        x = left + j * cell + cell / 2
        body.append(_text(x, top - 8, m["label"], "t sm", "start", f'transform="rotate(-55 {x:.1f} {top - 8})"'))
    for i, ident in enumerate(ids):
        y = top + i * cell
        body.append(_text(left - 8, y + cell / 2 + 4, ident, "t sm", "end"))
        for j, (m, s) in enumerate(order):
            on = ident in s
            body.append(f'<rect x="{left + j * cell + 1}" y="{y + 1}" width="{cell - 2}" height="{cell - 2}" rx="2" '
                        f'class="{"cell on" if on else "cell"}"><title>{escape(m["name"])} / {escape(ident)}: '
                        f'{"essential" if on else "not essential"}</title></rect>')
    return _svg(width, height, "".join(body), "Essential exchanges shared across models")
