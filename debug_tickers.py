#!/usr/bin/env python3
"""
Run this once via workflow_dispatch to inspect what yfinance
actually returns for each index ticker. Check the Actions log output.
"""
import yfinance as yf

TICKERS = {
    "Nifty 50":        "^NSEI",
    "Nifty Midcap 150":"NIFTYMIDCAP150.NS",
    "Nifty Smallcap 250":"NIFTYSMLCAP250.NS",
}

for name, ticker in TICKERS.items():
    print(f"\n{'='*50}")
    print(f"  {name}  ({ticker})")
    print(f"{'='*50}")
    try:
        t    = yf.Ticker(ticker)
        from datetime import timedelta
        start = (__import__("datetime").datetime.today() - timedelta(days=3*365)).strftime("%Y-%m-%d")
        hist = t.history(start=start, interval="1d")
        if len(hist) < 10:
            hist = t.history(period="max", interval="1d")
        c    = hist["Close"].dropna()

        if c.empty:
            print("  ❌ No data returned at all")
            continue

        n = len(c)
        last  = c.iloc[-1]
        h52w  = c.tail(252).max()
        h3y   = c.max()
        dma   = c.tail(200).mean() if n >= 200 else None
        dd    = (h52w - last) / h52w * 100

        print(f"  Sessions returned : {n}  ({'✅ full year' if n >= 252 else '⚠️ under 252 — using partial high'})")
        print(f"  Date range        : {c.index[0].date()}  →  {c.index[-1].date()}")
        print(f"  Last close        : {last:,.2f}")
        print(f"  52w high          : {h52w:,.2f}  {'✅' if h52w > last else '⚠️ equals last close — possible data issue'}")
        print(f"  3y high           : {h3y:,.2f}")
        print(f"  200-DMA           : {dma:,.2f}" if dma else "  200-DMA          : ⚠️ not enough data (<200 sessions)")
        print(f"  Drawdown          : {dd:.2f}%  {'✅ would trigger alerts' if dd > 0 else '❌ 0% — no alert will ever fire'}")

        # flag if NaN values exist before dropna
        raw_n = len(hist["Close"])
        if raw_n != n:
            print(f"  ⚠️  NaN rows dropped : {raw_n - n} (raw={raw_n}, clean={n})")

    except Exception as e:
        print(f"  ❌ Fetch failed: {e}")
