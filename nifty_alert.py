#!/usr/bin/env python3
"""
📈 Nifty Alert Bot
------------------
Alerts on Telegram when the Nifty 50 crosses a *new* drawdown rung
(5 / 10 / 15 / 20 %) measured from its 52-week high — so you only ever
hear when it gets CHEAPER than the last time you were alerted.

State is persisted in nifty_state.json (committed back by the workflow),
which is what stops the daily-spam problem.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ── Config ────────────────────────────────────────────────────────────
TICKER = "^NSEI"                       # Nifty 50 index on Yahoo Finance
THRESHOLDS = [5, 10, 15, 20]           # drawdown rungs (%) from 52w high
RESET_BAND = 1.0                       # re-arm ladder once back within this % of the high
STATE_FILE = Path("nifty_state.json")

IST = timezone(timedelta(hours=5, minutes=30))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("nifty_alert.log"),
    ],
)
log = logging.getLogger("nifty")


# ── Market data ───────────────────────────────────────────────────────
def get_quote() -> dict:
    """Return current price, 52w high, 3y high, and 200-DMA for the Nifty."""
    import yfinance as yf

    t = yf.Ticker(TICKER)
    hist = t.history(period="3y", interval="1d")
    closes = hist["Close"].dropna()
    if closes.empty:
        raise RuntimeError("No price history returned from Yahoo Finance.")

    high_52w = float(closes.tail(252).max())   # ~1 trading year
    high_3y = float(closes.max())               # full 3-year window
    dma200 = float(closes.tail(200).mean())

    # Prefer a fresh intraday price (to catch same-day drops);
    # fall back to the last daily close.
    price = None
    try:
        intra = t.history(period="1d", interval="1m")["Close"].dropna()
        if len(intra):
            price = float(intra.iloc[-1])
    except Exception as e:  # noqa: BLE001
        log.warning("Intraday fetch failed (%s); using last close.", e)
    if price is None:
        price = float(closes.iloc[-1])

    return {
        "price": price,
        "high_52w": high_52w,
        "high_3y": high_3y,
        "dma200": dma200,
    }


# ── State ─────────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            log.warning("State file corrupt; starting fresh.")
    return {"highest_threshold_triggered": 0, "last_updated": None, "last_price": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))
    log.info("State saved: %s", state)


# ── Core decision logic (pure function → easy to test) ────────────────
def evaluate(drawdown_pct: float, prev_level: int) -> dict:
    """
    Decide whether to alert.

    Returns dict with:
      fire        -> bool, send an alert this run?
      new_level   -> int, threshold to store as 'highest triggered'
      reset       -> bool, did the ladder re-arm (back near the high)?
    """
    # Recovered back to (near) the high → re-arm the whole ladder, stay quiet.
    if drawdown_pct <= RESET_BAND:
        return {"fire": False, "new_level": 0, "reset": prev_level != 0}

    qualifying = [t for t in THRESHOLDS if drawdown_pct >= t]
    current = max(qualifying) if qualifying else 0

    # Only alert when we've crossed into a DEEPER rung than before.
    if current > prev_level:
        return {"fire": True, "new_level": current, "reset": False}

    # Same or shallower (partial recovery, not back to top) → keep locked, quiet.
    return {"fire": False, "new_level": prev_level, "reset": False}


# ── Telegram ──────────────────────────────────────────────────────────
def send_telegram(text: str) -> None:
    token = os.environ.get("BOT_TOKEN")
    chat_id = os.environ.get("CHAT_ID")
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
TRANCHE = {5: "tranche 1", 10: "tranche 2", 15: "tranche 3", 20: "tranche 4"}


def build_message(q: dict, level: int, *, summary: bool = False) -> str:
    dd_52w = (q["high_52w"] - q["price"]) / q["high_52w"] * 100
    dd_3y = (q["high_3y"] - q["price"]) / q["high_3y"] * 100
    below_dma = q["price"] < q["dma200"]
    dma_line = ("🔻 BELOW 200-DMA — trend confirms the fall"
                if below_dma else
                "🟢 above 200-DMA — trend still intact (shallow dip)")
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")

    header = ("📊 <b>NIFTY STATUS</b>" if summary
              else f"📉 <b>NIFTY ALERT — −{level}% level crossed</b>")
    action = "" if summary else f"\n👉 Consider deploying <b>{TRANCHE.get(level, '')}</b>.\n"

    return (
        f"{header}\n{action}"
        f"\nCurrent:  <b>{q['price']:,.0f}</b>"
        f"\n52w High: {q['high_52w']:,.0f}  (−{dd_52w:.1f}%)"
        f"\n3y High:  {q['high_3y']:,.0f}  (−{max(dd_3y,0):.1f}%)"
        f"\n200-DMA:  {q['dma200']:,.0f}"
        f"\n{dma_line}"
        f"\n\n🕒 {now}"
    )


# ── Main ──────────────────────────────────────────────────────────────
def main() -> int:
    force_summary = os.environ.get("FORCE_SEND_SUMMARY", "false").lower() == "true"

    try:
        q = get_quote()
    except Exception as e:  # noqa: BLE001
        log.error("Failed to fetch quote: %s", e)
        return 1

    drawdown = max(0.0, (q["high_52w"] - q["price"]) / q["high_52w"] * 100)
    state = load_state()
    prev = state.get("highest_threshold_triggered", 0)

    decision = evaluate(drawdown, prev)
    log.info("Drawdown %.2f%% | prev_level=%s | decision=%s", drawdown, prev, decision)

    if decision["fire"]:
        send_telegram(build_message(q, decision["new_level"]))
    elif force_summary:
        send_telegram(build_message(q, decision["new_level"], summary=True))
        log.info("Forced summary sent (no new alert level).")
    else:
        if decision["reset"]:
            log.info("Ladder re-armed (back near 52w high). No alert.")
        else:
            log.info("No new rung crossed. Staying quiet.")

    state.update(
        highest_threshold_triggered=decision["new_level"],
        last_updated=datetime.now(timezone.utc).isoformat(),
        last_price=round(q["price"], 2),
    )
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
