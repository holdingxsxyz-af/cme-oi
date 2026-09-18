#!/usr/bin/env python3
"""Raw positioning dump: weekly COT + daily CME open interest + settle + cross-currents.

Usage:
    python3 scripts/positions.py gold      # COMEX gold (GC)
    python3 scripts/positions.py silver    # COMEX silver (SI)
    python3 scripts/positions.py oil       # NYMEX WTI crude (CL)
    python3 scripts/positions.py           # default: gold

All sources are free and keyless:
  - COT     : CFTC Socrata (6dca-aqww.json, futures-only legacy)
  - daily OI: CME CmeWS (Akamai blocks plain clients; curl_cffi + impersonate="chrome")
  - settle  : Yahoo Finance chart API
  - spot    : api.gold-api.com / cross-current: ^TNX

Known traps (same list as SKILL.md):
  - COT: filtering by commodity_name alone can match an unrelated market -> filter by exchange name and take the row with the largest OI
  - CME: the `change` field does not always equal the day-over-day difference of `atClose` -> diff `atClose` yourself
  - CME: `atClose` arrives as a comma-formatted string -> strip before int()
  - COT publishes Friday 15:30 ET (Saturday 04:30 JST); a missing latest week is normal
  - The front month's OI collapses during contract roll -> read total OI, not the front month
"""
from __future__ import annotations

import datetime
import json
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}

PRODUCTS = {
    "gold": dict(sym="GC", pid=437, cot="GOLD", exch="COMMODITY EXCHANGE",
                 ref="gold.volume.html", yahoo="GC=F", spot="XAU", name="Gold"),
    "silver": dict(sym="SI", pid=458, cot="SILVER", exch="COMMODITY EXCHANGE",
                   ref="silver.volume.html", yahoo="SI=F", spot="XAG", name="Silver"),
    "oil": dict(sym="CL", pid=425, cot="CRUDE OIL", exch="NEW YORK MERCANTILE",
                ref="light-sweet-crude.volume.html", yahoo="CL=F", spot=None, name="WTI Crude"),
}
ALIASES = {"gold": "gold", "gc": "gold", "xau": "gold",
           "silver": "silver", "si": "silver", "xag": "silver",
           "oil": "oil", "wti": "oil", "crude": "oil", "cl": "oil"}


def num(s) -> int:
    return int(str(s).replace(",", "").strip() or 0)


def get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=timeout))


# ---------------- 1. weekly COT ----------------
def cot_weeks(p: dict, weeks: int = 7):
    d = datetime.date.today()
    while d.weekday() != 1:          # most recent Tuesday
        d -= datetime.timedelta(days=1)
    tues = [(d - datetime.timedelta(days=7 * i)).isoformat() for i in range(weeks)]
    out = []
    for dte in tues:
        q = urllib.parse.urlencode({
            "$where": (f'commodity_name="{p["cot"]}" AND '
                       f'market_and_exchange_names like "%{p["exch"]}%"'),
            "report_date_as_yyyy_mm_dd": dte, "$limit": "50"})
        try:
            g = get_json("https://publicreporting.cftc.gov/resource/6dca-aqww.json?" + q)
        except Exception as e:
            out.append((dte, None, None, None, f"err {e}"))
            continue
        if not g:
            out.append((dte, None, None, None, "not published"))
            continue
        r = max(g, key=lambda x: num(x.get("open_interest_all", 0)))
        out.append((dte, num(r["noncomm_positions_long_all"]),
                    num(r["noncomm_positions_short_all"]),
                    num(r["open_interest_all"]), r["market_and_exchange_names"]))
    return out


