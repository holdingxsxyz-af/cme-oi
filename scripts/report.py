#!/usr/bin/env python3
"""Positioning data collector + report renderer for the cme-oi skill.

Usage:
    python3 scripts/report.py gold --period 1w              # default: markdown, show as-is
    python3 scripts/report.py all --period 1m                # gold + silver + WTI
    python3 scripts/report.py gold --from 2026-08-01         # date-bounded period
    python3 scripts/report.py gold --period 1w --format json # raw data for tooling

period: 1w=7 sessions / 1m=22 / 3m=66 / 6m=132 / 1y=260 (COT weeks are derived)

Labels are English (the neutral base for code). Do not pin a display language:
match whoever you are talking to in your own words around the output.
Data sources are the same as positions.py (all free, no API keys).
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from positions import ALIASES, PRODUCTS, cot_weeks, daily_oi, get_json, verdict  # noqa: E402

PERIODS = {"1w": 7, "1m": 22, "3m": 66, "6m": 132, "1y": 260}


def iso(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def ohlc(p: dict) -> dict:
    """Daily high/low/settle -> {YYYYMMDD: {'h','l','c'}}"""
    u = f"https://query1.finance.yahoo.com/v8/finance/chart/{p['yahoo']}?interval=1d&range=1mo"
    try:
        r = get_json(u, 25)["chart"]["result"][0]
    except Exception:
        return {}
    q = r["indicators"]["quote"][0]
    out = {}
    for t, h, l, c in zip(r["timestamp"], q["high"], q["low"], q["close"]):
        d = datetime.datetime.utcfromtimestamp(t).strftime("%Y%m%d")
        if c is not None:
            out[d] = {"h": h, "l": l, "c": c}
    return out


def collect(key: str, days: int, weeks: int, since: str | None = None) -> dict:
    p = PRODUCTS[key]
    bars = ohlc(p)
    cl = {d: v["c"] for d, v in bars.items()}
    rows = [r for r in daily_oi(p, days) if (not since or r[0] >= since.replace("-", ""))]
    cots = sorted([r for r in cot_weeks(p, weeks) if r[1] is not None], key=lambda r: r[0])
    if since:
        cots = [c for c in cots if c[0].replace("-", "") >= since.replace("-", "")]

    daily, counts = [], {}
    prev_oi = prev_dte = None
    for dte, oi, front, err in rows:
        if oi is None:
            daily.append({"date": iso(dte), "oi": None, "doi": None, "close": None,
                          "dprice": None, "read": None,
                          "note": err or "not published"})
            continue
        doi = oi - prev_oi if prev_oi is not None else None
        c = cl.get(dte)
        pc = cl.get(prev_dte) if prev_dte else None
        dp = (c - pc) if (c is not None and pc is not None) else None
        v = verdict(doi, dp)
        if v:
            counts[v] = counts.get(v, 0) + 1
        bar = bars.get(dte, {})
        daily.append({"date": iso(dte), "oi": oi, "doi": doi, "close": c, "dprice": dp,
                      "high": bar.get("h"), "low": bar.get("l"),
                      "read": v or None,
                      "front_month": front[0] if front else None,
                      "front_oi": front[1] if front else None})
        prev_oi, prev_dte = oi, dte

    cot = None
    if cots:
        dte, lo, sh, oi, _ = cots[-1]
        net = lo - sh
        pk = max(cots, key=lambda r: r[1] - r[2])
        cot = {
            "latest_date": dte, "long": lo, "short": sh, "net": net,
            "wow_change": (net - (cots[-2][1] - cots[-2][2])) if len(cots) > 1 else None,
            "period_change": net - (cots[0][1] - cots[0][2]),
            "period_start": {"date": cots[0][0], "net": cots[0][1] - cots[0][2]},
            "peak": {"date": pk[0], "net": pk[1] - pk[2]},
            "drawdown_from_peak": net - (pk[1] - pk[2]),
            "total_oi": oi, "weeks": len(cots),
        }

    cot_weeks_detail = []
    for i, (dte, lo, sh, oi, _) in enumerate(cots):
        net = lo - sh
        cot_weeks_detail.append({
            "date": dte, "long": lo, "short": sh, "net": net,
            "wow": (net - (cots[i - 1][1] - cots[i - 1][2])) if i > 0 else None,
            "total_oi": oi})

    valid = [r for r in daily if r["oi"] is not None]
    px = [r for r in valid if r["close"]]
    summary = {
        "oi": ({"from": valid[0]["oi"], "to": valid[-1]["oi"],
                "change": valid[-1]["oi"] - valid[0]["oi"]} if len(valid) >= 2 else None),
        "price": ({"from": px[0]["close"], "to": px[-1]["close"],
                   "change": px[-1]["close"] - px[0]["close"]} if len(px) >= 2 else None),
        "cot_net": ({"from": cot["period_start"]["net"], "to": cot["net"],
                     "change": cot["period_change"]} if cot else None),
        "read_counts": counts,
    }

    cross = {}
    if p["spot"]:
        try:
            cross[p["spot"]] = get_json(f"https://api.gold-api.com/price/{p['spot']}", 20).get("price")
        except Exception:
            pass
    try:
        cross["US10Y"] = get_json("https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX"
                                  "?interval=1d&range=1mo", 20)["chart"]["result"][0]["meta"].get("regularMarketPrice")
    except Exception:
        pass

    return {
        "product": p["name"], "symbol": p["sym"], "as_of": datetime.datetime.now().isoformat(timespec="minutes"),
        "daily_period": {"from": valid[0]["date"], "to": valid[-1]["date"],
                         "business_days": len(valid)} if valid else None,
        "cot_period": {"from": cots[0][0], "to": cots[-1][0], "weeks": len(cots)} if cots else None,
        "cot": cot, "cot_weeks": cot_weeks_detail, "daily": daily,
        "summary": summary, "cross_currents": cross,
    }


def min_text(d: dict) -> str:
    """Plain text (no rules, no padding) for logs."""
    o = [f"{d['product']} ({d['symbol']})  {d['as_of']}"]
    if d["cot"]:
        c = d["cot"]
        o.append(f"spec net {c['net']:+,} (w/w {c['wow_change']:+,}, period {c['period_change']:+,}, "
                 f"from {c['peak']['date']} peak {c['drawdown_from_peak']:+,})")
    for r in d["daily"]:
        if r["oi"] is None:
            o.append(f"{r['date']}  —  {r['note']}")
        else:
            o.append(f"{r['date']}  OI {r['oi']:,}"
                     + (f" ({r['doi']:+,})" if r["doi"] is not None else "")
                     + (f"  close {r['close']:,.2f}" if r["close"] else "")
                     + (f" ({r['dprice']:+.2f})" if r["dprice"] is not None else "")
                     + (f"  {r['read']}" if r["read"] else ""))
    s = d["summary"]
    if s["oi"]:
        o.append(f"period: OI {s['oi']['change']:+,}"
                 + (f" / COT net {s['cot_net']['change']:+,}" if s["cot_net"] else "")
                 + (f" / price {s['price']['change']:+,.2f}" if s["price"] else ""))
    if d["cross_currents"]:
        o.append(" / ".join(f"{k} {v}" for k, v in d["cross_currents"].items()))
    return "\n".join(o)


def md_report(d: dict) -> str:
    """Markdown that renders well in terminals (headings, tables, rules, bold). Data first."""
    o = [f"## {d['product']} ({d['symbol']})"]
    s = d["summary"]
    line = []
    if s["oi"]:
        line.append(f"OI {s['oi']['from']:,} → {s['oi']['to']:,} ({s['oi']['change']:+,})")
    if s["price"]:
        line.append(f"Settle {s['price']['from']:,.2f} → {s['price']['to']:,.2f} ({s['price']['change']:+,.2f})")
    if line:
        o.append(" · ".join(line))
    o.append("")

    o.append("| Date | ΔOI | High | Low | Read |")
    o.append("|---|---:|---:|---:|---|")
    for r in d["daily"]:
        h = f"{r['high']:,.2f}" if r.get("high") else "—"
        l = f"{r['low']:,.2f}" if r.get("low") else "—"
        if r["oi"] is None:
            o.append(f"| {r['date'][5:]} | — | {h} | {l} | {r['note']} |")
        else:
            doi = f"{r['doi']:+,}" if r["doi"] is not None else "—"
            o.append(f"| {r['date'][5:]} | {doi} | {h} | {l} | {r['read'] or ''} |")
    o.append("")

    if d["cot"]:
        c = d["cot"]
        o.append("**COT (speculator net)**")
        o.append("")
        o.append("| Week | Long | Short | Net | w/w |")
        o.append("|---|---:|---:|---:|---:|")
        for w in d.get("cot_weeks", []):
            wow = f"{w['wow']:+,}" if w["wow"] is not None else "—"
            o.append(f"| {w['date'][5:]} | {w['long']:,} | {w['short']:,} | {w['net']:+,} | {wow} |")
        o.append("")
        note = [f"Latest {c['latest_date'][5:]} **{c['net']:+,}**"]
        if c["wow_change"] is not None:
            note.append(f"w/w {c['wow_change']:+,}")
        if c["drawdown_from_peak"]:
            note.append(f"**{c['drawdown_from_peak']:+,}** from the {c['peak']['date'][5:]} peak")
        if c["total_oi"]:
            note.append(f"OI {c['total_oi']:,}")
        o.append(" · ".join(note))
        o.append("")

    if d["cross_currents"]:
        o.append("---")
        o.append(" · ".join(f"{k} {v:,.2f}" if isinstance(v, (int, float)) else f"{k} {v}"
                            for k, v in d["cross_currents"].items()))
    return "\n".join(o)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("product", nargs="?", default="gold")
    ap.add_argument("--period", default=None, choices=list(PERIODS))
    ap.add_argument("--days", type=int, default=None)
    ap.add_argument("--weeks", type=int, default=None)
    ap.add_argument("--from", dest="since", default=None, help="YYYY-MM-DD")
    ap.add_argument("--format", default="md", choices=["md", "json", "text"])
    a = ap.parse_args()
    keys = list(PRODUCTS) if a.product.lower() in ("all", "*") else \
        [ALIASES.get(a.product.lower(), "gold")]
    days = a.days or PERIODS.get(a.period or "1m", 22)
    if a.since:
        span = (datetime.date.today() - datetime.date.fromisoformat(a.since)).days
        days = max(days, int(span * 5 / 7) + 3)
    weeks = a.weeks or max(4, round(days / 5) + 1)

    data = [collect(k, days, weeks, a.since) for k in keys]
    if a.format == "json":
        print(json.dumps(data if len(data) > 1 else data[0], ensure_ascii=False, indent=1))
    elif a.format == "md":
        blocks = []
        if len(data) > 1:
            head = ["| Product | ΔOI | Settle | COT net |", "|---|---:|---:|---:|"]
            for d in data:
                s = d["summary"]
                doi = f"{s['oi']['change']:+,}" if s["oi"] else "—"
                px = f"{s['price']['change']:+,.2f}" if s["price"] else "—"
                cn = f"{s['cot_net']['change']:+,}" if s["cot_net"] else "—"
                head.append(f"| {d['product']} | {doi} | {px} | {cn} |")
            blocks.append("\n".join(head))
        blocks += [md_report(d) for d in data]
        print("\n\n".join(blocks))
    else:
        print("\n\n".join(min_text(d) for d in data))


if __name__ == "__main__":
    main()
