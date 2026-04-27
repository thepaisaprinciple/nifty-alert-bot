"""
Nifty Index Drawdown Alert Bot  (v2 — fixed)
=============================================
Data sources (priority order):
  1. niftyindices.com  — POST API (official NSE Indices site, all 9 indices)
  2. Yahoo Finance     — fallback for the 4 broad indices that have YF tickers

Fixes vs v1:
  - Replaced broken NSE /api/historical/indicesHistory (changed endpoint)
  - Corrected Yahoo Finance tickers (NIFTYMIDCAP150.NS, NIFTYSMLCAP250.NS ...)
  - Removed emoji from matplotlib chart titles (no emoji fonts on GitHub Actions)
  - Proper cookie session for niftyindices.com
"""

import io
import os
import re
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

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID   = os.environ["CHAT_ID"]

ALERT_LEVELS = [5, 10, 20]
CHART_YEARS  = 3
DATA_YEARS   = 5

# niftyindices.com name  =>  Yahoo Finance ticker (None = no YF ticker)
INDICES = {
    "Nifty 50":                     {"ni": "NIFTY 50",                      "yf": "^NSEI"},
    "Nifty Next 50":                {"ni": "NIFTY NEXT 50",                 "yf": "^NSMIDCP"},
    "Nifty Midcap 150":             {"ni": "NIFTY MIDCAP 150",              "yf": "NIFTYMIDCAP150.NS"},
    "Nifty Smallcap 250":           {"ni": "NIFTY SMALLCAP 250",            "yf": "NIFTYSMLCAP250.NS"},
    "Nifty 200 Momentum 30":        {"ni": "NIFTY200 MOMENTUM 30",          "yf": None},
    "Nifty 500 Momentum 50":        {"ni": "NIFTY500 MOMENTUM 50",          "yf": None},
    "Nifty Midcap 150 Momentum 50": {"ni": "NIFTY MIDCAP150 MOMENTUM 50",  "yf": None},
    "Nifty 200 Value 30":           {"ni": "NIFTY200 VALUE 30",             "yf": None},
    "Nifty 500 Value 50":           {"ni": "NIFTY500 VALUE 50",             "yf": None},
}

# ─────────────────────────────────────────────────────────────────────
# DATA SOURCE 1: niftyindices.com
# ─────────────────────────────────────────────────────────────────────

_NI_BASE    = "https://www.niftyindices.com"
_NI_API_URL = f"{_NI_BASE}/Backpage.aspx/getHistoricaldatatabletoString"

_NI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Referer": f"{_NI_BASE}/reports/historical-data",
    "Origin": _NI_BASE,
}


def get_ni_session() -> requests.Session:
    """Open a cookie session with niftyindices.com."""
    s = requests.Session()
    s.headers.update(_NI_HEADERS)
    try:
        # Must visit the page first to get session cookies
        s.get(f"{_NI_BASE}/reports/historical-data", timeout=25)
        time.sleep(2)
    except Exception as e:
        print(f"  [NI session] warning: {e}")
    return s


def _parse_ni_html_table(html: str) -> pd.DataFrame:
    """
    niftyindices.com returns an HTML <table> string inside {"d": "..."}.
    Parse it into [date, close] DataFrame.
    """
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return pd.DataFrame()
    if not tables:
        return pd.DataFrame()

    df = tables[0]

    # Find date column and close/price column by name pattern
    date_col  = next((c for c in df.columns if re.search(r"date", str(c), re.I)), None)
    close_col = next(
        (c for c in df.columns if re.search(r"clos|price", str(c), re.I)), None
    )
    # Positional fallback
    if date_col is None:  date_col  = df.columns[0]
    if close_col is None: close_col = df.columns[1]

    out = pd.DataFrame({
        "date":  pd.to_datetime(df[date_col],  dayfirst=True, errors="coerce"),
        "close": pd.to_numeric(df[close_col].astype(str).str.replace(",", ""),
                               errors="coerce"),
    })
    return out.dropna().sort_values("date").reset_index(drop=True)


