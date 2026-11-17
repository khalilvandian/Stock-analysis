// The ticker explorer (issue #20): draws ticker.html?s=SYMBOL from tickers/SYMBOL.json and
// tickers/index.json, written by analysis/explore.py. No libraries; charts are inline SVG.
"use strict";

const $ = (sel, el = document) => el.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const ok = (v) => v !== null && v !== undefined && Number.isFinite(v);
const DASH = "<span class='na'>—</span>";

// --- number formats ---------------------------------------------------------------------
function money(v, cur = "$") {
  if (!ok(v)) return DASH;
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  if (a >= 1e12) return `${s}${cur}${(a / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${s}${cur}${(a / 1e9).toFixed(a >= 1e11 ? 0 : 1)}B`;
  if (a >= 1e6) return `${s}${cur}${(a / 1e6).toFixed(0)}M`;
  return `${s}${cur}${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}
const price = (v) => (ok(v) ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : DASH);
const pct = (v, d = 1) => (ok(v) ? `${(v * 100).toFixed(d)}%` : DASH);
const spct = (v, d = 1) => (ok(v) ? `${v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%` : DASH);
const mult = (v) => (ok(v) ? `${v.toFixed(1)}x` : DASH);
const plain = (v, d = 2) => (ok(v) ? v.toFixed(d) : DASH);
const shares = (v) => (ok(v) ? `${(v / 1e9).toFixed(2)}B` : DASH);
const FORMATS = { money, price, pct, spct, mult, plain, shares };
const strip = (html) => html.replace(/<[^>]+>/g, "");

// --- tooltip ----------------------------------------------------------------------------
const tip = document.createElement("div");
tip.className = "tip";
tip.hidden = true;
document.body.appendChild(tip);
function showTip(e, html) {
  tip.innerHTML = html;
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + r.width > innerWidth - 8) x = e.clientX - r.width - 14;
  if (y + r.height > innerHeight - 8) y = e.clientY - r.height - 14;
  tip.style.left = `${x}px`;
  tip.style.top = `${y}px`;
}
const hideTip = () => (tip.hidden = true);

// --- charts -----------------------------------------------------------------------------
const W = 640, H = 220, PAD = { l: 56, r: 12, t: 12, b: 26 };

function ticks(lo, hi, n = 4) {
  if (lo === hi) { lo -= 1; hi += 1; }
  const step0 = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0);
  const out = [];
  // from at or below the lowest value to at or above the highest, so no mark is clipped
  for (let v = Math.floor(lo / step) * step; ; v += step) {
    out.push(+v.toFixed(10));
    if (v >= hi - step * 1e-9 || out.length > 50) break;
  }
  return out;
}

function axisLabel(v, fmt) {
  return strip(FORMATS[fmt] ? FORMATS[fmt](v) : String(v));
}

// One series of bars, one per period. Negative bars are drawn in the muted ink and
// labelled by their sign in the tooltip, so colour is never the only cue.
function barChart(labels, values, fmt, name, small = false) {
  // Grid charts are drawn at about the size they are shown, so the text stays readable.
  const W = small ? 360 : 640, H = small ? 210 : 220, PAD = { l: small ? 50 : 56, r: 8, t: 12, b: 26 };
  const vals = values.map((v) => (ok(v) ? v : null));
  const present = vals.filter((v) => v !== null);
  if (!present.length) return "<p class='empty'>No data.</p>";
  const t = ticks(Math.min(0, ...present), Math.max(0, ...present));
  const lo = t[0], hi = t[t.length - 1];
  const y = (v) => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo));
  const n = labels.length, bw = (W - PAD.l - PAD.r) / n, gap = Math.max(2, bw * 0.28);
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)} by period">`;
  for (const v of t) s += `<line class="grid" x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${PAD.l - 6}" y="${y(v) + 4}" text-anchor="end">${esc(axisLabel(v, fmt))}</text>`;
  s += `<line class="base" x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(0)}" y2="${y(0)}"/>`;
  const every = Math.ceil(n / (small ? 6 : 12));
  labels.forEach((lab, i) => {
    const x = PAD.l + i * bw + gap / 2, w = bw - gap, v = vals[i];
    if (v !== null) {
      const y0 = y(0), y1 = y(v), top = Math.min(y0, y1), h = Math.max(1, Math.abs(y1 - y0));
      const r = Math.min(4, w / 2, h);
      // rounded at the data end, square at the baseline
      const d = v >= 0
        ? `M${x},${y0}V${top + r}Q${x},${top} ${x + r},${top}H${x + w - r}Q${x + w},${top} ${x + w},${top + r}V${y0}Z`
        : `M${x},${y0}V${top + h - r}Q${x},${top + h} ${x + r},${top + h}H${x + w - r}Q${x + w},${top + h} ${x + w},${top + h - r}V${y0}Z`;
      s += `<path class="bar${v < 0 ? " neg" : ""}" d="${d}"/>`;
    }
    s += `<rect class="hit" x="${PAD.l + i * bw}" y="${PAD.t}" width="${bw}" height="${H - PAD.t - PAD.b}" data-i="${i}"/>`;
    if ((n - 1 - i) % every === 0) s += `<text x="${x + w / 2}" y="${H - 8}" text-anchor="middle">${esc(lab)}</text>`;
  });
  s += "</svg>";
  const id = `c${Math.random().toString(36).slice(2)}`;
  setTimeout(() => {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelectorAll(".hit").forEach((h) => {
      const i = +h.dataset.i;
      h.addEventListener("mousemove", (e) => showTip(e, `<b>${esc(labels[i])}</b><br>${esc(name)}: ${FORMATS[fmt](vals[i])}`));
      h.addEventListener("mouseleave", hideTip);
    });
  });
  return `<div class="chart" id="${id}">${s}</div>`;
}

// A price line with a crosshair. points: [[date, value], ...]
function lineChart(points, name) {
  const pts = points.filter((p) => ok(p[1]));
  if (pts.length < 2) return "<p class='empty'>No prices.</p>";
  const vs = pts.map((p) => p[1]);
  const t = ticks(Math.min(...vs), Math.max(...vs));
  const lo = t[0], hi = t[t.length - 1];
  const x = (i) => PAD.l + (W - PAD.l - PAD.r) * (i / (pts.length - 1));
  const y = (v) => PAD.t + (H - PAD.t - PAD.b) * (1 - (v - lo) / (hi - lo));
  let s = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)}">`;
  for (const v of t) s += `<line class="grid" x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(v)}" y2="${y(v)}"/><text x="${PAD.l - 6}" y="${y(v) + 4}" text-anchor="end">${esc(axisLabel(v, "price"))}</text>`;
  let lastYear = "";
  const step = Math.max(1, Math.floor(pts.length / 8));
  pts.forEach((p, i) => {
    const lab = pts.length > 300 || points.length > 300 ? p[0].slice(0, 4) : p[0].slice(0, 7);
    if (i % step === 0 && lab !== lastYear) { s += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${lab}</text>`; lastYear = lab; }
  });
  s += `<path class="line" d="${pts.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p[1]).toFixed(1)}`).join("")}"/>`;
  s += `<line class="cross" x1="0" x2="0" y1="${PAD.t}" y2="${H - PAD.b}" visibility="hidden"/><circle class="dotm" r="4" visibility="hidden"/>`;
  s += `<rect class="hit" x="${PAD.l}" y="${PAD.t}" width="${W - PAD.l - PAD.r}" height="${H - PAD.t - PAD.b}"/></svg>`;
  const id = `c${Math.random().toString(36).slice(2)}`;
  setTimeout(() => {
    const el = document.getElementById(id);
    if (!el) return;
    const svg = $("svg", el), cross = $(".cross", el), dot = $(".dotm", el);
    $(".hit", el).addEventListener("mousemove", (e) => {
      const b = svg.getBoundingClientRect();
      const px = ((e.clientX - b.left) / b.width) * W;
      const i = Math.max(0, Math.min(pts.length - 1, Math.round(((px - PAD.l) / (W - PAD.l - PAD.r)) * (pts.length - 1))));
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(pts[i][1])); dot.setAttribute("visibility", "visible");
      showTip(e, `<b>${esc(pts[i][0])}</b><br>${esc(name)}: ${price(pts[i][1])}`);
    });
    $(".hit", el).addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
  });
  return `<div class="chart" id="${id}">${s}</div>`;
}

// --- building blocks --------------------------------------------------------------------
const tile = (label, value, note = "") => `<div class="card tile"><small>${esc(label)}</small><b>${value}</b>${note ? `<em>${note}</em>` : ""}</div>`;
const tiles = (list) => `<div class="strip">${list.join("")}</div>`;
const panel = (title, inner, note = "") => `<section class="card xpanel"><h3>${esc(title)}</h3>${inner}${note ? `<p class="note">${note}</p>` : ""}</section>`;

function median(xs) {
  const v = xs.filter(ok).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

// Statement rows: [label, item key or function(i) of the column, format]
function statement(cols, rows, get, derived = new Set()) {
  let h = `<div class="wrap"><table class="fin"><thead><tr><th></th>${cols.map((c) => `<th class="n">${esc(c)}</th>`).join("")}</tr></thead><tbody>`;
  for (const [label, key, fmt] of rows) {
    h += `<tr><th scope="row">${esc(label)}</th>`;
    cols.forEach((_, i) => {
      const v = get(key, i);
      const mark = typeof key === "string" && derived.has(`${i}:${key}`) ? "<sup title='Fiscal year less the first three quarters'>*</sup>" : "";
      h += `<td class="n">${FORMATS[fmt](v)}${mark}</td>`;
    });
    h += "</tr>";
  }
  return h + "</tbody></table></div>";
}

const INCOME = [["Revenue", "revenue", "money"], ["Operating income", "operating_income", "money"], ["Depreciation and amortization", "d_and_a", "money"], ["EBITDA", "ebitda", "money"], ["Interest expense", "interest_expense", "money"], ["Net income", "net_income", "money"], ["Diluted EPS", "eps_diluted", "price"]];
const BALANCE = [["Cash and equivalents", "cash", "money"], ["Short-term debt", "short_term_debt", "money"], ["Long-term debt", "long_term_debt", "money"], ["Total debt", "total_debt", "money"], ["Net debt", "net_debt", "money"], ["Total assets", "total_assets", "money"], ["Total liabilities", "total_liabilities", "money"], ["Shareholders' equity", "equity", "money"], ["Shares outstanding", "shares_outstanding", "shares"]];
const CASHFLOW = [["Operating cash flow", "operating_cf", "money"], ["Capital expenditure", "capex", "money"], ["Free cash flow", "free_cf", "money"]];

// --- the tabs ---------------------------------------------------------------------------
function summary(t, idx) {
  const s = t.snapshot, r = t.ratios, g = t.growth, k = t.technicals;
  const dcf = (t.valuation.dcf || [])[0];
  const peers = (idx?.tickers || []).filter((x) => x.sector === t.profile.sector);
  const med = (key) => median(peers.map((x) => x[key]));
  const abs = tiles([
    tile("Price", price(s.price), esc(t.asof || "")),
    tile("Market value", money(s.market_cap)),
    tile("Our DCF fair value", dcf ? price(dcf.fair_value) : DASH, dcf ? esc(dcf.as_of) : "not run"),
    tile("Revenue (TTM)", money(s.revenue)),
    tile("EBITDA (TTM)", money(s.ebitda)),
    tile("Net income (TTM)", money(s.net_income)),
    tile("Diluted EPS (TTM)", price(s.eps_diluted)),
    tile("Operating cash flow", money(s.operating_cf)),
    tile("Capex", money(s.capex)),
    tile("Free cash flow", money(s.free_cf)),
    tile("Cash", money(s.cash)),
    tile("Total debt", money(s.total_debt)),
    tile("Net debt", money(s.net_debt)),
    tile("Short-term debt", money(s.short_term_debt)),
    tile("Long-term debt", money(s.long_term_debt)),
  ]);
  const rrows = [
    ["P/E", r.pe, "pe", mult], ["Price / sales", r.ps, "ps", mult], ["Price / book", r.pb, "pb", mult],
    ["EV / EBITDA", r.ev_ebitda, "ev_ebitda", mult], ["FCF yield", r.fcf_yield, "fcf_yield", pct],
    ["Dividend yield", t.dividends?.yield, "div_yield", pct], ["Net margin", r.net_margin, "net_margin", pct],
    ["Return on equity", r.roe, "roe", pct], ["Net debt / EBITDA", r.net_debt_to_ebitda, "net_debt_to_ebitda", mult],
    ["Revenue growth, 5 yr a year", g.revenue_5y, "revenue_5y", pct], ["EPS growth, 5 yr a year", g.eps_5y, "eps_5y", pct],
  ];
  const ratioTable = `<div class="wrap"><table><thead><tr><th>Ratio</th><th class="n">${esc(t.symbol)}</th><th class="n">Sector median</th></tr></thead><tbody>${rrows.map(([l, v, key, fmt]) => `<tr><td>${l}</td><td class="n">${fmt(v)}</td><td class="n">${fmt(med(key))}</td></tr>`).join("")}</tbody></table></div>`;
  const more = `<div class="wrap"><table><tbody>${[
    ["Operating margin", pct(r.operating_margin)], ["EBITDA margin", pct(r.ebitda_margin)], ["FCF margin", pct(r.fcf_margin)],
    ["Return on assets", pct(r.roa)], ["Debt / equity", mult(r.debt_to_equity)], ["Interest cover (EBITDA / interest)", mult(r.interest_cover)],
    ["Cash / short-term debt", mult(r.cash_to_short_term_debt)], ["Capex / operating cash flow", pct(r.capex_to_ocf)],
    ["EV / revenue", mult(r.ev_revenue)], ["Earnings yield", pct(r.earnings_yield)],
  ].map(([l, v]) => `<tr><td>${l}</td><td class="n">${v}</td></tr>`).join("")}</tbody></table></div>`;
  const grow = `<div class="wrap"><table><thead><tr><th>A year, compounded</th><th class="n">3 yr</th><th class="n">5 yr</th><th class="n">10 yr</th></tr></thead><tbody>${[["Revenue", "revenue"], ["Diluted EPS", "eps"], ["Free cash flow", "fcf"], ["Shares outstanding", "shares"]].map(([l, key]) => `<tr><td>${l}</td>${[3, 5, 10].map((n) => `<td class="n">${pct(g[`${key}_${n}y`])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const range = ok(k.high52) && ok(k.low52) && k.high52 > k.low52 ? (s.price - k.low52) / (k.high52 - k.low52) : null;
  const tech = tiles([
    tile("20-day average", price(k.sma20), ok(k.sma20) ? spct(s.price / k.sma20 - 1) + " vs price" : ""),
    tile("From the 52-week high", ok(k.high52) ? spct(s.price / k.high52 - 1) : DASH),
    tile("Momentum 12-1", spct(k.momentum_12_1), "a year ago to a month ago"),
    tile("50-day average",price(k.sma50), ok(k.sma50) ? spct(s.price / k.sma50 - 1) + " vs price" : ""),
    tile("200-day average", price(k.sma200), ok(k.sma200) ? spct(s.price / k.sma200 - 1) + " vs price" : ""),
    tile("RSI (14 days)", plain(k.rsi14, 0), ok(k.rsi14) ? (k.rsi14 < 30 ? "oversold" : k.rsi14 > 70 ? "overbought" : "neutral") : ""),
    tile("52-week range", `${price(k.low52)} – ${price(k.high52)}`, ok(range) ? `at ${pct(range, 0)} of the range` : ""),
    tile("Total return, 1 yr", spct(k.return_1y)),
    tile("Total return, 5 yr a year", spct(k.return_5y)),
    tile("Total return, 10 yr a year", spct(k.return_10y)),
  ]);
  // Ten-year cards: the latest fiscal year and its compound growth over (up to) ten years.
  const a = t.annual, n = a.years.length, span = Math.min(10, n - 1);
  const ten = (label, vals, fmt) => {
    const last = vals[n - 1], first = vals[n - 1 - span];
    const g = ok(last) && ok(first) && first > 0 && last > 0 && span > 0 ? (last / first) ** (1 / span) - 1 : null;
    return tile(label, FORMATS[fmt](last), ok(g) ? `${spct(g)} a year over ${span} yrs` : `over ${span} yrs`);
  };
  const fcfA = a.items.operating_cf.map((v, i) => (ok(v) && ok(a.items.capex[i]) ? v + a.items.capex[i] : null));
  const nm = t.annual_ratios.net_margin || [];
  const marginPts = ok(nm[n - 1]) && ok(nm[n - 1 - span]) ? `${((nm[n - 1] - nm[n - 1 - span]) * 100 > 0 ? "+" : "")}${((nm[n - 1] - nm[n - 1 - span]) * 100).toFixed(1)} pts over ${span} yrs` : "";
  const tenCards = n > 1 ? tiles([
    ten("Revenue", a.items.revenue, "money"), ten("Net income", a.items.net_income, "money"), ten("Diluted EPS", a.items.eps_diluted, "price"),
    ten("Free cash flow", fcfA, "money"), tile("Net margin", pct(nm[n - 1]), marginPts), ten("Shares outstanding", a.items.shares_outstanding, "shares"),
  ]) : "";
  const s1 = t.screener?.stage1 || {};
  const health = tiles([
    tile("Altman Z-score", plain(s1.altman_z_score_ttm, 2), ok(s1.altman_z_score_ttm) ? (s1.altman_z_score_ttm > 3 ? "safe zone (> 3)" : s1.altman_z_score_ttm < 1.8 ? "distress zone (< 1.8)" : "grey zone") : ""),
    tile("Piotroski F-score", plain(s1.piotroski_f_score_ttm, 0), "of 9"),
    tile("Interest cover", mult(r.interest_cover), "EBITDA / interest"),
    tile("Debt / assets", plain(r.debt_to_assets)),
    tile("Net debt / EBITDA", mult(r.net_debt_to_ebitda)),
  ]);
  const stats = tiles([
    tile("P/E (TTM)", mult(r.pe)), tile("EV / EBITDA (TTM)", mult(r.ev_ebitda)), tile("Dividends (TTM)", price(t.dividends?.ttm), pct(t.dividends?.yield, 2)),
    tile("Volume", ok(k.volume) ? k.volume.toLocaleString("en-US") : DASH, ok(k.avg_volume_3m) ? `3-month average ${k.avg_volume_3m.toLocaleString("en-US")}` : ""),
  ]);
  return `<h2>Absolute values</h2>${abs}<p class="note">Flows over the last twelve months to ${esc(s.period_end || "—")}; balance sheet at that date; price and market value at the close of ${esc(t.asof || "—")}.</p>
    ${tenCards ? `<h2>Last fiscal year, and the ten years before it</h2>${tenCards}` : ""}
    <h2>Price</h2><div class="card xpanel">${priceChart(t)}</div>${stats}
    <h2>Financial health</h2>${health}
    <h2>Ratios</h2><div class="cols">${panel("Against the sector", ratioTable, `${peers.length} companies in ${esc(t.profile.sector || "the sector")}.`)}${panel("More ratios", more)}</div>
    <h2>Growth</h2>${panel("Compound growth from the fiscal-year statements", grow)}
    <h2>Technicals</h2>${tech}<p class="note">Total return reinvests the dividends (adjusted close).</p>`;
}

function priceChart(t) {
  const w = t.prices.weekly, d = t.prices.daily;
  const ranges = { "1Y": d.map((p) => [p[0], p[1]]).slice(-252), "5Y": w.slice(-262).map((p) => [p[0], p[1]]), "10Y": w.map((p) => [p[0], p[1]]) };
  const id = `pc${Math.random().toString(36).slice(2)}`;
  setTimeout(() => {
    const box = document.getElementById(id);
    if (!box) return;
    box.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      box.querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b));
      $(".plot", box).innerHTML = lineChart(ranges[b.dataset.r], "Close");
    }));
  });
  return `<div id="${id}"><div class="seg">${Object.keys(ranges).map((r) => `<button type="button" data-r="${r}"${r === "5Y" ? " class=on" : ""}>${r}</button>`).join("")}</div><div class="plot">${lineChart(ranges["5Y"], "Close")}</div></div>`;
}

