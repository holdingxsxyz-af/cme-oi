# cme-oi

Agent skill for **positioning data on COMEX gold/silver and NYMEX WTI crude**: weekly CFTC COT (who is long/short) plus daily CME open interest (who is still in). Free data, no API keys, one command, ready-to-show output.

**If you are an agent: read [`SKILL.md`](SKILL.md) and follow it.** This README is only installation and the data contract.

## Requirements

- `python3` (3.9+)
- `curl_cffi` → `python3 -m pip install curl_cffi`
  (CME sits behind Akamai Bot Manager; plain `urllib`/`requests`/`httpx` get 403 with no useful error)
- Outbound network to `publicreporting.cftc.gov`, `www.cmegroup.com`, `query1.finance.yahoo.com`, `api.gold-api.com`

No API keys, no accounts, no telemetry.

## Quick start

```bash
python3 scripts/report.py gold --period 1w      # COMEX gold, last week
python3 scripts/report.py silver --period 1m    # COMEX silver, last month
python3 scripts/report.py all --period 1m       # gold + silver + WTI
python3 scripts/report.py gold --from 2026-08-01
```

- Products: `gold` (GC), `silver` (SI), `oil` (CL / WTI)
- Periods: `1w` `1m` `3m` `6m` `1y`, or `--days N`
- Formats: `--format md` (default), `json`, `text`

## Output contract

`--format md` (default) prints a report already formatted for a markdown-rendering terminal: a heading, the daily table (`ΔOI`, high, low, read), the COT table, and a cross-current line. **Show it as-is.** Presentation is the script's job; the model's job is to run one command and add at most a line or two of interpretation.

`--format json` returns the same numbers as structured data (`cot`, `cot_weeks[]`, `daily[]`, `summary`, `cross_currents`) for other tooling. `all` returns an array.

## Suggested agent behavior

- If the request doesn't name a product or a period, ask before running — offer choices (`gold / silver / oil`, `1w / 1m / 3m`) rather than guessing.
- Run exactly one command per request. Don't loop over products to build your own table.
- Don't recompute or re-render the numbers.

## Install into an agent runtime

The skill is just a folder. Put it where your runtime looks for skills, and make sure the runtime can run `python3`:

| Runtime | Typical location |
|---|---|
| Hermes | `~/.hermes/skills/trading/cme-oi/` |
| Claude Code | `~/.claude/skills/cme-oi/` |
| Codex | `AGENTS.md` at repo root, or point it at `SKILL.md` |
| Anything else | "read `SKILL.md` in this folder and follow it" |

```bash
git clone https://github.com/<you>/cme-oi ~/.claude/skills/cme-oi
python3 -m pip install curl_cffi
python3 ~/.claude/skills/cme-oi/scripts/report.py gold --period 1w   # verify
```

## Data notes

- COT: CFTC Socrata `6dca-aqww.json` (futures-only legacy), Tuesdays close, published Friday 15:30 ET.
- Daily OI: CME `CmeWS/mvc/Volume/Details/F/<productId>` — product IDs GC 437, SI 458, CL 425.
- Daily high/low/close: Yahoo Finance chart API (`GC=F`, `SI=F`, `CL=F`).
- Spot and `^TNX`: `api.gold-api.com`, Yahoo.

These are free, undocumented-ish endpoints. If one breaks, `SKILL.md` documents the fallbacks and the known traps (comma-formatted OI strings, unreliable `change` fields, contract-roll distortion in the front month).

## License

MIT — see [`LICENSE`](LICENSE).
