// Live prices for every page of the site (issue #35). The hourly quotes (TradingView, 15-20
// minutes delayed) come from the web API's public GET /quotes; every value that depends on the
// price is recomputed here with the formulas of analysis/explore.py. Without the API a page
// keeps the close it was built with.
//
// The ticker page (explorer.js) calls Live.applyQuote on its company. The list pages built by
// analysis/site.py mark their cells and Live.updatePage fills them:
//   data-live="SYM key fmt"      one company's value from the index (price, market_cap, pe, ...)
//   data-live-med="SECTOR key fmt"  the median of a sector's companies ("*" = every company)
//   data-live-sum="SECTOR key"   the sum of a sector's companies (market value)
//   data-live-asof               replaced by when the prices were quoted
"use strict";
window.Live = (() => {
  const URL = "https://stock-api-bk.azurewebsites.net/quotes";
  const NY = "America/New_York";
  const ok = (v) => v !== null && v !== undefined && Number.isFinite(v);
  const posDiv = (a, b) => (ok(a) && ok(b) && a > 0 && b > 0 ? a / b : null);
  const sDiv = (a, b) => (ok(a) && ok(b) && b !== 0 ? a / b : null);

  let pending = null;
  // One request per page, however many callers ask. The free API plan can take a while to wake.
  function getQuotes() {
    if (pending) return pending;
    pending = (async () => {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 60000);
      try {
        const r = await fetch(URL, { signal: ctl.signal });
        if (!r.ok) return null;
        const body = await r.json();
        const at = body.columns || [];
        const col = (name) => at.indexOf(name);
        const quotes = {};
        for (const [sym, row] of Object.entries(body.quotes || {})) {
          quotes[sym] = {
            price: row[col("price")], change_pct: row[col("change_pct")], session: row[col("session")],
            at: row[col("price_at")], delay: col("delay_s") >= 0 ? row[col("delay_s")] : null,
            currency: col("currency") >= 0 ? row[col("currency")] : "USD",
          };
        }
        return { fetched_at: body.fetched_at, quotes };
      } catch { return null; } finally { clearTimeout(timer); }
    })();
    return pending;
  }

  // A company's price-dependent values at price p, from its snapshot (explore.py: snapshot, ratios).
  function reprice(s, p) {
    const cap = ok(s.shares_outstanding) && s.shares_outstanding > 0 ? p * s.shares_outstanding : null;
    const ev = ok(cap) && ok(s.net_debt) ? cap + s.net_debt : null;
    return {
      market_cap: cap, enterprise_value: ev,
      pe: posDiv(p, s.eps_diluted), ps: posDiv(cap, s.revenue), pb: posDiv(cap, s.equity),
      ev_ebitda: posDiv(ev, s.ebitda), ev_revenue: posDiv(ev, s.revenue),
      fcf_yield: sDiv(s.free_cf, cap), earnings_yield: sDiv(s.net_income, cap),
    };
  }

  // A quote applies when it is a positive price in the page's currency, no older than the close
  // the page was built on.
  function usable(q, asof, fetchedAt, currency = "USD") {
    if (!q || !ok(q.price) || q.price <= 0) return false;
    if ((q.currency || "USD") !== (currency || "USD")) return false;
    const day = fetchedAt ? new Date(`${fetchedAt}Z`).toLocaleDateString("en-CA", { timeZone: NY }) : "";
    return !asof || day >= asof;
  }

  function applyQuote(t, q, fetchedAt) {
    if (!usable(q, t.asof, fetchedAt, t.profile?.currency)) return false;
    const p = q.price, s = t.snapshot, x = reprice(s, p);
    t.close = { price: s.price, asof: t.asof };
    s.price = p;
    s.market_cap = x.market_cap;
    s.enterprise_value = x.enterprise_value;
    for (const k of ["pe", "ps", "pb", "ev_ebitda", "ev_revenue", "fcf_yield", "earnings_yield"]) t.ratios[k] = x[k];
    t.valuation.pe_now = x.pe;
    if (t.dividends && ok(t.dividends.ttm)) t.dividends.yield = sDiv(t.dividends.ttm, p);
    t.live = { ...q, fetched_at: fetchedAt };
    return true;
  }

  // The index has no share counts: scale its price-dependent values by the price change.
  function applyQuoteToRow(x, q, fetchedAt) {
    if (!usable(q, x.asof, fetchedAt) || !ok(x.price) || x.price <= 0) return false;
    const f = q.price / x.price;
    const ev0 = ok(x.market_cap) && ok(x.net_debt) ? x.market_cap + x.net_debt : null;
    const ebitda = ok(ev0) && ok(x.ev_ebitda) && x.ev_ebitda > 0 ? ev0 / x.ev_ebitda : null;
    if (ok(x.market_cap)) x.market_cap *= f;
    for (const k of ["pe", "ps", "pb"]) if (ok(x[k])) x[k] *= f;
    for (const k of ["fcf_yield", "div_yield"]) if (ok(x[k])) x[k] /= f;
    if (ok(ebitda)) x.ev_ebitda = posDiv(x.market_cap + x.net_debt, ebitda);
    x.price = q.price;
    return true;
  }

  const nyTime = (iso, withDay) => new Date(`${iso}Z`).toLocaleString("en-US", { timeZone: NY, hour: "numeric", minute: "2-digit", ...(withDay ? { month: "short", day: "numeric" } : {}) });

  // When a quote's price was traded, in words: TradingView's own delay for the listing (15
  // minutes for US exchanges, 20 for Tokyo); outside the session it is the latest close.
  function when(q, fetchedAt, long = false) {
    const lag = ok(q.delay) && q.delay > 0 ? `${Math.round(q.delay / 60)} min delayed, ` : "real time, ";
    if (q.session === "market" && q.at) return `${long ? lag : ""}${nyTime(q.at, true)} New York`;
    return long && fetchedAt ? `latest close, checked ${nyTime(fetchedAt, true)} New York` : "latest close";
  }

  // The same number formats as analysis/site.py (fmt_money and the fmt patterns).
  const DASH = "—";
  const FMT = {
    money: (v) => {
      if (!ok(v)) return DASH;
      const a = Math.abs(v), s = v < 0 ? "−" : "", d = a < 1e11 ? 1 : 0;
      if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(2)}T`;
      if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(d)}B`;
      if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(d)}M`;
      return `${s}$${a.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
    },
    price: (v) => (ok(v) ? `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : DASH),
    mult: (v) => (ok(v) ? `${v.toFixed(1)}x` : DASH),
    pct: (v) => (ok(v) ? `${(v * 100).toFixed(1)}%` : DASH),
  };
  const median = (xs) => {
    const v = xs.filter(ok).sort((a, b) => a - b);
    if (!v.length) return null;
    const m = Math.floor(v.length / 2);
    return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
  };

  function setCell(el, v, fmt) {
    if (!FMT[fmt]) return;
    el.textContent = FMT[fmt](v);
    if ("v" in el.dataset) el.dataset.v = ok(v) ? String(v) : "";
    el.classList.add("live");
  }

  // Fill the marked cells of a list page from the index, repriced with the latest quotes.
  async function updatePage(indexUrl = "tickers/index.json") {
    const marked = document.querySelectorAll("[data-live],[data-live-med],[data-live-sum],[data-live-asof]");
    if (!marked.length) return false;
    const [quotes, idx] = await Promise.all([
      getQuotes(), fetch(indexUrl, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    ]);
    if (!quotes || !idx) return false;
    const rows = idx.tickers || [];
    let n = 0;
    for (const x of rows) n += applyQuoteToRow(x, quotes.quotes[x.symbol], quotes.fetched_at) ? 1 : 0;
    if (!n) return false;
    const bySym = Object.fromEntries(rows.map((x) => [x.symbol, x]));
    const inSector = (s) => (s === "*" ? rows : rows.filter((x) => (x.sector || "Not classified") === s));
    document.querySelectorAll("[data-live]").forEach((el) => {
      const [sym, key, fmt] = el.dataset.live.split(" ");
      if (bySym[sym]) setCell(el, bySym[sym][key], fmt);
    });
    document.querySelectorAll("[data-live-med]").forEach((el) => {
      const parts = el.dataset.liveMed.split(" "), fmt = parts.pop(), key = parts.pop();
      setCell(el, median(inSector(parts.join(" ")).map((x) => x[key])), fmt);
    });
    document.querySelectorAll("[data-live-sum]").forEach((el) => {
      const parts = el.dataset.liveSum.split(" "), key = parts.pop();
      setCell(el, inSector(parts.join(" ")).reduce((a, x) => a + (ok(x[key]) ? x[key] : 0), 0), "money");
    });
    const any = Object.values(quotes.quotes).find((q) => q.session === "market") || Object.values(quotes.quotes)[0];
    document.querySelectorAll("[data-live-asof]").forEach((el) => {
      el.textContent = `Prices and the values that use them: ${when(any, quotes.fetched_at, true)} (TradingView, refreshed every hour on weekdays).`;
    });
    return true;
  }

  return { getQuotes, reprice, usable, applyQuote, applyQuoteToRow, when, median, updatePage };
})();

if (document.querySelector("[data-live],[data-live-med],[data-live-sum],[data-live-asof]")) Live.updatePage();