function financials(t, mode) {
  const a = mode === "Q" ? t.quarterly : t.annual;
  const cols = mode === "Q" ? a.label : a.years.map((y) => `FY${y}`);
  const items = a.items;
  const derived = new Set((a.derived || []).map(([end, item]) => `${a.period_end.indexOf(end)}:${item}`));
  const get = (key, i) => {
    if (key === "free_cf") return ok(items.operating_cf[i]) && ok(items.capex[i]) ? items.operating_cf[i] + items.capex[i] : null;
    if (key === "net_debt") return ok(items.total_debt[i]) ? items.total_debt[i] - (items.cash[i] || 0) : null;
    return items[key]?.[i];
  };
  const seg = `<div class="seg" data-fin>${[["A", "Annual"], ["Q", "Quarterly"]].map(([k, l]) => `<button type="button" data-m="${k}"${k === mode ? " class=on" : ""}>${l}</button>`).join("")}</div>`;
  const note = mode === "Q" ? "Each quarter on its own (three months). * Fourth quarter worked out as the fiscal year less the first three quarters. EPS and shares on today's share basis." : "Fiscal years as reported in the latest filing; balance sheet at the fiscal year end. EPS and shares on today's share basis.";
  return `${seg}<h2>Income statement</h2>${panel("", statement(cols, INCOME, get, derived))}
    <h2>Balance sheet</h2>${panel("", statement(cols, BALANCE, get))}
    <h2>Cash flow</h2>${panel("", statement(cols, CASHFLOW, get, derived))}<p class="note">${note} Source: SEC company facts, Yahoo where SEC has no value.</p>`;
}

