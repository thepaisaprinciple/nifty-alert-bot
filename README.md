# 📈 Nifty Alert Bot

A free, zero-infrastructure Telegram bot that monitors **9 Nifty indices** and fires alerts whenever any index drops **5% / 10% / 20%** from its rolling peak — with a beautiful 3-year bar chart attached.

---

## 🗂️ Files

```
nifty-alert-bot/
├── .github/
│   └── workflows/
│       └── nifty_alert.yml   ← GitHub Actions scheduler
├── nifty_alert.py             ← Main bot script
├── requirements.txt
└── README.md
```

---

## 📊 Indices Monitored

| Index | NSE API Name |
|---|---|
| Nifty 50 | NIFTY 50 |
| Nifty Next 50 | NIFTY NEXT 50 |
| Nifty Midcap 150 | NIFTY MIDCAP 150 |
| Nifty Smallcap 250 | NIFTY SMALLCAP 250 |
| Nifty 200 Momentum 30 | NIFTY200 MOMENTUM 30 |
| Nifty 500 Momentum 50 | NIFTY500 MOMENTUM 50 |
| Nifty Midcap 150 Momentum 50 | NIFTY MIDCAP150 MOMENTUM 50 |
| Nifty 200 Value 30 | NIFTY200 VALUE 30 |
| Nifty 500 Value 50 | NIFTY500 VALUE 50 |

---

## 🚀 Setup Guide

### Step 1 — Create a Telegram Bot

1. Open Telegram → search **@BotFather**
2. Send `/newbot` and follow prompts
3. Copy the **BOT_TOKEN** you receive

### Step 2 — Get your Chat ID

**For a group/channel:**
1. Add the bot to your channel/group as admin
2. Send any message in the channel
3. Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
4. Find `"chat":{"id": -XXXXXXXXX}` — that's your **CHAT_ID** (negative number for groups)

**For personal chat:**
1. Start a conversation with your bot
2. Same URL as above → `"chat":{"id": XXXXXXXXX}`

### Step 3 — Add GitHub Secrets

In your repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret Name | Value |
|---|---|
| `BOT_TOKEN` | Your Telegram bot token |
| `CHAT_ID` | Your channel/group chat ID |

### Step 4 — Push Files

```bash
git clone https://github.com/YOUR_USERNAME/nifty-alert-bit
cd nifty-alert-bit

# Copy all files from this repo into it
# Then:
git add .
git commit -m "Add Nifty Alert Bot"
git push
```

### Step 5 — Test it manually

1. Go to your repo → **Actions** tab
2. Click **"Nifty Alert Bot"** → **"Run workflow"** → **Run**
3. Check your Telegram channel!

---

## ⏰ Schedule

The bot runs automatically **twice on weekdays**:

| Time (IST) | Purpose |
|---|---|
| 9:00 AM | Pre-market check |
| 3:45 PM | Post-market close check |

To change the schedule, edit `.github/workflows/nifty_alert.yml`:
```yaml
- cron: "15 10 * * 1-5"   # 3:45 PM IST = 10:15 UTC
```

---

## 📬 What You'll Receive

### 🚨 Alert Message (with chart)
```
🟠 Nifty Midcap 150

📅 Date    : 27 Apr 2025
📈 Peak    : 22,500.00  (15 Sep 2024)
📉 Current : 19,800.00
🔻 Drawdown: -12.00%

🚨 ⚠️ -5% breached  |  ⚠️ -10% breached
#NiftyAlert #NiftyMidcap150
```
*...plus a dark-themed monthly bar chart for the past 3 years*

### ✅ Daily Summary (always sent)
```
📊 Nifty Daily Summary — 27 Apr 2025

🟢 Nifty 50: 24,100  (+0.2% from peak)
🟢 Nifty Next 50: 69,800  (-1.1% from peak)
🟠 Nifty Midcap 150: 19,800  (-12.0% from peak)
...
```

---

## 💡 Customisation

### Change alert thresholds
In `nifty_alert.py`:
```python
ALERT_LEVELS = [5, 10, 20]   # change to whatever you want, e.g. [3, 7, 15]
```

### Change chart history
```python
CHART_YEARS = 3   # or 5 for 5-year chart
```

### Add more indices
```python
INDICES["Nifty Bank"] = {"nse": "NIFTY BANK", "yf": "^NSEBANK"}
```

---

## 💸 Cost

**100% Free:**
- GitHub Actions: 2,000 free minutes/month (you'll use ~5 min/day)
- NSE India API: Free public API
- Yahoo Finance: Free via `yfinance`
- Telegram Bot API: Free

---

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| No data for momentum/value indices | NSE API sometimes throttles — bot retries automatically |
| "Chat not found" error | Make sure bot is added to the channel as admin |
| Workflow not running | Check Actions are enabled in repo settings |
| Bot token invalid | Regenerate via @BotFather using `/token` |
