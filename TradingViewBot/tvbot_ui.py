"""
TradingView Analysis Bot - the website (Streamlit). Started by app.py.
All the data and portfolio logic lives in tvbot_core.py; settings live in settings.py.
"""
import importlib
import json
import os
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import settings as S
import tvbot_core as core
import tvbot_news as news

HERE = os.path.dirname(os.path.abspath(__file__))
REFRESH_SECONDS = 3       # how often pages re-check for new data (local only - this never contacts TradingView)

CSS = """
<style>
.block-container { padding-top: 4.2rem; max-width: 1300px; }
.tvb-head h1 { font-size: 1.75rem; margin: 0 0 .15rem; padding: 0; }
.tvb-head p { color: #556275; margin: 0 0 1rem; max-width: 900px; line-height: 1.45; }
.tvb-footer { text-align: center; color: #7a869a; font-size: 12px; margin: 2.5rem 0 1rem; }
.tvb-badge { padding: 2px 8px; border-radius: 4px; font-weight: 600; }
.tvb-rec-head { border-radius: 8px; padding: 10px 16px; margin: 1.1rem 0 .5rem; display: flex;
                justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 4px 16px; }
.tvb-rec-head span { font-size: 1.25rem; font-weight: 700; }
.tvb-rec-head b { font-weight: 600; }
.tvb-reason { margin: .1rem 0 .35rem; color: #3a4556; }
.tvb-status { display: flex; flex-wrap: wrap; gap: 6px 8px; margin: -.5rem 0 .9rem; }
.tvb-chip { background: #fff; border: 1px solid #dde2ea; border-radius: 999px; padding: 2px 11px;
            font-size: .8rem; color: #3a4556; white-space: nowrap; }
.tvb-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.tvb-summary { display: flex; flex-wrap: wrap; gap: 8px; margin: .2rem 0 .8rem; }
.tvb-summary a { text-decoration: none; color: inherit; background: #fff; border: 1px solid #dde2ea;
                 border-radius: 8px; padding: 6px 12px; font-size: .85rem; }
.tvb-summary a:hover { border-color: #2f6fe4; }
.tvb-error { max-width: 760px; margin: 40px auto; padding: 24px 28px; border-radius: 10px;
             background: #fff4f4; border: 1px solid #f1b0b0; }
.tvb-error h2 { color: #b3261e; margin-top: 0; }
</style>
"""

PORTFOLIO_HELP = """
**What this page is for:** you write down what you have bought (in Sharesies or anywhere else), and the app watches
it for you. **The app never buys or sells anything** - it only tells you when it's worth taking a look.

**Adding something you bought**
- Pick the market, type its code (e.g. **AAPL** for Apple, **FPH** for Fisher & Paykel Healthcare, **BTC** for
  Bitcoin), the price you paid for **one** share or coin, and how many you bought. Not sure of the code? Top Picks and
  the Dashboard show each code next to the company name.
- **Which currency?** US shares and crypto: **US dollars**. NZ shares: **NZ dollars**. Forex: the second currency of
  the pair (USD for NZDUSD). Sharesies shows the US-dollar price per share in your order confirmation.
- If TradingView is busy, the holding is saved anyway and checked on the next refresh (it shows *Checking...*).

**Selling and deleting**
- **Sell:** pick the holding, enter how many you sold (or tick *Sell everything*) and the price you sold at (leave it
  at 0 to use today's price). The profit or loss goes into *Profit from sales*.
- **Delete** removes something you entered by mistake, without recording a profit or loss.
- **Reset profit/loss** starts the *profit from sales* count again. Your holdings are kept.

**Your safety level (the most important number here)**
- Every holding gets a **safety level**: a price below today's price where you'd say *"this isn't working, I'll sell"*.
  Deciding that **before** things go wrong is what stops a small loss becoming a big one.
- It starts at what you paid minus **2 × the typical daily move** (how much the price usually moves in a day, worked
  out from the last 14 days). As the price rises, the level rises with it (it never goes down), so it protects more
  of your gains.
- **Room to fall %** is how far the price can drop before it reaches the safety level.

**What the app tells you to do** - it looks at the safety level *and* TradingView's chart signal:
- 🟢 **All fine** - nothing to do.
- 🟡 **Keep an eye on it** - nothing to do now, just check it now and then.
- 🔴 **Think about selling** - the price is near or below the safety level, or the signals have turned down. The line
  under the holding says how strong the warning is. Whether to sell is your decision; you sell in Sharesies yourself.

**Buy score today** (shown for some holdings) answers *"would I buy this today?"*. It's a different question from
*"I own it - should I worry?"*, so a holding can have a low buy score and still be *All fine*.
"""


# ---------------------------------------------------------------- shared app state (one per server)
def get_app():
    """The one shared app (portfolio + live data). If the program files were updated while the app was
    running, the old objects no longer match the new code - so stop them and start fresh."""
    core_changed = getattr(core, 'LOADED_FROM_MTIME', None) != os.path.getmtime(core.__file__)
    if core_changed:                       # tvbot_core.py on disk is newer than the copy in memory
        importlib.reload(core)
    app = _build_app()
    if core_changed or not isinstance(app['store'], core.MarketStore) or not isinstance(app['portfolio'], core.Portfolio):
        try:
            app['store'].stop()
        except Exception:
            pass
        for key in ('portfolio', 'practice'):    # wait for any save in progress, then stop the old copies writing
            if app.get(key) is not None:
                with app[key].lock:
                    app[key].retired = True
        _build_app.clear()
        app = _build_app()
    return app


@st.cache_resource(show_spinner=False)
def _build_app():
    portfolio = core.Portfolio()
    checks = core.health_check(portfolio)
    for s, n, d in checks:                      # health check goes to the black window, not the page
        print(f'[health check] {s.upper():4}  {n}: {d}', flush=True)
    practice = core.Portfolio(core.practice_path())   # pretend money, for trying ideas first
    store = core.MarketStore(portfolio, practice=practice)
    core.apply_prefs(store, core.load_prefs())     # remembered settings, if "Remember these settings" is on
    if not any(s == 'fail' for s, _, _ in checks):
        store.start()
    return {'portfolio': portfolio, 'practice': practice, 'store': store, 'checks': checks}


get_app.clear = _build_app.clear     # lets the tests start a fresh app