function charts(t, mode) {
  const a = mode === "Q" ? t.quarterly : t.annual;
  const labels = mode === "Q" ? a.label.map((l) => l.replace(" FY", " ’").replace(/’(\d\d)(\d\d)/, "’$2")) : a.years.map(String);
  const it = a.items;
  const fcf = it.operating_cf.map((v, i) => (ok(v) && ok(it.capex[i]) ? v + it.capex[i] : null));
  const netDebt = it.total_debt.map((v, i) => (ok(v) ? v - (it.cash[i] || 0) : null));
  const margin = it.net_income.map((v, i) => (ok(v) && ok(it.revenue[i]) && it.revenue[i] ? v / it.revenue[i] : null));
  const list = [["Revenue", it.revenue, "money"], ["EBITDA", it.ebitda, "money"], ["Net income", it.net_income, "money"], ["Diluted EPS", it.eps_diluted, "price"], ["Operating cash flow", it.operating_cf, "money"], ["Free cash flow", fcf, "money"], ["Net debt", netDebt, "money"], ["Net margin", margin, "pct"], ["Shares outstanding", it.shares_outstanding, "shares"]];
  if (mode !== "Q") list.push(["Return on equity", t.annual_ratios.roe, "pct"], ["P/E at the fiscal year end", t.annual_ratios.pe, "mult"], ["Dividend per share (calendar year)", null, "price"]);
  const seg = `<div class="seg" data-chart>${[["A", "Annual"], ["Q", "Quarterly"]].map(([k, l]) => `<button type="button" data-m="${k}"${k === mode ? " class=on" : ""}>${l}</button>`).join("")}</div>`;
  const cards = list.map(([name, vals, fmt]) => {
    if (vals === null) {
      const dv = t.dividends?.per_year || [];
      if (!dv.length) return "";
      return panel(name, barChart(dv.map((d) => String(d[0])), dv.map((d) => d[1]), fmt, name, true));
    }
    return panel(name, barChart(labels, vals, fmt, name, true));
  });
  return `${seg}<div class="charts">${cards.join("")}</div>`;
}

