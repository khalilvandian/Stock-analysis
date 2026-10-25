# Setting up a Claude workspace for this project

This project is designed to run in **Claude Code on the web** (claude.ai/code). Each session is a fresh cloud container that clones this repository. The repository, its `CLAUDE.md`, the reports and the saved data are what carry the work from one session to the next.

## 1. Repository

- GitHub: `khalilvandian/Stock-analysis`.
- The default branch is currently `claude/api-access-test-2fn7y1`, which is the only branch. New sessions start from it, so they already have everything.
- Optional tidy-up: rename it to `main` on GitHub (Settings → Branches), then start new sessions from `main`.

## 2. Cloud environment

Use the existing **Market analysis** environment, or create a new one. To edit it, open the cloud environment menu in the session's title bar and choose **Edit**.

### Environment variables

Add these as environment variables (or under *Network secrets*, where that section is offered):

```
SEC_USER_AGENT=stock-analysis <your contact email>
FMP_API_KEY=<a new FMP key>
```

- `SEC_USER_AGENT` is recommended. The SEC asks automated clients to identify themselves. Without it, the code sends a generic name.
- `FMP_API_KEY` is optional; the analysis runs without it. **Generate a new key** in your FMP account: the key pasted into the original chat is exposed.
- Never paste keys into the chat or commit them.

### Network access

The analysis needs these hosts:

```
query1.finance.yahoo.com
query2.finance.yahoo.com
fc.yahoo.com
www.sec.gov
data.sec.gov
financialmodelingprep.com
pypi.org
files.pythonhosted.org
```

If the environment uses a limited network level, add them under **Allowed domains** and keep **Allow package managers** ticked, or choose a broader level.

Steps: https://code.claude.com/docs/en/cloud-environments#network-access

### Setup script

No setup script is needed. The repository's SessionStart hook (`.claude/hooks/session-start.sh`) runs `uv sync` when a cloud session starts.

## 3. Starting a session

1. Go to claude.ai/code and start a new session.
2. Pick the repository `khalilvandian/Stock-analysis` and the **Market analysis** environment.
3. Claude reads `CLAUDE.md` automatically.

A good first message:

> Read README.md, CLAUDE.md and reports/README.md. Refresh the data (sector.py, then history.py), rebuild the three dashboards, and tell me what changed since the last reports.

Refreshing the data takes about 2 minutes. The first SEC download is about 250 MB, cached in `.cache/sec/`.

## 4. A Claude chat Project (optional)

A Project in the Claude chat app is useful for discussion, and for keeping the reports at hand as reference. It cannot run the scripts or refresh data; use Claude Code sessions for that.

1. Create a project named "Stock Analysis".
2. Add as project knowledge:
   - `README.md`
   - `CLAUDE.md`
   - `reports/README.md` and the reports you want
   - `config/absolute_values.toml`

   Add them via the GitHub integration if it's available, or by uploading the files.
3. Paste these project instructions:

> This project analyses listed companies, starting with the US utilities sector, using the code in github.com/khalilvandian/Stock-analysis. Always start with absolute values and their history (price, market value, DCF fair value, debt total/net/short/long, cash, revenue, EBITDA, net income, EPS, operating cash flow, capex, free cash flow) before ratios, scores or summaries. Prefer medians over averages for growth. Weight debt health most (cash vs short-term debt, cash vs long-term debt, net debt/EBITDA, interest cover), then profitability and cash, then cheapness. State the data date and the caveats. Nothing is investment advice.

## 5. Connected tools

- **GitHub:** must stay connected so sessions can push. If a push is refused, reconnect at https://claude.ai/connect-github.
- **Web search:** built into Claude. It's used for company guidance and deal research.
- **Artifacts:** used to publish the dashboards. Republishing an existing page keeps its link only when done from the session that published it, or by passing the page's URL.

## 6. Security notes

- The FMP key pasted into the original chat should be replaced (see section 2).
- An early commit of `analysis/history.py` included the owner's email address as the SEC contact. The current code reads it from `SEC_USER_AGENT` instead, but the old value remains in git history. Rewriting history can remove it if needed.
