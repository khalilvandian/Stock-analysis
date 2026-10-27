# Operations

How to run and change things day to day, what to do when something breaks, and the test
policy. The step-by-step processes are in [`PROCESSES.md`](PROCESSES.md).

## Running things

| Task | Command |
|---|---|
| Install or update the environment | `uv sync` |
| Everything the evening run builds | `uv run python analysis/watchlist.py` |
| Key numbers only, nothing written | `uv run python analysis/watchlist.py --numbers` |
| Market screener | `uv run python analysis/screener.py` |
| Market report alone | `uv run python analysis/market.py` |
| Check the latest outputs (no network) | `uv run python analysis/validate.py [--verbose] [--strict]` |
| Build the site locally | `python analysis/site.py _site` |
| Send the last run's email | `uv run python analysis/send_email.py` |
| Refresh the utilities data | `uv run python analysis/sector.py && uv run python analysis/history.py` |
| Rebuild the dashboards | `uv run python dashboard/build_absolute.py && uv run python dashboard/build_sector.py && uv run python dashboard/build.py` |
| Regenerate the metrics doc | `uv run python -m stock_analysis.metrics doc` |
| Pre-commit check | `uv run ruff check . && uv run ruff format --check . && uv run pytest` |

### Caches

Delete a cache to force fresh downloads; nothing in it is needed to rebuild.

| Cache | Lifetime | Clear it when |
|---|---|---|
| `.cache/screener/tradingview_*_<date>.pkl`, `yahoo_fill_<date>.pkl`, `prices_<date>.pkl` | One day (new date, new file) | A rerun the same day must see new data: use `--refresh` |
| `.cache/screener/stage1_full.pkl` | Until the next Stage 1 run | Stage 2 complains about missing columns: rerun Stage 1 |
| `.cache/sec/<SYMBOL>.json` | `history.py`: until `--refresh`; watch list: 1 day | A new 10-K is out and `history.py` should see it |
| `.cache/watchlist/email.html`, `last_run.json` | Until the next run | Never needed by hand |

### Where to change things