const RATIO_ROWS = [
  ["Valuation (price in the fiscal year-end week)", null],
  ["P/E", "pe", "mult"], ["Price / sales", "ps", "mult"], ["Price / book", "pb", "mult"], ["EV / EBITDA", "ev_ebitda", "mult"], ["FCF yield", "fcf_yield", "pct"],
  ["Profitability", null],
  ["Operating margin", "operating_margin", "pct"], ["EBITDA margin", "ebitda_margin", "pct"], ["Net margin", "net_margin", "pct"], ["FCF margin", "fcf_margin", "pct"], ["Return on equity", "roe", "pct"], ["Return on assets", "roa", "pct"],
  ["Debt", null],
  ["Debt / equity", "debt_to_equity", "mult"], ["Net debt / EBITDA", "net_debt_to_ebitda", "mult"], ["Interest cover (EBITDA / interest)", "interest_cover", "mult"],
  ["Per share (today's share basis)", null],
  ["Free cash flow per share", "fcf_per_share", "price"], ["Book value per share", "book_per_share", "price"], ["Price at the year end", "price", "price"], ["Market value at the year end", "market_cap", "money"],
];

// The company now against its sector and against its own last five fiscal years.
function ratioCompare(t, idx) {
  const r = t.ratios, ar = t.annual_ratios;
  const peers = (idx?.tickers || []).filter((x) => x.sector === t.profile.sector);
  const avg5 = (key) => { const v = (ar[key] || []).slice(-5).filter(ok); return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null; };
  const diff = (a, b) => (ok(a) && ok(b) && b !== 0 ? spct(a / b - 1, 0) : DASH);
  const rows = [
    ["P/E", r.pe, "pe", "pe", mult], ["Price / sales", r.ps, "ps", "ps", mult], ["Price / book", r.pb, "pb", "pb", mult],
    ["EV / EBITDA", r.ev_ebitda, "ev_ebitda", "ev_ebitda", mult], ["FCF yield", r.fcf_yield, "fcf_yield", "fcf_yield", pct],
    ["Net margin", r.net_margin, "net_margin", "net_margin", pct], ["Return on equity", r.roe, "roe", "roe", pct],
    ["Net debt / EBITDA", r.net_debt_to_ebitda, "net_debt_to_ebitda", "net_debt_to_ebitda", mult], ["Debt / equity", r.debt_to_equity, null, "debt_to_equity", mult],
  ];
  return `<div class="wrap"><table><thead><tr><th>Ratio</th><th class="n">${esc(t.symbol)} now</th><th class="n">Sector median</th><th class="n">Diff</th><th class="n">${esc(t.symbol)} 5-yr average</th><th class="n">Diff</th></tr></thead><tbody>${rows.map(([l, v, sk, ak, f]) => {
    const sm = sk ? median(peers.map((x) => x[sk])) : null, a5 = avg5(ak);
    return `<tr><td>${l}</td><td class="n"><b>${f(v)}</b></td><td class="n">${f(sm)}</td><td class="n">${diff(v, sm)}</td><td class="n">${f(a5)}</td><td class="n">${diff(v, a5)}</td></tr>`;
  }).join("")}</tbody></table></div>`;
}

