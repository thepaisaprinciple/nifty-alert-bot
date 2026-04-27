"""
Nifty Index Drawdown Alert Bot
================================
Monitors 9 Nifty indices, alerts on Telegram when any drops
5% / 10% / 20% from its rolling peak, with a 3-year bar chart.

Data sources (in priority order):
  1. NSE India public API  (all 9 indices including momentum/value)
  2. Yahoo Finance          (fallback for Nifty 50, Next 50, Midcap, Smallcap)
"""

import io
import os
import time
import requests
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.patches as mpatches
from datetime import datetime, timedelta

# ─────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ["BOT_TOKEN"]   # set in GitHub Secrets
CHAT_ID   = os.environ["CHAT_ID"]     # set in GitHub Secrets

ALERT_LEVELS = [5, 10, 20]            # drawdown % thresholds
CHART_YEARS  = 3                      # years of history shown in chart
DATA_YEARS   = 5                      # years of data to fetch for peak calc

# Index name → { NSE API name, Yahoo Finance ticker (or None) }
INDICES = {
    "Nifty 50":                     {"nse": "NIFTY 50",                    "yf": "^NSEI"},
    "Nifty Next 50":                {"nse": "NIFTY NEXT 50",               "yf": "^NSMIDCP"},
    "Nifty Midcap 150":             {"nse": "NIFTY MIDCAP 150",            "yf": "^NSEMDCP50"},
    "Nifty Smallcap 250":           {"nse": "NIFTY SMALLCAP 250",          "yf": "^NSESC250"},
    "Nifty 200 Momentum 30":        {"nse": "NIFTY200 MOMENTUM 30",        "yf": None},
    "Nifty 500 Momentum 50":        {"nse": "NIFTY500 MOMENTUM 50",        "yf": None},
    "Nifty Midcap 150 Momentum 50": {"nse": "NIFTY MIDCAP150 MOMENTUM 50", "yf": None},
    "Nifty 200 Value 30":           {"nse": "NIFTY200 VALUE 30",           "yf": None},
    "Nifty 500 Value 50":           {"nse": "NIFTY500 VALUE 50",           "yf": None},
}

# ─────────────────────────────────────────────────────────────────────
# DATA FETCHING — NSE INDIA
# ─────────────────────────────────────────────────────────────────────

