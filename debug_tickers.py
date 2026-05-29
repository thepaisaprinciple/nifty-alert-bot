#!/usr/bin/env python3
"""
Smallcap 250 ETF chooser.
Ranks candidate ETFs on what actually matters for a DRAWDOWN bot:
liquidity (rupee turnover), history length, data gaps, and — when 3+
candidates resolve — an empirical tracking error using the cross-ETF
consensus as a stand-in benchmark (we can't fetch the raw index itself).

Run via workflow_dispatch and read the Actions log.
"""
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# All track (or closely proxy) the Nifty Smallcap 250. Unknown/dead
# tickers are skipped automatically.
CANDIDATES = {
    "Motilal Oswal SC250": "MOSMALL250.NS",
    "HDFC SC250":          "HDFCSML250.NS",
    "Nippon SC250":        "NIFTYSMALLCAP250.NS",
    "ICICI SC250":         "ICICISML250.NS",
    "Kotak SC250":         "KOTAKSML.NS",
}

start = (datetime.today() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")


def fetch_df(ticker):
    """Return a DataFrame with Close + Volume, trying both fetch paths."""
    for how in ("history", "download"):
        try:
            if how == "history":
                df = yf.Ticker(ticker).history(start=start, interval="1d")
            else:
                df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.droplevel(1)
            df = df[["Close", "Volume"]].dropna()
            if len(df) >= 10:
                return df, how
        except Exception:
            continue
    return pd.DataFrame(), "none"


# 1) Fetch everything that resolves
data = {}
for name, ticker in CANDIDATES.items():
    df, how = fetch_df(ticker)
    if not df.empty:
        data[name] = {"ticker": ticker, "df": df, "how": how}
    else:
        print(f"❌ {name:20s} {ticker:22s} : no data (skipped)")

if not data:
    print("\nNo candidate ETFs returned data — tell Claude and we'll widen the list.")
    raise SystemExit

# 2) Build a cross-ETF consensus return series (proxy benchmark)
ret = {}
for name, d in data.items():
    r = d["df"]["Close"].pct_change()
    r.index = r.index.tz_localize(None) if r.index.tz is not None else r.index
    ret[name] = r
ret_df = pd.DataFrame(ret).dropna(how="all")
consensus = ret_df.median(axis=1)  # robust stand-in for the true index return

# 3) Score each candidate
print(f"\n{'ETF':20s} {'sessions':>8} {'avg ₹turnover':>14} {'gaps%':>6} {'trk.err':>8} {'drawdown':>9}")
print("-" * 72)
rows = []
for name, d in data.items():
    df = d["df"]
    n = len(df)
    last = df["Close"].iloc[-1]
    h52w = df["Close"].tail(252).max()
    dd = (h52w - last) / h52w * 100
    turnover = float((df["Close"] * df["Volume"]).tail(60).mean())   # ₹ traded/day
    gaps = float((df["Volume"].tail(120) == 0).mean() * 100)          # % zero-volume days
    # empirical tracking error vs consensus (annualised), only meaningful with 3+ ETFs
    if len(data) >= 3:
        diff = (ret_df[name] - consensus).dropna()
        te = float(diff.std() * np.sqrt(252) * 100)
    else:
        te = float("nan")
    rows.append((name, n, turnover, gaps, te, dd, h52w, last))
    te_str = f"{te:6.2f}%" if not np.isnan(te) else "   n/a"
    print(f"{name:20s} {n:8d} {turnover:14,.0f} {gaps:5.1f}% {te_str:>8} {dd:8.2f}%")

# 4) Recommend: prefer full-year history, then highest turnover, then lowest TE
def key(r):
    name, n, turnover, gaps, te, dd, *_ = r
    return (n >= 252, turnover, -(te if not np.isnan(te) else 0))
best = sorted(rows, key=key, reverse=True)[0]
print(f"\n👉 Best for a drawdown bot: {best[0]} ({CANDIDATES[best[0]]})")
print(f"   {best[1]} sessions · ₹{best[2]:,.0f}/day turnover · drawdown {best[5]:.2f}%")
print(f"   52w high {best[6]:,.2f} · last {best[7]:,.2f}")
