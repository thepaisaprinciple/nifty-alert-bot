#!/usr/bin/env python3
"""
Run via workflow_dispatch to inspect what yfinance actually returns
for each index ticker. Check the Actions log output.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

TICKERS = {
    "Nifty 50":           "^NSEI",
    "Nifty Midcap 150":   "NIFTYMIDCAP150.NS",
    "Nifty Smallcap 250": "NIFTYSMLCAP250.NS",
}

start = (datetime.today() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")


def fetch(ticker):
    # Strategy 1: Ticker.history
    try:
        c = yf.Ticker(ticker).history(start=start, interval="1d")["Close"].dropna()
        if len(c) >= 10:
            return c, "Ticker.history"
    except Exception as e:
        print(f"  Ticker.history failed: {e}")

    # Strategy 2: yf.download
    try:
        df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        c = df["Close"].dropna()
        if len(c) >= 10:
            return c, "yf.download"
    except Exception as e:
        print(f"  yf.download failed: {e}")

    return pd.Series(dtype=float), "none"


for name, ticker in TICKERS.items():
    print(f"\n{'='*50}")
    print(f"  {name}  ({ticker})")
    print(f"{'='*50}")

    closes, method = fetch(ticker)

    if closes.empty:
        print("  ❌ No data returned by either method")
        continue

    n     = len(closes)
    last  = closes.iloc[-1]
    h52w  = closes.tail(252).max()
    h3y   = closes.max()
    dma   = closes.tail(200).mean() if n >= 200 else None
    dd    = (h52w - last) / h52w * 100

    print(f"  Fetch method      : {method}")
    print(f"  Sessions returned : {n}  ({'✅ full year' if n >= 252 else '⚠️ partial'})")
    print(f"  Date range        : {closes.index[0].date()}  →  {closes.index[-1].date()}")
    print(f"  Last close        : {last:,.2f}")
    print(f"  52w high          : {h52w:,.2f}  {'✅' if h52w > last else '⚠️ equals last close'}")
    print(f"  3y high           : {h3y:,.2f}")
    print(f"  200-DMA           : {dma:,.2f}" if dma else "  200-DMA          : ⚠️ not enough data")
    print(f"  Drawdown          : {dd:.2f}%  {'✅' if dd > 0 else '❌ 0% — alerts wont fire'}")