# ---------------------------------------------------------------- formatting helpers
def fmt_num(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return '–'
    if not isinstance(v, (int, float)):
        return str(v)
    a = abs(v)
    return f'{v:,.2f}' if a >= 100 else f'{v:,.4f}' if a >= 1 else f'{v:.6g}'


def fmt_signed(v):
    return '–' if v is None or pd.isna(v) else f'{v:+,.2f}'


def fmt_pct(v):
    return '–' if v is None or pd.isna(v) else f'{v:+.2f}%'


def fmt_qty(v):
    return f'{v:,.8g}'


def _pl_css(v):
    if isinstance(v, (int, float)) and not pd.isna(v) and v != 0:
        return 'color:#0b7a3b;font-weight:600' if v > 0 else 'color:#b3261e;font-weight:600'
    return ''


def fmt_pts(v):
    if v is None or pd.isna(v):
        return '–'
    return f'{v:.0f}' if float(v).is_integer() else f'{v:.1f}'


# Everyday names for the columns, used in every table (the data keeps its short internal names).
DISPLAY_NAMES = {
    'Rating': 'Chart signal', 'Band': 'Strength', 'Opp. score': 'Buy score today',
    'Qty': 'Quantity', 'Bought': 'Paid (each)', 'Now': 'Price now', 'Ccy': 'Currency',
    'P/L': 'Profit/loss', 'P/L %': 'Profit/loss %',
    'ATR': 'Typical daily move', 'ATR %': 'Typical daily move %', 'High close': 'Highest close seen',
    'Initial level': 'First safety level', 'Trailing level': 'Safety level', 'To level %': 'Room to fall %',
    'At risk': 'Loss if it falls to the safety level', 'ATR status': 'Safety check',
    'Protective': 'Safety level', 'Hit it': 'Fell to it',
    'Value held': 'Value now', 'Realised': 'Profit from sales', 'Unrealised': 'Profit on paper',
    'Total': 'Total profit',
    'Oscillators': 'Short-term signals', 'Moving Avgs': 'Trend signals',
    'Osc B/N/S': 'Short-term Buy/Neutral/Sell', 'MA B/N/S': 'Trend Buy/Neutral/Sell',
}

# Short explanations of each column (shown when you hover over a heading, and in "What do these columns mean?").
COLUMN_HELP = {
    'Name': 'The company, coin or currency pair. For forex it also says which currency is getting stronger',
    'Chart signal': "TradingView's verdict from 26 chart tools: Strong Buy, Buy, Neutral, Sell or Strong Sell. It "
                    'describes the price trend right now - it is not a forecast',
    'Score': 'Buy score, 0-100: how strong and steady the price trend looks today. Higher is better. It is NOT the chance that '
             'the price goes up',
    'Buy score today': 'The Top Picks buy score (0-100), shown for Strong Buy holdings: "would I buy this today?"',
    'Strength': 'The buy score in words: 90+ Exceptional · 80+ Very strong · from the entry score Qualifies · '
                '10 below it Watchlist · lower Ignore',
    'Status': 'QUALIFIED = passes every safety check, so it is a buy idea. REJECTED = it failed at least one '
              'check - see Why',
    'Why': 'Each check it failed, with its numbers, e.g. "Score too low: 66.2, needs 70". Several are separated by ·',
    'Buy': 'How many of the 26 chart tools say Buy', 'Neutral': 'How many say Neutral', 'Sell': 'How many say Sell',
    'Indicator balance': 'From -1 (every chart tool says Sell) to +1 (every one says Buy)',
    'Short-term signals': 'The verdict of the 11 chart tools that look at the last few days or weeks',
    'Trend signals': 'The verdict of the 15 chart tools that follow the longer trend (moving averages)',
    'Typical daily move': 'How much the price usually moves in a day (average of the last 14 days; called ATR)',
    'Typical daily move %': 'The typical daily move as a share of the price. Higher = a bumpier ride',
    'Safety check': 'How close the price is to your safety level: Comfortable · Getting close (within one typical '
                    'daily move) · Very close (within half of one) · Fallen below',
    'Highest close seen': 'The highest daily closing price the app has seen since you added the holding',
    'First safety level': 'What you paid minus 2 × the typical daily move',
    'Safety level': 'The price where you\'d sell if things go wrong: the highest close minus 2 × the typical daily '
                    'move. It only ever moves up',
    'Room to fall %': 'How far the price can fall before it reaches your safety level',
    'Loss if it falls to the safety level': 'How much value you would lose from today if the price fell to the '
                                            'safety level',
    'Profit/loss': 'Profit (green) or loss (red) so far, in the currency the price is in',
    'Profit/loss %': 'Profit or loss as a percentage of what you paid',
    'Value (NZ$)': 'What the holding is worth today, in NZ dollars',
    'Profit/loss (NZ$)': 'Profit or loss so far, in NZ dollars',
    'Currency': 'The currency the prices are in',
    'Quantity': 'How many shares, coins or units you hold', 'Paid (each)': 'What you paid for one',
    'Price now': 'Today\'s price for one',
    'Value now': 'What your holdings are worth today', 'Profit from sales': 'Profit or loss on things you have sold',
    'Profit on paper': 'Profit or loss on things you still own (it changes with the price)',
    'Total profit': 'Profit from sales + profit on paper',
    'Chart': 'Open the price chart on TradingView',
    'Return %': 'Change in price since the pick was logged',
    'Benchmark %': 'What simply owning the whole market did over the same time (S&P 500, S&P/NZX 50 or Bitcoin; '
                   '0% for cash)',
    'Compared with': 'What the pick is measured against. Forex pairs and Bitcoin itself have no market to compare '
                     'with, so they are compared with holding cash (0%)',
    'Beat it': 'Did the pick do better than what it is compared with?',
    **{f'After {label} %': f'Return when the pick was {label} old (as first seen by the app at that age)'
       for label in core.SIGNAL_HORIZONS},
    'Lowest %': 'Lowest price the app has seen since the pick was logged, compared with the price then',
    'Fell to it': 'Did the price fall to its safety level? – = no level recorded (older picks)',
    'With exit %': 'Return if you had sold at the safety level when it was reached; otherwise today\'s return',
    'Price from': '"live" = from data loaded this session; "saved" = the last price the app saw for it',
    'Business': 'A quick look at the company (shares only). P/E = share price ÷ a year\'s profit per share: lower '
                'is cheaper, 15-25 is typical, above ~40 is expensive. Earnings = profit growth over the last year. '
                '"Losing money" = not profitable',
    'News': 'The mood of recent headlines: Positive, Neutral or Negative (rated by a computer, so not perfect)',
    'Sentiment': 'Average headline mood from -1 (all negative) to +1 (all positive)',
}


def part_headers(weights, fx_weights):
    """Breakdown column headings, e.g. 'Momentum /10 · FX /15' where forex's own score gives the part another max."""
    return {k: f'{k} /{w}' + (f' · FX /{fx_weights[k]}' if fx_weights.get(k, w) != w else '')
            for k, w in weights.items()}


def part_help(weights, fx_weights, what='score'):
    """Hover text for the breakdown columns, including what each part means for forex."""
    out = {}
    for k, h in part_headers(weights, fx_weights).items():
        fx = (f" Forex: {core.FX_PART_NAMES.get(k, k.lower())}, out of {fx_weights[k]}." if k in fx_weights
              else ' Forex: not used.')
        out[h] = f'{k} part of the {what}, out of {weights[k]}.{fx}'
    return out


COLUMN_HELP.update(part_help(core.WEIGHTS, core.FX_WEIGHTS))
MAIN_HEADERS = part_headers(core.WEIGHTS, core.FX_WEIGHTS)
EARLY_HEADERS = part_headers(core.EARLY_WEIGHTS, core.FX_EARLY_WEIGHTS)


def table(df, colour_cols=('Rating', 'Oscillators', 'Moving Avgs'), pl_cols=(), fmt=None,
          rating_prefix_cols=(), key=None, colours=None, column_config=None):
    """Show a DataFrame with the app's colours, all rows visible (no inner scrolling), with a hover explanation on
    known column headings. colours: {column: {value: css}} for any other coloured columns.
    Columns get their everyday names (DISPLAY_NAMES); the arguments may use either name."""
    if 'Ticker' in df.columns:            # full ticker given -> a 'Chart' link to TradingView, last column
        df = df.assign(Chart=df['Ticker'].map(chart_url)).drop(columns='Ticker')
    names = {c: DISPLAY_NAMES[c] for c in df.columns if c in DISPLAY_NAMES}
    if names:
        df = df.rename(columns=names)
        r = lambda c: names.get(c, c)
        colour_cols, pl_cols, rating_prefix_cols = ([r(c) for c in cols] for cols in
                                                    (colour_cols, pl_cols, rating_prefix_cols))
        fmt = {r(k): v for k, v in (fmt or {}).items()} if isinstance(fmt, dict) else fmt
        colours = {r(k): v for k, v in (colours or {}).items()}
        column_config = {r(k): v for k, v in (column_config or {}).items()}
    config = {c: st.column_config.Column(help=COLUMN_HELP[c]) for c in df.columns if c in COLUMN_HELP}
    if 'Chart' in df.columns:
        config['Chart'] = st.column_config.LinkColumn('Chart', display_text='Open ↗', help=COLUMN_HELP['Chart'],
                                                      width='small')
    config.update(column_config or {})
    sty = df.style
    for col, mapping in (colours or {}).items():
        if col in df.columns:
            sty = sty.map(lambda v, m=mapping: m.get(v, ''), subset=[col])
    cols = [c for c in colour_cols if c in df.columns]
    if cols:
        sty = sty.map(lambda v: core.COLOURS.get(v, ''), subset=cols)
    cols = [c for c in pl_cols if c in df.columns]
    if cols:
        sty = sty.map(_pl_css, subset=cols)
    cols = [c for c in rating_prefix_cols if c in df.columns]
    if cols:
        sty = sty.map(lambda v: core.COLOURS.get(v.split(' (')[0], '') if isinstance(v, str) else '', subset=cols)
    sty = sty.format(fmt or {}, na_rep='–')
    st.dataframe(sty, hide_index=True, height=35 * (len(df) + 1) + 3, key=key, column_config=config)


def with_business(df):
    """Add a 'Business' column (shares only): a quick look at the company behind the chart signal."""
    if df.empty or 'Ticker' not in df.columns or 'Market' not in df.columns:
        return df
    summary = {}
    for mk, g in df.groupby('Market'):
        try:
            f = core.fundamentals(mk, list(g['Ticker']), get_app()['store'])
        except Exception:                 # TradingView busy etc. - the column just shows '–' this time
            f = {}
        summary.update({t: core.business_summary(f.get(t)) for t in g['Ticker']})
    return df.assign(Business=df['Ticker'].map(lambda t: summary.get(t, '–')))


def explain_columns(cols, nested=False):
    """'What do these columns mean?' - the column explanations written out (hover help is easy to miss, and doesn't
    work on a phone). nested=True (already inside a fold-out): a short caption instead of another fold-out."""
    shown = list(dict.fromkeys(DISPLAY_NAMES.get(c, c) for c in cols))
    lines = [f'**{c}**: {COLUMN_HELP[c]}' for c in shown if c in COLUMN_HELP]
    if not lines:
        return
    if nested:
        st.caption(' · '.join(lines))
        return
    with st.expander('What do these columns mean?', icon=':material/help:'):
        st.markdown('\n'.join(f'- {x}' for x in lines))


def display_name(store, ticker, market=None, rating=None):
    """The everyday name next to a code: the company or coin ('Fisher & Paykel Healthcare', 'Bitcoin'), or for forex
    what the pair means ('US dollar vs Swiss franc: the US dollar is getting stronger'). '' if not known yet."""
    if market == 'Forex' or (market is None and str(ticker).startswith('FX')):
        return core.pair_meaning(ticker, rating)
    for a in (store.analysis(ticker), store.analysis(ticker, core.RISK_INTERVAL)):
        d = a.indicators.get('description') if a is not None else None
        if isinstance(d, str) and d:
            return news.clean_name(d)
    hit = core._scanned.get(ticker)
    if hit and isinstance(hit[2].get('description'), str):
        return news.clean_name(hit[2]['description'])
    return news._names.get(ticker) or ''


def with_names(df, store, after='Symbol'):
    """Add a 'Name' column (company, coin or what a forex pair means) right after the code."""
    if df.empty or 'Ticker' not in df.columns:
        return df
    mk = df['Market'] if 'Market' in df.columns else [None] * len(df)
    rating = df['Rating'] if 'Rating' in df.columns else [None] * len(df)
    names = [display_name(store, t, m, r) for t, m, r in zip(df['Ticker'], mk, rating)]
    out = df.assign(Name=names)
    cols = [c for c in out.columns if c != 'Name']
    at = cols.index(after) + 1 if after in cols else 0
    return out[cols[:at] + ['Name'] + cols[at:]]


def plain_mood(regimes):
    """'US Stocks rising · Crypto falling' - each market's overall direction in words."""
    return ' · '.join(f'**{mk}** {core.PLAIN_REGIME.get(label, label)}' for mk, (_, label) in regimes.items())


def with_why(df, ok_status, ok_text):
    """The Why column says so when a symbol passes every rule, instead of being blank."""
    if df.empty or 'Why' not in df.columns:
        return df
    return df.assign(Why=[w if isinstance(w, str) and w else (f'✓ {ok_text}' if s == ok_status else '')
                          for w, s in zip(df['Why'], df['Status'])])


def why_summary(df, ok_status, what='the rest'):
    """A one-line count of the reasons symbols failed, most common first."""
    if df.empty or 'Why' not in df.columns:
        return
    from collections import Counter
    counts = Counter(lbl for w, s in zip(df['Why'], df['Status']) if s != ok_status for lbl in core.why_labels(w))
    if counts:
        st.caption(f'**Why {what} failed** (a symbol can fail more than one rule): '
                   + ' · '.join(f'{lbl} **{n}**' for lbl, n in counts.most_common())
                   + '. Hover over *Why* for details; each row lists its own reasons with the numbers.')


def score_table(df, key, lead_cols=('Symbol',)):
    """An opportunity-score table: the score as a bar, its band and status, and why it was rejected.
    The 8-part breakdown is one switch away (off by default, so the table stays readable)."""
    parts = st.toggle('Show score breakdown', key=f'{key}_parts',
                      help='Adds the 8 parts the score is made of (Indicators /30, Trend /20, ...).')
    df = with_why(with_names(with_business(df), get_app()['store']), 'QUALIFIED', 'Passes every safety check')
    cols = [*lead_cols, 'Name', 'Score', 'Band', 'Status', *(core.WEIGHTS if parts else ()), 'Business', 'Why',
            'Ticker']
    renamed = MAIN_HEADERS
    bar = st.column_config.ProgressColumn('Score', help=COLUMN_HELP['Score'], min_value=0, max_value=100,
                                          format='%.1f', width='small')
    why = st.column_config.TextColumn('Why', help=COLUMN_HELP['Why'], width='large')
    table(df[[c for c in cols if c in df.columns]].rename(columns=renamed), colour_cols=('Rating',),
          colours={'Band': core.BAND_COLOURS, 'Status': core.STATUS_COLOURS},
          fmt={h: fmt_pts for h in renamed.values()}, key=key,
          column_config={'Score': bar, 'Why': why})
    explain_columns(['Name', 'Score', 'Strength', 'Status', 'Business', 'Why', 'Chart'])


def page_head(title, desc):
    st.markdown(f'<div class="tvb-head"><h1>{title}</h1><p>{desc}</p></div>', unsafe_allow_html=True)
    status_bar()


def _ago(t):
    secs = (pd.Timestamp.now() - pd.Timestamp(t)).total_seconds()
    return 'just now' if secs < 60 else f'{int(secs // 60)} min ago' if secs < 3600 else f'{secs / 3600:.0f} h ago'


@st.fragment(run_every=REFRESH_SECONDS)
def status_bar():
    """One line of chips on every page: is each market open, and how fresh is its data?"""
    store = get_app()['store']
    chips = []
    for mk in S.RUN_MARKETS:
        sess = core.market_session(mk)
        data = store.state.get(mk)
        if store.errors.get(mk) and not data:
            dot, state = '#e0a400', 'not loaded'
        elif not data:
            dot, state = '#e0a400', 'loading'
        else:
            dot = '#9aa3af' if sess and sess[0] == 'closed' else '#1e9e55'
            state = ('closed · ' if sess and sess[0] == 'closed' else 'open · ' if sess else '') + _ago(data['time'])
        auto = ' · <span title="refreshes by itself">⟳</span>' if (store.auto_cfg(mk) or {}).get('on') else ''
        chips.append(f'<span class="tvb-chip"><span class="tvb-dot" style="background:{dot}"></span>'
                     f'<b>{mk}</b> {state}{auto}</span>')
    left, right = st.columns([6, 1.1], vertical_alignment='center')
    left.markdown(f'<div class="tvb-status">{"".join(chips)}</div>', unsafe_allow_html=True)
    alerts_box(store, right)


def alerts_box(store, col):
    """New alerts pop up (once per browser tab); the Alerts button lists the recent ones."""
    alerts = list(store.alerts)
    last = alerts[-1]['id'] if alerts else 0
    seen = st.session_state.setdefault('alerts_seen', last)   # a newly opened tab doesn't replay old alerts
    for a in alerts:
        if a['id'] > seen:
            st.toast(a['text'], icon=':material/warning:' if a['level'] == 'warn' else ':material/trending_up:')
    st.session_state['alerts_seen'] = last
    recent = [a for a in alerts if (pd.Timestamp.now() - pd.Timestamp(a['time'])).total_seconds() < 86400]
    with col.popover(f'Alerts ({len(recent)})', icon=':material/notifications:', width='stretch'):
        if not recent:
            st.caption('Nothing new. You will see an alert here (and a pop-up) when one of your holdings moves to '
                       '**Think about selling**, or when there is a new buy idea on Top Picks. Alerts only work '
                       'while the app is running.')
        for a in reversed(recent):
            mark = '⚠️' if a['level'] == 'warn' else '📈'
            st.markdown(f"{mark} **{a['time']:%H:%M}** &nbsp; {a['text']}")


def rate_limit_notice():
    wait = core.rate_limit_wait()
    if wait:
        when = f'{wait // 60} min {wait % 60} s' if wait >= 60 else f'{wait} seconds'
        st.warning(f'TradingView is busy (it has had too many requests from this connection). To let it clear, the '
                   f'app is pausing all requests and will try again in {when}. Until then you see the last data it '
                   'received. It catches up by itself, and clicking Refresh won\'t speed it up.',
                   icon=':material/hourglass_top:')


def timeframe_note():
    label = core.timeframe_label(get_app()['store'].interval)
    st.caption(f'Based on the **{label}** chart. Change the timeframe on the Dashboard.')
    rate_limit_notice()


def counts_line(df):
    counts = df['Rating'].value_counts().reindex(list(core.COLOURS), fill_value=0)
    return ' &nbsp;·&nbsp; '.join(f'<span class="tvb-badge" style="{core.COLOURS[k]}">{k}</span> {v}'
                                  for k, v in counts.items())


# ---------------------------------------------------------------- pages
def page_dashboard():
    store = get_app()['store']
    page_head('Dashboard: every market',
              "Every share, coin and currency pair the app watches, with TradingView's <b>chart signal</b> - from "
              '<b>Strong Buy</b> (the price trend is clearly up) to <b>Strong Sell</b> (clearly down). It comes from '
              '26 chart tools; <b>Buy / Neutral / Sell</b> count how many of them agree. Each table starts with the '
              'most positive. This page is the raw view: for buy ideas, go to <b>Top Picks</b>.')
    if store.beginner:
        c2, c3 = st.columns([1.3, 6.2], vertical_alignment='bottom')
        c3.caption(f'**Beginner mode is on:** ratings use the 1 Day chart (what the scores are designed for) and each '
                   f'market refreshes by itself every {S.BEGINNER_AUTO_MINUTES} minutes while it is open. Switch '
                   'Beginner mode off on the **Home** page for the timeframe and refresh controls.')
    else:
        c0, c2, c3 = st.columns([1.5, 1.3, 4.7], vertical_alignment='bottom')
        labels = list(core.DASH_TIMEFRAMES)
        current = core.timeframe_label(store.interval)
        choice = c0.selectbox('Timeframe', labels, index=labels.index(current) if current in labels else 2,
                              key='dash_timeframe',
                              help='Which chart the ratings are based on: 1 Day looks at daily prices, 1 Hour at '
                                   'hourly ones (quicker to change, but noisier). Applies to every page. The buy '
                                   'scores are designed for 1 Day.')
        if store.set_interval(core.DASH_TIMEFRAMES[choice]):
            store.refresh_stale()      # remembered results show at once; only missing/out-of-date markets are fetched
            core.save_prefs(store)
        remember = c3.toggle('Remember these settings', value=store.remember, key='remember_prefs',
                             help='Keep the timeframe and each market\'s auto-refresh choice for the next time you '
                                  'start the app. Off = every start begins on 1 Day with auto-refresh off.')
        if remember != store.remember:
            store.remember = remember
            core.save_prefs(store)
    if c2.button('Refresh all', icon=':material/refresh:', key='refresh_all'):
        with st.spinner('Refreshing all markets...'):
            store.refresh_all(manual=True)
    explain_columns(['Name', 'Price', 'Chart signal', 'Buy', 'Neutral', 'Sell', 'Indicator balance',
                     'Short-term signals', 'Trend signals', 'Chart'])
    dashboard_markets()


def auto_controls(store, mk, col_on, col_every):
    """A market's own auto-refresh switch (off by default) and how often (1 min ... 4 hours)."""
    cfg = store.auto[mk]
    choices = list(core.AUTO_CHOICES)
    current = next((k for k, v in core.AUTO_CHOICES.items() if v == cfg['minutes']), '5 min')
    on = col_on.toggle('Auto-refresh', value=cfg['on'], key=f'auto_{mk}',
                       help=f'Refresh {mk} by itself at the interval on the right. Off = only when you click Refresh.')
    every = col_every.selectbox('Every', choices, index=choices.index(current), key=f'auto_every_{mk}',
                                label_visibility='collapsed', help=f'How often {mk} refreshes by itself.')
    if on != cfg['on'] or core.AUTO_CHOICES[every] != cfg['minutes']:
        store.set_auto(mk, on=on, minutes=core.AUTO_CHOICES[every])
        core.save_prefs(store)


@st.fragment(run_every=REFRESH_SECONDS)
def dashboard_markets():
    store = get_app()['store']
    label = core.timeframe_label(store.interval)
    st.caption(f'Ratings on the **{label}** chart.')
    rate_limit_notice()
    # Overview: every market's ratings at a glance; click one to jump to its table.
    items = []
    for mk in S.RUN_MARKETS:
        data = store.state.get(mk)
        if data is None or data['df'].empty:
            continue
        n = data['df']['Rating'].value_counts()
        parts = [f'<span class="tvb-badge" style="{core.COLOURS[k]}">{int(n.get(k, 0))}</span>'
                 for k in core.COLOURS]
        items.append(f'<a href="#{mk.lower().replace(" ", "-")}" title="Strong Buy · Buy · Neutral · Sell · '
                     f'Strong Sell - click to jump to {mk}"><b>{mk}</b>&nbsp; {" ".join(parts)}</a>')
    if items:
        st.markdown(f'<div class="tvb-summary">{"".join(items)}</div>', unsafe_allow_html=True)
    for mk in S.RUN_MARKETS:
        with st.container(border=True):
            h1, h_on, h_every, h2 = st.columns([3.2, 1.3, 1.2, 1.5], vertical_alignment='center')
            h1.subheader(mk)
            if not store.beginner:
                auto_controls(store, mk, h_on, h_every)
            asset_explainer(mk)
            if h2.button(f'Refresh {mk}', icon=':material/refresh:', key=f'refresh_{mk}'):
                with st.spinner(f'Refreshing {mk}...'):
                    store.refresh(mk, manual=True)
            if store.errors.get(mk) and not core.rate_limit_wait():   # during a cool-down the notice above says it all
                st.warning(f'Refresh failed: {store.errors[mk]}')
            data = store.state.get(mk)
            if not data:
                if core.rate_limit_wait():
                    st.info(f'Waiting for TradingView before loading the {label} chart...')
                elif not store.errors.get(mk):
                    st.info(f'Loading the {label} chart from TradingView...')
                continue
            status = ' &nbsp;·&nbsp; <i>updating...</i>' if store.is_loading(mk) else ''
            nxt = store.next_auto(mk)
            if nxt and not store.is_settled(mk):
                status += f' &nbsp;·&nbsp; next auto-refresh {max(nxt, core.dt.datetime.now()):%H:%M:%S}'
            elif not store.auto_cfg(mk)['on']:
                status += ' &nbsp;·&nbsp; auto-refresh off'
            if store.is_settled(mk):
                h = S.MARKETS[mk]['hours']
                status += (f" &nbsp;·&nbsp; <b>market closed</b>: final data from the last session, not re-fetched "
                           f"until it opens ({h['open']} {h['tz'].split('/')[-1].replace('_', ' ')} time)")
            st.markdown(counts_line(data['df']) + f" &nbsp;&nbsp; <span style='color:#7a869a'>updated "
                        f"{data['time']:%H:%M:%S}{status}</span>", unsafe_allow_html=True)
            if data['missing']:
                st.caption('No data for: ' + ', '.join(data['missing']))
            view = with_names(data['df'].assign(Ticker=lambda d: d['Symbol'],
                                                Symbol=lambda d: d['Symbol'].map(core.short)), store)
            table(view.drop(columns='Market').rename(columns={'Score': 'Indicator balance'}),
                  fmt={'Price': fmt_num, 'Indicator balance': '{:+.2f}'}, key=f'tbl_{mk}')


def current_portfolio(app):
    """The portfolio picked with the Real money / Practice switch on My Portfolio."""
    return app['practice'] if st.session_state.get('pf_mode') == 'Practice' else app['portfolio']


def page_portfolio():
    app = get_app()
    store = app['store']
    page_head('My portfolio', 'Write down what you\'ve bought and the app watches it for you. Each holding gets a '
                              '<b>safety level</b> (the price where you\'d sell if things go wrong) and one of three '
                              'messages: <b>All fine</b>, <b>Keep an eye on it</b> or <b>Think about selling</b>. '
                              'Everything is saved automatically. The app never buys or sells for you.')
    st.segmented_control('Portfolio', ['Real money', 'Practice'], default='Real money', key='pf_mode', required=True,
                         help='Practice = pretend money, kept completely separate. Try ideas there first and see how '
                              'they would have done before using real money.')
    pf = current_portfolio(app)
    if pf is app['practice']:
        st.info('**Practice portfolio**: pretend money, saved separately from your real portfolio. Add ideas here '
                '(or with **Try it in Practice** on an idea card) and follow how they do.',
                icon=':material/science:')
    with st.expander('How the portfolio works'):
        st.markdown(PORTFOLIO_HELP)

    msg = st.session_state.pop('pf_msg', None)
    if msg:            # done -> a pop-up in the corner; a problem -> a red box that stays until you act on it
        if msg[0]:
            st.toast(msg[1], icon=':material/check_circle:')
        else:
            st.error(msg[1])

    # Your holdings come first; adding and selling open from these buttons.
    left, right, _ = st.columns([1.3, 1.3, 4], vertical_alignment='center')
    with left.popover('Add holding', icon=':material/add:', type='primary', width='stretch'), \
            st.form('add_form', clear_on_submit=True, border=False):
        st.markdown('#### Add something you bought')
        mk = st.selectbox('Market', S.RUN_MARKETS, key='add_market')
        sym = st.text_input('Code', placeholder='e.g. AAPL (Apple), FPH (Fisher & Paykel), BTC (Bitcoin)',
                            key='add_symbol', help='The short code for the share or coin. Top Picks and the Dashboard '
                                                   'show each code next to its name.')
        price = st.number_input('Price you paid for ONE share or coin', min_value=0.0, value=0.0, format='%g',
                                key='add_price')
        st.caption('Currency: **US dollars** for US shares and crypto, **NZ dollars** for NZ shares, and the second '
                   'currency for forex (USD for NZDUSD). Sharesies shows the US-dollar price per share in your order '
                   'confirmation.')
        qty = st.number_input('How many you bought', min_value=0.0, value=0.0, format='%g', key='add_qty')
        if st.form_submit_button('Add holding', icon=':material/add:', type='primary', key='add_submit'):
            with st.spinner(f'Checking {sym.upper()} with TradingView...'):
                st.session_state['pf_msg'] = pf.add(mk, sym, price, qty, store)
            st.rerun()

    with right.popover('Sell or delete', icon=':material/sell:', width='stretch',
                       disabled=not pf.holdings), st.form('sell_form', border=False):
        st.markdown('#### Sell a holding')
        labels = {h['id']: f"{core.short(h['ticker'])}  —  {h['qty']:,.8g} @ {h['buy_price']:,.8g}" for h in pf.holdings}
        hid = st.selectbox('Holding', list(labels), format_func=lambda i: labels.get(i, i),
                           placeholder='No holdings yet', key='sell_holding')
        sell_all = st.checkbox('Sell everything in this holding', key='sell_all')
        sqty = st.number_input('Quantity to sell', min_value=0.0, value=0.0, format='%g', key='sell_qty')
        sprice = st.number_input('Sell price (leave 0 to use the current price)', min_value=0.0, value=0.0,
                                 format='%g', key='sell_price')
        b1, b2 = st.columns(2)
        do_sell = b1.form_submit_button('Sell', icon=':material/sell:', type='primary', key='sell_submit')
        do_delete = b2.form_submit_button('Delete holding', icon=':material/delete:', key='delete_submit',
                                          help='Remove an entry added by mistake (no profit/loss recorded)')
        if do_sell:
            h = pf.get(hid)
            q = h['qty'] if (h and sell_all) else sqty
            st.session_state['pf_msg'] = pf.sell(hid, q, sprice, store.current_price(h))
            st.rerun()
        if do_delete:
            st.session_state['pf_msg'] = pf.delete(hid)
            st.rerun()

    portfolio_view()


def nzd_overview(pf, tbl, store):
    """One set of numbers for the whole portfolio, in NZ dollars (every currency converted)."""
    summary = core.pl_summary(pf, tbl)
    if summary.empty:
        return
    rates, as_of, _ = core.nzd_rates(store)
    if len(rates) == 1 and any(c != 'NZD' for c in summary['Ccy']):
        st.caption('Totals in NZ dollars appear once the NZDUSD rate has loaded (it comes from the Forex market).')
        return
    tot, missing = core.nzd_totals(summary, rates)
    cost = tot['Value held'] - tot['Unrealised']
    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric('What you own is worth (NZ$)', f"{tot['Value held']:,.2f}")
        c2.metric('Profit on paper (NZ$)', f"{tot['Unrealised']:+,.2f}",
                  delta=f"{tot['Unrealised'] / cost * 100:+.1f}%" if cost > 0 else None,
                  help='Profit or loss on what you still own. It is only "on paper" until you sell.')
        c3.metric('Profit from sales (NZ$)', f"{tot['Realised']:+,.2f}",
                  help='Profit or loss on things you have already sold.')
        c4.metric('Total profit (NZ$)', f"{tot['Total']:+,.2f}")
        note = (f"Converted at 1 USD = {rates['USD']:,.4f} NZD (TradingView NZDUSD, {as_of:%H:%M})."
                if 'USD' in rates and as_of else 'All in NZD.')
        if missing:
            note += f" Not included (no rate yet): {', '.join(missing)}."
        st.caption(note)


OTHER_GROUP = 'WAITING FOR DATA'
OTHER_STYLE = core.TONE['neutral']


GROUP_HINTS = {'Think about selling': 'Look at these first. The line under each one says how strong the warning is.',
               'Keep an eye on it': 'Nothing to do now - just check them now and then.',
               'All fine': 'Nothing to do.',
               OTHER_GROUP: 'The app is still getting the data for these.'}


def plain_group(rec):
    return core.PLAIN_REC.get(rec, OTHER_GROUP)


def with_nzd(tbl, store):
    """Add the holding's value and profit/loss in NZ dollars (converted with rates the app already has)."""
    rates = core.nzd_rates(store)[0]
    rate = pd.to_numeric(tbl['Ccy'].map(lambda c: rates.get(c)), errors='coerce')
    num = lambda c: pd.to_numeric(tbl[c], errors='coerce')
    return tbl.assign(**{'Value (NZ$)': num('Value') * rate, 'Profit/loss (NZ$)': num('P/L') * rate})


def holdings_by_recommendation(tbl, store):
    """Holdings grouped under three plain headings, most urgent first (Think about selling, Keep an eye on it,
    All fine). Each group lists its holdings, then the plain-English reason for each one. Empty groups are left out."""
    group = tbl['Recommendation'].map(plain_group)
    worst_first = list(reversed(core.RECOMMENDATIONS))
    tbl = with_nzd(tbl, store).assign(**{'ATR status': tbl['ATR status'].map(lambda s: core.PLAIN_ATR.get(s, s))})
    for i, name in enumerate(core.PLAIN_REC_ORDER + [OTHER_GROUP]):
        rows = tbl[group == name]
        if rows.empty:
            continue
        rows = rows.sort_values('Recommendation', key=lambda s: s.map(
            lambda r: worst_first.index(r) if r in worst_first else 99))
        style = core.PLAIN_REC_COLOURS.get(name, OTHER_STYLE)
        n = len(rows)
        st.markdown(f'<div class="tvb-rec-head" style="{style}"><span>{name}</span>'
                    f'<b>{n} holding{"s" if n != 1 else ""}</b></div>', unsafe_allow_html=True)
        st.caption(GROUP_HINTS[name])
        shown = rows[['Symbol', 'Qty', 'Bought', 'Now', 'Ccy', 'Value (NZ$)', 'P/L', 'P/L %', 'Profit/loss (NZ$)',
                      'Rating', 'ATR status', 'Opp. score', 'Ticker', 'Market']]
        shown = with_names(shown.assign(**{'Opp. score': shown['Opp. score'].map(fmt_pts)}),   # '–' not 'None'
                           get_app()['store']).drop(columns='Market')
        table(shown, colour_cols=('Rating',), pl_cols=('P/L', 'P/L %', 'Profit/loss (NZ$)'),
              colours={'ATR status': core.PLAIN_ATR_COLOURS},
              fmt={'Qty': fmt_qty, 'Bought': fmt_num, 'Now': fmt_num, 'P/L': fmt_signed, 'P/L %': fmt_pct,
                   'Value (NZ$)': '{:,.2f}', 'Profit/loss (NZ$)': fmt_signed},
              key=f'tbl_holdings_{i}')
        for _, r in rows.iterrows():
            note = r['Reason'] or (r['Recommendation'] if name == OTHER_GROUP else '')
            if note:
                st.markdown(f"<div class='tvb-reason'><b>{r['Symbol']}</b>: {note}</div>", unsafe_allow_html=True)


@st.fragment(run_every=REFRESH_SECONDS)
def portfolio_view():
    app = get_app()
    pf, store = current_portfolio(app), app['store']
    tbl = core.portfolio_table(pf, store)

    nzd_overview(pf, tbl, store)
    st.markdown('#### What you own')
    timeframe_note()
    if tbl.empty:
        st.info('Nothing here yet. Click **Add holding** above to record something you have bought - or switch to '
                '**Practice** and try ideas with pretend money first.')
    else:
        st.caption('**The app never buys or sells for you** - it only tells you when to take a look. Safety levels '
                   'always use daily prices.')
        holdings_by_recommendation(tbl, store)
        explain_columns(['Name', 'Quantity', 'Paid (each)', 'Price now', 'Currency', 'Value (NZ$)', 'Profit/loss',
                         'Profit/loss %', 'Profit/loss (NZ$)', 'Chart signal', 'Safety check', 'Buy score today'])

        st.markdown('#### Safety levels: where you would sell if things go wrong')
        risk = tbl[tbl['ATR status'].isin(core.ATR_STATUSES)]     # holdings still waiting for data are explained above
        if risk.empty:
            st.caption('No safety levels yet - they appear once the daily prices have loaded.')
        else:
            risk = risk.assign(**{'ATR status': risk['ATR status'].map(core.PLAIN_ATR)})
            table(risk[['Symbol', 'Now', 'Trailing level', 'To level %', 'At risk', 'Ccy', 'ATR status', 'ATR',
                        'ATR %', 'High close', 'Initial level']], colour_cols=(),
                  colours={'ATR status': core.PLAIN_ATR_COLOURS},
                  fmt={'Now': fmt_num, 'ATR': fmt_num, 'ATR %': '{:.1f}%', 'High close': fmt_num,
                       'Initial level': fmt_num, 'Trailing level': fmt_num, 'To level %': '{:+.1f}%',
                       'At risk': '{:,.2f}'}, key='tbl_risk')
            explain_columns(['Safety level', 'Room to fall %', 'Loss if it falls to the safety level', 'Safety check',
                             'Typical daily move', 'Typical daily move %', 'Highest close seen',
                             'First safety level'])

    since = pf.meta.get('pl_since', 'the start')
    h1, h2 = st.columns([5, 1.3], vertical_alignment='bottom')
    h1.markdown(f"#### Profit and loss <span style='font-weight:normal;color:#7a869a;font-size:.9rem'>"
                f"(since {since}, in each currency)</span>", unsafe_allow_html=True)
    with h2.popover('Reset profit/loss', icon=':material/restart_alt:'):
        st.write('Start the "profit from sales" count again and clear the sales list? Your holdings are kept.')
        if st.button('Yes, reset', type='primary', key='reset_confirm'):
            st.session_state['pf_msg'] = pf.reset_pl()
            st.rerun(scope='app')
    summary = core.pl_summary(pf, tbl)
    if summary.empty:
        st.caption('Nothing yet.')
    else:
        table(summary, colour_cols=(), pl_cols=('Realised', 'Unrealised', 'Total'),
              fmt={'Value held': '{:,.2f}', 'Realised': fmt_signed, 'Unrealised': fmt_signed, 'Total': fmt_signed},
              key='tbl_pl')

    sales = core.sales_table(pf)
    if not sales.empty:
        st.markdown('#### Things you have sold')
        table(sales, colour_cols=(), pl_cols=('P/L',),
              fmt={'Qty': fmt_qty, 'Bought': fmt_num, 'Sold': fmt_num, 'P/L': fmt_signed}, key='tbl_sales')


def score_help():
    return f"""
**In short:** the app only considers things whose price trend TradingView rates **Strong Buy**. It gives each a
**buy score out of 100** for how strong and steady that trend looks (is it rising steadily, beating the market, not too
jumpy, not already shot up?). Then it applies **safety checks** - e.g. it must be in a long-term uptrend and not
too expensive compared with its recent prices. Only those passing every check are **QUALIFIED** buy ideas.
A high score means a strong trend **today**; it is not a promise, and not the chance of a gain.

**The detail, for the curious.** Each Strong Buy's score (the Composite Opportunity Score) is built from 8 parts:

| Part | Max | What earns points |
|---|---|---|
| Indicators | 30 | TradingView's overall rating of the 26 indicators (+1 = 30 points; bearish = 0) |
| Trend | 20 | Price above SMA200 (5), SMA50 above SMA200 (5), price above SMA50 (3), SMA20 above SMA50 (3), SMA50 rising (2), SMA200 rising (2) |
| Rel. strength | 15 | Beating the benchmark (S&P 500 for shares, Bitcoin for crypto) over about 3 months: more than 15 points ahead = 15, 10–15 = 13, 5–10 = 10, 0–5 = 7, behind = 0. Bitcoin is judged on its own return. |
| Momentum | 10 | RSI 50–70 (3), MACD histogram rising (3), rate of change positive (2), ADX above 25 in an uptrend (2). RSI above 80 costs 2. |
| Volume | 10 | Volume vs its average: over 1.5× = 10, 1.2–1.5× = 7, 1.0–1.2× = 4, 0.8–1.0× = 2 |
| Regime | 5 | The whole market: S&P 500 and Nasdaq above their SMA200 (for crypto, Bitcoin). Strong bull 5, bullish 4, mixed 2, bearish 0 |
| Risk | 5 | Calmer is better: daily range (ATR) up to 3% of price = 5, 3–5% = 4, 5–7% = 2 |
| Entry | 5 | Not chasing: price 0–3% above its 20-bar average = 5 … more than 12% above = 0 |

**Bands:** 90+ Exceptional · 80–89 Very strong · {S.ENTRY_MIN_SCORE}–79 Qualifies ·
{S.ENTRY_MIN_SCORE - 10}–{S.ENTRY_MIN_SCORE - 1} Watchlist · under {S.ENTRY_MIN_SCORE - 10} Ignore.

**Entry rules (a high score never overrides these).** To qualify for a new position a Strong Buy must
score **{S.ENTRY_MIN_SCORE}+** ({S.BEAR_MIN_SCORE}+ if its market is bearish), trade **above its SMA200**,
trade at least **${S.MIN_DAILY_DOLLAR_VOLUME:,.0f} a day**, and be no more than **{S.MAX_EXTENSION_PCT}%** above its
20-bar average. *Why* says what a rejected symbol failed.

**How much to put in** is worked out on each idea card from *your* total and the idea's safety level (the
same rules as the calculator on the Learn page): a fall to the safety level should cost you only about 1% of your
money, and no more than 10% of your money goes into one idea.

**Forex has its own score, out of exactly 100.** Currencies have no volume, benchmark or market regime and move about
a tenth as much as shares, so pairs are scored on:

| Part | Max | What earns points |
|---|---|---|
| Indicators | 30 | Same as above |
| Trend | 20 | Same as above |
| Rel. strength | 20 | **Currency strength**: the base currency's strength minus the quote currency's over about 3 months, measured across all 28 major pairs. Over 3% = 20, 1.5–3% = 15, 0.5–1.5% = 10, 0–0.5% = 6, behind = 0 |
| Momentum | 15 | The momentum points above × 1.5 |
| Entry | 10 | Not chasing, forex-sized: 0–0.5% above the 20-bar average = 10, 1% = 8, 1.5% = 5, 2.5% = 2, more = 0; below it = 6 |
| Risk | 5 | Calmer is better, forex-sized: daily range (ATR) up to 0.6% of price = 5, 0.9% = 4, 1.3% = 2 |

The entry rules are the same except forex has no liquidity limit and may be at most **{S.MAX_EXTENSION_PCT_FX}%** above
its 20-bar average (not {S.MAX_EXTENSION_PCT}%).

**Volume while a market is trading:** today's bar is still filling up, so its volume is scaled up to a full day by how
much of the session has passed (e.g. half-way through, half a normal day's volume counts as normal). Crypto bars are
scaled the same way. In the first 15% of a session or bar it's too early to judge, so volume is left out and the
rest scaled up to 100. On charts other than 1 Day, relative strength uses the 9-bar change
instead of 3 months.

These thresholds are sensible starting points, not proven ones. They can be changed in `settings.py`.
"""


def page_top_picks():
    page_head('Top picks: today\'s buy ideas',
              'The app checks every share, coin and currency pair it watches, scores how strong and steady each price trend '
              'looks, and runs safety checks. <b>Only the ones that pass every check are shown as ideas.</b> Some days '
              'there are none, and staying out is a perfectly good decision. Updates by itself.')
    timeframe_note()
    with st.expander('How the score and the safety checks work'):
        st.markdown(score_help())
    top_picks_view()


def track_line(summ):
    """One honest line: has following these picks worked so far?"""
    if summ is None or summ['beat_pct'] is None:
        return ('**Does this work?** The app is still building its track record - no past picks are old enough to '
                'judge yet. Treat every idea as unproven.')
    few = summ['n_aged'] < 20
    return (f"**Does this work?** So far, {summ['beat_pct']:.0f}% of {summ['n_aged']} past picks did better than "
            'simply owning the market' + (' - but that is far too few picks to trust yet.' if few else '.')
            + ' Details under **Track record**.')


def sizing_text(store, market, ticker, price, safety):
    """'How much?': the position-size calculator's answer for this idea, using the total saved on the Home page."""
    rate = core.nzd_rates(store)[0].get(core.quote_ccy(market, ticker))
    total = store.total_invested
    size = core.position_size(total, 1, price * rate, safety * rate, cap_pct=10) if rate else None
    if size is None:
        return ('**How much?** Use the position-size calculator on the **Learn** page with today\'s price and the '
                'safety level.')
    return (f"**How much?** With **NZ${total:,.0f}** invested in total, put in about **NZ${size['cost']:,.0f}**. If "
            f"the price falls to the safety level you'd lose about NZ${size['loss']:,.0f} "
            f"({size['loss_pct']:.1f}% of your money) - a small, planned loss. Change your total on the **Home** page; "
            'the full calculator is on **Learn**.')


ASSET_WARNING = {
    'Crypto': 'Crypto can rise or fall by half in a few months, and Sharesies doesn\'t offer it. If you buy any, keep '
              'it to a very small amount you could lose completely, and only use an NZ-registered exchange.',
    'Forex': 'Forex is a currency exchange rate, not something to own. It is almost always traded with borrowed money, '
             'and most beginners who trade it lose money. Use it here to understand currency moves.',
}


def idea_card(store, row, key, summ=None, fetch_news=True):
    """One buy idea in plain words: what it is, how strong, the business and the news, the plan (target, safety
    level), how much to put in, and the next steps - so you know exactly what to look at."""
    t, mk = row['Ticker'], row['Market']
    name = display_name(store, t, mk, row.get('Rating'))
    with st.container(border=True):
        st.markdown(f"### {row['Symbol']} <span style='font-size:.95rem;color:#556275'>{_safe(name)} · {mk}</span>",
                    unsafe_allow_html=True)
        st.progress(min(1.0, row['Score'] / 100), text=f"Buy score {row['Score']:.0f}/100 - {row['Band']}")
        st.caption('The buy score rates how strong and steady the price trend looks **today**. It is not the chance that the '
                   'price goes up.')
        if mk in ASSET_WARNING:
            st.warning(ASSET_WARNING[mk], icon=':material/warning:')
        if mk in ('US Stocks', 'NZ Stocks'):
            try:
                biz = core.business_summary(core.fundamentals(mk, [t], store).get(t))
            except Exception:
                biz = '–'
            if biz != '–':
                st.markdown(f'**The business:** {biz}')
        if news.enabled():
            if fetch_news:
                news.request(mk, [t])
            e = news.get(t)
            s = e and e['summary']
            mood = (f"{s['label']} ({s['n']} recent headline{'s' if s['n'] != 1 else ''})" if s
                    else ('checking...' if fetch_news else 'not checked yet') if e is None
                    else 'no recent headlines')
            st.markdown(f'**Recent news:** {mood}. Read the headlines on **Symbol Details** before deciding.')
        known = core.target_data_if_known(t, store)
        plan = core.exit_plan(known[0]) if known else None
        ccy = core.quote_ccy(mk, t)
        if plan:
            first = plan['stages'][0]
            st.markdown(f"**The plan:** now {core.money(plan['price'], ccy)} · first place to take some profit "
                        f"{core.money(first['low'], ccy)} ({(first['low'] / plan['price'] - 1) * 100:+.1f}%) · "
                        f"**safety level {core.money(plan['protect'], ccy)}** "
                        f"({(plan['protect'] / plan['price'] - 1) * 100:+.1f}%): if it closes below this, sell.")
            st.markdown(sizing_text(store, mk, t, plan['price'], plan['protect']))
        st.markdown(track_line(summ))
        price = plan['price'] if plan else None
        if price:
            p1, p2 = st.columns([1.4, 1.6], vertical_alignment='bottom')
            amount = p1.number_input(f'Practice amount ({ccy})', min_value=0.0, value=1000.0, step=100.0,
                                     key=f'{key}_amt')
            if p2.button('Try it in Practice', icon=':material/science:', key=f'{key}_practice', width='stretch',
                         help='Buys it with pretend money in your Practice portfolio, so you can follow how it does.'):
                ok, msg = get_app()['practice'].add_known(mk, t, price, amount / price)
                (st.toast(msg, icon=':material/science:') if ok else st.error(msg))
        where = ('buy it in **Sharesies** (Learn: *From an idea to an order*)' if mk in ('US Stocks', 'NZ Stocks')
                 else 'it is not on Sharesies - see Learn before going further')
        st.caption(f'**Next steps:** 1. read the business line and the news · 2. note the safety level · '
                   f'3. try it in Practice first · 4. if you go ahead, {where}, then record it on My Portfolio.')


@st.fragment(run_every=REFRESH_SECONDS)
def top_picks_view():
    store = get_app()['store']
    opp, best, regimes = core.opportunities(store)
    bull, bear = core.top_picks(store)
    if bull.empty:
        st.info('Loading from TradingView...')
        return
    if regimes:
        st.caption('Overall market mood: ' + plain_mood(regimes) + '. When a whole market is falling, the safety '
                   'checks are stricter.')
    records = {kind: core.track_record(store, kind) for kind in core.SIGNAL_KINDS}
    early = core.early_opportunities(store)
    n_early = 0 if early.empty else int(((early['Status'] == 'EARLY') & (early['Main'] != 'QUALIFIED')).sum())
    tabs = st.tabs(['Today\'s ideas', 'Everything scored', f'Riskier: early ideas ({n_early})', 'News',
                    'Track record', 'What are shares, crypto and forex?'])
    with tabs[0]:
        ok = opp[opp['Status'] == 'QUALIFIED'] if not opp.empty else opp
        if ok.empty:
            why = ('nothing is rated Strong Buy right now' if opp.empty
                   else f'none of the {len(opp)} Strong Buys passes every safety check')
            st.info(f'**No buy idea today:** {why}. Staying out is a perfectly good decision - the app will alert '
                    'you when something qualifies.', icon=':material/block:')
        else:
            shares = ok[ok['Market'].isin(['US Stocks', 'NZ Stocks'])]
            ordered = pd.concat([shares, ok.drop(shares.index)])        # shares first: you can buy them on Sharesies
            st.markdown(f'**{len(ok)}** idea{"s" if len(ok) != 1 else ""} passed every safety check today'
                        + (' - showing the best 3.' if len(ok) > 3 else '.') + ' Shares come first because you can '
                        'buy them on Sharesies.')
            for i, (_, row) in enumerate(ordered.head(3).iterrows()):
                idea_card(store, row, key=f'idea_{i}', summ=records['qualified'][1])
        if not opp.empty:
            exit_targets_box(opp, key='exit_top')
    with tabs[1]:
        st.markdown('#### Every Strong Buy, best score first')
        st.caption('Only things TradingView rates **Strong Buy** are scored. *Status* says whether each passed every '
                   'safety check; *Why* says what it failed.')
        if opp.empty:
            st.info('Nothing is rated Strong Buy right now.', icon=':material/block:')
        else:
            opp_table(opp)
        with st.expander('TradingView rating only: the 10 most positive and most negative'):
            c1, c2 = st.columns(2, gap='large')
            fmt = {'Indicator balance': '{:+.2f}'}
            with c1:
                st.markdown('#### Most positive')
                table(bull.rename(columns={'Score': 'Indicator balance'}), fmt=fmt, key='tbl_bull')
            with c2:
                st.markdown('#### Most negative')
                table(bear.rename(columns={'Score': 'Indicator balance'}), fmt=fmt, key='tbl_bear')
    with tabs[2]:
        st.markdown('#### Riskier: early ideas (trends just turning up)')
        st.warning('These try to catch a rise **near its start**, before it is a Strong Buy. Earlier means more '
                   'false starts: many of these fizzle out. Check the **Track record** tab to see whether they have '
                   'worked before trusting them.', icon=':material/warning:')
        with st.expander('How the early score works'):
            st.markdown(early_help())
        if early.empty:
            st.info('Nothing is rated Buy or Strong Buy right now.', icon=':material/block:')
        else:
            st.markdown(f'**{n_early}** early idea(s) that don\'t yet qualify on the main score.')
            early_table(early)
    with tabs[3]:
        news_picks_box(opp, early)
    with tabs[4]:
        track_record_compare(records)
        for kind, (df, summ) in records.items():
            track_record_box(df, summ, kind)
    with tabs[5]:
        asset_types_table()
    st.caption('Looking beyond your watchlists? **Market Scan** (under Advanced in the menu) searches whole markets.')


def page_market_scan():
    page_head('Market scan: search beyond your watchlists',
              'Top Picks only looks at the few dozen names in your watchlists. This page searches a <b>whole market</b> '
              'at once (click a button) and scores what it finds the same way. More choice also means more '
              'unfamiliar names: read the <b>Business</b> column and the news before trusting any of them.')
    timeframe_note()
    market_scan_view()


@st.fragment(run_every=REFRESH_SECONDS)
def market_scan_view():
    market_scan(get_app()['store'])


def scan_scope(mk):
    """What a market's scan searches (shown on the page)."""
    cap = get_app()['store'].scan_min_cap()
    us = (f'US companies worth over US${cap / 1e9:,.1f} billion' if cap else 'every US share (any size)')
    return {'Crypto': 'every coin on Binance priced in USDT (not futures)',
            'US Stocks': f'{us} on NASDAQ, NYSE or AMEX',
            'NZ Stocks': 'every company listed on the NZX (any size)',
            'Forex': 'the 28 pairs between the 8 major currencies'}.get(mk, 'the whole market')


def market_scan(store):
    """Widget: Strong Buys outside the watchlists, found by scanning one market at a time, SCAN_MIN_SCORE and up."""
    sc = store.scan
    with st.container(border=True):
        st.caption('Searches TradingView for everything rated **Buy or Strong Buy** that is not in your watchlists. '
                   f'Strong Buys in a long-term uptrend get the buy score (listed from {S.SCAN_MIN_SCORE}); every one '
                   'also gets the riskier **early score**, which looks for rises just starting (listed from '
                   f'{S.SCAN_EARLY_MIN_SCORE}). Each market takes one request, only when you click its button.')
        if store.beginner:
            st.caption(f'**Beginner mode:** US companies worth less than US${S.BEGINNER_MIN_MARKET_CAP / 1e9:,.0f} '
                       'billion are left out - small companies can swing wildly and are easier to manipulate.')
        cols = st.columns(len(S.RUN_MARKETS))
        for col, mk in zip(cols, S.RUN_MARKETS):
            if col.button(f'Scan {mk}', icon=':material/travel_explore:', key=f'scan_{mk}',
                          disabled=bool(sc['running']), help=f'Searches {scan_scope(mk)}. One request.'):
                store.start_scan(mk)
                st.session_state['scan_tab'] = mk          # show that market's tab, where its results will appear
        if sc['running']:
            st.info(sc['progress'] or f"Scanning {sc['running']}...", icon=':material/hourglass_top:')
        tabs = st.tabs([*S.RUN_MARKETS, NEWS_TAB], key='scan_tab', on_change='rerun')
        for tab, mk in zip(tabs, S.RUN_MARKETS):
            with tab:
                scan_result(store, mk, sc['results'].get(mk))
        with tabs[-1]:
            scan_news(sc['results'])


NEWS_TAB = 'News (QUALIFIED)'
SCAN_NEWS_MAX = 30          # news for at most this many QUALIFIED scan results (best scores first)


def scan_news(results):
    """Market Scan's News tab: a brief news breakdown for every QUALIFIED symbol the scans found."""
    rows = []
    for mk in S.RUN_MARKETS:
        res = results.get(mk)
        df = res['df'] if res else pd.DataFrame()
        if not df.empty:
            rows += df[df['Status'] == 'QUALIFIED'].to_dict('records')
    if not news.enabled():
        st.caption('News is switched off (NEWS_ENABLED in settings.py).')
        return
    if not rows:
        st.info('No QUALIFIED symbols yet. Scan a market above; the news for every QUALIFIED symbol it finds shows '
                'here.', icon=':material/newspaper:')
        return
    rows = sorted(rows, key=lambda r: -(r['Score'] or 0))
    more = len(rows) - SCAN_NEWS_MAX
    rows = rows[:SCAN_NEWS_MAX]
    for mk in dict.fromkeys(r['Market'] for r in rows):
        news.request(mk, [r['Ticker'] for r in rows if r['Market'] == mk])
    st.caption(f'The last {S.NEWS_MAX_AGE_DAYS} days\' headlines for each QUALIFIED symbol from the scans, rated by '
               'FinBERT. **For context only: it does not change any score.** Fetched in the background, one '
               'symbol at a time, so the list fills in over a minute or so.'
               + (f' Showing the {SCAN_NEWS_MAX} best scores ({more} more not shown).' if more > 0 else ''))
    if news.status():
        st.caption(news.status())
    table_rows = []
    for r in rows:
        e = news.get(r['Ticker'])
        s = e and e['summary']
        table_rows.append({'Market': r['Market'], 'Symbol': r['Symbol'], 'Score': r['Score'],
                           'News': s['label'] if s else ('…' if e is None else '–'),
                           'Sentiment': s['score'] if s else None,
                           'Positive': s['pos'] if s else None, 'Neutral': s['neu'] if s else None,
                           'Negative': s['neg'] if s else None, 'Ticker': r['Ticker']})
    table(pd.DataFrame(table_rows), colour_cols=(), colours={'News': news.LABEL_COLOURS},
          fmt={'Score': '{:.1f}', 'Sentiment': '{:+.2f}', 'Positive': '{:.0f}', 'Neutral': '{:.0f}',
               'Negative': '{:.0f}'}, key='tbl_scan_news')
    for r in rows:
        e = news.get(r['Ticker'])
        with st.container(border=True):
            st.markdown(f"**{r['Symbol']}** · {r['Market']} · score {r['Score']:.1f}")
            if e is None:
                st.caption('Getting headlines...')
            elif e['error'] and not e['items']:
                st.caption(f"Could not get news: {e['error']}")
            elif not e['items']:
                st.caption(f'No headlines in the last {S.NEWS_MAX_AGE_DAYS} days.')
            else:
                if e['summary']:
                    st.markdown(news_breakdown(e), unsafe_allow_html=True)
                else:
                    st.caption('Headlines found; waiting for their ratings.')
                with st.expander(f"All {len(e['items'])} headlines"):
                    st.markdown(headline_list(e['items']), unsafe_allow_html=True)


def scan_result(store, mk, res):
    if res is None:
        st.caption(f'{mk} not scanned yet. It searches {scan_scope(mk)}.')
        return
    label = core.timeframe_label(res['interval'])
    st.caption(f"Scanned at {res['time']:%H:%M:%S} on the **{label}** chart. "
               f"{res['found'].get(mk, 0)} Buy or Strong Buy symbols found outside your watchlist.")
    if res['interval'] != store.interval:
        st.warning(f'This scan used the {label} chart. Scan again for the {core.timeframe_label(store.interval)} '
                   'chart.', icon=':material/schedule:')
    for msg in res['errors'].values():
        st.warning(f'Not scanned: {msg}')
    df = res['df']
    st.markdown('##### Strong Buys, with their buy score')
    if df.empty:
        if not res['errors']:
            st.info(f'No other {mk} Strong Buy scored {S.SCAN_MIN_SCORE} or more.')
    else:
        n_ok = int((df['Status'] == 'QUALIFIED').sum())
        st.markdown(f'**{len(df)}** scored {S.SCAN_MIN_SCORE}+, of which **{n_ok}** pass every safety check '
                    '(*QUALIFIED*).')
        shown = df
        if len(df) > 25 and not st.toggle(f'Show all {len(df)}', key=f'scan_all_{mk}'):
            shown = df.head(25)
        score_table(shown, key=f'tbl_scan_{mk}')
        why_summary(df, 'QUALIFIED', f'the other {len(df) - n_ok}')
    early = res.get('early', core.pd.DataFrame())
    st.markdown('##### Early signals (riskier): rises just starting')
    with st.expander('How the early score works'):
        st.markdown(early_help())
    if early.empty:
        if not res['errors']:
            st.info(f'No other {mk} Buy or Strong Buy scored {S.SCAN_EARLY_MIN_SCORE} or more on the early score.')
    else:
        n_early = int(((early['Status'] == 'EARLY') & (early['Main'] != 'QUALIFIED')).sum())
        st.markdown(f'**{len(early)}** scored {S.SCAN_EARLY_MIN_SCORE}+, of which **{n_early}** are *EARLY* and '
                    'don\'t yet qualify on the main score.')
        early_table(early, key=f'tbl_scan_early_{mk}', lead_cols=('Symbol',))
        why_summary(early, 'EARLY', f"the other {len(early) - int((early['Status'] == 'EARLY').sum())}")
    frames = [d for d in (df, early) if not d.empty]
    if frames:                                               # every symbol found, not just the ones on screen
        exit_targets_box(core.pd.concat(frames, ignore_index=True).drop_duplicates('Ticker'), key=f'exit_scan_{mk}')


def fmt_share(v):
    return '–' if v is None or pd.isna(v) else f'{v:.0f}%'


def fmt_signed_pct(v):
    return '–' if v is None or pd.isna(v) else f'{v:+.1f}%'


TRACK_HORIZON_COLS = [f'After {label} %' for label in core.SIGNAL_HORIZONS]


def track_record_compare(records):
    """QUALIFIED vs EARLY at a glance: the question the two track records exist to answer."""
    rows = []
    for kind, (_, s) in records.items():
        row = {'Picks': core.SIGNAL_KINDS[kind], 'Logged': 0 if s is None else s['n']}
        if s is not None:
            row.update({'Average return %': s['avg'], 'Benchmark %': s['bench_avg'], 'Beat it': s['beat_pct'],
                        'Went up': s['win_pct'], 'With exit %': s['exit_avg'],
                        **{f'After {label} %': s['horizons'][label]['avg'] for label in core.SIGNAL_HORIZONS}})
        rows.append(row)
    st.markdown('#### Track record: main score vs early score')
    pcts = ['Average return %', 'Benchmark %', 'With exit %'] + TRACK_HORIZON_COLS
    df = pd.DataFrame(rows).reindex(columns=['Picks', 'Logged', *pcts[:2], 'Beat it', 'Went up', *pcts[2:]])
    table(df, colour_cols=(), pl_cols=tuple(pcts), key='tbl_track_compare',
          fmt={**{c: fmt_signed_pct for c in pcts}, 'Beat it': fmt_share, 'Went up': fmt_share})
    st.caption('Average of every pick at least a day old. *Beat it* = share of picks that did better than their '
               'benchmark (forex and Bitcoin are compared with holding cash). *After 1 / 4 / 12 weeks* only count '
               'picks that have reached that age, so they are the fairest comparison. Details in the two boxes below.')


def track_record_box(df, summ, kind='qualified'):
    """How past QUALIFIED (or EARLY) picks have done since - the evidence for (or against) following the signals."""
    word = core.SIGNAL_KINDS[kind]
    title = f'Track record: how past {word} picks have done'
    with st.expander(title + (f" ({summ['n']} logged since {summ['since']})" if summ else ''), expanded=False):
        st.caption(f'Every time a watchlist symbol is {word} on the daily chart, the app writes down its price, its '
                   'benchmark\'s (S&P 500, S&P/NZX 50 or Bitcoin) and its safety level, at most once a week per '
                   'symbol. It uses the daily chart whatever timeframe you have on screen. This is the honest test: '
                   '**do the signals beat simply owning the market?** It builds up while the app runs, so give it a '
                   'few weeks before reading much into it.')
        if summ is None:
            st.info('Nothing logged yet. Picks are logged automatically while the app is running.')
            return
        c = st.columns(5)
        c[0].metric('Picks logged', summ['n'])
        c[1].metric('Average return', fmt_signed_pct(summ['avg']))
        c[2].metric('Benchmark, same dates', fmt_signed_pct(summ['bench_avg']))
        c[3].metric('Picks that beat it', fmt_share(summ['beat_pct']))
        c[4].metric('With the exit rule', fmt_signed_pct(summ['exit_avg']),
                    help='Average return if you had sold at the safety level whenever the price fell to it')
        notes = []
        if summ['n_aged'] < 20:
            notes.append(f"Only {summ['n_aged']} pick(s) are at least a day old - too few to judge the signals yet.")
        if summ['n_missing']:
            notes.append(f"{summ['n_missing']} pick(s) have no price yet (their market hasn't loaded) and are left "
                         'out of the averages.')
        if summ['n_hit']:
            notes.append(f"{summ['n_hit']} pick(s) fell to their safety level.")
        if notes:
            st.caption(' '.join(notes))
        h = summ['horizons']
        st.markdown('**At fixed ages** (like with like): ' + ' · '.join(
            f"after {label}: " + (f"{fmt_signed_pct(v['avg'])} on average, {fmt_share(v['beat_pct'])} beat it "
                                  f"({v['n']} pick{'s' if v['n'] != 1 else ''})" if v['n'] else 'none yet')
            for label, v in h.items()))
        shown = df.head(50)
        yes_no = {True: 'Yes', False: 'No'}
        table(shown.assign(**{'Beat it': shown['Beat it'].map(yes_no).fillna('–'),
                              'Hit it': shown['Hit it'].map(yes_no).fillna('–')}),
              colour_cols=(), pl_cols=('Return %', 'Benchmark %', 'Lowest %', 'With exit %', *TRACK_HORIZON_COLS),
              fmt={'Score': fmt_pts, 'Then': fmt_num, 'Now': fmt_num, 'Protective': fmt_num, 'Return %': fmt_pct,
                   'Benchmark %': fmt_pct, 'Lowest %': fmt_pct, 'With exit %': fmt_pct,
                   **{col: fmt_pct for col in TRACK_HORIZON_COLS}},
              key=f'tbl_track_{kind}')
        st.caption('*Lowest* and the fixed-age prices only cover the time the app was running. Picks logged before '
                   'these columns existed have no safety level, so *Fell to it* shows –.')
        st.download_button('Download as CSV (for Excel)', df.to_csv(index=False).encode('utf-8'),
                           file_name=f'track_record_{kind}.csv', mime='text/csv', icon=':material/download:',
                           key=f'dl_track_{kind}')


def exit_targets_box(df, key):
    """Pick a symbol from the table above and get staged take-profit targets, worked out from TradingView's data."""
    if df.empty or 'Ticker' not in df.columns:
        return
    rows = {r['Ticker']: r for _, r in df.iterrows()}
    with st.container(border=True):
        st.markdown('#### Plan your exit: where to take profit, and your safety level')
        st.caption('**Decide how you will get out before you buy.** Pick a symbol: the app shows prices where rises '
                   'often pause (good places to take some profit) and the **safety level** where you\'d sell if it '
                   'goes wrong. Worked out from TradingView\'s own numbers (past price levels, analysts\' forecasts '
                   'and how much the price usually moves) - no guessing.')
        store = get_app()['store']
        c1, c2 = st.columns([3, 1.3], vertical_alignment='bottom')
        t = c1.selectbox('Symbol', list(rows), key=f'{key}_sym', format_func=lambda x: (
            f"{rows[x]['Symbol']} ({rows[x]['Market']})"
            + (f" · score {rows[x]['Score']:.0f}" if pd.notna(rows[x].get('Score')) else '')))
        known = core.target_data_if_known(t, store)          # no request: loaded data or an earlier fetch
        label = 'Refresh the plan' if known else 'Show the plan'
        if c2.button(label, icon=':material/refresh:' if known else ':material/flag:', key=f'{key}_go',
                     width='stretch', help='Gets the latest figures from TradingView (one request).' if known
                     else 'Works out the targets (one request if the app doesn\'t already have the figures).'):
            try:
                known = core.fetch_target_data(rows[t]['Market'], t, store, force=bool(known))
                st.session_state.pop(f'{key}_err', None)
            except Exception as e:
                st.session_state[f'{key}_err'] = (t, str(e) or type(e).__name__)
        err = st.session_state.get(f'{key}_err')
        if err and err[0] == t:
            st.warning(f'Could not get the data for {core.short(t)}: {err[1]}')
        if not known:
            return
        values, when = known
        r = rows[t]
        ccy = core.quote_ccy(r['Market'], t)
        st.markdown(core.exit_write_up(r['Symbol'], r['Rating'], core.exit_plan(values), ccy))
        st.caption(f'Calculated from TradingView\'s daily data at {when:%H:%M}. Chart levels only, not financial '
                   'advice. The app never places a trade.')
        price = core._num(values, 'close')
        if price and plan_ok(values):
            st.markdown(sizing_text(store, r['Market'], t, price, core.exit_plan(values)['protect']))
        if price:                          # try the idea with pretend money first
            p1, p2 = st.columns([2, 1.6], vertical_alignment='bottom')
            amount = p1.number_input(f'Practice amount ({ccy})', min_value=0.0, value=1000.0, step=100.0,
                                     key=f'{key}_amt')
            if p2.button('Add to Practice portfolio', icon=':material/science:', key=f'{key}_practice',
                         width='stretch'):
                ok, msg = get_app()['practice'].add_known(r['Market'], t, price, amount / price)
                (st.toast(msg, icon=':material/science:') if ok else st.error(msg))


def plan_ok(values):
    return core.exit_plan(values) is not None


def opp_table(opp):
    view = opp
    if len(opp) > 15 and not st.toggle(f'Show all {len(opp)} Strong Buys', key='opp_all'):
        view = opp.head(15)
    score_table(view, key='tbl_opp', lead_cols=('Market', 'Symbol'))


COLUMN_HELP['Main'] = ('QUALIFIED = it also passes the main checks today, so the rise is no longer "early" (it is '
                       'one of Today\'s ideas)')
EARLY_HELP = {
    'Status': 'EARLY = passes every early check. REJECTED = see Why',
    'Main': COLUMN_HELP['Main'],
    **part_help(core.EARLY_WEIGHTS, core.FX_EARLY_WEIGHTS, 'early score'),
}


def early_table(df, key='tbl_early', lead_cols=('Market', 'Symbol')):
    """The Early Entry Score table (Buy and Strong Buy symbols)."""
    parts = st.toggle('Show early score breakdown', key=f'{key}_parts')
    view = df if len(df) <= 15 or st.toggle(f'Show all {len(df)}', key=f'{key}_all') else df.head(15)
    view = with_why(with_names(view, get_app()['store']), 'EARLY', 'Passes every early check')
    renamed = EARLY_HEADERS
    cols = [*lead_cols, 'Name', 'Rating', 'Score', 'Status', 'Main', *(core.EARLY_WEIGHTS if parts else ()), 'Why',
            'Ticker']
    bar = st.column_config.ProgressColumn('Score', help='Early Entry Score, 0-100: how strongly the trend is turning up',
                                          min_value=0, max_value=100, format='%.1f', width='small')
    config = {'Score': bar, 'Why': st.column_config.TextColumn('Why', help=COLUMN_HELP['Why'], width='large')}
    config.update({c: st.column_config.Column(help=h) for c, h in EARLY_HELP.items()})
    table(view[[c for c in cols if c in view.columns]].rename(columns=renamed), colour_cols=('Rating',),
          colours={'Status': core.EARLY_STATUS_COLOURS, 'Main': core.STATUS_COLOURS},
          fmt={v: fmt_pts for v in renamed.values()}, key=key, column_config=config)
    explain_columns(['Name', 'Chart signal', 'Status', 'Main', 'Why', 'Chart'])


def early_help():
    return f"""
The main score mostly rewards things that only appear once a run is mature: a **Strong Buy** rating, SMA50 above
SMA200, and 3 months of beating the market. So it tends to qualify symbols late in a move. The **Early Entry Score**
looks for a trend that is **turning up**, and scores **Buy** as well as Strong Buy symbols:

| Part | Max | What earns points |
|---|---|---|
| Turn | 30 | Price back above SMA20 (8 if it crossed in the last bar, else 4), SMA20 crossing above SMA50 (8; 4 if about to cross, 2 if already above), MACD crossing up while still below zero (7) or histogram turning up from below zero (5), RSI rising through 50 (7) or rising between 45 and 62 (4) |
| Shift | 20 | Oscillator rating (up to 10), +DI crossing above -DI (5; 2 if already above), Awesome Oscillator rising (5 from below zero, else 2) |
| Not late | 20 | Starts at 20. 3-month gain over 15/25/40% costs 3/6/10, RSI over 68/75 costs 4/8, price over 6/9% above SMA20 costs 3/6 |
| Rel. 1M | 10 | Beating the benchmark over about a month: more than 5 points ahead = 10, 2–5 = 7, 0–2 = 5 |
| Volume | 10 | Same as the main score |
| Regime | 5 | Same as the main score |
| Risk | 5 | Same as the main score |

**EARLY** means: Buy or Strong Buy, early score **{S.EARLY_MIN_SCORE}+** ({S.EARLY_BEAR_MIN_SCORE}+ in a bearish market),
price above its SMA20, enough liquidity, and no more than {S.MAX_EXTENSION_PCT}% above SMA20.

**Forex has its own early score, out of exactly 100** (nothing left out or scaled up):

| Part | Max | What earns points |
|---|---|---|
| Turn | 30 | Same as above |
| Shift | 20 | Same as above |
| Rel. 1M | 20 | **Currency strength**: the base currency's strength minus the quote currency's over 1 month, measured across all 28 major pairs (over 1.5% = 12, 0.75–1.5% = 9, 0.25–0.75% = 6, 0–0.25% = 3), +8 if the base currency is gaining faster lately than over 3 months (1 Day chart only) |
| Not late | 15 | Starts at 15. 3-month move over 2.5/4/6% costs 2/5/8, RSI over 68/75 costs 3/6, price over 1.2/2% above SMA20 costs 2/4 |
| Regime | 10 | The pair's own bigger trend: price above its SMA200 and SMA50 rising = 10, one of the two = 4 |
| Risk | 5 | Calmer is better, forex-sized: daily range (ATR) up to 0.6% of price = 5, 0.9% = 4, 1.3% = 2 |

For forex, "no more than X% above SMA20" is **{S.MAX_EXTENSION_PCT_FX}%** instead of {S.MAX_EXTENSION_PCT}%.

**Earlier means less certain.** Many turns fizzle out. EARLY picks are logged in their own track record so you can see
whether they actually beat the main score before you use them.
"""


# ---------------------------------------------------------------- news and sentiment
def _news_ago(when):
    """'3 h ago' for a time-zone-aware time (headline times are in UTC)."""
    if when is None:
        return ''
    mins = (pd.Timestamp.now(tz='UTC') - pd.Timestamp(when)).total_seconds() / 60
    return (f'{mins:.0f} min ago' if mins < 60 else f'{mins / 60:.0f} h ago' if mins < 48 * 60
            else f'{mins / 1440:.0f} days ago')


def _badge(label):
    return (f'<span class="tvb-badge" style="{news.LABEL_COLOURS.get(label, "")}">{label}</span>' if label
            else '<span class="tvb-badge" style="color:#7a869a">not rated</span>')


def _safe(text):
    import html
    return html.escape(text or '').replace('$', '&#36;')     # ($ would start a maths formula in Streamlit)


def _headline_link(i):
    return (f"<a href=\"{_safe(i['url'])}\" target=\"_blank\">{_safe(i['title'])}</a>"
            f" <span style=\"color:#7a869a\">· {_safe(i['source'])} · {_news_ago(i['published'])}</span>")


def news_breakdown(e):
    """A brief breakdown of a symbol's news (HTML): the overall mood, how the headlines split, and the most
    positive and most negative headline, so you needn't read them all."""
    s = e and e.get('summary')
    if not s:
        return ''
    out = [f"{_badge(s['label'])} &nbsp;<b>{s['label']}</b> overall (average {s['score']:+.2f} from {s['n']} "
           f"headline{'s' if s['n'] != 1 else ''}): {s['pos']} positive · {s['neu']} neutral · {s['neg']} negative"]
    rated = [i for i in e['items'] if i.get('score') is not None]
    best = max(rated, key=lambda i: i['score'], default=None)
    worst = min(rated, key=lambda i: i['score'], default=None)
    if best and best['score'] >= 0.3:
        out.append(f"<span style=\"color:#0b7a3b\">▲ Most positive:</span> {_headline_link(best)}")
    if worst and worst['score'] <= -0.3:
        out.append(f"<span style=\"color:#b3261e\">▼ Most negative:</span> {_headline_link(worst)}")
    if len(out) == 1:
        out.append('<span style="color:#7a869a">No headline is strongly positive or negative.</span>')
    return '<div style="line-height:1.9">' + '<br>'.join(out) + '</div>'


def headline_list(items):
    """Every headline, each with its rating (HTML)."""
    return ('<div style="line-height:1.9">'
            + '<br>'.join(f"{_badge(i.get('label'))} &nbsp;{_headline_link(i)}" for i in items) + '</div>')


@st.fragment(run_every=REFRESH_SECONDS)
def news_panel(market, ticker):
    """Symbol Details: recent headlines for one symbol, each rated by FinBERT, and the overall mood."""
    with st.container(border=True):
        st.markdown(f'**News** from the last {S.NEWS_MAX_AGE_DAYS} days, rated by FinBERT (a financial-news model on '
                    'this computer). Shown for context only: it does not change any score.')
        if not news.enabled():
            st.caption('News is switched off (NEWS_ENABLED in settings.py).')
            return
        news.request(market, [ticker])
        e = news.get(ticker)
        if e is None:
            st.caption('Getting the latest headlines...')
            return
        if news.status():
            st.caption(news.status())
        if e['error'] and not e['items']:
            st.warning(f"Could not get news: {e['error']}")
            return
        if not e['items']:
            st.caption(f"No headlines in the last {S.NEWS_MAX_AGE_DAYS} days ({e['source']}).")
            return
        if e['summary']:
            st.markdown(news_breakdown(e), unsafe_allow_html=True)
        with st.expander(f"All {len(e['items'])} headlines", expanded=not e['summary']):
            st.markdown(headline_list(e['items']), unsafe_allow_html=True)
        st.caption(f"From {e['source']}, checked {_news_ago(pd.Timestamp.fromtimestamp(e['time'], tz='UTC'))}. "
                   'Headlines only: articles open on the publisher\'s site.')


def news_picks_box(opp, early):
    """Top Picks: the news mood for today's QUALIFIED and EARLY picks (fetched in the background)."""
    if not news.enabled():
        return
    rows = []
    for d, kind in ((opp, 'QUALIFIED'), (early, 'EARLY')):
        if d.empty or 'Ticker' not in d.columns:
            continue
        for _, r in d[d['Status'] == kind].iterrows():
            if not any(x['Ticker'] == r['Ticker'] for x in rows):
                rows.append({'Market': r['Market'], 'Symbol': r['Symbol'], 'Signal': kind, 'Ticker': r['Ticker']})
    st.markdown('#### News on today\'s picks')
    if not rows:
        st.caption('No QUALIFIED or EARLY picks right now, so there is no news to check.')
        return
    for mk in dict.fromkeys(r['Market'] for r in rows):
        news.request(mk, [r['Ticker'] for r in rows if r['Market'] == mk])
    for r in rows:
        e = news.get(r['Ticker'])
        s = e and e['summary']
        r.update({'News': s['label'] if s else ('…' if e is None else '–'),
                  'Sentiment': s['score'] if s else None, 'Headlines': len(e['items']) if e else None,
                  'Latest headline': e['items'][0]['title'] if e and e['items'] else
                  ('loading...' if e is None else (e['error'] or 'none this week'))})
    st.caption('Recent headlines for each pick, rated Positive / Neutral / Negative by FinBERT. Sentiment runs from −1 '
               '(all negative) to +1 (all positive). **For context only: it does not change any score.** The mood '
               'is also saved with each logged pick, so later you can check whether it helped. See every headline '
               'on **Symbol Details**.')
    if news.status():
        st.caption(news.status())
    df = pd.DataFrame(rows)[['Market', 'Symbol', 'Signal', 'News', 'Sentiment', 'Headlines', 'Latest headline',
                             'Ticker']]
    table(df, colour_cols=(), colours={'News': news.LABEL_COLOURS, 'Signal': {**core.STATUS_COLOURS,
                                                                             **core.EARLY_STATUS_COLOURS}},
          fmt={'Sentiment': '{:+.2f}', 'Headlines': '{:.0f}'}, key='tbl_news_picks',
          column_config={'Latest headline': st.column_config.TextColumn('Latest headline', width='large')})


@st.fragment(run_every=REFRESH_SECONDS)
def reload_when_loaded():
    """On a page opened before any data arrived: redraw the page as soon as it has (no click needed)."""
    if get_app()['store'].all_symbols():
        st.rerun(scope='app')


TV_CHART_INTERVAL = {'1m': '1', '5m': '5', '15m': '15', '30m': '30', '1h': '60', '2h': '120', '4h': '240',
                     '1d': 'D', '1W': 'W', '1M': 'M'}


def chart_url(ticker):
    """TradingView's chart page for a symbol (opens in your browser; TradingView's free charts)."""
    return 'https://www.tradingview.com/chart/?symbol=' + quote(ticker, safe='')


def tv_chart(ticker, interval, height=460):
    """TradingView's free embeddable chart for one symbol, on the app's timeframe."""
    # A fixed height: TradingView's 'autosize' measures its box too early inside Streamlit's frame and draws squashed.
    cfg = {'autosize': False, 'width': '100%', 'height': height, 'symbol': ticker,
           'interval': TV_CHART_INTERVAL.get(interval, 'D'),
           'timezone': 'Pacific/Auckland', 'theme': 'light', 'style': '1', 'locale': 'en',
           'hide_side_toolbar': True, 'allow_symbol_change': False, 'save_image': False,
           'studies': ['STD;SMA'], 'support_host': 'https://www.tradingview.com'}
    components.html(
        '<div class="tradingview-widget-container" style="width:100%">'
        '<div class="tradingview-widget-container__widget"></div>'
        '<script type="text/javascript" '
        'src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>'
        f'{json.dumps(cfg)}</script></div>', height=height + 10)


def page_symbol():
    store = get_app()['store']
    page_head('Symbol details: one name up close',
              'Pick any share, coin or currency pair to see its price chart, its recent news, whether the short and '
              'long-term trends agree, and what each of TradingView\'s 26 chart tools says. Use it to double-check an '
              'idea before you act on it.')
    timeframe_note()
    options = store.all_symbols()
    if not options:
        st.info('Loading from TradingView...')
        reload_when_loaded()
        return
    default = options.index('BINANCE:BTCUSDT') if 'BINANCE:BTCUSDT' in options else 0
    mk_of = {t: market_of(store, t) for t in options}
    t = st.selectbox('Symbol', options, index=default, key='detail_symbol', format_func=lambda x: (
        f'{core.short(x)} - {display_name(store, x, mk_of.get(x))}'.rstrip(' -')))
    a = store.analysis(t)
    s = a.summary
    rating = core.LABELS[s['RECOMMENDATION']]
    mk = mk_of.get(t)
    st.markdown(f'<b>{t}</b> {_safe(display_name(store, t, mk, rating))} &nbsp; <span class="tvb-badge" '
                f'style="{core.COLOURS[rating]}">{rating}</span> &nbsp; '
                f"Buy <b>{s['BUY']}</b> · Neutral <b>{s['NEUTRAL']}</b> · Sell <b>{s['SELL']}</b> &nbsp; "
                f'<a href="{chart_url(t)}" target="_blank">Open on TradingView ↗</a>', unsafe_allow_html=True)
    st.caption(f'**{rating}** is TradingView\'s verdict on the price trend right now: of its 26 chart tools, '
               f"{s['BUY']} say Buy, {s['NEUTRAL']} Neutral and {s['SELL']} Sell. It is not a forecast.")
    timeframe_check_box(store, t)
    if mk:
        news_panel(mk, t)
    with st.expander('Price chart', expanded=True):
        tv_chart(t, store.interval)
    bd = core.breakdown(a)
    cols = st.columns(2, gap='large')
    for col, (group, g) in zip(cols, bd.groupby('Type', sort=False)):
        with col:
            st.markdown(f'#### {group}s ({len(g)})')
            table(g[['Indicator', 'Signal']], colour_cols=('Signal',), key=f'tbl_{group}')


def market_of(store, ticker):
    """Which market a ticker belongs to (from the data loaded, or the holdings)."""
    for data in list(store._data.values()):
        for mk, d in list(data.items()):
            if ticker in d['raw']:
                return mk
    return next((h['market'] for p in store.portfolios for h in p.holdings if h['ticker'] == ticker), None)


def timeframe_check_box(store, t):
    """Do the 1 Hour, 4 Hours, 1 Day and 1 Week charts agree? Timeframes already loaded are reused; the rest cost
    one request, only when you click."""
    mk = market_of(store, t)
    with st.container(border=True):
        h1, h2 = st.columns([4, 1.4], vertical_alignment='center')
        h1.markdown('**Timeframe check**: do the short and long-term charts agree? Signals that agree across '
                    'timeframes are more reliable.')
        ratings, when = core.timeframe_check(store, mk, t)
        missing = [lbl for lbl, a in ratings.items() if a is None]
        label = f"Check {', '.join(missing)}" if missing else 'Refresh'
        if mk and h2.button(label, icon=':material/schedule:', key='tf_check', width='stretch',
                            help='One request to TradingView for this symbol. Timeframes the app already has are '
                                 'reused.'):
            try:
                core.timeframe_check(store, mk, t, fetch=True, force=not missing)
                st.rerun()                     # redraw so the button and chips show the new state straight away
            except Exception as e:
                st.warning(f'Could not get the other timeframes: {e}')
        cells = []
        for lbl, a in ratings.items():
            if a is None:
                cells.append(f'<span class="tvb-chip"><b>{lbl}</b> not loaded</span>')
            else:
                r, s = core.LABELS[a.summary['RECOMMENDATION']], a.summary
                cells.append(f'<span class="tvb-chip"><b>{lbl}</b> <span class="tvb-badge" '
                             f'style="{core.COLOURS[r]}">{r}</span> {s["BUY"]}/{s["NEUTRAL"]}/{s["SELL"]}</span>')
        st.markdown(f'<div class="tvb-status" style="margin:.3rem 0">{"".join(cells)}</div>', unsafe_allow_html=True)
        note = core.agreement(ratings)
        if note:
            st.caption(note + (f' Checked at {when:%H:%M}.' if when else ''))


# What each kind of market is, in plain words: shown on the Dashboard, Top Picks and Learn.
# (Typical yearly swings are rough guides from recent decades, not promises.)
ASSET_TYPES = {
    'US Stocks': {
        'label': 'US shares',
        'what': 'A share is a small piece of a company, such as Apple or Microsoft. If the company grows its profits, '
                'the share price tends to rise over time, and many pay you a part of their profit (a dividend).',
        'swing': 'A single large US share often moves 20-40% up or down in a year. The S&P 500 (the 500 biggest US '
                 'companies together) typically moves about 15-20%.',
        'where': 'On **Sharesies**, bought in US dollars (Sharesies converts your NZ dollars for a small fee).',
        'verdict': 'A sensible place to start, in small amounts, after index funds.',
    },
    'NZ Stocks': {
        'label': 'NZ shares',
        'what': 'Shares in New Zealand companies listed on the NZX, such as Fisher & Paykel Healthcare, Mainfreight or '
                'Meridian Energy. Many pay regular dividends.',
        'swing': 'Large NZ shares often move 15-35% in a year; small ones more. Some trade so little that buying and '
                 'selling at a fair price can be hard.',
        'where': 'On **Sharesies**, in NZ dollars.',
        'verdict': 'A sensible place to start, in small amounts, after index funds. You know many of the companies.',
    },
    'Crypto': {
        'label': 'Crypto',
        'what': 'Digital coins such as Bitcoin and Ethereum. There is no company, profit or dividend behind them: the '
                'price is simply what other buyers will pay. Prices here are in US dollars (USDT is a coin that '
                'tracks the US dollar).',
        'swing': 'Bitcoin often moves 50-80% in a year; smaller coins far more. Falls of 70-90% have happened several '
                 'times, and some coins have gone to almost nothing.',
        'where': 'Not on Sharesies. Only use an exchange registered in NZ: look it up on the **Financial Service '
                 'Providers Register** (fsp-register.companiesoffice.govt.nz) before sending money. Never let anyone '
                 'contacting you out of the blue "help" you buy crypto - that is how most scams start.',
        'verdict': 'Only a very small amount you could afford to lose completely.',
    },
    'Forex': {
        'label': 'Forex (currencies)',
        'what': 'Exchange rates between two currencies. **NZDUSD 0.60** means one NZ dollar buys 0.60 US dollars. If '
                'it rises, the first currency (here the NZ dollar) is getting stronger. You don\'t "own" forex the '
                'way you own a share; traders bet on the rate moving.',
        'swing': 'Major currency pairs usually move only 5-10% in a year. To make that worthwhile, forex traders borrow '
                 'to trade much bigger amounts (leverage), which makes losses large and fast.',
        'where': 'Not on Sharesies. Forex brokers must publish how many of their clients lose money - it is often 70% '
                 'or more.',
        'verdict': 'Not recommended for beginners. Use it here to understand currency moves - e.g. a stronger NZ '
                   'dollar makes US shares cheaper to buy.',
    },
}


def asset_explainer(mk):
    """A short fold-out on the Dashboard: what this market is, how risky, where you could buy it."""
    a = ASSET_TYPES.get(mk)
    if not a:
        return
    with st.expander(f"What are {a['label'].lower()}? How risky? Where can I buy them?", icon=':material/help:'):
        st.markdown(f"**What it is:** {a['what']}  \n**How much it moves:** {a['swing']}  \n"
                    f"**Where to buy in NZ:** {a['where']}  \n**For a beginner:** {a['verdict']}")


def asset_types_table():
    """Shares, crypto and forex side by side (Top Picks tab and the Learn page)."""
    rows = ''.join(f"| **{a['label']}** | {a['what']} | {a['swing']} | {a['where']} | {a['verdict']} |\n"
                   for mk, a in ASSET_TYPES.items() if mk in S.RUN_MARKETS)
    st.markdown('| | What it is | How much it moves | Where to buy in NZ | For a beginner |\n'
                '|---|---|---|---|---|\n' + rows)
    st.caption('Typical yearly moves are rough guides from recent years, not promises. Whatever you buy, the rule is '
               'the same: decide your safety level first, and keep each idea small.')


LEARN = {
    'Start here: three rules': """
*Written for New Zealand investors using **Sharesies**. General information, not financial advice.*

1. **Only invest money you can afford to lose.** Prices can fall a long way and stay down for years. Keep an
   emergency fund (3-6 months of expenses) in the bank first, and make sure you're getting your full KiwiSaver
   employer and government contributions; that's free money before any of this.
2. **Put most of your money in low-cost, diversified funds.** On Sharesies you can buy funds that own the whole
   NZX 50 or the US S&P 500 (for example the Smartshares and Kernel index funds, or US ETFs such as VOO). They
   spread your money over dozens or hundreds of companies, so no single bad pick can sink you. Over the long run,
   most professional stock-pickers don't beat these funds.
3. **Use this app for a small "ideas" slice**, say 5-10% of what you invest, and **practise first** in the
   Practice portfolio (My Portfolio page) before using real money.
""",
    'From an idea in the app to an order in Sharesies': """
1. **Find the idea:** the idea cards on **Top Picks** (or on Home). Sharesies offers **NZX, US and ASX shares and
   funds**. It does **not** offer crypto or forex.
2. **Check it:** read the card's **business** line (is the company profitable? is it expensive?) and its **news**
   (open Symbol Details to read the headlines). If anything worries you, skip it - there will be other ideas.
3. **Plan the exit before you buy:** the card shows the **safety level** (where you'd sell if it goes wrong) and the
   first place to take some profit. *Plan your exit* on Top Picks shows all the levels.
4. **Size it:** the card's **How much?** line does this for you (from your total on the Home page), so a fall to the
   safety level only costs about 1% of your money. The calculator below lets you try other numbers.
5. **Practise:** click **Try it in Practice** and follow it for a few weeks first.
6. **Buy in Sharesies:** search the code shown in the app (e.g. **FPH** for Fisher & Paykel Healthcare on the
   NZX, **AAPL** for Apple in the US). Sharesies lets you invest a **dollar amount**, so small amounts work. US shares
   are bought in US dollars, so Sharesies converts your NZD first (there's a currency-exchange fee).
7. **Record it here:** on My Portfolio click **Add holding** with the price per share and the number of shares
   Sharesies shows in your order confirmation. For US shares, enter the **US-dollar** price.
8. **Let the app watch it:** each holding shows **All fine**, **Keep an eye on it** or **Think about selling**, and
   **Alerts** pop up when that changes. If you decide to sell, you do that yourself in Sharesies; this app never
   trades.
""",
    'Shares, crypto and forex: what\'s the difference?': None,         # drawn by asset_types_table()
    'What the signals mean (and what they don\'t)': """
- **Strong Buy / Buy / Neutral / Sell / Strong Sell** (the *chart signal*) is TradingView's reading of **26 chart
  tools**. It describes the **price trend right now**. It is not a forecast and knows **nothing about the business,
  its debt, or the news.**
- **The buy score (0-100)** ranks Strong Buys by how strong and steady the trend looks (is it rising steadily, beating the
  market, calm, not already shot up?). A high score means **a strong trend today** - not "safe", and not the chance
  of a gain.
- **QUALIFIED** only means it passes the app's safety checks today. Signals change, often within days.
- **The safety level** is the price where you'd sell if the idea goes wrong. Every idea card shows it. Decide it
  *before* you buy, and stick to it: that one habit stops small losses becoming big ones.
- **The Business column** (shares only) is your sense check: a very high P/E, shrinking earnings or "losing money"
  means the price depends on hope. That's fine for a small bet, not for your savings.
- **EARLY** (the second table on Top Picks) tries to catch a trend **as it turns up**, before it is a Strong Buy.
  Earlier means more false starts, so it is tracked separately.
- **Check the track record before trusting either score.** The **Track record** on Top Picks logs every QUALIFIED
  and EARLY pick and shows how they went against the market. It is only weeks old, so it is still mostly noise:
  look at the *after 4 weeks* and *after 12 weeks* figures once there are a few dozen picks.
""",
    'NZ shares, US shares and funds on Sharesies': """
| | NZX shares | US shares | Index funds / ETFs |
|---|---|---|---|
| **Trading hours (NZ time)** | 10am-4:45pm weekdays | Overnight: about 3:30am-10am in the NZ summer, 1:30am-8am in winter (shifts by an hour around the daylight-saving changes) | Same as the market they're listed on |
| **Currency** | NZD | USD: Sharesies converts your NZD (a currency-exchange fee applies each way) | NZD for NZX-listed funds |
| **Choice** | About 130 companies, many small and thinly traded | Thousands of companies, very liquid | Whole markets in one buy |
| **Dividends** | Many NZ companies pay regular dividends | Fewer; US tax is withheld from them | Paid out or reinvested, depending on the fund |
| **For a beginner** | Good for knowing the companies; check the *low liquidity* flag | Fine in small amounts; watch the currency fees | **The best place to start** for most of your money |

**Orders placed outside trading hours** wait for the market to open, and the opening price can be quite different
from the last price you saw in the app. A **limit order** (buy only up to a price you choose) protects you from that.
Sharesies' order types change from time to time, so check what's available when you place the order.

**Crypto and forex aren't available on Sharesies.** See *Shares, crypto and forex: what's the difference?* above for
what they are, how much they move and where they're traded.
""",
    'Costs and tax in New Zealand': """
- **Sharesies fees:** there's a fee on each buy and sell order (or a monthly plan that covers a set amount of
  trading), plus a currency-exchange fee when your NZD is converted for US or Australian shares. Fees change,
  so check **sharesies.nz/pricing**. On small amounts, fees can eat a big part of a gain, so avoid trading often.
- **NZ shares:** dividends usually come with tax already deducted. Gains on shares you buy to hold long term are
  generally not taxed in NZ, but **frequent trading for profit can make your gains taxable**.
- **US shares:** US tax is withheld from dividends (lower once you've completed the US tax form Sharesies asks
  for, the W-8BEN).
- **Overseas shares over NZ$50,000 (FIF rules):** if the total **cost** of your overseas shares goes over
  **NZ$50,000**, different tax rules apply, usually tax on 5% of their value each year. Many ASX-listed Australian
  companies are exempt. Below the threshold, generally only dividends are taxed.
- **Funds:** many NZ funds on Sharesies are **PIEs**, taxed at your Prescribed Investor Rate (PIR: 10.5%, 17.5% or
  28%). Make sure your PIR is set correctly in Sharesies.
- Tax rules change and depend on your situation: check **ird.govt.nz** or ask an adviser. This is general
  information, not tax advice.
""",
    'Glossary': """
| Term | Meaning |
|---|---|
| **Share / stock** | A small piece of a company |
| **Code / ticker / symbol** | The short name a share or coin trades under, e.g. AAPL for Apple |
| **Chart signal** | TradingView's verdict on the price trend right now: Strong Buy, Buy, Neutral, Sell, Strong Sell |
| **Buy score** | The app's 0-100 rating of how strong and steady a Strong Buy's trend looks today (not a chance of gain) |
| **QUALIFIED** | Passes every one of the app's safety checks today: a buy idea |
| **Safety level** | The price where you'd sell if things go wrong, decided before you buy (also called a stop-loss) |
| **Typical daily move (ATR)** | How much the price usually moves in a day, averaged over 14 days |
| **Take profit** | Selling some or all of a holding after it has risen, to lock in the gain |
| **Benchmark** | What simply owning the whole market did, e.g. the S&P 500 or the NZX 50 |
| **Bullish / bearish** | Prices rising / prices falling |
| **Volatile** | Moves up and down a lot |
| **SMA200** | The average price over the last 200 days. Above it is generally an uptrend |
| **Pivot / resistance** | A price level where rallies have tended to pause |
| **P/E** | Share price ÷ a year's earnings per share. Lower = cheaper; 15-25 is typical |
| **Dividend yield** | Yearly dividends as a % of the share price |
| **Index fund / ETF** | A fund that owns every company in an index (e.g. the NZX 50), for a low fee |
| **Diversification** | Spreading money over many investments so one failure doesn't hurt much |
| **Leverage** | Borrowing to trade bigger than your money. Losses can exceed what you put in |
| **Realised / unrealised** | Profit from things you've sold / on paper, for things you still hold |
| **Limit order** | An order that only buys (or sells) at the price you set or better |
| **PIE / PIR** | Portfolio Investment Entity (a NZ fund type) / your Prescribed Investor Rate, the tax rate it uses |
| **FIF** | Foreign Investment Fund rules: NZ tax rules for overseas shares above NZ$50,000 cost |
""",
}


def page_learn():
    page_head('Learn', 'New to investing? Start here. Written for New Zealand investors using <b>Sharesies</b>: what '
                       'the app can and can\'t tell you, how to go from an idea to an order, costs and NZ tax. '
                       'General information only, not financial advice.')
    for i, (title, body) in enumerate(LEARN.items()):
        with st.expander(title, expanded=(i == 0)):
            if body is None:
                asset_types_table()
            else:
                st.markdown(body)
        if title.startswith('From an idea'):
            position_calculator()


CALCULATOR_HELP = """
**What it does.** It answers the question every new investor should ask *before* buying: **"How much should I put
in?"** Instead of guessing ("I'll put in $2,000"), you decide in advance how much you're prepared to lose if the
idea goes wrong, and the calculator works out the amount to invest so that a bad outcome is **small and planned**.
One wrong pick then can't do serious damage, so you can afford to be wrong several times while you learn.

**How it works.** It uses two simple rules and recommends the **smaller** of the two amounts:

1. **The risk rule.** Every idea has a point where you'd admit it isn't working: the **safety level** shown on each
   idea card and under *Plan your exit* on Top Picks. If you buy at $48.40 and would get out at $46.20, you'd lose $2.20 per share. If you're
   only prepared to lose 1% of your money, the calculator works out how many shares keep that loss to 1%.
2. **The "not too much in one basket" rule.** Even with a close safety level, putting a big slice of your money
   into one company is risky. Prices can *jump* past your safety level overnight on bad news. So no single idea
   gets more than a set share of your money (10% is a sensible start).

**How to use it, step by step.**

1. **Total invested:** everything you have invested (your Sharesies balance plus anything elsewhere, but not your
   emergency fund).
2. **Willing to lose on this idea:** 1% is a common starting point; 2% is about the upper limit most people use.
3. **Most in any one idea:** leave it at 10% unless you have a good reason.
4. **Buy price:** today's price (shown on Top Picks or in Sharesies).
5. **Safety level:** copy it from the idea card, or from **Plan your exit** on Top Picks (click *Show the plan*).
6. Read the answer: **the dollar amount to invest** (Sharesies lets you buy by dollar amount) and how much you'd lose
   if it hits the safety level.

**Worked example.** You have **$10,000** invested. Fisher & Paykel Healthcare (FPH) is $48.40, with a protective
level of $46.20.
- Risk rule (1% = $100 at most): $100 ÷ $2.20 a share = about 45 shares, roughly **$2,200**.
- Basket rule (10% = $1,000 at most): about **$1,000**.
- **The calculator says invest about $1,000** (the smaller). If FPH falls to $46.20 you'd lose about $45, under half
  a percent of your money. That is a mistake you can easily recover from.

**Important.** The app **doesn't sell for you**. If the price reaches the safety level, you sell in Sharesies
yourself (the app's alerts and *Think about selling* will tell you). Fees and currency conversion (for US shares) add a
little to the cost. And a price can open *below* the safety level after bad news, so the loss can be bigger
than planned. That's why the basket rule matters.
"""


def position_calculator():
    """How much to buy so a bad outcome is small and planned: the risk rule and the one-basket cap, smaller wins."""
    with st.expander('Position-size calculator: how much should I put into one idea?', expanded=False):
        st.markdown(CALCULATOR_HELP)
        st.divider()
        st.markdown('##### Try it with your numbers')
        c1, c2 = st.columns(2)
        total = c1.number_input('Total invested ($)', min_value=0.0, value=10000.0, step=500.0, key='calc_total',
                                help='Everything you have invested - your Sharesies balance plus anything else. '
                                     'Not your emergency fund.')
        risk = c2.slider('Willing to lose on this idea (% of total)', 0.5, 3.0, 1.0, 0.5, key='calc_risk',
                         help='If the idea fails and the price falls to the safety level, you lose this much of '
                              'your total. 1% is a common starting point.')
        price = c1.number_input('Buy price ($ per share)', min_value=0.0, value=48.40, format='%g', key='calc_price',
                                help="Today's price, from Top Picks or Sharesies.")
        stop = c2.number_input('Safety level ($ per share)', min_value=0.0, value=46.20, format='%g',
                               key='calc_stop', help='From the idea card on Top Picks: the price where you\'d admit '
                                                     'the idea isn\'t working and sell.')
        cap = c1.slider('Most in any one idea (% of total)', 2, 25, 10, 1, key='calc_cap',
                        help='However close the safety level, never put more than this into one company. '
                             '10% is a sensible start.')
        size = core.position_size(total, risk, price, stop, cap_pct=cap)
        if size is None:
            st.warning('The safety level must be **below** the buy price (it\'s where you\'d sell if the price '
                       'falls).')
            return
        st.success(f"**Invest about ${size['cost']:,.0f}** (about {size['units']:,.4g} shares, "
                   f"{size['share_pct']:.0f}% of your total).  \nIf the price falls to the safety level "
                   f"(${stop:,.2f}) you'd lose about **${size['loss']:,.0f}**, which is {size['loss_pct']:.1f}% of "
                   'your total.', icon=':material/calculate:')
        if size['limited_by'] == 'cap':
            st.caption(f"The risk rule alone would allow about ${size['risk_cost']:,.0f}, but that's more than "
                       f"{cap}% of your money in one idea, so the basket rule keeps it to "
                       f"${size['cap_cost']:,.0f}.")
        else:
            st.caption(f"Limited by the risk rule: a bigger amount would mean losing more than {risk:g}% of your "
                       'total if the price falls to the safety level.')
        st.caption('Remember: the app never sells for you. If the price reaches the safety level, sell in '
                   'Sharesies yourself. The alerts and *Think about selling* on My Portfolio will tell you when.')


PAGE_OBJS = {}     # menu label -> st.Page, filled in by main() so pages can link to each other


def go_to(label, text, icon=None):
    """A link to another page (plain text when there's no menu, e.g. in the tests)."""
    if label in PAGE_OBJS:
        st.page_link(PAGE_OBJS[label], label=text, icon=icon)
    else:
        st.markdown(f'**{text}** ({label} in the menu)')


HOME_STEPS = [
    ('Learn', ':material/school:', 'Learn the basics first',
     'Emergency fund and KiwiSaver come first, and low-cost index funds should hold most of your money. This app is '
     'for a small "ideas" slice.'),
    ('Top Picks', ':material/trophy:', 'Look at today\'s idea',
     'Only ideas that pass every safety check are shown - some days there are none, and that\'s fine.'),
    ('Symbol Details', ':material/search:', 'Check the business and the news',
     'Is the company profitable? Are recent headlines worrying? If anything bothers you, skip it.'),
    ('Learn', ':material/calculate:', 'Decide how much',
     'The idea card works it out from your total (below), so a bad outcome costs only about 1% of your money.'),
    ('My Portfolio', ':material/science:', 'Practise first, then buy in Sharesies',
     'Try it with pretend money in the Practice portfolio for a few weeks. Learn shows how to place the order.'),
    ('My Portfolio', ':material/account_balance_wallet:', 'Record it and let the app watch it',
     'Each holding shows All fine, Keep an eye on it or Think about selling, with an alert when it changes.'),
    ('Top Picks', ':material/fact_check:', 'Check the app\'s own record',
     'The Track record tab shows whether past ideas actually beat simply owning the market.'),
]


def page_home():
    page_head('Home', 'Start here. Your portfolio, anything that needs your attention, and today\'s strongest idea - '
                      'then a step-by-step path from "I\'m new" to "I own it and know what to watch".')
    beginner_switch()
    home_view()
    st.divider()
    st.markdown('#### Your path, step by step')
    for n, (page, icon, title, text) in enumerate(HOME_STEPS, 1):
        c1, c2 = st.columns([2.2, 5], vertical_alignment='center')
        with c1:
            go_to(page, f'{n}. {title}', icon)
        c2.caption(text)
    st.caption('Chart signals and company figures from TradingView - general information, not financial advice. '
               'The app never buys or sells; you do that in Sharesies.')


def beginner_switch():
    store = get_app()['store']
    c1, c2 = st.columns([1.6, 5], vertical_alignment='center')
    on = c1.toggle('Beginner mode', value=store.beginner, key='beginner_mode',
                   help='On: simpler screens, the 1 Day chart only (what the scores are designed for), every market '
                        'refreshing by itself, and Market Scan limited to larger companies. Off: all the controls.')
    c2.caption('**On** (recommended while you learn): fewer settings to worry about. **Off**: the timeframe and '
               'refresh controls on the Dashboard, and every company size in Market Scan.')
    if on != store.beginner:
        store.set_beginner(on)
        core.save_prefs(store)


@st.fragment(run_every=REFRESH_SECONDS)
def home_view():
    app = get_app()
    pf, store = app['portfolio'], app['store']
    rate_limit_notice()
    tbl = core.portfolio_table(pf, store)

    st.markdown('#### Your portfolio')
    if tbl.empty and not pf.realised:
        st.info('You haven\'t recorded anything yet. Add what you own on **My Portfolio**, or try ideas with '
                'pretend money in its **Practice** portfolio first.', icon=':material/account_balance_wallet:')
    else:
        nzd_overview(pf, tbl, store)

    left, right = st.columns(2, gap='large')
    with left:
        st.markdown('#### Needs your attention')
        home_attention(tbl, store)
        st.markdown('#### Your total invested')
        total = st.number_input('Everything you have invested (NZ$)', min_value=0.0, value=float(store.total_invested),
                                step=500.0, key='home_total',
                                help='Your Sharesies balance plus anything else you have invested - not your emergency '
                                     'fund. The idea cards use it to work out how much to put into one idea. It stays '
                                     'on this computer.')
        if total > 0 and total != store.total_invested:
            store.total_invested = total
            core.save_prefs(store)
    with right:
        st.markdown("#### Today's strongest idea")
        home_idea(store)


def home_attention(tbl, store):
    """Holdings on 'Think about selling' (worst first), holdings not found, and today's alerts."""
    items = []
    if not tbl.empty:
        worst_first = list(reversed(core.RECOMMENDATIONS))
        bad = tbl[tbl['Recommendation'].map(plain_group) == 'Think about selling']
        style = core.PLAIN_REC_COLOURS['Think about selling']
        for _, r in bad.sort_values('Recommendation', key=lambda s: s.map(worst_first.index)).iterrows():
            items.append(f'<span class="tvb-badge" style="{style}">Think about selling</span> '
                         f'<b>{r["Symbol"]}</b>: {r["Reason"]}')
        for _, r in tbl[tbl['Recommendation'].isin(['Not found'])].iterrows():
            items.append(f'<b>{r["Symbol"]}</b>: not found on TradingView - check the code on My Portfolio.')
    today = [a for a in store.alerts if (pd.Timestamp.now() - pd.Timestamp(a['time'])).total_seconds() < 86400]
    for a in reversed(today[-3:]):
        items.append(f"{'⚠️' if a['level'] == 'warn' else '📈'} {a['time']:%H:%M} {a['text']}")
    if not items:
        msg = ('Nothing needs your attention: every holding is **All fine** or **Keep an eye on it**.'
               if not tbl.empty else 'Nothing to watch yet.')
        st.success(msg, icon=':material/check_circle:')
        return
    for it in items:
        st.markdown(f'<div class="tvb-reason">{it}</div>', unsafe_allow_html=True)
    st.caption('*Think about selling* means **take a look** on My Portfolio and decide. The app never sells for you.')


def home_idea(store):
    """The top watchlist SHARE idea as an idea card (no extra TradingView requests)."""
    if not store.ready():
        st.info('Loading from TradingView...')
        return
    opp, _, _ = core.opportunities(store)
    # Only what you can buy on Sharesies: shares (US and NZ), not crypto or forex.
    shares = [mk for mk in S.RUN_MARKETS if S.MARKETS[mk]['screener'] in core.STOCK_SCREENERS]
    ok = opp[(opp['Status'] == 'QUALIFIED') & opp['Market'].isin(shares)] if not opp.empty else opp
    if ok.empty:
        st.info('**No share passes every safety check today.** Staying out is a perfectly good decision - the app '
                'will alert you when one does. Top Picks shows every market.', icon=':material/block:')
        return
    st.caption('The strongest chart signal among the shares in your watchlists (crypto and forex aren\'t on '
               'Sharesies, so they\'re left out here).')
    idea_card(store, ok.iloc[0], key='home', summ=core.track_record(store, 'qualified')[1], fetch_news=False)


PAGES = {   # menu label -> (page function, icon, url) - in the order a beginner needs them
    'Home': (page_home, ':material/home:', 'home'),
    'Learn': (page_learn, ':material/school:', 'learn'),
    'Top Picks': (page_top_picks, ':material/trophy:', 'top-picks'),
    'My Portfolio': (page_portfolio, ':material/account_balance_wallet:', 'portfolio'),
    'Dashboard': (page_dashboard, ':material/monitoring:', 'dashboard'),
    'Market Scan': (page_market_scan, ':material/travel_explore:', 'market-scan'),
    'Symbol Details': (page_symbol, ':material/search:', 'symbol'),
}


ADVANCED_PAGES = ['Dashboard', 'Market Scan', 'Symbol Details']    # grouped under "Advanced" in the menu


def error_page(checks):
    rows = ''.join(f"<tr><td>{'❌' if s == 'fail' else '⚠️' if s == 'warn' else '✅'}</td><td><b>{n}</b></td>"
                   f'<td>{d}</td></tr>' for s, n, d in checks)
    st.markdown('<div class="tvb-error"><h2>❌ The app could not start</h2><p>A start-up check found a problem. '
                'Fix the item(s) marked ❌ below, then start the app again. See <b>README.md</b>, section 8, for help.</p>'
                f'<table>{rows}</table></div>', unsafe_allow_html=True)


def setup_page():
    st.set_page_config(page_title='TradingView Bot', page_icon='📈', layout='wide', initial_sidebar_state='collapsed')
    st.markdown(CSS, unsafe_allow_html=True)
    st.logo(os.path.join(HERE, 'assets', 'logo.svg'), size='large')


def footer():
    st.markdown('<div class="tvb-footer">Data from TradingView · Chart signals only, not financial advice · '
                'The app never buys or sells for you</div>', unsafe_allow_html=True)
    if 'Learn' in PAGE_OBJS:
        _, c, _ = st.columns([2, 1, 2])
        with c:
            go_to('Learn', 'New here? Read the Learn page', ':material/school:')


def main():
    setup_page()
    app = get_app()
    if any(s == 'fail' for s, _, _ in app['checks']):
        error_page(app['checks'])
        st.stop()
    pages = [st.Page(fn, title=label, icon=icon, url_path=url, default=(label == 'Home'))
             for label, (fn, icon, url) in PAGES.items()]
    PAGE_OBJS.update({label: p for label, p in zip(PAGES, pages)})
    main_pages = [PAGE_OBJS[k] for k in PAGES if k not in ADVANCED_PAGES]
    st.navigation({'': main_pages, 'Advanced': [PAGE_OBJS[k] for k in ADVANCED_PAGES]}, position='top').run()
    footer()


def render_page(label):
    """Used by the tests: draw one page without the menu."""
    setup_page()
    PAGES[label][0]()