function ratiosTab(t, idx) {
  const r = t.annual_ratios, cols = t.annual.years.map((y) => `FY${y}`);
  let h = `<div class="wrap"><table class="fin"><thead><tr><th></th>${cols.map((c) => `<th class="n">${c}</th>`).join("")}<th class="n">Now (TTM)</th></tr></thead><tbody>`;
  const now = { ...t.ratios, price: t.snapshot.price, market_cap: t.snapshot.market_cap, book_per_share: t.snapshot.book_per_share, fcf_per_share: ok(t.snapshot.free_cf) && ok(t.snapshot.shares_outstanding) ? t.snapshot.free_cf / t.snapshot.shares_outstanding : null };
  for (const [label, key, fmt] of RATIO_ROWS) {
    if (!key) { h += `<tr><th scope="row" class="grp" colspan="${cols.length + 2}">${esc(label)}</th></tr>`; continue; }
    h += `<tr><th scope="row">${esc(label)}</th>${cols.map((_, i) => `<td class="n">${FORMATS[fmt](r[key]?.[i])}</td>`).join("")}<td class="n"><b>${FORMATS[fmt](now[key])}</b></td></tr>`;
  }
  h += "</tbody></table></div>";
  const pick = [["P/E", "pe", "mult"], ["EV / EBITDA", "ev_ebitda", "mult"], ["Net margin", "net_margin", "pct"], ["Return on equity", "roe", "pct"], ["FCF yield", "fcf_yield", "pct"], ["Net debt / EBITDA", "net_debt_to_ebitda", "mult"]];
  return `<h2>Now, against the sector and the last five years</h2>${panel("", ratioCompare(t, idx), "Diff = how far the company's figure is above (+) or below (−) the comparison.")}
    <h2>Ratios, every fiscal year</h2>${panel("", h,"Ratios of a loss, negative equity or negative EBITDA are left blank. Fiscal years from the statements; the last column uses the latest twelve months and today's price.")}
    <div class="charts">${pick.map(([n, k, f]) => panel(n, barChart(t.annual.years.map(String), r[k] || [], f, n, true))).join("")}</div>`;
}

