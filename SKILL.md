---
name: cme-oi
description: Use when asked about gold, silver, or WTI open interest (OI), CFTC COT positioning, or who is long/short before a trade. Fetches free weekly COT + daily CME OI and prints a formatted report.
license: MIT
---

# cme-oi — COMEX/NYMEX positioning (COT + daily open interest)

Two free data systems, one answer:

| | **COT (weekly, CFTC)** | **CME open interest (daily)** |
|---|---|---|
| Frequency | Weekly — Tuesday close, published Friday 15:30 ET | Every day |
| Content | **Who** holds it (speculators / commercials / retail) and **which way** | Total open interest and volume, per contract month |
| Direction | Yes | No — OI has no direction label |
| Use | Confirm the large-spec **side** | Track **who is still in** day by day |

Both measure the same total open interest (~420k in gold for a large month) — split by **holder** weekly, by **month** daily.

## Requirements

```bash
python3 -m pip install curl_cffi
```

`curl_cffi` is the only external dependency. CME is behind Akamai Bot Manager: plain `urllib`/`requests`/`httpx` are 403'd (often with no error, just a timeout), so the CME calls impersonate Chrome's TLS. Everything else is standard library. No API keys.

If `curl_cffi` is missing, COT, prices and cross-currents still work; only the daily OI table is empty.

## Workflow — ask first, run once, show as-is

1. **Product** — infer from the user's words when obvious; otherwise ask with choices: gold (GC) / silver (SI) / WTI (CL). "All"/"everything" → all three.
2. **Period** — ask with choices: `1w` / `1m` / `3m`. Don't silently default; the period changes the answer. If the user gives a date, use `--from YYYY-MM-DD`.
3. **Run exactly one command.** Formatting belongs to the script:

```bash
python3 scripts/report.py <gold|silver|oil|all> --period <1w|1m|3m>
python3 scripts/report.py gold --from 2026-08-01
```

4. **Show the output as-is.** No re-rendering, no recomputation. Add at most 1–2 lines of interpretation afterwards.

Formats: `--format md` (default — headings, tables and rules that render in any markdown terminal), `json` (structured, for tooling), `text` (plain, for logs). Labels follow `--lang ja|en` (default `ja`); the numbers are language-neutral.

Match the user's language in whatever you say around the output.

## Products and IDs

| Product | Symbol | CFTC `commodity_name` | CME product ID | CME volume page |
|---|---|---|---|---|
| Gold | GC | `GOLD` | **437** | `gold.volume.html` |
| Silver | SI | `SILVER` | **458** | `silver.volume.html` |
| WTI crude | CL | `CRUDE OIL` | **425** | `crude-oil/light-sweet-crude.volume.html` |

If a product ID ever changes, open the volume page in a browser and watch `Volume/LastTotals/<id>`. The table above is current.

## Data sources

**1. Weekly COT — CFTC Socrata** (`6dca-aqww.json`, futures-only legacy):

```
https://publicreporting.cftc.gov/resource/6dca-aqww.json
  ?$where=commodity_name="GOLD" AND market_and_exchange_names like "%COMMODITY EXCHANGE%"
  &report_date_as_yyyy_mm_dd=2026-09-08&$limit=50
```

Traps:
- Filter by **exchange name**, not just `commodity_name` — some weeks the commodity name alone matches a small, unrelated market. Take the row with the largest open interest.
- Exclude `MICRO` contracts if you only want the full-size market.
- `report_date_as_yyyy_mm_dd` must be a **Tuesday**. Ordering by date with a limit returns only one date's worth of markets, so pull each week explicitly.
- A missing latest week returns an empty array. That is normal: publication is Friday 15:30 ET (Saturday 04:30 JST).

**2. Daily CME volume and open interest** (needs `curl_cffi`):

```
https://www.cmegroup.com/CmeWS/mvc/Volume/Details/F/<productId>/<YYYYMMDD>/P?tradeDate=<YYYYMMDD>&pageSize=500
```

```python
from curl_cffi import requests as creq
r = creq.get(url, headers={
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cmegroup.com/markets/metals/precious/gold.volume.html",
    "Origin": "https://www.cmegroup.com",
}, impersonate="chrome", timeout=25)
d = r.json()          # totals.atClose = OI, totals.totalVolume, monthData[] = per month
```

Traps:
- `totals.change` and `monthData[].change` do **not** always equal the day-over-day difference of `atClose`. Fetch several days and diff yourself.
- `atClose` arrives as a comma-formatted string (`"43,015"`) — strip before `int()`.
- The front month's OI collapses during contract roll (WTI's October went 177,992 → 86,712 in one day). Use **total** OI for the OI×price read; use the front month only to see which contract is the battleground.
- Set the `Referer` to match the product.

**3. Daily high/low/close** — Yahoo Finance chart API (`GC=F`, `SI=F`, `CL=F`, `interval=1d`).

**4. Cross-currents** — `api.gold-api.com/price/XAU|XAG` for spot, `^TNX` on Yahoo for the US 10-year.

CME's daily OI for a session lands after that session's close. Line the close up with the same day's OI before reading anything into it.

## Reading it: OI × price

OI tells you how many are in, not which way. Pair the OI change with the price change:

| OI | Price | Likely read |
|---|---|---|
| down | down | **Long liquidation** — positions closed, often forced. The cleanest signal |
| up | up | New longs coming in |
| up | down | New shorts coming in |
| down | up | Short covering |

Then put the COT net next to it for direction and size: net long plus rising OI is crowd; net long falling while price holds is absorption.

## Limits

- A large net long is not a bullish guarantee — it is also the fuel for a reversal. Read it as "buying pressure is strong", nothing more.
- COT covers through Tuesday only. Anything from Wednesday on shows up in the daily OI, not in the COT.
- Daily OI never says *who*. Only the COT splits holder types.
- Positioning is context, not a trigger. Combine it with the chart.

## Files

- `scripts/report.py` — CLI, default markdown report, `--format json|text`
- `scripts/positions.py` — raw data dump, used for verification
