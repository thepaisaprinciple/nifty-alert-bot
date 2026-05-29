#!/usr/bin/env python3
"""
📈 Nifty Multi-Index Alert Bot
------------------------------
Pings Telegram when any tracked index crosses a *new* drawdown rung
(measured from its 52-week high) — so you only hear when it gets CHEAPER
than the last alert. Each index has its own ladder because midcaps and
smallcaps are far more volatile than the Nifty 50.

Per-index state is persisted in nifty_state.json (committed back by the
workflow) — that is what stops the daily-spam problem.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ── Config: edit indices / ladders here ───────────────────────────────
# thresholds = drawdown rungs (%) from the 52-week high, shallow -> deep.
INDICES = [
    {"key": "NIFTY50",     "name": "Nifty 50",
     "ticker": "^NSEI",             "thresholds": [5, 10, 15, 20]},
    {"key": "MIDCAP150",   "name": "Nifty Midcap 150",
     "ticker": "NIFTYMIDCAP150.NS", "thresholds": [5, 10, 15, 20]},
    # Smallcap 250: raw index NIFTYSMLCAP250.NS has no usable history in
    # yfinance, so we proxy with the HDFC ETF (3y history, high liquidity).
    {"key": "SMALLCAP250", "name": "Nifty Smallcap 250",
     "ticker": "HDFCSML250.NS",     "thresholds": [5, 10, 15, 20],
     "proxy_etf": True},
    # Strategy index - SKIPPED for now. Yahoo has no raw index; the only
    # proxy is the Motilal Oswal ETF (launched Jun-2025), too new for a
    # clean 52w/3y high or 200-DMA. Uncomment to re-enable (~mid-2026 it
    # will have a full year of history).
    # {"key": "MOM150M50",   "name": "Nifty Midcap150 Momentum 50",
    #  "ticker": "MOMIDMTM.NS",       "thresholds": [10, 15, 20, 30],
    #  "proxy_etf": True},
]

RESET_BAND = 1.0          # re-arm a ladder once back within this % of the high
STATE_FILE = Path("nifty_state.json")
IST = timezone(timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler("nifty_alert.log")],
)
log = logging.getLogger("nifty")


# ── Market data ───────────────────────────────────────────────────────
def _fetch_closes(ticker: str, start: str):
    """
    Try two fetch strategies and return the first that yields >= 10 rows.

    Some NSE index tickers (e.g. NIFTYSMLCAP250.NS) silently break with
    Ticker.history() but work fine via yf.download(), which uses a different
    internal API path. We try both so every ticker is covered.
    """
    import yfinance as yf
    import pandas as pd

    # Strategy 1: Ticker.history with explicit start date
    try:
        closes = yf.Ticker(ticker).history(start=start, interval="1d")["Close"].dropna()
        if len(closes) >= 10:
            log.info("[%s] fetched %d rows via Ticker.history.", ticker, len(closes))
            return closes
    except Exception as e:
        log.warning("[%s] Ticker.history failed: %s", ticker, e)

    # Strategy 2: yf.download — different API path, works for quirky NSE indices
    try:
        df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        # yfinance >=0.2 may return MultiLevel columns for a single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        closes = df["Close"].dropna()
        if len(closes) >= 10:
            log.info("[%s] fetched %d rows via yf.download.", ticker, len(closes))
            return closes
    except Exception as e:
        log.warning("[%s] yf.download failed: %s", ticker, e)

    import pandas as pd
    return pd.Series(dtype=float)


def get_quote(ticker: str) -> dict:
    """Return price + reference highs/DMA, flagging when history is short."""
    start = (datetime.now(timezone.utc) - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
    closes = _fetch_closes(ticker, start)

    if closes.empty:
        raise RuntimeError(f"No price history for {ticker}.")

    n = len(closes)
    high_52w = float(closes.tail(252).max())          # ~1 trading year
    high_3y = float(closes.max())
    dma200 = float(closes.tail(200).mean()) if n >= 200 else None

    price = None
    try:
        intra = t.history(period="1d", interval="1m")["Close"].dropna()
        if len(intra):
            price = float(intra.iloc[-1])
    except Exception as e:  # noqa: BLE001
        log.warning("[%s] intraday fetch failed (%s); using last close.", ticker, e)
    if price is None:
        price = float(closes.iloc[-1])

    return {
        "price": price,
        "high_52w": high_52w,
        "high_3y": high_3y,
        "dma200": dma200,
        "sessions": n,
        "full_year": n >= 252,     # enough data for a true 52-week high?
        "has_3y": n >= 504,        # ~2y+ before the 3y line is meaningful
    }


# ── State ─────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            log.warning("State file corrupt; starting fresh.")
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))
    log.info("State saved.")


# ── Core decision logic (pure -> unit-tested) ─────────────────────────
def evaluate(drawdown_pct: float, prev_level: int, thresholds: list) -> dict:
    if drawdown_pct <= RESET_BAND:
        return {"fire": False, "new_level": 0, "reset": prev_level != 0}

    qualifying = [t for t in thresholds if drawdown_pct >= t]
    current = max(qualifying) if qualifying else 0

    if current > prev_level:
        return {"fire": True, "new_level": current, "reset": False}
    return {"fire": False, "new_level": prev_level, "reset": False}


# ── Telegram ──────────────────────────────────────────────────────────
def send_telegram(text: str) -> None:
    token, chat_id = os.environ.get("BOT_TOKEN"), os.environ.get("CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("BOT_TOKEN / CHAT_ID env vars are not set.")
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=30,
    )
    resp.raise_for_status()
    log.info("Telegram message sent.")


# ── Message formatting ────────────────────────────────────────────────
DOWN = "\u25BC"                                   # ▼ down triangle
PALETTE = ["\U0001F7E1", "\U0001F7E0", "\U0001F534", "\U0001F7E3"]  # 🟡 🟠 🔴 🟣
GREEN = "\U0001F7E2"                               # 🟢 near highs / healthy


def severity_dot(drawdown: float, thresholds: list) -> str:
    """Colour by how deep we currently are: 🟢 → 🟡 → 🟠 → 🔴 → 🟣."""
    crossed = [i for i, t in enumerate(thresholds) if drawdown >= t]
    if not crossed:
        return GREEN
    return PALETTE[min(max(crossed), len(PALETTE) - 1)]


def index_block(cfg: dict, q: dict, level: int, fired: bool) -> str:
    """One index rendered as a header line + a blockquote 'card'."""
    dd_52w = max(0.0, (q["high_52w"] - q["price"]) / q["high_52w"] * 100)
    dot = severity_dot(dd_52w, cfg["thresholds"])
    high_label = "52w High" if q["full_year"] else "High (since launch)"

    header = f"{dot} <b>{cfg['name']}</b> : {DOWN} {dd_52w:.1f}%"

    body = []
    if level > 0:
        thr = cfg["thresholds"]
        label = f"tranche {thr.index(level) + 1}" if level in thr else f"{level}% level"
        if fired:
            body.append(f"\U0001F6D2 Deploy {label}  (crossed {DOWN} {level}%)")
        else:
            body.append(f"\u2713 Already at {label}  ({DOWN} {level}%)")

    body.append(f"Price    : {q['price']:,.0f}")
    body.append(f"{high_label} : {q['high_52w']:,.0f}")

    if q["has_3y"]:
        dd_3y = max(0.0, (q["high_3y"] - q["price"]) / q["high_3y"] * 100)
        body.append(f"3y High  : {q['high_3y']:,.0f}  ({DOWN} {dd_3y:.1f}%)")

    if q["dma200"] is not None:
        below = q["price"] < q["dma200"]
        body.append("Trend    : \U0001F534 below 200-DMA" if below
                    else "Trend    : \U0001F7E2 above 200-DMA")
    else:
        body.append("Trend    : \u23F3 200-DMA not ready")

    if cfg.get("proxy_etf"):
        body.append("<i>tracked via ETF proxy</i>")

    return header + "\n<blockquote>" + "\n".join(body) + "</blockquote>"


def build_message(blocks: list, alert: bool) -> str:
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    if alert:
        header = ("\U0001F6A8 <b>INDEX ALERT : new level crossed</b>\n"
                  "<i>\U0001F7E1 shallow \u2192 \U0001F7E3 deep</i>")
    else:
        header = "\U0001F4CA <b>INDEX STATUS</b>"
    return header + "\n\n" + "\n\n".join(blocks) + f"\n\n\U0001F552 {now}"


# ── Main ──────────────────────────────────────────────────────────────
def main() -> int:
    force_summary = os.environ.get("FORCE_SEND_SUMMARY", "false").lower() == "true"
    state = load_state()

    fired_blocks = []
    all_blocks = []
    had_error = False

    for cfg in INDICES:
        key = cfg["key"]
        try:
            q = get_quote(cfg["ticker"])
        except Exception as e:  # noqa: BLE001
            log.error("[%s] fetch failed: %s", key, e)
            had_error = True
            continue

        drawdown = max(0.0, (q["high_52w"] - q["price"]) / q["high_52w"] * 100)
        prev = state.get(key, {}).get("highest_threshold_triggered", 0)
        d = evaluate(drawdown, prev, cfg["thresholds"])
        log.info("[%s] dd=%.2f%% prev=%s -> %s", key, drawdown, prev, d)

        block = index_block(cfg, q, d["new_level"], d["fire"])
        all_blocks.append(block)
        if d["fire"]:
            fired_blocks.append(block)

        state[key] = {
            "highest_threshold_triggered": d["new_level"],
            "last_price": round(q["price"], 2),
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    if fired_blocks:
        send_telegram(build_message(fired_blocks, alert=True))
    elif force_summary and all_blocks:
        send_telegram(build_message(all_blocks, alert=False))
        log.info("Forced summary sent (no new alert levels).")
    else:
        log.info("No new rungs crossed. Staying quiet.")

    save_state(state)
    return 1 if had_error and not all_blocks else 0


if __name__ == "__main__":
    sys.exit(main())
