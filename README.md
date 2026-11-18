# TradingView Analysis Bot: User Guide

This app is written for someone **new to investing**. It watches US shares, NZ shares (NZX), crypto coins and currency pairs (forex) using TradingView's free data, and helps you with four questions, in this order:

1. **Is there a sensible idea today?** It scores how strong and steady each price trend looks, runs safety checks, and shows only the ideas that pass every one, as plain-English **idea cards**. Some days there are none, and staying out is a perfectly good decision.
2. **Is the business OK, and is the news OK?** Each card has a quick look at the company and the mood of recent headlines.
3. **How much should I put in, and when would I get out?** Each card shows a **safety level** (the price where you'd sell if things go wrong) and a dollar amount, worked out so a bad outcome costs you only about 1% of your money.
4. **I own it: what should I do now?** Each holding shows **All fine**, **Keep an eye on it** or **Think about selling**, with an alert when that changes.

TradingView's own verdict on each price trend (its **chart signal**, from 26 chart tools) runs from **Strong Buy · Buy · Neutral · Sell · Strong Sell**.

**Beginner mode** is on at first. It keeps the screens simple (see [section 3](#3-starting-the-app)). The app **never buys or sells anything**; you do that yourself, e.g. in Sharesies.

> ⚠️ **This is not financial advice.** The app reads chart patterns, plus a quick look at company figures and headlines. It doesn't know your personal situation. Use it as one opinion among many, and start with the **Learn** page.

---

## Contents
1. [What's in the folder](#1-whats-in-the-folder)
2. [First-time setup](#2-first-time-setup)
3. [Starting the app](#3-starting-the-app)
4. [Reading the market tables](#4-reading-the-market-tables)
5. [Your portfolio](#5-your-portfolio)
6. [Other pages](#6-other-pages)
7. [Changing what the app watches](#7-changing-what-the-app-watches)
8. [Problems and fixes](#8-problems-and-fixes)
9. [Moving to another computer](#9-moving-to-another-computer)
10. [Checking the app works](#10-checking-the-app-works)

---

## 1. What's in the folder

| File | What it is |
|---|---|
| `start_app.bat` (Windows) / `start_app.command` (Mac) | **Starts the app in your web browser.** This is the one you double-click. The setup also puts a **"TradingView Bot"** shortcut on your desktop. |
| `settings.py` | **What the app watches** (watchlists, refresh rate). Open it in any text editor to change things (section 7). |
| `setup_windows.bat` | One-click setup for Windows PCs |
| `setup_mac.sh` | Setup for Apple Macs |
| `portfolio.json` | **Your saved holdings and profit/loss.** It's created the first time you add a holding. Don't delete it. |
| `run_tests.bat` / `run_tests.sh` | Runs a full check of the app (see [section 10](#10-checking-the-app-works)) |
| `portfolio.json.bak` | An automatic backup of your portfolio from just before the last change |
| `practice_portfolio.json` | Your **Practice** portfolio (pretend money), kept separate from the real one |
| `signals.json` | The **Track record**: every QUALIFIED and EARLY pick the app has logged, with the prices it has seen for each since, used to show how the signals have done |
| `check_track_record.bat` (Windows) / `check_track_record.sh` (Mac) | Shows the Track record **without opening the app** (see [Track record](#business-column-track-record-and-practice)) |
| `preferences.json` | Your choices: Beginner mode on/off, your **total invested** (used for the "How much?" answers), and, if **Remember these settings** is on, the Dashboard's timeframe and refresh settings |
| `app.py`, `tvbot_ui.py`, `tvbot_core.py`, `assets`, `.streamlit`, `tests`, `requirements.txt` | The app's program files. You can ignore them. |
| `.venv` folder | Created by the setup. You can ignore it. |
---

## 2. First-time setup

### Getting the app
1. Download **`TradingViewBot.zip`** from the Google Drive link you were given.
2. Unzip it somewhere permanent, such as your Documents folder (not your Downloads folder, which some computers clear out):
   - **Windows:** right-click the zip → **Extract All…** → choose a folder → **Extract**.
   - **Mac:** double-click the zip. A **TradingViewBot** folder appears; move it to Documents.
3. Follow the steps below for your computer, using the files in that folder.

You only need to do this **once per computer**. It installs everything the app needs: Python and some add-ons. It also puts a **"TradingView Bot"** shortcut on your desktop. Anything that's already installed is skipped.

You'll need an internet connection. Setup usually takes **15–30 minutes** (longer on slow internet): the news feature needs a large add-on (about 1 GB in total). The first time news is rated, the app also downloads its news-reading model once (about 440 MB) in the background; the app works normally while that happens.

### On Windows
1. Open the app's folder.
2. **Double-click `setup_windows.bat`.**
3. A black window appears and shows its progress in 3 steps.
   - If Windows shows a blue box saying *"Windows protected your PC"*, click **More info**, then **Run anyway**.
   - If it asks for permission to install something, click **Yes**.
4. When you see **"Setup complete"**, the app opens in your web browser.

### On a Mac
1. Open **Terminal**. Press **⌘ Cmd + Space**, type `Terminal` and press **Enter**.
2. Type `bash` followed by **one space**. Don't press Enter yet.
3. Drag the file **`setup_mac.sh`** from Finder into the Terminal window. Its location is filled in for you.
4. Press **Enter**.
5. If it asks for your **password**, type your Mac login password and press Enter. Nothing appears on screen while you type; that's normal.
   - If your Mac says a file "can't be opened because it is from an unidentified developer", use the Terminal method above rather than double-clicking. After setup has run once, double-clicking works.
6. When you see **"Setup complete"**, the app opens in your web browser.

---

## 3. Starting the app

1. **Double-click "TradingView Bot"** on your desktop. You can also double-click `start_app.bat` (Windows) or `start_app.command` (Mac) in the app's folder.
2. A small black window opens (Terminal on a Mac), and **your web browser opens the app** a few seconds later.
3. The app opens on the **Home** page. It shows *"Loading from TradingView…"* for a few seconds, then fills in by itself.
4. Use the **menu along the top** to move between pages, in the order you'll need them: **Home · Learn · Top Picks · My Portfolio**. The more detailed pages (**Dashboard · Market Scan · Symbol Details**) are under **Advanced**.

> 🏠 **The app opens on Home**, which is where to start:
> - **Beginner mode** switch (on at first). **On:** ratings always use the 1 Day chart (what the scores are designed for), every market refreshes by itself every 15 minutes while it trades, Market Scan leaves out small US companies, and the Dashboard hides its timeframe and refresh controls. **Off:** all the controls. The app remembers your choice.
> - **Your portfolio:** its value and profit in NZ dollars.
> - **Needs your attention:** holdings on *Think about selling* (worst first, with the reason), plus today's alerts. If nothing needs you, it says so.
> - **Your total invested:** everything you have invested, in NZ$ (not your emergency fund). The idea cards use it to work out how much to put into one idea. It stays on your computer.
> - **Today's strongest idea:** the best **share** idea in your watchlists, as an idea card (see [Top Picks](#6-other-pages)). Crypto and forex are left out here because Sharesies doesn't offer them.
> - **Your path, step by step:** seven steps from *Learn the basics* to *Check the app's own record*, each linking to the page that does it.
>
> Home makes no TradingView requests of its own; it uses the data the app already has.

> 💾 **Data is kept, not re-loaded.** Once the app has loaded something from TradingView, it's kept: refreshing the browser page, switching pages or coming back to a timeframe shows it again instantly, with its time ("updated 14:32"), and doesn't ask TradingView again. The app only fetches when you click a **Refresh** button, when a market's **auto-refresh** is on, or when it needs data it doesn't have yet (e.g. a timeframe you haven't opened). Pages also share data: Plan your exit, the Business column and the timeframe check reuse what the Dashboard and Market Scan have already loaded.

> 🎓 **New to investing?** Start with the **Learn** page. It's written for New Zealand investors using **Sharesies**: three rules to start with, how to go from an idea in the app to an order in Sharesies, a position-size calculator, how NZ and US shares and funds differ, and NZ costs and tax.

**On every page:**
- **Status chips** under the title show each market: a green dot when it's open (or trades around the clock), grey when it's closed, and how long ago its data updated. ⟳ means it refreshes by itself.
- **Alerts** (top right) lists what changed recently. A new alert also pops up in the corner of any open page: when one of your holdings moves to **Think about selling**, or there's a new buy idea on Top Picks. Alerts only work while the app is running.
- **Names:** every table shows the company or coin name next to its code (e.g. *FPH Fisher & Paykel Healthcare*). For forex it says what the pair is doing, e.g. *NZ dollar vs US dollar: the NZ dollar is getting weaker against the US dollar*.
- **What do these columns mean?** Under each main table, this fold-out explains every column in plain words. (You can also hover over a heading.)
- **Chart links:** **Open ↗** in a table's *Chart* column opens that symbol's chart on tradingview.com.

**That's it.** Everything loads when the app starts. In Beginner mode every market then refreshes by itself; with it off, turn on a market's **Auto-refresh** switch on the Dashboard (see section 4).

> The app quietly checks itself every time it starts. If everything is fine you won't see anything. If something is badly wrong, you'll see a red **"The app could not start"** page explaining what to fix (see [section 8](#8-problems-and-fixes)). Smaller warnings, such as TradingView being busy, appear only in the black window.

> ⚠️ **Keep the black window open** while you use the app; you can minimise it. **To stop the app, close that window.** Your portfolio is saved automatically.

> 💡 **The browser didn't open?** Open your web browser yourself and go to **http://localhost:8501**.
>
> 🔒 The app is only reachable from your own computer. Other people on your network can't open it.

---

## 4. Reading the market tables

Click **Advanced → Dashboard** in the menu. It's the raw view of every market the app watches; for buy ideas, use **Top Picks**. There are four tables: **Crypto**, **US Stocks**, **NZ Stocks** and **Forex**. Each has a fold-out, **What are … ? How risky? Where can I buy them?**, that explains that kind of market in plain words.

> 🔰 **In Beginner mode** the Dashboard has no timeframe or auto-refresh controls: ratings use the 1 Day chart and every market refreshes by itself every 15 minutes while it's open. The buttons below are what you see with Beginner mode **off** (switch it on Home).

> 🕒 **Closed markets aren't re-fetched.** The US and NZ share markets only trade on weekdays (US 9:30am–4pm New York time, NZX 10am–4:45pm NZ time). Once the app has the final data from a session, it stops asking TradingView for that market until it opens again, and its table says **market closed**. Nothing can change while it's closed, and this keeps the app well clear of TradingView's request limits. Crypto and forex refresh as normal. Public holidays aren't known to the app, so on those days it just refreshes as usual.

### The buttons

| Button | What it does |
|---|---|
| **Timeframe** | Which chart the ratings are based on: **1 Hour, 4 Hours, 1 Day, 1 Week** or **4 Weeks**. Each market's table appears as soon as it's loaded, usually within a few seconds. The app keeps every timeframe it has loaded, so switching back to one you've viewed is instant and costs no request (its time shows how old it is; click Refresh for the latest). If you switch many times quickly, TradingView may ask the app to slow down; a yellow notice then shows how long until it tries again, and the tables catch up by themselves. It applies to every page, including the ratings on your portfolio page (the safety levels there always use the daily chart). Short timeframes react quickly but are noisier; long ones show the bigger trend. *4 Weeks* uses TradingView's monthly chart. The app starts on 1 Day each time; you can change the starting timeframe in `settings.py`. |
| **Auto-refresh** (on each market) | Each market has its own switch, **off by default**. Turn it on and pick how often in the box next to it: **1 min, 5 min, 15 min, 30 min, 1 hour or 4 hours**. The market's status line shows when it will next refresh, or *auto-refresh off*. With it off, that market only updates when you click Refresh. It also controls how often your holdings in that market update. The settings last until you close the app; when it restarts, every switch is off again, unless **Remember these settings** is on. Short intervals on several markets use more of TradingView's request allowance. |
| **Remember these settings** | Off by default. Turn it on to keep your timeframe and every market's auto-refresh choice for the next time you start the app. They're saved in `preferences.json` next to your portfolio. Turn it off to go back to starting on 1 Day with auto-refresh off. |
| **Market summary** (under the buttons) | Each market's count of Strong Buy · Buy · Neutral · Sell · Strong Sell. Click one to jump to its table. |
| **Refresh all** | Updates every market now (except a closed market that already has its final data) |
| **Refresh Crypto / US Stocks / NZ Stocks / Forex** | Updates just that market, even if it's closed |

Next to each button you'll see **"updated 14:30:05"**, the time of the last update.

### The table columns

Each table is sorted with the **most positive at the top** and the most negative at the bottom.

| Column | Meaning |
|---|---|
| **Symbol** | The code of the coin, share or currency pair, e.g. `BTCUSDT` = Bitcoin priced in US dollars |
| **Name** | The company or coin, or for forex what the pair is doing |
| **Price** | Current price |
| **Chart signal** | TradingView's overall verdict (see colours below) |
| **Buy / Neutral / Sell** | How many of the 26 chart tools say each thing |
| **Indicator balance** | A single number from **-1** (every chart tool says Sell) to **+1** (every one says Buy) |
| **Short-term signals** | The verdict from the 11 chart tools that look at the last few days or weeks |
| **Trend signals** | The verdict from the 15 chart tools that follow the longer trend (moving averages) |

### The colours

| Colour | Chart signal | In plain English |
|---|---|---|
| 🟩 Dark green | **Strong Buy** | Almost all signals are positive |
| 🟢 Light green | **Buy** | Most signals are positive |
| ⬜ Grey | **Neutral** | Mixed or no clear direction |
| 🔴 Pink | **Sell** | Most signals are negative |
| 🟥 Dark red | **Strong Sell** | Almost all signals are negative |

**Example:** `Strong Sell, Buy 1, Neutral 10, Sell 15` means 15 of the 26 indicators say Sell and only 1 says Buy.

---

## 5. Your portfolio

Click **My Portfolio** in the menu. A short **"How the portfolio works"** link on that page opens a summary of everything below.

### Adding something you bought

| Box | What to enter |
|---|---|
| **Market** | Pick Crypto, US Stocks, NZ Stocks or Forex |
| **Code** | The short code, e.g. `BTC`, `ETH`, `AAPL` (Apple), `FPH` (Fisher & Paykel Healthcare), `NZDUSD`. Top Picks and the Dashboard show each code next to its name. |
| **Price you paid for ONE share or coin** | See the currency note below (it's also on the form) |
| **How many you bought** | E.g. `0.05` Bitcoin or `20` shares |

Click the blue **Add holding** button at the top of the page, fill in the boxes, then click **Add holding** in the box. A message pops up in the corner to confirm. If something is wrong (e.g. a missing price), a red message stays on the page until you fix it.

- You'll see *"Checking … on TradingView"*, then a green **"Added"** message within a few seconds.
- A **red message** means the symbol wasn't recognised. Check the spelling and the Market you picked.
- **TradingView busy?** The holding is still saved, with a message saying it will be checked on the next refresh. Until then it shows **Checking...**. If the symbol turns out not to exist, it shows **Not found**; delete it and add it again.
- **Bought the same thing more than once at different prices?** Add each purchase as a separate holding.

> 💱 **Currency note:** enter prices in the currency TradingView uses:
> - **Crypto:** US dollars (USDT)
> - **US shares:** US dollars
> - **Forex:** the *second* currency of the pair. For `NZDUSD`, that's US dollars.
>
> If you paid in NZ dollars, convert to US dollars first.

### Selling all or part of a holding

| Box | What to enter |
|---|---|
| **Holding** | Pick which holding you sold from the list |
| **Sell everything in this holding** | Tick this if you sold all of it, and you can leave the quantity empty |
| **Quantity to sell** | How many you sold, if you sold only part |
| **Sell price** | The price you sold at. **Leave it at 0** to use today's market price. |

These boxes open from the **Sell or delete** button at the top of the page. Then click **Sell**. The profit or loss on that sale is recorded, and anything you didn't sell stays in your portfolio.

**Delete holding** removes a holding you entered by mistake. It **doesn't** record any profit or loss.

### What the app tells you to do

Every holding gets one of three messages, and the holdings are grouped under them, most urgent first:

| Message | Meaning |
|---|---|
| 🔴 **Think about selling** | The price is near or below your safety level, or the chart signals have turned down. **Look at it and decide.** The line under the holding says how strong the warning is, from *"take a look"* to *"this is the strongest warning: selling is worth serious thought"*. |
| 🟡 **Keep an eye on it** | Nothing to do now, just check it now and then. |
| 🟢 **All fine** | Nothing to do. |

Holdings still being checked go under a grey *Waiting For Data* heading at the end. Under each group, every holding has a one-line reason in plain English, e.g. *"The price can fall 6.2% (to 57,200) before it reaches your safety level. You are up 16.7% on what you paid. Chart signal: Strong Buy."*

> 🛑 **The app never buys or sells anything.** The messages are there to help you decide; you sell in Sharesies yourself.

### The holdings table

| Column | Meaning |
|---|---|
| **Name** | The company, coin or currency pair |
| **Quantity / Paid (each) / Price now** | How many you hold, what you paid for one, and today's price |
| **Currency** | The currency the prices are in |
| **Value (NZ$)** | What the holding is worth today, in NZ dollars |
| **Profit/loss**, **Profit/loss %**, **Profit/loss (NZ$)** | Your profit (green) or loss (red) so far, in the price's currency, as a %, and in NZ dollars |
| **Chart signal** | TradingView's verdict on the price trend |
| **Safety check** | How close the price is to your safety level: **Comfortable**, **Getting close** (within one typical daily move), **Very close** (within half of one) or **Fallen below** |
| **Buy score today** | The Top Picks buy score, for Strong Buy holdings only: *"would I buy this today?"* |

### Safety levels: where you'd sell if things go wrong

Every holding gets a **safety level**: a price below today's price where you'd say *"this isn't working, I'll sell"*. Deciding that **before** things go wrong is what stops a small loss becoming a big one. (Elsewhere this is called a *trailing stop-loss*.)

- It's based on the **typical daily move**: how much the price usually moves in a day, averaged over the last 14 days (traders call this the *ATR*, Average True Range).
- When you add a holding, the level starts at **what you paid − 2 × the typical daily move**.
- As the price rises, it follows: **highest daily close since you added it − 2 × the typical daily move**.
- It **never moves down**. So as the price climbs, the level climbs with it and protects more of your gain.

| Column | Meaning |
|---|---|
| **Safety level** | Where the level is now |
| **Room to fall %** | How far the price can fall before it reaches the safety level |
| **Loss if it falls to the safety level** | How much value you'd lose from today if the price fell to the level |
| **Safety check** | Comfortable · Getting close · Very close · Fallen below (see above) |
| **Typical daily move / %** | The typical daily move, in price and as a % of the price |
| **Highest close seen** | The highest daily close the app has seen since you added the holding |
| **First safety level** | Where the level started |

**How the message is chosen.** It combines the safety check with TradingView's chart signal, so a dip in a strong trend isn't treated like a dip with bad signals:

| Chart signal | Comfortable | Getting close | Very close | Fallen below |
|---|---|---|---|---|
| Strong Buy / Buy | All fine | All fine | Keep an eye on it | Think about selling |
| Neutral | All fine | Keep an eye on it | Think about selling | Think about selling (stronger) |
| Sell | Keep an eye on it | Think about selling | Think about selling (stronger) | Think about selling (strongest) |
| Strong Sell | Think about selling | Think about selling (stronger) | Think about selling (strongest) | Think about selling (strongest) |

Good to know:
- Safety levels always use **daily** prices.
- The app can only see daily closes **while it's running**. Leave it running to track the highest close accurately.
- The **buy score** asks *"would I buy this today?"*. The **message** asks *"I already own it, should I be worried?"*. A holding can score poorly as a new buy and still be *All fine*.

### Totals in NZ dollars

At the top of the page, one box shows your whole portfolio **in NZ dollars**: **what you own is worth**, **profit on paper** (on what you still own, with the % on what you paid), **profit from sales** and **total profit**. US dollar and USDT amounts are converted with TradingView's NZDUSD rate, which comes from the Forex market, so no extra requests are needed. The rate and its time are shown underneath. Any currency the app has no rate for is listed rather than guessed.

### Profit and loss in each currency

Below your holdings is the same summary for each currency, before conversion:

| Column | Meaning |
|---|---|
| **Value now** | What your current holdings are worth today |
| **Profit from sales** | Profit or loss from things you've **sold** |
| **Profit on paper** | Profit or loss on things you **still own** (changes with the price) |
| **Total profit** | Both added together |

**Things you have sold** lists your last 15 sales.

**Reset profit/loss** starts the *profit from sales* count again from today. It asks you to confirm first. It clears that total and the sales list, but **keeps your holdings**.

Everything here is saved automatically and is still there next time you open the app.

---

## 6. Other pages

Use the menu along the top:

| Page | What it shows |
|---|---|
| **Learn** | Start here. Written for NZ investors using **Sharesies**: three rules to start with, how to go from an idea to an order, **shares, crypto and forex: what's the difference?** (what each is, how much it typically moves in a year, where you can buy it in NZ, and whether it suits a beginner), what the signals do and don't mean, NZ costs and tax, a glossary, and the position-size calculator. |
| **Top Picks** | Today's buy ideas, in tabs (see *Top Picks* below). Updates by itself. |
| **Advanced → Market Scan** | Ideas **outside** your watchlists, one market at a time (see *Market scan* below). |
| **Advanced → Symbol Details** | Pick any share, coin or pair (the list shows names) to see its **price chart**, its **recent news**, and what each of the 26 chart tools says. The **Timeframe check** shows its chart signal on the 1 Hour, 4 Hours, 1 Day and 1 Week charts, and whether they agree; signals that agree across timeframes are more reliable. Timeframes already loaded show at once; click the button to get the rest (one request). |

### Top Picks

The page has six tabs:

| Tab | What's in it |
|---|---|
| **Today's ideas** | Up to three **idea cards**, for things that passed every safety check (shares first, because you can buy them on Sharesies). If nothing passed, it says so: staying out is a perfectly good decision. Below the cards, **Plan your exit** shows the full plan for any scored symbol. |
| **Everything scored** | Every Strong Buy with its buy score, whether it passed (*Status*) and what it failed (*Why*). The 10 most positive and most negative by TradingView's verdict alone are folded away at the bottom. |
| **Riskier: early ideas** | The early score (see below). Clearly marked as riskier. |
| **News** | The mood of recent headlines for every idea and early idea. |
| **Track record** | Has following the ideas actually worked? (see below) |
| **What are shares, crypto and forex?** | The side-by-side explainer from the Learn page. |

**An idea card** tells you, in plain words, everything to look at before deciding:
- **What it is:** the code, name and market, and the **buy score** (0–100) as a bar. The card says plainly that the score rates how strong and steady the price trend looks today. It is **not** the chance that the price goes up.
- **A warning for crypto and forex**, which aren't on Sharesies and are much riskier.
- **The business** (shares only): profitable? expensive? growing?
- **Recent news:** the mood of the last week's headlines.
- **The plan:** today's price, the first place to take some profit, and the **safety level** (if it closes below this, sell).
- **How much?** The dollar amount to put in, from your **total invested** on Home: a fall to the safety level should cost about 1% of your money, and no more than 10% of your money goes into one idea. (This is the position-size calculator from the Learn page, done for you.)
- **Does this work?** One honest line from the track record, e.g. *"So far, 60% of 12 past picks did better than simply owning the market - but that is far too few picks to trust yet."*
- **Try it in Practice** with pretend money, and **next steps** (check the business and news, note the safety level, practise, then buy in Sharesies and record it on My Portfolio).

### The buy score (Top Picks)

TradingView's verdict only counts how many chart tools agree. Two symbols can both be *Strong Buy* while one is clearly the better opportunity. So the **buy score** (its full name is the *Composite Opportunity Score*) ranks **only the symbols rated Strong Buy**; anything else is left off the table, since only a Strong Buy can be a new idea. The score (0–100) adds up 8 parts:

| Part | Max | Asks |
|---|---|---|
| Indicators | 30 | How bullish is TradingView's overall rating? |
| Trend | 20 | Are the 20-, 50- and 200-bar moving averages lined up and rising? |
| Rel. strength | 15 | Is it beating the market (S&P 500 for shares, Bitcoin for crypto) over about 3 months? |
| Momentum | 10 | Is momentum building (RSI, MACD, rate of change, ADX)? Very overbought loses points. |
| Volume | 10 | Is more being traded than usual? |
| Regime | 5 | Is the market as a whole in an uptrend? |
| Risk | 5 | How calm is it? Wild swings score lower. |
| Entry | 5 | Has it already run far above its 20-bar average? (Don't chase.) |

**Strength** (the score in words): 90+ Exceptional · 80–89 Very strong · 70–79 Qualifies · 60–69 Watchlist · under 60 Ignore. The **How the score and the safety checks work** link on the page has the full point tables.

**Safety checks.** A high score never overrides them. To be **QUALIFIED** (a buy idea), a Strong Buy must score **70+** (**85+** if its whole market is falling), trade above its 200-day average (a long-term uptrend), be traded enough each day, and be no more than 12% above its 20-day average (not already shot up). The **Why** column says what a rejected symbol failed. The **overall market mood** line at the top of Top Picks says whether each market as a whole is rising, mixed or falling.

### The early score (Top Picks, "Riskier: early ideas")

The main score mostly rewards trends that are already mature: a Strong Buy rating, moving averages lined up. By then much of the move may be over. The **Early Entry Score** (0–100) is a second, separate score that looks for trends **turning up**, so it also scores symbols rated plain **Buy**:

| Part | Max | Asks |
|---|---|---|
| Turn | 30 | Is the trend turning up? Price back above its 20-bar average, the 20-bar crossing the 50-bar, MACD crossing up while still below zero, RSI rising through 50 |
| Shift | 20 | Are the short-term momentum indicators switching to positive? |
| Not late | 20 | Starts full, loses points if it has already gained a lot over 3 months, is very overbought, or is far above its 20-bar average |
| Rel. 1M | 10 | Is it beating its market over about a month? |
| Volume | 10 | Is more being traded than usual? |
| Regime | 5 | Is the market as a whole in an uptrend? |
| Risk | 5 | How calm is it? |

A symbol is **EARLY** when it scores **65+** (**80+** if its market is bearish), is rated Buy or Strong Buy, trades above its 20-bar average but no more than 12% above it, and is traded enough each day. The **How the early score works** link on the page has the full point tables. The table says when a symbol **also** qualifies on the main score (then it's no longer early). A newly EARLY symbol raises an alert. Market Scan scores whole markets the same way and lists early signals scoring 60+. **Earlier means more false starts**, so compare its track record with the main score's before trusting it. The thresholds are `EARLY_MIN_SCORE`, `EARLY_BEAR_MIN_SCORE` and `SCAN_EARLY_MIN_SCORE` in `settings.py`.

### Business column, Track record and Practice

- **Business** (shares only) gives a quick look at the company behind the chart signal, e.g. *P/E 40 · earnings +20% · dividend 0.3%*, or *losing money*. A chart signal knows nothing about the business, so this is your sense check. On the 1 Day chart it comes with the normal data at no extra cost; otherwise it's fetched once and kept until you refresh that market.
- **Track record** (on Top Picks) answers the most important question: **would following the signals have beaten simply owning the market?** Every time a watchlist symbol is **QUALIFIED**, or separately **EARLY**, on the daily chart, the app writes down its price, its benchmark's (S&P 500, S&P/NZX 50 or Bitcoin) and its safety level (2 × the typical daily move below the price), at most once a week per symbol and kind. It always uses the daily chart: if you're viewing another timeframe, it fetches each market's daily data once at start-up and then every 6 hours while that market is open. It builds up while the app runs, so give it a few weeks.
  - **Main score vs early score:** a small table compares the two at a glance (average return, benchmark, share that beat it, share that went up, return with the exit rule, and the return at fixed ages).
  - **Each pick** shows its return since, against its benchmark over the same time. Forex pairs and Bitcoin itself have no benchmark, so they're compared with **holding cash (0%)**.
  - **At fixed ages:** each pick's return when it was **1 week, 4 weeks and 12 weeks** old (about 5, 20 and 60 trading days). This is the fairest comparison, because "return since" mixes picks of different ages.
  - **Lowest % / Safety level / Fell to it / With exit %:** the lowest price seen since the pick, and whether it fell to its safety level. *With exit %* is what you'd have made if you had sold at that level when it was reached, which is what the app's own advice would have had you do.
  - **No pick drops out:** if a pick's market hasn't loaded yet, the last price the app saw is used (*Price from* says "saved" and the date); with no price at all it shows *no price yet* and is left out of the averages.
  - Lowest prices and fixed-age prices are only recorded **while the app is running**. Picks logged before these columns existed have no safety level.
  - **Download as CSV** saves the table for Excel.
  - **Without opening the app:** double-click **`check_track_record.bat`** (Windows; on a Mac run `bash check_track_record.sh` in Terminal). It fetches today's prices (one request per market) and prints both track records. It never changes any file, so it's safe to run while the app is open.
- **Practice portfolio:** **Try it in Practice** on an idea card (or under *Plan your exit*) buys an idea with pretend money. On My Portfolio, the **Real money / Practice** switch shows it. It's a complete portfolio (safety levels, messages, NZ$ totals), kept separate from your real one. Try ideas here first.

### Plan your exit (Top Picks and Market Scan)

**Decide how you'll get out before you buy.** Under the idea cards there's a **Plan your exit** box. Pick a symbol and click **Show the plan** to see where to think about taking some profit if the price keeps rising, and where your safety level is:

- **Short-term** (days): the nearest price where rises often stall, e.g. a monthly price level or the top of its usual range lately.
- **Medium-term** (weeks): the next one further up, e.g. a higher monthly level or the average analyst forecast.
- **Stretch** (months): the most optimistic analyst forecast (for shares), or the furthest level.
- **Safety level:** 2 × the typical daily move below today's price. If the price closes below it, the rise has probably failed: that's where you'd sell.
- **How much?** The same dollar amount as on the idea cards.

Every number comes from TradingView's own data (daily chart): monthly price levels (*pivots*), the top of its usual range (*upper Bollinger band*), the highest price of the past year, analysts' 12-month forecasts (shares only) and the typical daily move. **No AI is used and nothing is guessed.** If there's no past price level in a range, the target is based on the typical daily move, and the write-up says so. It also points out when a share is at its highest price of the past year, or already above the average analyst forecast. On the 1 Day chart, watchlist symbols and anything found by Market Scan need **no extra request**, because the figures came with the data already loaded. Otherwise it's one request, kept until you refresh. Once shown, the plan stays when you refresh the page or come back; **Refresh the plan** gets the latest.

### Market scan

Your watchlists only cover a few dozen names. **Advanced → Market Scan** searches TradingView for **every other Buy and Strong Buy**, one market at a time. Click the button for the market you want:
- **Scan Crypto:** coins on Binance priced in USDT (not futures).
- **Scan US Stocks:** every US share on NASDAQ, NYSE or AMEX. **In Beginner mode**, companies worth less than US$2 billion are left out (small companies can swing wildly and are easier to manipulate); with Beginner mode off, every size is included unless you set `SCAN_MIN_MARKET_CAP`.
- **Scan NZ Stocks:** every company listed on the NZX.
- **Scan Forex:** the 28 pairs between the major currencies (USD, EUR, JPY, GBP, CHF, AUD, NZD, CAD).

Strong Buys above their 200-day average get the same buy score, and those scoring **65 or more** are listed in that market's tab, best first, with the same *QUALIFIED / REJECTED* check and *Why* column. Every one also gets the **early score**, and those scoring **60 or more** are listed in a second table, *Early signals (riskier)*.

Each market is found and scored in a **single request** of a few seconds, even the whole US market. It runs in the background, and only one scan runs at a time; the buttons are greyed out until it finishes. Each tab keeps its last result and when it was scanned. If TradingView gets busy, the scan waits a minute and tries again. The idea cards on Top Picks still only look at your watchlists.

Forex has its **own** main and early scores, each out of exactly 100, with forex-sized steps and **currency strength** (each currency against all the others, from the 28 major pairs) in place of relative strength and market regime. The scores are designed for the **1 Day** chart. On other timeframes, relative strength uses a shorter measure. *How the score works* on Top Picks has the full tables.

### News and sentiment (Top Picks and Symbol Details)

**Symbol Details** shows the last week's headlines for the symbol you pick, each rated **Positive / Neutral / Negative** by **FinBERT**, a model trained on financial news that runs on your own computer. Each **idea card** shows the overall mood, and the **News** tab on Top Picks has a *News on today's picks* table for every QUALIFIED and EARLY pick.

- **Where headlines come from:** Google News, searched by company or coin name (or the currency pair). For US shares you can use **Finnhub** instead by putting a free key from finnhub.io in `FINNHUB_API_KEY` in `settings.py`. Only headlines are read; articles open on the publisher's site, and nothing behind a paywall is touched.
- **Context only:** the mood does **not** change any score. It is saved with each pick in the track record, so after a few weeks you can see whether it would have helped.
- **First use:** FinBERT downloads once (about 440 MB) and takes a minute or so to load. Headlines show straight away; their ratings appear when it's ready. If it isn't installed (run setup again) or can't download, headlines still show, unrated.
- News is fetched in the background, one request at a time, and kept for an hour. Settings: `NEWS_ENABLED`, `NEWS_MAX_AGE_DAYS`, `NEWS_PER_SYMBOL`, `NEWS_CACHE_MINUTES`.

> These thresholds are sensible starting points, not proven ones; ideally they'd be tuned by backtesting. They are all in `settings.py` (see section 7).

---

## 7. Changing what the app watches

Settings are in the file **`settings.py`** in the app's folder.

1. **Close the app's black window** if it's open.
2. Open `settings.py` in any text editor. On Windows: right-click it → **Open with** → **Notepad**. On a Mac: right-click → **Open With** → **TextEdit**.
3. Make your change and save (**Ctrl+S** on Windows, **⌘ Cmd+S** on a Mac).
4. Start the app again from the desktop shortcut.

If a setting is wrong, the app shows a red **"The app could not start"** page that names the problem.

**Adding or removing a symbol:** find the market's `'watchlist'` list and add or remove a code. Keep the **quote marks** and **commas**:
```
'watchlist': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'PEPEUSDT'],
```
For US shares listed on the New York Stock Exchange, put `NYSE:` in front, e.g. `'NYSE:KO'` for Coca-Cola.

**How often it refreshes:** in Beginner mode, every market refreshes by itself every `BEGINNER_AUTO_MINUTES` (15) while it trades. With Beginner mode off, it's set on the Dashboard, per market (each market's **Auto-refresh** switch and interval). `POLL_MINUTES = 5` in `settings.py` only controls how long results are reused when you switch timeframe.

**Beginner mode:** `BEGINNER_MODE = True` is what the app starts with the very first time (after that, the switch on Home is remembered). `BEGINNER_AUTO_MINUTES` (15) and `BEGINNER_MIN_MARKET_CAP` (US$2 billion, the smallest US company Market Scan includes in Beginner mode).

**Hide a whole market:** remove it from the line `RUN_MARKETS = ['Crypto', 'US Stocks', 'NZ Stocks', 'Forex']`.

**NZ shares:** the NZ watchlist is 20 of the largest NZX companies; add or remove codes as for any market (e.g. `'AIR'`). NZ prices are in NZ dollars, the benchmark is the S&P/NZX 50 index, and because the NZX trades far less than the US, its liquidity limit is lower (`'min_daily_value': 200_000` NZD a day: about 49 of the 113 NZX companies pass, covering 98% of all NZX trading).

**Opportunity score rules:** `ENTRY_MIN_SCORE` (70; the band labels and amounts follow it), `BEAR_MIN_SCORE` (85), `WIN_MARGIN` (5), `MAX_EXTENSION_PCT` (12), and `MIN_DAILY_DOLLAR_VOLUME`. For the market scan: `SCAN_MIN_SCORE` (65), `SCAN_MIN_MARKET_CAP` (0 = every size; set e.g. `2_000_000_000` to skip US shares under $2 billion) and `SCAN_MAX_PER_MARKET` (5000). Each has a note beside it explaining what it does.

> If the app won't start after a change, reopen `settings.py`, undo your change with **Ctrl+Z** (Windows) or **⌘ Cmd+Z** (Mac), save, and try again.

---

## 8. Problems and fixes

| What you see | What to do |
|---|---|
| **The browser didn't open** | Open your browser and go to **http://localhost:8501**. |
| **The page says it can't connect** | The app isn't running, or its black window was closed. Double-click **TradingView Bot** on your desktop again. |
| **The black window closes straight away** | Run the setup again (section 2). |
| **Setup says "This folder's location is too long for Windows"** (or pip mentions *Long Path*) | Windows limits how long a file's location can be, and one of the add-ons has very long file names. Move the whole TradingViewBot folder somewhere shorter, e.g. straight into **Documents**, and run the setup again. |
| **Red "The app could not start" page** | Read the item marked ❌. **Settings:** undo your last change (section 7). **Python** or **Packages:** run the setup again (section 2). Then restart the app. |
| **`[health check] WARN Portfolio contents`** in the black window | Part of `portfolio.json` was damaged. The good entries were loaded, and the original file was kept with `.broken-` or `.original-` and the date in its name, so nothing is lost. |
| **`[health check] WARN TradingView connection`** in the black window | TradingView is busy or you're offline. The app keeps trying. Wait a few minutes. |
| **The page stays blank** | Refresh the page (**F5**). If it still doesn't appear, try a different browser (Chrome, Edge or Safari), then close the black window and start the app again. |
| **Grey "Connecting…" or "Please wait…" box** | The black window was closed or the app is restarting. Start the app again from the desktop shortcut. |
| **Yellow "TradingView is busy" notice** | TradingView has had too many requests from your internet connection. The app pauses **all** requests for a while (1 minute at first, up to 15 minutes if it keeps happening) and shows the last data it received. It catches up by itself. If it keeps happening, close the black window, wait 15 minutes, then start the app again. Avoid clicking Refresh repeatedly or switching timeframes quickly. |
| **Red "was not found on TradingView"** when adding | Check the spelling and that you picked the right Market. Look the symbol up on tradingview.com if unsure. |
| **Buttons or tables don't appear** | Refresh the browser page (**F5**, or **⌘ Cmd+R** on a Mac). |
| **Nothing happens when I click a button** | The app may still be busy. Wait 30 seconds. If it's still stuck, close the black window and start the app again. |
| **Portfolio shows "Loading…"** | The first update takes a few seconds after starting. Wait, or click **Refresh all**. |
| **A holding says "Not found"** | That code isn't recognised. Delete it and add it again with the correct code. |
| **Reason says "Waiting for daily data"** | The safety level needs daily prices. It appears within a few minutes by itself. |
| **I can't find the timeframe or auto-refresh controls** | Beginner mode is on. Switch it off on the **Home** page. |
| **Something else went wrong** | Close the black window and start the app again. This fixes most problems. |

---

## 9. Moving to another computer

1. Copy the **whole app folder** to the new computer, including your own files:
   - **`portfolio.json`**: your holdings and profit/loss.
   - **`practice_portfolio.json`**: your Practice portfolio.
   - **`signals.json`**: the Track record (QUALIFIED and EARLY picks).
   - **`preferences.json`**: your remembered settings.
   - `settings.py`.
2. **Except** the `.venv` folder: delete it from the copy. The setup builds a fresh one for the new computer.
3. Run the setup for that computer (section 2).

> 💾 **Tip:** keep a backup copy of `portfolio.json` (and `practice_portfolio.json` and `signals.json`) somewhere safe, such as a USB stick or cloud storage. They hold your portfolio history and the app's track record.
>
> 📦 **Sharing the app with someone else?** Send them the zip, not your folder. The zip never contains these personal files, so they start with an empty portfolio.

---

## 10. Checking the app works

The app quietly checks itself each time it starts (see section 3). There's also a **full test** that tries every feature: adding, selling, profit/loss, reset, saving, damaged files, a busy TradingView, and several things happening at once. Run it after setting up a new computer, or after anyone changes the app.

- **Windows:** double-click **`run_tests.bat`**.
- **Mac:** in Terminal, type `bash ` (with a space), drag in **`run_tests.sh`**, and press Enter.

It takes under a minute, works offline, and **never touches your real portfolio**; it uses a pretend TradingView in a temporary folder. You'll see a list ending in either:

- **"ALL GOOD, the app is ready to use."**
- **"SOME TESTS FAILED"**, with a short reason under each failed item. A copy of the results is saved in `tests/last_test_report.txt` if you need to send it to someone.