function valuation(t, idx) {
  const v = t.valuation, s = t.snapshot;
  const up = (x) => (ok(x) && ok(s.price) ? `${spct(x / s.price - 1, 0)} vs price` : "");
  // Relative fair value: what the sector's median multiples would pay for this company.
  const peers = (idx?.tickers || []).filter((x) => x.sector === t.profile.sector && x.symbol !== t.symbol);
  const medPE = median(peers.map((x) => x.pe)), medEV = median(peers.map((x) => x.ev_ebitda));
  const relPE = ok(medPE) && ok(s.eps_diluted) && s.eps_diluted > 0 ? medPE * s.eps_diluted : null;
  const relEV = ok(medEV) && ok(s.ebitda) && s.ebitda > 0 && ok(s.shares_outstanding) ? (medEV * s.ebitda - (s.net_debt || 0)) / s.shares_outstanding : null;
  const relative = `<h2>Relative fair value</h2>${tiles([
    tile("Sector median P/E", mult(medPE), `${peers.length} peer${peers.length === 1 ? "" : "s"}`), tile("Price at the sector P/E", price(relPE), up(relPE)),
    tile("Sector median EV / EBITDA", mult(medEV)), tile("Price at the sector EV / EBITDA", price(relEV && relEV > 0 ? relEV : null), relEV > 0 ? up(relEV) : ""),
  ])}<p class="note">Price at the sector EV / EBITDA = (median multiple × TTM EBITDA − net debt) ÷ shares. Peers: the other companies of the ${esc(t.profile.sector || "")} sector in the database.</p>`;
  return valuationBody(t, v, s, up) + relative + valuationDcf(v);
}

function valuationBody(t, v, s, up) {
  const pe = t.annual_ratios.pe || [];
  return `<h2>EPS fair value: the company's own P/E history</h2>${tiles([
    tile("Price", price(s.price), esc(t.asof || "")),
    tile("P/E now (TTM)", mult(v.pe_now)),
    tile(`Median P/E, last ${v.pe_years || 0} yrs`, mult(v.pe_median_10y)),
    tile("Price at the median P/E", price(v.price_at_median_pe), up(v.price_at_median_pe)),
    tile("Lowest P/E, same years", mult(v.pe_low_10y)),
    tile("Price at the lowest P/E", price(v.price_at_low_pe), up(v.price_at_low_pe)),
    tile("Graham number", price(v.graham_number), up(v.graham_number)),
    ...(ok(v.cheap_price) ? [tile("Screener cheap price", price(v.cheap_price), `at a cheap P/E of ${mult(v.cheap_pe)}`)] : []),
  ])}
  <p class="note">Price at a P/E = that P/E × TTM diluted EPS; P/E per year = the price in the fiscal year-end week over that year's EPS. Graham number = √(22.5 × EPS × book value per share), only for positive earnings and equity. The cheap price comes from Stage 2 of the market screener (top 3 per sector only).</p>
  ${panel("P/E at each fiscal year end", barChart(t.annual.years.map(String), pe, "mult", "P/E"))}`;
}

function valuationDcf(v) {
  const dcf = (v.dcf || []).map((d) => `<tr><td>${esc(d.method)}</td><td class="d">${esc(d.as_of)}</td><td class="n">${price(d.fair_value)}</td><td class="n">${price(d.price)}</td><td class="n">${ok(d.fair_value) && ok(d.price) ? spct(d.fair_value / d.price - 1, 0) : DASH}</td></tr>`).join("");
  return `<h2>DCF fair value: our discounted cash flow</h2>${dcf ?panel("", `<div class="wrap"><table><thead><tr><th>Method</th><th>As of</th><th class="n">Fair value</th><th class="n">Price then</th><th class="n">Upside then</th></tr></thead><tbody>${dcf}</tbody></table></div>`) : "<p class='empty'>No DCF has been run for this company yet (analysis/dcf_firm.py).</p>"}`;
}

