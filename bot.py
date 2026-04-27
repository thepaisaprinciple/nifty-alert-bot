import matplotlib
matplotlib.use('Agg')

import yfinance as yf
import pandas as pd
import requests
import mplfinance as mpf
import matplotlib.pyplot as plt
import json
import os
import math

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# -------------------------
# SETTINGS
# -------------------------
TEST_MODE = True  # change to False when going live

INDICES = {
    "Nifty 50": "^NSEI",
    "Nifty Next 50": "^NSMIDCP",
    "Nifty Midcap 150": "NIFTYMIDCAP150.NS",
    "Nifty Smallcap 250": "NIFTYSMLCAP250.NS",
    "Nifty Microcap 250": "NIFTY_MICROCAP250.NS",
    "Nifty 200 Momentum 30": "NIFTY200MOMENTM30.NS"
}

# -------------------------
# STATE
# -------------------------
def load_state():
    try:
        with open("state.json", "r") as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    with open("state.json", "w") as f:
        json.dump(state, f)

# -------------------------
# FETCH DATA
# -------------------------
def get_data(symbol):
    try:
        data = yf.download(symbol, period="3y", interval="1d")

        if data is None or data.empty:
            return None

        if 'Close' not in data.columns:
            return None

        return data

    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

# -------------------------
# CALCULATE (FINAL FIXED)
# -------------------------
def calculate(data):
    try:
        df = data.copy()

        # Ensure required columns exist
        required_cols = ['Open', 'High', 'Low', 'Close']
        for col in required_cols:
            if col not in df.columns:
                print(f"Missing column: {col}")
                return None

        close = df['Close']
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]

        close = close.dropna()
        if close.empty:
            return None

        # Calculate rolling peak
        df.loc[:, 'Rolling Peak'] = close.rolling(252).max()

        # Drop invalid rows
        df = df.dropna(subset=['Rolling Peak'])

        if df.empty:
            return None

        # Calculate drawdown
        df.loc[:, 'Drawdown %'] = (
            (df['Close'] - df['Rolling Peak']) / df['Rolling Peak']
        ) * 100

        return df

    except Exception as e:
        print(f"Calculation error: {e}")
        return None
# -------------------------
# ALERT LEVEL
# -------------------------
def get_level(dd):
    if dd <= -20:
        return "🔴 20% Crash"
    elif dd <= -10:
        return "🟠 10% Correction"
    elif dd <= -5:
        return "🟡 5% Dip"
    return None

# -------------------------
# CHART
# -------------------------
def generate_chart(data, name):
    filename = f"/tmp/{name.replace(' ', '_')}.png"

    try:
        data = data.tail(300).copy()

        apds = [
            mpf.make_addplot(data['Rolling Peak'], linestyle='dashed')
        ]

        fig, axlist = mpf.plot(
            data,
            type='candle',
            style='yahoo',
            addplot=apds,
            returnfig=True,
            volume=False,
            title=name
        )

        ax = axlist[0]

        ax.fill_between(
            data.index,
            data['Close'],
            data['Rolling Peak'],
            where=(data['Close'] < data['Rolling Peak']),
            alpha=0.2
        )

        latest_price = data['Close'].iloc[-1]
        latest_dd = data['Drawdown %'].iloc[-1]

        ax.scatter(data.index[-1], latest_price, s=80)

        ax.annotate(
            f"{latest_dd:.2f}%",
            (data.index[-1], latest_price),
            xytext=(-60, 30),
            textcoords='offset points',
            arrowprops=dict(arrowstyle="->")
        )

        plt.savefig(filename, bbox_inches='tight')
        plt.close()

        print("Chart saved:", filename)
        return filename

    except Exception as e:
        print(f"Chart error {name}: {e}")
        return None

# -------------------------
# TELEGRAM
# -------------------------
def send(msg, img=None):
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={
                "chat_id": CHAT_ID,
                "text": msg,
                "parse_mode": "HTML"
            }
        )
        print("Message response:", response.text)

        if img and os.path.exists(img):
            with open(img, 'rb') as f:
                response = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                    data={"chat_id": CHAT_ID},
                    files={"photo": f}
                )
            print("Photo response:", response.text)

    except Exception as e:
        print("Telegram error:", e)

# -------------------------
# MAIN
# -------------------------
def run():
    state = load_state()

    for name, symbol in INDICES.items():
        print(f"Processing {name}")

        data = get_data(symbol)
        if data is None:
            continue

        data = calculate(data)
        if data is None or data.empty:
            continue

        latest = data.iloc[-1]
        dd = latest['Drawdown %']

        try:
            if isinstance(dd, pd.Series):
                dd = dd.iloc[0]

            dd = float(dd)

            if math.isnan(dd):
                continue

        except:
            continue

        level = get_level(dd)

        # -------------------------
        # TEST MODE → send everything
        # -------------------------
        if TEST_MODE:
            msg = f"📊 <b>{name}</b>\nDrawdown: {dd:.2f}%"
            if level:
                msg += f"\n{level}"

            chart = generate_chart(data, name)
            send(msg, chart)
            continue

        # -------------------------
        # PRODUCTION MODE
        # -------------------------
        if not level:
            continue

        if state.get(name) == level:
            continue

        msg = f"{level}\n<b>{name}</b>\nDrawdown: {dd:.2f}%"
        chart = generate_chart(data, name)

        send(msg, chart)
        state[name] = level

    save_state(state)

# -------------------------
# RUN
# -------------------------
if __name__ == "__main__":
    run()
