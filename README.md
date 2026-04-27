# 📊 Nifty Drawdown Alert Bot

A fully automated Telegram bot that tracks Indian stock market indices and sends alerts when they fall from recent peaks.

---

## 🚀 Features

* 📉 Detects drawdowns from rolling peak (1-year)
* 🚨 Alerts at:

  * 5% dip
  * 10% correction
  * 20% crash
* 🕯️ Candlestick charts with drawdown highlight
* 🔁 Runs automatically 3 times daily
* 🆓 Completely free using GitHub Actions

---

## 📊 Indices Covered

* Nifty 50
* Nifty Next 50
* Nifty Midcap 150
* Nifty Smallcap 250
* Nifty Microcap 250*
* Nifty 200 Momentum 30*
* Nifty 500*

* Some indices may not always be available via Yahoo Finance

---

## ⚙️ Setup Guide

### 1. Create Telegram Bot

* Open Telegram → Search **BotFather**
* Run:

  ```
  /start
  /newbot
  ```
* Save your BOT TOKEN

---

### 2. Create Telegram Channel

* Create a new channel
* Add bot as **Admin**
* Note your channel username (e.g. `@yourchannel`)

---

### 3. Configure Secrets (GitHub)

Go to:
Settings → Secrets → Actions

Add:

* `BOT_TOKEN`
* `CHAT_ID` → (use `@yourchannel`)

---

### 4. Install Dependencies

```
pip install -r requirements.txt
```

---

### 5. Run Locally (Optional)

```
python bot.py
```

---

### 6. Automation (GitHub Actions)

The bot runs automatically:

* 10:00 AM IST
* 12:00 PM IST
* 3:40 PM IST

You can also trigger manually from **Actions tab**

---

## 🧠 How It Works

* Fetches historical data (Yahoo Finance)
* Calculates rolling peak (252 days)
* Measures drawdown %
* Sends alert only when a new level is crossed
* Generates candlestick chart with:

  * Peak overlay
  * Drawdown highlight
  * Latest drop annotation

---

## ⚠️ Disclaimer

This project is for educational purposes only.
Not financial advice. Always do your own research before investing.

---

## 💡 Future Improvements

* NSE API integration (all indices)
* Weekly summary alerts
* Multi-index comparison charts
* Dashboard / UI

---

## 🤝 Contributing

Feel free to fork and improve!

---

## ⭐ Support

If you find this useful, consider giving a ⭐ to the repo!