| To change | Edit | Then |
|---|---|---|
| A watch-list stock, peer group, target P/E or EPS correction | `config/watchlist.toml` | `uv run pytest tests/test_watchlist.py` |
| Claude's verdict, summary, risks, news | `analyses/<SYMBOL>/notes.md`, `analyses/market/notes.md`, `analyses/summaries/notes.md` | Next run copies them into the PDFs and the site |
| A screener threshold, rule set, category test or universe | `config/screeners.toml` | `PROCESSES.md` section 12 |
| The absolute values list | `config/absolute_values.toml` | `PROCESSES.md` section 13 |
| A metric | `config/metrics.toml` | Regenerate `docs/METRICS.md` |
| The S&P 500 list for market breadth | `config/market_universe.csv` (`symbol,name,sector,industry`, Yahoo tickers such as `BRK-B`) | Refresh by hand from Wikipedia's "List of S&P 500 companies" |
| The evening steps | `docs/EVENING_RUN.md` | The scheduled session reads it every evening |
| Run time | The scheduled task in Claude Code (not in the repository); `timezone` in `config/watchlist.toml` for file names | |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| FMP returns HTTP 402 "not available under your current subscription" | The free plan covers few symbols | Nothing to fix: no analysis uses FMP. Use Yahoo, SEC or TradingView |
| FMP returns 401 or "Invalid API KEY" | The key in `FMP_API_KEY` is invalid (the current one is) | Only needed if FMP is ever used: generate a new key in the FMP account and set it in the cloud environment, never in the repository |
| `RuntimeError: FMP_API_KEY is not set` | `FMPClient` created without a key | Set `FMP_API_KEY`, or don't use `FMPClient` |
| Yahoo: `401 Invalid Crumb`, `Unauthorized`, empty frames, or "No price data" | yfinance's cookie and crumb handshake failed, or Yahoo changed its interface | Make sure `fc.yahoo.com`, `query1` and `query2.finance.yahoo.com` are allowed; retry; update yfinance (`uv lock --upgrade-package yfinance && uv sync`) and run the tests |
| Yahoo: `Too Many Requests` or `YFRateLimitError` | Heavy use (the screener's gap filling, many tickers) | Wait and rerun; the day caches mean finished work isn't downloaded again. `watchlist.fetch_row` already retries a missing price four times |
| SEC: HTTP 403 | No or generic `User-Agent`; SEC blocks unidentified automated clients | Set `SEC_USER_AGENT` to `<project name> <contact>` in the cloud environment (never commit the contact) |
| SEC: slow first run, about 250 MB | First download of company facts for every utility | Normal; cached in `.cache/sec/` |
| SEC: market value 25x too low after a split | Share counts filed before a split | `history.split_adjust` and `watchlist.split_adjust` rescale shares and EPS; check the split is in Yahoo's `splits` |
| TradingView: HTTP 400, or a column of blanks | The unofficial endpoint renamed or dropped a field | Find the field on tradingview.com/screener, update `stage1.COLUMNS` (and `stage2.NEEDS`, `screen_common.USD_FIELDS`, `config/metrics.toml` sources if used there), run `uv run pytest tests/test_screener.py` |
| TradingView: far fewer companies than expected | Index code or filters changed, or one market failed | Check `[universe]` in `config/screeners.toml`; rerun with `--refresh` |
| Stage 2: "Stage 1 output lacks [...]" | Stage 1's pickle is from an older Stage 1 | `uv run python analysis/stage1.py` |
| `validate.py` reports FAIL | An output is broken (a missing PDF, an inconsistent screener row, a broken identity) | Read the check's detail (`--verbose` for WARN rows), fix the cause, rebuild; if it can't be fixed tonight, say so in the email |
| Market report says the screener's data is not from today | The screener failed in the evening run; the report used the last results | Read the run's output for the error; rerun `uv run python analysis/screener.py`, then `uv run python analysis/watchlist.py --no-screener` if the PDFs must be rebuilt |
| `RuntimeError: No Chrome or Chromium found` | No browser for the PDFs | Set `CHROME_PATH`, or install Chromium |
| Brevo: 401 "Key not found" or "unauthorized" | Wrong or missing `BREVO_API_KEY` | Check the key in the cloud environment settings |
| Brevo: 401 "unrecognised IP address" | Brevo's "authorized IPs" blocking; the cloud environment's IP changes | In Brevo, Security, Authorized IPs: turn the blocking off |
| Brevo: 400 about the sender | `WATCHLIST_EMAIL_FROM` is not a verified sender | Verify the sender in Brevo, or fix the setting (`Name <address>`) |
| `No recipient: set WATCHLIST_EMAIL_TO or pass --to` | Recipient setting missing | Set `WATCHLIST_EMAIL_TO` in the cloud environment |
| Email links go to GitHub, not the site | `WATCHLIST_BRANCH` is set to a branch other than `main` | Unset it for evening runs on `main` |
| Pages workflow fails at deploy, or the site is not updated | Pages is not set to deploy from Actions, or the push didn't touch the workflow's paths | GitHub, Settings, Pages, Build and deployment, Source: **GitHub Actions** (one time). Run the workflow by hand from the Actions tab |
| `uv sync` or downloads fail with "certificate verify failed" | A TLS-inspecting proxy in the cloud environment | Use the system trust store: `UV_SYSTEM_CERTS=true` (older uv: `UV_NATIVE_TLS=true`, now deprecated), or point `SSL_CERT_FILE` (and `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE` for requests and yfinance's curl backend) at the proxy's CA bundle. Never turn verification off |
| `git push` refused | The GitHub connection lapsed | Reconnect GitHub for Claude (see `SETUP.md`, section 5) |

## Test policy

- **Tests never hit the network.** HTTP made with `httpx` is mocked with `respx`
  (`tests/test_fmp.py`, the TradingView and ECB tests in `tests/test_screener.py`).
  Code that calls `yfinance` or SEC is tested on small hand-made frames, not live calls.
- **Tests guard the contracts between parts:** configured absolute values exist in the
  saved data (`test_absolute.py`); every metric is complete and `docs/METRICS.md` is up to
  date (`test_metrics.py`); every configured screener rule is known and Stage 2 refuses
  Stage 1 output without its columns (`test_screener.py`); the watch list has what each
  stock needs and dated PDFs are never overwritten (`test_watchlist.py`); missing values,
  splits, currencies and cross-checks between sources (`test_pipeline_units.py`, on saved
  responses in `tests/fixtures/`).
- A known bug can be pinned with `pytest.mark.xfail(strict=True)` and a reason saying what is
  wrong; when the bug is fixed the test starts passing, fails as "XPASS", and the mark must
  be removed.
- `test_absolute.py` reads the committed `data/sector/` files, so keep them in the
  repository.
- A new feature gets a test in the same style: a small frame in, the expected frame out.

**Before every commit:**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Ruff settings are in `pyproject.toml` (line length 100, Python 3.11, rules E, F, I, UP, B).
To fix formatting: `uv run ruff format .`.

## Secrets

The repository is public. Never write an API key, a token or an email address into code,
docs, notes, reports or commit messages. Refer to the variables by name: `FMP_API_KEY`,
`SEC_USER_AGENT`, `BREVO_API_KEY`, `WATCHLIST_EMAIL_FROM`, `WATCHLIST_EMAIL_TO`. Set them in
the cloud environment's settings, or in a local `.env` (ignored by git, template in
`.env.example`).
