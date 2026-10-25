# Constellation Energy (CEG): overview

*Data as of 2026-09-25 close (Yahoo Finance). Written 2026-09-27.*

## Absolute values (latest 12 months, US$)

| Value | Amount |
|---|---|
| Share price | $263.27 |
| Market value | $93.3bn |
| Revenue | $31.3bn |
| EBITDA | $8.23bn |
| Net income | $3.46bn |
| EPS (12m) / forward EPS | $10.24 / $13.32 |
| Operating cash flow | $4.21bn |
| Capex | −$3.90bn |
| Free cash flow | $0.31bn |
| Total debt / short-term / long-term | $24.7bn / $5.59bn / $19.1bn |
| Cash | $0.70bn |

## History

| | FY2021 | FY2022 | FY2023 | FY2024 | FY2025 |
|---|---|---|---|---|---|
| Revenue | $19.7bn | $24.4bn | $24.9bn | $23.6bn | $25.5bn |
| Net income | −$0.2bn | −$0.2bn | $1.6bn | $3.7bn | $2.3bn |
| Diluted EPS | – | −$0.49 | $5.01 | $11.89 | $7.40 |
| Total debt | $7.9bn | $5.8bn | $9.3bn | $8.4bn | $9.0bn |
| Cash | $0.5bn | $0.4bn | $0.4bn | $3.0bn | $3.6bn |
| Free cash flow | −$2.7bn | −$4.0bn | −$7.7bn | −$5.0bn | $1.3bn |

## Business

- **Description:** US power producer and retailer. It has about 31.7 GW of its own capacity across nuclear, wind, solar, gas and hydro, and about 55 GW including Calpine. It reports five regional segments (Mid-Atlantic, Midwest, New York, ERCOT, Other) and has about 15,300 employees. It was spun off from Exelon in early 2022.
- **Core asset:** the largest US nuclear fleet, which produces carbon-free power around the clock.
- **Growth drivers:**
  - Long-term contracts with data-center and big-tech customers: Microsoft (the Crane / Three Mile Island Unit 1 restart, 835 MW, 2027), Meta (Clinton) and Walmart.
  - Nuclear uprates and licence extensions.
- **Calpine (closed 2026-01-07):** adds the largest US gas fleet and geothermal plants (The Geysers), with a strong position in Texas and California.

## Caveats

- Operating cash flow was negative in 2021–2024 because CEG books collections on receivables it has sold under *investing* rather than *operating* cash flow. Free cash flow history therefore understates its cash generation.
- The 2021 annual statements are incomplete, because CEG was spun off from Exelon in early 2022.

Reproduce: `uv run python analysis/absolute.py --history CEG`, `uv run python analysis/debt.py CEG`.