# ---------------- 2. daily CME open interest ----------------
def daily_oi(p: dict, days: int = 6):
    try:
        from curl_cffi import requests as creq
    except ImportError:
        print("  ! curl_cffi missing: python3 -m pip install curl_cffi")
        return []
    h = {"Accept": "application/json, text/plain, */*",
         "Referer": f"https://www.cmegroup.com/markets/metals/precious/{p['ref']}"
         if p["sym"] != "CL" else
         f"https://www.cmegroup.com/markets/energy/crude-oil/{p['ref']}",
         "Origin": "https://www.cmegroup.com"}
    dates, d = [], datetime.date.today()
    while len(dates) < days:
        if d.weekday() < 5:
            dates.append(d.strftime("%Y%m%d"))
        d -= datetime.timedelta(days=1)
    rows = []
    for dte in dates:
        url = (f"https://www.cmegroup.com/CmeWS/mvc/Volume/Details/F/{p['pid']}/{dte}/P"
               f"?tradeDate={dte}&pageSize=500")
        try:
            dd = creq.get(url, headers=h, impersonate="chrome", timeout=25).json()
        except Exception as e:
            rows.append((dte, None, None, f"err {e}"))
            continue
        t = dd.get("totals", {})
        ms = sorted((m for m in dd.get("monthData", []) if num(m.get("atClose")) > 0),
                    key=lambda m: -num(m["totalVolume"]))
        front = ms[0] if ms else {}
        rows.append((dte, num(t.get("atClose")) or None,
                     (front.get("month"), num(front.get("atClose")) if front else None), None))
    return list(reversed(rows))


# ---------------- 3. settles ----------------
def closes(p: dict):
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{p['yahoo']}?interval=1d&range=1mo"
    try:
        r = get_json(u, 25)["chart"]["result"][0]
    except Exception as e:
        print("  ! settle fetch failed:", e)
        return {}
    return {datetime.datetime.utcfromtimestamp(t).strftime("%Y%m%d"): c
            for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c}


def verdict(doi, dp):
    """OI change x price change -> the standard read."""
    if doi is None or dp is None:
        return ""
    if doi > 0 and dp > 0:
        return "New longs"
    if doi > 0 and dp < 0:
        return "New shorts"
    if doi < 0 and dp < 0:
        return "Long liquidation"
    if doi < 0 and dp > 0:
        return "Short covering"
    return "flat"


def main():
    key = ALIASES.get((sys.argv[1] if len(sys.argv) > 1 else "gold").lower(), "gold")
    p = PRODUCTS[key]
    print(f"=== {p['name']} ({p['sym']}) positioning dump "
          f"{datetime.datetime.now():%Y-%m-%d %H:%M} ===")

    print("\n[1] weekly COT  non-commercial (speculators), futures-only, COMEX full-size")
    prev = None
    for dte, lo, sh, oi, note in cot_weeks(p):
        if lo is None:
            print(f"  {dte}  {note}")
            continue
        dn = f"  w/w net {(lo - sh) - prev:+9,}" if prev is not None else ""
        print(f"  {dte}  L{lo:>8,} S{sh:>7,} net{lo - sh:>+9,}  OI {oi:>9,}{dn}")
        prev = lo - sh

    print("\n[2] daily CME OI (total / busiest month) and settle")
    cl = closes(p)
    doil = daily_oi(p)
    prev_oi = prev_dte = None
    for dte, oi, front, err in doil:
        if oi is None:
            print(f"  {dte}  {err if err else 'not published yet'}")
            continue
        dl = f"{oi - prev_oi:+7,d}" if prev_oi is not None else "      -"
        c = cl.get(dte)
        pc = cl.get(prev_dte) if prev_dte else None
        dc = f"{c - pc:+8.2f}" if (c and pc) else "       -"
        v = verdict(oi - prev_oi if prev_oi is not None else None, (c - pc) if (c and pc) else None)
        f = f" | front {front[0]} OI {front[1]:,}" if front else ""
        print(f"  {dte}  OI {oi:>8,} Δ{dl}  close {c:>9,.2f} Δ{dc}  {v}{f}")
        prev_oi, prev_dte = oi, dte

    print("\n[3] cross-currents")
    if p["spot"]:
        try:
            g = get_json(f"https://api.gold-api.com/price/{p['spot']}", 20)
            print(f"  {p['spot']} spot: {g.get('price')}")
        except Exception as e:
            print("  spot err", e)
    try:
        y = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?interval=1d&range=1mo", 20)
        print("  US10Y (^TNX):", y["chart"]["result"][0]["meta"].get("regularMarketPrice"))
    except Exception as e:
        print("  tnx err", e)


if __name__ == "__main__":
    main()