def fetch_niftyindices(session: requests.Session, ni_name: str,
                       years: int = DATA_YEARS) -> pd.DataFrame:
    """
    Fetch up to `years` of data from niftyindices.com in ~1-year chunks.
    Date format required: DD-Mon-YYYY  e.g. 01-Jan-2023
    """
    end   = datetime.today()
    start = end - timedelta(days=365 * years + 30)
    chunks, cursor = [], end

    while cursor > start:
        chunk_start = max(start, cursor - timedelta(days=364))
        payload = {
            "name":      ni_name,
            "startDate": chunk_start.strftime("%d-%b-%Y"),
            "endDate":   cursor.strftime("%d-%b-%Y"),
        }
        try:
            r = session.post(_NI_API_URL, json=payload, timeout=30)
            r.raise_for_status()
            raw      = r.json()
            html_str = raw.get("d", "")
            if html_str and len(html_str) > 100:
                chunk_df = _parse_ni_html_table(html_str)
                if not chunk_df.empty:
                    chunks.append(chunk_df)
                    print(f"    NI OK [{chunk_start.date()} -> {cursor.date()}]"
                          f"  rows={len(chunk_df)}")
                else:
                    print(f"    NI empty table [{chunk_start.date()} -> {cursor.date()}]")
            else:
                print(f"    NI no data [{chunk_start.date()} -> {cursor.date()}]"
                      f"  response={r.text[:80]}")
            time.sleep(1.2)
        except Exception as e:
            print(f"    NI error [{chunk_start.date()} -> {cursor.date()}]: {e}")

        cursor = chunk_start - timedelta(days=1)

    if not chunks:
        return pd.DataFrame()

    return (
        pd.concat(chunks)
        .drop_duplicates("date")
        .sort_values("date")
        .reset_index(drop=True)
    )


# ─────────────────────────────────────────────────────────────────────
# DATA SOURCE 2: Yahoo Finance  (fallback)
# ─────────────────────────────────────────────────────────────────────

def fetch_yfinance(ticker: str, years: int = DATA_YEARS) -> pd.DataFrame:
    try:
        import yfinance as yf
        start = datetime.today() - timedelta(days=365 * years + 30)
        raw   = yf.download(ticker, start=start, progress=False, auto_adjust=True)
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
    peak_idx  = df["close"].idxmax()
    peak_val  = df.loc[peak_idx, "close"]
    peak_date = df.loc[peak_idx, "date"]
    curr_val  = df.iloc[-1]["close"]
    drawdown  = (curr_val - peak_val) / peak_val * 100
    return float(curr_val), float(peak_val), float(drawdown), peak_date


def breached_levels(drawdown_pct: float) -> list:
    return [lvl for lvl in ALERT_LEVELS if drawdown_pct <= -lvl]


# ─────────────────────────────────────────────────────────────────────
# CHART  (ASCII-only title — no emoji, GitHub Actions has no emoji font)
# ─────────────────────────────────────────────────────────────────────

BAR_PALETTE = {
    "ok":     "#2ecc71",
    "warn":   "#f39c12",
    "danger": "#e74c3c",
    "crash":  "#922b21",
}

def _bar_color(dd: float) -> str:
    if dd <= -20: return BAR_PALETTE["crash"]
    if dd <= -10: return BAR_PALETTE["danger"]
    if dd <= -5:  return BAR_PALETTE["warn"]
    return BAR_PALETTE["ok"]

def _severity(dd: float) -> str:
    if dd <= -20: return "[CRASH -20%+]"
    if dd <= -10: return "[DANGER -10%+]"
    if dd <= -5:  return "[ALERT -5%+]"
    return "[OK]"