def get_nse_session() -> requests.Session:
    """Open a session with NSE (required for cookie-based auth)."""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept": "*/*",
        "Connection": "keep-alive",
        "Referer": "https://www.nseindia.com/",
    })
    try:
        s.get("https://www.nseindia.com", timeout=15)
        time.sleep(2)
        s.get("https://www.nseindia.com/market-data/live-equity-market", timeout=10)
        time.sleep(1)
    except Exception as e:
        print(f"  [NSE session] warning: {e}")
    return s


def _nse_chunk(session: requests.Session, nse_name: str,
               from_dt: datetime, to_dt: datetime) -> pd.DataFrame:
    """Fetch one chunk (≤ 1 year) of NSE index history."""
    params = {
        "indexType": nse_name,
        "from":      from_dt.strftime("%d-%m-%Y"),
        "to":        to_dt.strftime("%d-%m-%Y"),
    }
    r = session.get(
        "https://www.nseindia.com/api/historical/indicesHistory",
        params=params, timeout=20
    )
    r.raise_for_status()
    records = r.json().get("data", {}).get("indexCloseOnlineRecords", [])
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    # NSE date column is "EOD_TIMESTAMP" with format like "09-Jan-2024"
    df["date"]  = pd.to_datetime(df["EOD_TIMESTAMP"], dayfirst=True, errors="coerce")
    df["close"] = pd.to_numeric(df["EOD_CLOSE_INDEX_VAL"], errors="coerce")
    return df[["date", "close"]].dropna()


def fetch_nse(session: requests.Session, nse_name: str,
              years: int = DATA_YEARS) -> pd.DataFrame:
    """Fetch `years` of data from NSE, one year-chunk at a time."""
    end   = datetime.today()
    start = end - timedelta(days=365 * years + 30)
    chunks, cursor = [], end

    while cursor > start:
        chunk_start = max(start, cursor - timedelta(days=364))
        try:
            df = _nse_chunk(session, nse_name, chunk_start, cursor)
            if not df.empty:
                chunks.append(df)
            time.sleep(0.8)
        except Exception as e:
            print(f"    NSE chunk error [{chunk_start.date()}–{cursor.date()}]: {e}")
        cursor = chunk_start - timedelta(days=1)

    if not chunks:
        return pd.DataFrame()

    result = (
        pd.concat(chunks)
        .drop_duplicates("date")
        .sort_values("date")
        .reset_index(drop=True)
    )
    return result


# ─────────────────────────────────────────────────────────────────────
# DATA FETCHING — YAHOO FINANCE (fallback)
# ─────────────────────────────────────────────────────────────────────

def fetch_yfinance(ticker: str, years: int = DATA_YEARS) -> pd.DataFrame:
    """Fetch data from Yahoo Finance (no API key needed)."""
    try:
        import yfinance as yf
        start = datetime.today() - timedelta(days=365 * years + 30)
        raw = yf.download(ticker, start=start, progress=False, auto_adjust=True)
        if raw.empty:
            return pd.DataFrame()
        df = raw[["Close"]].reset_index()
        df.columns = ["date", "close"]
        df["date"]  = pd.to_datetime(df["date"]).dt.tz_localize(None)
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        return df.dropna().sort_values("date").reset_index(drop=True)
    except Exception as e:
        print(f"    yfinance error [{ticker}]: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────
# DRAWDOWN LOGIC
# ─────────────────────────────────────────────────────────────────────

def compute_drawdown(df: pd.DataFrame):
    """
    Returns:
      curr_val    – latest closing value
      peak_val    – all-time high within the dataset
      drawdown_pct – (curr - peak) / peak * 100  [negative = drop]
      peak_date   – date of the peak
    """
    df = df.copy()
    peak_idx  = df["close"].idxmax()
    peak_val  = df.loc[peak_idx, "close"]
    peak_date = df.loc[peak_idx, "date"]
    curr_val  = df.iloc[-1]["close"]
    drawdown  = (curr_val - peak_val) / peak_val * 100
    return float(curr_val), float(peak_val), float(drawdown), peak_date


def breached_levels(drawdown_pct: float) -> list[int]:
    """Return list of ALERT_LEVELS that have been breached (drawdown is negative)."""
    return [lvl for lvl in ALERT_LEVELS if drawdown_pct <= -lvl]


# ─────────────────────────────────────────────────────────────────────
# CHART GENERATION
# ─────────────────────────────────────────────────────────────────────

BAR_PALETTE = {
    "ok":     "#2ecc71",   # < 5% drop   → green
    "warn":   "#f39c12",   # 5–10% drop  → amber
    "danger": "#e74c3c",   # 10–20% drop → red
    "crash":  "#922b21",   # > 20% drop  → dark red
}

def _bar_color(dd: float) -> str:
    if dd <= -20: return BAR_PALETTE["crash"]
    if dd <= -10: return BAR_PALETTE["danger"]
    if dd <= -5:  return BAR_PALETTE["warn"]
    return BAR_PALETTE["ok"]


def make_chart(df: pd.DataFrame, index_name: str,
               curr_val: float, peak_val: float,
               peak_date, drawdown_pct: float) -> bytes:
    """
    Build a dark-themed monthly bar chart for the last CHART_YEARS.
    Returns raw PNG bytes.
    """
    cutoff   = datetime.today() - timedelta(days=365 * CHART_YEARS)
    df_plot  = df[df["date"] >= cutoff].copy()
    df_plot.set_index("date", inplace=True)

    # Resample to month-end
    monthly = (
        df_plot["close"]
        .resample("ME")
        .last()
        .dropna()
        .reset_index()
    )
    monthly.columns = ["date", "close"]

    # Rolling peak within plot window (for per-bar color)
    monthly["peak"]  = monthly["close"].cummax()
    monthly["dd"]    = (monthly["close"] - monthly["peak"]) / monthly["peak"] * 100
    colors           = [_bar_color(d) for d in monthly["dd"]]
    colors[-1]       = _bar_color(drawdown_pct)   # override last bar with real dd

    # ── Figure ──────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(15, 6), facecolor="#0d1117")
    ax.set_facecolor("#161b22")

    ax.bar(monthly["date"], monthly["close"],
           width=22, color=colors, edgecolor="none", alpha=0.90)

    # Peak reference line
    ax.axhline(
        y=peak_val, color="#f1c40f",
        linestyle="--", linewidth=1.6, alpha=0.85,
        label=f"All-time High: {peak_val:,.0f}  ({peak_date.strftime('%d %b %Y')})"
    )

    # Annotate current value
    last_date = monthly["date"].iloc[-1]
    ax.annotate(
        f"  ▼ {abs(drawdown_pct):.1f}% from peak\n  Now: {curr_val:,.0f}",
        xy=(last_date, curr_val),
        xytext=(-90, -55), textcoords="offset points",
        color="white", fontsize=9.5, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#e74c3c", lw=1.5),
        bbox=dict(boxstyle="round,pad=0.45",
                  facecolor=_bar_color(drawdown_pct), alpha=0.85),
    )

    # ── Styling ─────────────────────────────────────────────────────
    ax.set_title(
        f"{'🔴' if drawdown_pct <= -20 else '🟠' if drawdown_pct <= -10 else '🟡'}  "
        f"{index_name}  —  {CHART_YEARS}-Year Monthly Chart",
        color="white", fontsize=13, fontweight="bold", pad=14
    )
    ax.set_ylabel("Index Value", color="#8b949e", fontsize=10)
    ax.tick_params(colors="#8b949e", labelsize=9)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b'%y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.xticks(rotation=45, ha="right", color="#8b949e")
    for spine in ax.spines.values():
        spine.set_edgecolor("#30363d")
    ax.grid(axis="y", color="#21262d", linestyle="--", linewidth=0.6)
    ax.set_axisbelow(True)

    # Legend
    legend_patches = [
        mpatches.Patch(facecolor=BAR_PALETTE["ok"],     label="< 5% drawdown"),
        mpatches.Patch(facecolor=BAR_PALETTE["warn"],   label="5 – 10% drawdown"),
        mpatches.Patch(facecolor=BAR_PALETTE["danger"], label="10 – 20% drawdown"),
        mpatches.Patch(facecolor=BAR_PALETTE["crash"],  label="> 20% drawdown"),
    ]
    leg = ax.legend(
        handles=legend_patches + ax.lines,
        loc="upper left", facecolor="#21262d",
        edgecolor="#30363d", labelcolor="white",
        fontsize=8.5, framealpha=0.9
    )

    plt.tight_layout(pad=1.2)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ─────────────────────────────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────────────────────────────

def _tg_post(endpoint: str, **kwargs) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{endpoint}"
    r   = requests.post(url, timeout=30, **kwargs)
    if not r.ok:
        print(f"  [Telegram] {r.status_code}: {r.text[:200]}")
    return r.ok


def send_photo(photo_bytes: bytes, caption: str):
    _tg_post(
        "sendPhoto",
        files={"photo": ("chart.png", photo_bytes, "image/png")},
        data={"chat_id": CHAT_ID, "caption": caption,
              "parse_mode": "HTML"},
    )


def send_text(text: str):
    _tg_post(
        "sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
    )


def send_summary(today: str, results: list[dict]):
    """Send a daily summary table even when no alerts fire."""
    lines = [f"📊 <b>Nifty Daily Summary — {today}</b>\n"]
    for r in results:
        icon = "🔴" if r["dd"] <= -10 else "🟠" if r["dd"] <= -5 else "🟢"
        lines.append(
            f"{icon} <b>{r['name']}</b>: {r['curr']:,.0f}"
            f"  ({r['dd']:+.1f}% from peak)"
        )
    send_text("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    today = datetime.today().strftime("%d %b %Y")
    print(f"\n{'='*55}")
    print(f"  Nifty Alert Bot  —  {today}")
    print(f"{'='*55}\n")

    nse_session  = get_nse_session()
    alerts_found = False
    results      = []

    for display_name, cfg in INDICES.items():
        print(f"→ {display_name}")
        df = pd.DataFrame()

        # 1️⃣ Try NSE India
        try:
            df = fetch_nse(nse_session, cfg["nse"])
            if not df.empty:
                print(f"   ✔ NSE: {len(df)} rows  "
                      f"[{df['date'].iloc[0].date()} → {df['date'].iloc[-1].date()}]")
        except Exception as e:
            print(f"   ✘ NSE failed: {e}")

        # 2️⃣ Fall back to Yahoo Finance
        if df.empty and cfg.get("yf"):
            print(f"   ↩ Trying Yahoo Finance ({cfg['yf']}) …")
            df = fetch_yfinance(cfg["yf"])
            if not df.empty:
                print(f"   ✔ YF: {len(df)} rows")

        if df.empty or len(df) < 30:
            print("   ⚠ Insufficient data, skipping.\n")
            continue

        curr_val, peak_val, dd_pct, peak_date = compute_drawdown(df)
        alerts  = breached_levels(dd_pct)
        results.append({"name": display_name, "curr": curr_val, "dd": dd_pct})

        status = f"cur={curr_val:,.0f}  peak={peak_val:,.0f}  dd={dd_pct:.2f}%"
        if alerts:
            print(f"   🚨 ALERT  {status}  levels={alerts}")
        else:
            print(f"   ✅ OK     {status}")

        if not alerts:
            print()
            continue

        alerts_found = True

        # ── Build Telegram caption ───────────────────────────────────
        top_level  = max(alerts)
        head_emoji = "🔴" if top_level >= 20 else "🟠" if top_level >= 10 else "🟡"
        lvl_str    = "  |  ".join(f"⚠️ -{lvl}% breached" for lvl in sorted(alerts))

        caption = (
            f"{head_emoji} <b>{display_name}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Date</b>       : {today}\n"
            f"📈 <b>Peak</b>       : {peak_val:,.2f}  "
            f"<i>({peak_date.strftime('%d %b %Y')})</i>\n"
            f"📉 <b>Current</b>    : {curr_val:,.2f}\n"
            f"🔻 <b>Drawdown</b>   : <b>{dd_pct:.2f}%</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🚨 {lvl_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"#NiftyAlert  "
            f"#{''.join(w.capitalize() for w in display_name.split())}"
        )

        # ── Generate chart & send ────────────────────────────────────
        try:
            chart_png = make_chart(df, display_name,
                                   curr_val, peak_val, peak_date, dd_pct)
            send_photo(chart_png, caption)
            print("   📤 Chart sent to Telegram.")
        except Exception as e:
            print(f"   Chart error: {e} — sending text only.")
            send_text(caption)

        print()
        time.sleep(1.5)

    # ── Daily summary (always send) ──────────────────────────────────
    if results:
        send_summary(today, results)
        if not alerts_found:
            print("No drawdown alerts today. Summary sent.")

    print("\nDone.")


if __name__ == "__main__":
    main()
