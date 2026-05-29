#!/usr/bin/env python3
"""
Smallcap 250 ticker finder.
The raw index NIFTYSMLCAP250.NS is broken in yfinance, so this tests
several ETF proxies + index variants and reports which return usable data.
Run via workflow_dispatch and read the Actions log.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# Candidates that all track Nifty Smallcap 250 (or close proxies)
CANDIDATES = {
    "Raw index (current)":        "NIFTYSMLCAP250.NS",
    "Motilal Oswal SC250 ETF":    "MOSMALL250.NS",
    "HDFC SC250 ETF":             "HDFCSML250.NS",
    "Nippon SC250 ETF":           "SMALLCAP.NS",
    "Smallcap 100 index (proxy)": "^CNXSC",
}

start = (datetime.today() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")


def fetch(ticker):
    try:
        c = yf.Ticker(ticker).history(start=start, interval="1d")["Close"].dropna()
        if len(c) >= 10:
            return c, "Ticker.history"
    except Exception:
        pass
    try:
        df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        c = df["Close"].dropna()
        if len(c) >= 10:
            return c, "yf.download"
    except Exception:
        pass
    return pd.Series(dtype=float), "none"


print("Testing Smallcap 250 candidate tickers...\n")
for name, ticker in CANDIDATES.items():
    closes, method = fetch(ticker)
    if closes.empty:
        print(f"❌ {name:28s} {ticker:20s} : no data")
        continue
    n    = len(closes)
    last = closes.iloc[-1]
    h52w = closes.tail(252).max()
    dd   = (h52w - last) / h52w * 100
    ok   = "✅" if (n >= 200 and dd > 0) else "⚠️"
    print(f"{ok} {name:28s} {ticker:20s} : {n:4d} sessions, "
          f"price {last:,.2f}, 52w high {h52w:,.2f}, drawdown {dd:.2f}% [{method}]")

print("\nPick the ticker with the most sessions + a sensible drawdown.")