def make_chart(df: pd.DataFrame, index_name: str,
               curr_val: float, peak_val: float,
               peak_date, drawdown_pct: float) -> bytes:
    cutoff  = datetime.today() - timedelta(days=365 * CHART_YEARS)
    df_plot = df[df["date"] >= cutoff].copy()
    df_plot.set_index("date", inplace=True)

    monthly = (
        df_plot["close"].resample("ME").last().dropna().reset_index()
    )
    monthly.columns = ["date", "close"]
    monthly["peak"] = monthly["close"].cummax()
    monthly["dd"]   = (monthly["close"] - monthly["peak"]) / monthly["peak"] * 100
    colors = [_bar_color(d) for d in monthly["dd"]]
    colors[-1] = _bar_color(drawdown_pct)

    fig, ax = plt.subplots(figsize=(15, 6), facecolor="#0d1117")
    ax.set_facecolor("#161b22")
    ax.bar(monthly["date"], monthly["close"],
           width=22, color=colors, edgecolor="none", alpha=0.90)
    ax.axhline(y=peak_val, color="#f1c40f", linestyle="--", linewidth=1.6, alpha=0.85,
               label=f"All-time High: {peak_val:,.0f}  ({peak_date.strftime('%d %b %Y')})")

    last_date = monthly["date"].iloc[-1]
    ax.annotate(
        f"  -{abs(drawdown_pct):.1f}% from peak\n  Now: {curr_val:,.0f}",
        xy=(last_date, curr_val), xytext=(-90, -55), textcoords="offset points",
        color="white", fontsize=9.5, fontweight="bold",
        arrowprops=dict(arrowstyle="->", color="#e74c3c", lw=1.5),
        bbox=dict(boxstyle="round,pad=0.45", facecolor=_bar_color(drawdown_pct), alpha=0.85),
    )

    # Pure ASCII title — no emoji glyphs
    ax.set_title(
        f"{_severity(drawdown_pct)}  {index_name}  |  {CHART_YEARS}-Year Monthly Chart",
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

    legend_patches = [
        mpatches.Patch(facecolor=BAR_PALETTE["ok"],     label="< 5% drawdown"),
        mpatches.Patch(facecolor=BAR_PALETTE["warn"],   label="5-10% drawdown"),
        mpatches.Patch(facecolor=BAR_PALETTE["danger"], label="10-20% drawdown"),
        mpatches.Patch(facecolor=BAR_PALETTE["crash"],  label="> 20% drawdown"),
    ]
    ax.legend(handles=legend_patches + ax.lines,
              loc="upper left", facecolor="#21262d", edgecolor="#30363d",
              labelcolor="white", fontsize=8.5, framealpha=0.9)

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
    _tg_post("sendPhoto",
             files={"photo": ("chart.png", photo_bytes, "image/png")},
             data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"})


def send_text(text: str):
    _tg_post("sendMessage",
             data={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"})


def send_summary(today: str, results: list):
    lines = ["\U0001F4CA <b>Nifty Daily Summary \u2014 " + today + "</b>\n"]
    for r in results:
        icon = "\U0001F534" if r["dd"] <= -10 else "\U0001F7E0" if r["dd"] <= -5 else "\U0001F7E2"
        lines.append(f"{icon} <b>{r['name']}</b>: {r['curr']:,.0f}  ({r['dd']:+.1f}% from peak)")
    send_text("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    today = datetime.today().strftime("%d %b %Y")
    print(f"\n{'='*57}")
    print(f"  Nifty Alert Bot (v2)  --  {today}")
    print(f"{'='*57}\n")

    ni_session   = get_ni_session()
    alerts_found = False
    results      = []

    for display_name, cfg in INDICES.items():
        print(f"\n-> {display_name}")
        df = pd.DataFrame()

        # 1. niftyindices.com
        print(f"   Trying niftyindices.com ({cfg['ni']}) ...")
        df = fetch_niftyindices(ni_session, cfg["ni"])
        if not df.empty:
            print(f"   OK: {len(df)} rows  "
                  f"[{df['date'].iloc[0].date()} -> {df['date'].iloc[-1].date()}]")

        # 2. Yahoo Finance fallback
        if df.empty and cfg.get("yf"):
            print(f"   Falling back to Yahoo Finance ({cfg['yf']}) ...")
            df = fetch_yfinance(cfg["yf"])
            if not df.empty:
                print(f"   OK (YF): {len(df)} rows")

        if df.empty or len(df) < 30:
            print("   WARNING: Insufficient data, skipping.")
            continue

        curr_val, peak_val, dd_pct, peak_date = compute_drawdown(df)
        alerts  = breached_levels(dd_pct)
        results.append({"name": display_name, "curr": curr_val, "dd": dd_pct})

        status = f"cur={curr_val:,.0f}  peak={peak_val:,.0f}  dd={dd_pct:.2f}%"
        print(f"   {'ALERT' if alerts else 'OK'}  {status}"
              + (f"  levels={alerts}" if alerts else ""))

        if not alerts:
            continue

        alerts_found = True
        top_level = max(alerts)
        head_icon = (
            "\U0001F534" if top_level >= 20 else
            "\U0001F7E0" if top_level >= 10 else
            "\U0001F7E1"
        )
        lvl_str = "  |  ".join(f"⚠️ -{lvl}% breached" for lvl in sorted(alerts))

        caption = (
            f"{head_icon} <b>{display_name}</b>\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001F4C5 <b>Date</b>       : {today}\n"
            f"\U0001F4C8 <b>Peak</b>       : {peak_val:,.2f}  <i>({peak_date.strftime('%d %b %Y')})</i>\n"
            f"\U0001F4C9 <b>Current</b>    : {curr_val:,.2f}\n"
            f"\U0001F53B <b>Drawdown</b>   : <b>{dd_pct:.2f}%</b>\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001F6A8 {lvl_str}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"#NiftyAlert  #{''.join(w.capitalize() for w in display_name.split())}"
        )

        try:
            chart_png = make_chart(df, display_name, curr_val, peak_val, peak_date, dd_pct)
            send_photo(chart_png, caption)
            print("   Chart sent to Telegram.")
        except Exception as e:
            print(f"   Chart error: {e} -- sending text only.")
            send_text(caption)

        time.sleep(1.5)

    if results:
        send_summary(today, results)
        if not alerts_found:
            print("\nNo drawdown alerts today. Summary sent.")

    print("\nDone.")


if __name__ == "__main__":
    main()
  