function dividendsTab(t) {
  const d = t.dividends;
  const py = d.per_year || [];
  return `<h2>Dividends</h2>${tiles([
    tile("Paid in the last 12 months", price(d.ttm)), tile("Yield", pct(d.yield, 2)), tile("Payout of EPS", pct(d.payout, 0)),
    tile("Years of increases in a row", String(d.growth_streak ?? "—")), tile("Growth, 5 yr a year", pct(d.cagr_5y)),
    tile("Last dividend", d.last ? price(d.last[1]) : DASH, d.last ? `ex-dividend ${esc(d.last[0])}` : ""),
    tile("Frequency", { 1: "Yearly", 2: "Twice a year", 4: "Quarterly", 12: "Monthly" }[d.per_year_count] || (d.per_year_count ? `${d.per_year_count} a year` : DASH), "payments in the last 12 months"),
  ])}
  ${panel("Dividend per share by calendar year", barChart(py.map((x) => String(x[0]) + (x[0] === d.partial_year ? "*" : "")), py.map((x) => x[1]), "price", "Dividends"), d.partial_year ? `* ${d.partial_year} so far.` : "")}
  ${panel("Latest payments (ex-dividend date)", `<div class="wrap"><table><thead><tr><th>Date</th><th class="n">Per share</th></tr></thead><tbody>${(d.recent || []).slice().reverse().map(([day, v]) => `<tr><td class="d">${esc(day)}</td><td class="n">${price(v)}</td></tr>`).join("")}</tbody></table></div>`)}
  <p class="note">Per share on today's share basis. Source: Yahoo daily prices.</p>`;
}

function earningsTab(t) {
  const e = t.earnings, h = e.history || [];
  const last = h.slice(-16);
  return `<h2>Earnings</h2>${tiles([
    tile("Next report", e.next ? esc(e.next.date) : DASH), tile("EPS estimate, next quarter", e.next ? price(e.next.eps_estimate) : DASH),
    tile("Beat the estimate, last 12", pct(e.beat_rate, 0)),
  ])}
  ${panel("Surprise: reported EPS against the estimate", barChart(last.map((x) => x[0].slice(0, 7)), last.map((x) => (ok(x[3]) ? x[3] / 100 : null)), "spct", "Surprise"))}
  ${panel("History", `<div class="wrap"><table><thead><tr><th>Report date</th><th class="n">Estimate</th><th class="n">Reported</th><th class="n">Surprise</th><th class="n">Surprise %</th></tr></thead><tbody>${h.slice().reverse().map(([d, est, rep, sur]) => `<tr><td class="d">${esc(d)}</td><td class="n">${price(est)}</td><td class="n">${price(rep)}</td><td class="n">${ok(rep) && ok(est) ? (Math.abs(rep - est) < 0.005 ? "In line" : (rep > est ? "Beat by " : "Missed by ") + price(Math.abs(rep - est))) : DASH}</td><td class="n">${ok(sur) ? spct(sur / 100) : DASH}</td></tr>`).join("")}</tbody></table></div>`)}
  <p class="note">Quarterly EPS as Yahoo reports it (adjusted), with the analysts' consensus. Source: Yahoo.</p>`;
}

