// ---------------------------------------------------------------------------
// Small inline-SVG charts for the generated HTML report. Colours come from CSS
// variables defined in reportDocumentHtml(), so the charts follow the report's
// light/dark toggle. Every mark carries a <title> (hover tooltip). Loaded
// after app.js.
// ---------------------------------------------------------------------------
const RC_SERIES = ["var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)", "var(--s6)"];
const rcEsc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const rcShort = (s, n) => { s = String(s); return s.length > n ? s.slice(0, n - 1) + "…" : s; };
const rcNum = (v) => (Number.isInteger(v) ? String(v) : Number(v.toPrecision(3)).toString());

function rcFigure(title, svg, legendHtml, note) {
  return `<figure class="rc-figure"><figcaption>${rcEsc(title)}</figcaption>${svg}${legendHtml || ""}${note ? `<div class="rc-note">${rcEsc(note)}</div>` : ""}</figure>`;
}

// Horizontal bars: items = [{label, value, color?}], one row per item.
function rcBars(items, opts) {
  opts = opts || {};
  items = (items || []).filter(i => Number.isFinite(i.value));
  if (!items.length) return "";
  const W = 720, labelW = 210, valueW = 64, rowH = 24, top = 4;
  const max = Math.max(...items.map(i => i.value), 1e-12);
  const barW = W - labelW - valueW;
  const H = top + items.length * rowH + 4;
  const rows = items.map((it, k) => {
    const y = top + k * rowH;
    const w = Math.max(2, (it.value / max) * barW);
    const tip = `${it.label}: ${rcNum(it.value)}${opts.unit ? " " + opts.unit : ""}`;
    return `<g><title>${rcEsc(tip)}</title>
      <text x="${labelW - 8}" y="${y + 15}" text-anchor="end" class="rc-t">${rcEsc(rcShort(it.label, 30))}</text>
      <path d="M${labelW} ${y + 5}h${w - 4}a4 4 0 0 1 4 4v2a4 4 0 0 1-4 4h-${w - 4}z" fill="${it.color || "var(--s1)"}"/>
      <text x="${labelW + w + 6}" y="${y + 15}" class="rc-t rc-v">${rcEsc(rcNum(it.value))}</text></g>`;
  }).join("");
  const svg = `<svg viewBox="0 0 ${W} ${H}" class="rc-svg" role="img" aria-label="${rcEsc(opts.title || "bar chart")}">
    <line x1="${labelW}" y1="${top}" x2="${labelW}" y2="${H - 4}" class="rc-axis"/>${rows}</svg>`;
  return rcFigure(opts.title || "", svg, "", opts.note);
}

// Column histogram of numeric values.
function rcHist(values, opts) {
  opts = opts || {};
  values = (values || []).filter(Number.isFinite);
  if (!values.length) return "";
  const W = 720, H = 220, left = 46, right = 12, top = 10, bottom = 34;
  let lo = Math.min(...values), hi = Math.max(...values);
  if (lo === hi) { lo -= 0.5; hi += 0.5; }
  const n = opts.bins || 20, step = (hi - lo) / n;
  const counts = new Array(n).fill(0);
  values.forEach(v => { counts[Math.min(n - 1, Math.floor((v - lo) / step))]++; });
  const maxC = Math.max(...counts);
  const pw = W - left - right, ph = H - top - bottom, bw = pw / n;
  const y = (c) => top + ph - (c / maxC) * ph;
  const grid = [0, 0.5, 1].map(f => {
    const c = Math.round(maxC * f), yy = y(c);
    return `<line x1="${left}" y1="${yy}" x2="${W - right}" y2="${yy}" class="rc-grid"/><text x="${left - 6}" y="${yy + 4}" text-anchor="end" class="rc-t">${c}</text>`;
  }).join("");
  const bars = counts.map((c, i) => {
    if (!c) return "";
    const x = left + i * bw + 1, h = top + ph - y(c);
    const tip = `${rcNum(lo + i * step)} to ${rcNum(lo + (i + 1) * step)}: ${c}`;
    return `<path d="M${x} ${top + ph}v${-(h - 3)}a3 3 0 0 1 3-3h${bw - 8}a3 3 0 0 1 3 3v${h - 3}z" fill="var(--s1)"><title>${rcEsc(tip)}</title></path>`;
  }).join("");
  const ticks = [lo, (lo + hi) / 2, hi].map((v, i) =>
    `<text x="${left + (i * pw) / 2}" y="${H - 14}" text-anchor="${i === 0 ? "start" : i === 2 ? "end" : "middle"}" class="rc-t">${rcEsc(rcNum(v))}</text>`).join("");
  const svg = `<svg viewBox="0 0 ${W} ${H}" class="rc-svg" role="img" aria-label="${rcEsc(opts.title || "histogram")}">${grid}${bars}${ticks}
    <text x="${left + pw / 2}" y="${H - 1}" text-anchor="middle" class="rc-t">${rcEsc(opts.xLabel || "")}</text></svg>`;
  return rcFigure(opts.title || "", svg, "", opts.note);
}

// One stacked bar: parts = [{label, value, color}].
function rcStack(parts, opts) {
  opts = opts || {};
  parts = (parts || []).filter(p => p.value > 0);
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (!total) return "";
  const W = 720, H = 34;
  let x = 0;
  const segs = parts.map(p => {
    const w = (p.value / total) * W;
    const g = `<rect x="${x}" y="4" width="${Math.max(0, w - 2)}" height="26" rx="4" fill="${p.color}"><title>${rcEsc(`${p.label}: ${p.value} (${(100 * p.value / total).toFixed(1)}%)`)}</title></rect>`;
    x += w;
    return g;
  }).join("");
  const legend = `<div class="rc-legend">${parts.map(p =>
    `<span><i style="background:${p.color}"></i>${rcEsc(p.label)} <b>${p.value}</b> (${(100 * p.value / total).toFixed(1)}%)</span>`).join("")}</div>`;
  return rcFigure(opts.title || "", `<svg viewBox="0 0 ${W} ${H}" class="rc-svg" role="img" aria-label="${rcEsc(opts.title || "stacked bar")}">${segs}</svg>`, legend, opts.note);
}

// Count of rows per key -> top-N bar items (largest first, the rest folded into "Other").
function rcCountBy(rows, keyFn, topN) {
  const counts = new Map();
  rows.forEach(r => { const k = keyFn(r) || "Unannotated"; counts.set(k, (counts.get(k) || 0) + 1); });
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const items = sorted.slice(0, topN).map(([label, value]) => ({ label, value }));
  const rest = sorted.slice(topN).reduce((s, [, v]) => s + v, 0);
  if (rest) items.push({ label: `Other (${sorted.length - topN} more)`, value: rest, color: "var(--s-other)" });
  return items;
}