const CATEGORY = { slow_grower: "Slow grower", stalwart: "Stalwart", fast_grower: "Fast grower", cyclical: "Cyclical", turnaround: "Turnaround", asset_play: "Asset play" };
function screenerTab(t) {
  const s1 = t.screener.stage1 || {}, s2 = t.screener.stage2;
  const list = (v) => (Array.isArray(v) ? v : String(v || "").split(/;\s*/)).filter(Boolean);
  const chips = (v, cls) => list(v).map((x) => `<span class="badge ${cls}">${esc(x)}</span>`).join(" ") || "<span class='na'>none</span>";
  const rows = [
    ["Piotroski F-score (0–9)", plain(s1.piotroski_f_score_ttm, 0)], ["Altman Z-score", plain(s1.altman_z_score_ttm, 1)],
    ["Return on equity (TradingView, %)", plain(s1.return_on_equity_fq, 1)], ["Price / book", mult(s1.price_book_fq)],
    ["Debt / equity", mult(s1.debt_to_equity)], ["Interest cover", mult(s1.interest_cover)], ["Net debt / EBITDA", mult(s1.net_debt_to_ebitda)],
    ["Revenue growth, median a year", pct(s1.revenue_growth_median)], ["EPS growth, median a year", pct(s1.eps_growth_median)],
    ["EPS against its 5-year peak", pct(s1.eps_vs_5y_peak, 0)], ["Big EPS drops in 10 years", plain(s1.eps_big_drops_10y, 0)],
    ["Years with a dividend, of 10", plain(s1.dividend_years_10y, 0)],
  ];
  let h = `<h2>Market screener, Stage 1</h2>${tiles([
    tile("Lynch category", esc(CATEGORY[s1.category] || s1.category || "—")),
    tile("Financial statements", s1.status ? `<span class="badge ${s1.status === "pass" ? "good" : "warn"}">${esc(s1.status)}</span>` : DASH),
    tile("Rules used", esc(s1.rule_set || "—")), tile("Run", esc(s1.run_date || "—")),
  ])}
  ${panel("Rules failed", chips(s1.failed, "warn"))}${panel("Data missing", chips(s1.missing, ""))}${panel("Flags", chips(s1.flags, ""))}
  ${panel("Inputs", `<div class="wrap"><table><tbody>${rows.map(([l, v]) => `<tr><td>${l}</td><td class="n">${v}</td></tr>`).join("")}</tbody></table></div>`)}`;
  if (s2) {
    h += `<h2>Stage 2: cheap or close to cheap</h2>${tiles([
      tile("Rank in its sector", `#${esc(s2.rank_in_sector)}`), tile("Cheap P/E", mult(s2.cheap_pe), esc(s2.cheap_basis || "")),
      tile("Cheap price", price(s2.cheap_price)), tile("P/E now", mult(s2.pe_now)), tile("Sector P/E", mult(s2.sector_pe)),
      tile("Trend", esc(s2.trend || "—")), tile("RSI", esc(s2.rsi_read || "—")), tile("TradingView rating", esc(s2.tv_rating || "—")),
      tile("EPS forecast, next fiscal year", price(s2.earnings_per_share_forecast_next_fy)),
    ])}${s2.why ? panel("Why", `<p>${esc(s2.why)}</p>`) : ""}`;
  } else {
    h += `<p class="note">Not among the Stage 2 top 3 of its sector in this run.</p>`;
  }
  return h + `<p class="note">How the screener works: <a href="screener.html">Screener page</a>. Rules: docs/SCREENER.md.</p>`;
}

// --- page -------------------------------------------------------------------------------
const TABS = [
  ["summary", "Summary", () => true],
  ["financials", "Financials", (t) => t.annual.years.length],
  ["ratios", "Ratios", (t) => t.annual.years.length],
  ["valuation", "Fair value", () => true],
  ["dividends", "Dividends", (t) => (t.dividends?.per_year || []).length],
  ["earnings", "Earnings", (t) => (t.earnings?.history || []).length || t.earnings?.next],
  ["charts", "Charts", (t) => t.annual.years.length],
  ["screener", "Screener", (t) => t.screener?.stage1],
];

// The day's change against the previous close, with its sign in words as well as colour.
function change(t) {
  const d = t.prices.daily;
  if (d.length < 2 || !ok(d[d.length - 1][1]) || !ok(d[d.length - 2][1])) return "";
  const now = d[d.length - 1][1], prev = d[d.length - 2][1], diff = now - prev;
  return `<span class="chg ${diff >= 0 ? "up" : "down"}">${diff >= 0 ? "+" : "−"}${Math.abs(diff).toFixed(2)} (${spct(diff / prev, 2)})</span>`;
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-cache" });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function picker(idx) {
  const dl = $("#tickers");
  if (dl && idx) dl.innerHTML = idx.tickers.map((x) => `<option value="${esc(x.symbol)}">${esc(x.name || "")}</option>`).join("");
}

function resolve(q, idx) {
  q = (q || "").trim();
  if (!q || !idx) return q.toUpperCase();
  const up = q.toUpperCase();
  if (idx.tickers.some((x) => x.symbol === up)) return up;
  const hit = idx.tickers.find((x) => (x.name || "").toUpperCase().includes(up));
  return hit ? hit.symbol : up;
}

async function main() {
  const root = $("#explorer");
  const params = new URLSearchParams(location.search);
  let idx = null;
  try { idx = await getJSON("tickers/index.json"); } catch { /* the page still works without it */ }
  picker(idx);
  const sym = resolve(params.get("s") || "NVDA", idx);
  if (sym !== params.get("s")) history.replaceState(null, "", `?s=${encodeURIComponent(sym)}${location.hash}`);
  let t;
  try { t = await getJSON(`tickers/${encodeURIComponent(sym)}.json`); } catch {
    root.innerHTML = `<h1>${esc(sym)}</h1><p class="sub">This ticker is not in the database. The explorer covers the companies the ingest job has filled in (the S&P 500). <a href="tickers.html">See every ticker</a>.</p>`;
    return;
  }
  document.title = `${t.symbol}: ${t.profile.name || ""}`;
  const p = t.profile;
  const tabs = TABS.filter(([, , has]) => has(t));
  const watch = p.watchlist ? ` · <a href="${esc(t.symbol)}.html">On the watch list: dated analyses</a>` : "";
  root.innerHTML = `<div class="xhead"><div><h1>${esc(p.name || t.symbol)} <span class="muted">${esc(t.symbol)}</span></h1>
    <p class="sub">${esc(p.sector || "")}${p.industry ? " · " + esc(p.industry) : ""}${p.exchange ? " · " + esc(p.exchange) : ""}${p.sp500_since ? " · S&amp;P 500" : ""}${watch}</p></div>
    <div class="xprice"><b>${price(t.snapshot.price)}</b>${change(t)}<small>close of ${esc(t.asof || "—")}</small></div></div>
    <div class="tabs" role="tablist">${tabs.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}">${l}</button>`).join("")}</div>
    <div id="tab"></div><p class="note">Data as of ${esc(t.asof || "—")}, rebuilt ${esc(t.built)} from the project database (SEC EDGAR, Yahoo, TradingView). Not investment advice.</p>`;
  let finMode = "A", chartMode = "A";
  const show = (k) => {
    if (!tabs.some(([x]) => x === k)) k = "summary";
    root.querySelectorAll("[data-tab]").forEach((b) => { b.classList.toggle("on", b.dataset.tab === k); b.setAttribute("aria-selected", b.dataset.tab === k); });
    const el = $("#tab");
    const render = {
      summary: () => summary(t, idx), financials: () => financials(t, finMode), charts: () => charts(t, chartMode),
      ratios: () => ratiosTab(t, idx), valuation: () => valuation(t, idx), dividends: () => dividendsTab(t), earnings: () => earningsTab(t), screener: () => screenerTab(t),
    }[k];
    el.innerHTML = render();
    el.querySelectorAll("[data-fin] button").forEach((b) => b.addEventListener("click", () => { finMode = b.dataset.m; show("financials"); }));
    el.querySelectorAll("[data-chart] button").forEach((b) => b.addEventListener("click", () => { chartMode = b.dataset.m; show("charts"); }));
    if (location.hash !== `#${k}`) history.replaceState(null, "", `#${k}`);
  };
  root.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));
  show(location.hash.slice(1) || "summary");
}

main();
