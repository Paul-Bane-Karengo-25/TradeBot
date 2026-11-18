"""
TradingView Analysis Bot - core logic (no screen code).

Market data from TradingView, the portfolio (holdings, sales, profit/loss, saving), and the
start-up health check. The website (tvbot_ui.py) and the tests (tests/run_tests.py) both use this.
"""
import datetime as dt
import importlib.metadata as md
import json
import os
import platform
import shutil
import sys
import threading
import time
import uuid
from zoneinfo import ZoneInfo

import pandas as pd
import tradingview_ta
from tradingview_ta import Interval
from tradingview_ta.technicals import Compute

import settings as S

LABELS = {'STRONG_BUY': 'Strong Buy', 'BUY': 'Buy', 'NEUTRAL': 'Neutral', 'SELL': 'Sell', 'STRONG_SELL': 'Strong Sell'}
# ONE palette for every coloured cell in the app: green = good, amber/orange = caution, red = act.
# Every coloured cell also shows its word (e.g. "Strong Buy", "WARNING"), so nothing depends on colour alone.
TONE = {
    'good+':   'background-color:#0b7a3b;color:white',   # dark green
    'good':    'background-color:#8fd9a8;color:black',   # lighter green
    'neutral': 'background-color:#e1e4e8;color:black',   # grey
    'caution': 'background-color:#ffe08a;color:black',   # amber
    'warn':    'background-color:#ffb366;color:black',   # orange
    'bad':     'background-color:#f8b4b4;color:black',   # light red
    'bad+':    'background-color:#e00000;color:white',   # bright red
}
COLOURS = {'Strong Buy': TONE['good+'], 'Buy': TONE['good'], 'Neutral': TONE['neutral'],
           'Sell': TONE['bad'], 'Strong Sell': TONE['bad+']}
CRYPTO_QUOTES = ('USDT', 'USDC', 'FDUSD', 'USD', 'BTC', 'ETH', 'EUR')
TIMEFRAMES = {'1h': Interval.INTERVAL_1_HOUR, '4h': Interval.INTERVAL_4_HOURS,
              '1D': Interval.INTERVAL_1_DAY, '1W': Interval.INTERVAL_1_WEEK}

# Choices for the Dashboard's timeframe dropdown. TradingView has no 4-week chart; its monthly chart is the closest.
DASH_TIMEFRAMES = {'1 Hour': Interval.INTERVAL_1_HOUR, '4 Hours': Interval.INTERVAL_4_HOURS,
                   '1 Day': Interval.INTERVAL_1_DAY, '1 Week': Interval.INTERVAL_1_WEEK,
                   '4 Weeks': Interval.INTERVAL_1_MONTH}


def timeframe_label(interval):
    return next((k for k, v in DASH_TIMEFRAMES.items() if v == interval), str(interval))

LOADED_FROM_MTIME = os.path.getmtime(__file__)  # lets the website notice if this file was updated while running
tv_get = tradingview_ta.get_multiple_analysis   # the tests swap this for a fake TradingView
_sleep = time.sleep


# ---------------------------------------------------------------- small helpers
def _utc_now():
    return dt.datetime.now(dt.timezone.utc)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def short(ticker):
    return ticker.split(':')[-1]          # 'NASDAQ:AAPL' -> 'AAPL'


def to_ticker(market, symbol):
    """'BTC' -> 'BINANCE:BTCUSDT', 'AAPL' -> 'NASDAQ:AAPL', 'NYSE:JPM' stays as it is."""
    s = symbol.strip().upper().replace('/', '')
    if ':' in s:
        return s
    if market == 'Crypto' and not any(s.endswith(q) and len(s) > len(q) for q in CRYPTO_QUOTES):
        s += 'USDT'
    return f"{S.MARKETS[market]['exchange']}:{s}"


def candidates(market, symbol):
    """Tickers to try for what the user typed. US stocks: NASDAQ, then NYSE, then AMEX."""
    t = to_ticker(market, symbol)
    if market == 'US Stocks' and ':' not in symbol:
        ex, bare = t.split(':')
        return [t] + [f'{e}:{bare}' for e in ('NYSE', 'AMEX') if e != ex]
    return [t]


def quote_ccy(market, ticker):
    """Currency the price is quoted in (profit/loss is in this currency)."""
    s = short(ticker)
    if market == 'Forex':
        return s[-3:]
    if market == 'Crypto':
        return next((q for q in CRYPTO_QUOTES if s.endswith(q) and len(s) > len(q)), '?')
    return S.MARKETS.get(market, {}).get('currency', 'USD')


def breakdown(analysis):
    """Each of the 26 metrics and what it's signalling."""
    rows = []
    for group, data in [('Oscillator', analysis.oscillators), ('Moving Average', analysis.moving_averages)]:
        for name, signal in data['COMPUTE'].items():
            rows.append({'Type': group, 'Indicator': name, 'Signal': LABELS.get(signal, signal)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- market hours (fewer requests)
# A stock market's data can't change while it's closed, so once the app has fetched it after the close it isn't
# fetched again until the market reopens. Markets without 'hours' (crypto, forex) refresh as normal.
SETTLE_MINUTES = 30      # fetch once more this long after the close (TradingView's data can lag the close a little)


def _hhmm(s):
    h, m = s.split(':')
    return dt.time(int(h), int(m))


def market_session(mk, now_utc=None):
    """None if the market has no set hours; ('open', None); or ('closed', when the last session ended, in UTC).
    Weekends count as closed; public holidays aren't known, so they just refresh as usual."""
    h = S.MARKETS.get(mk, {}).get('hours')
    if not h:
        return None
    tz = ZoneInfo(h['tz'])
    now = (now_utc or _utc_now()).astimezone(tz)
    opens, closes = _hhmm(h['open']), _hhmm(h['close'])
    weekday = now.weekday() < 5
    if weekday and opens <= now.time() < closes:
        return 'open', None
    day = now.date() if weekday and now.time() >= closes else now.date() - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return 'closed', dt.datetime.combine(day, closes, tz).astimezone(dt.timezone.utc)


def session_progress(mk, now_utc=None):
    """How far through today's trading session a market with set hours is (0..1), or None when it isn't trading
    right now (then today's daily bar is complete) or has no set hours."""
    h = S.MARKETS.get(mk, {}).get('hours')
    s = market_session(mk, now_utc)
    if not h or not s or s[0] != 'open':
        return None
    tz = ZoneInfo(h['tz'])
    now = (now_utc or _utc_now()).astimezone(tz)
    opens = dt.datetime.combine(now.date(), _hhmm(h['open']), tz)
    closes = dt.datetime.combine(now.date(), _hhmm(h['close']), tz)
    return (now - opens) / (closes - opens)


def is_settled(mk, fetched, now_utc=None):
    """True if the market is closed and `fetched` (local time) was after its last close had settled - so fetching
    again would return exactly the same data."""
    s = market_session(mk, now_utc)
    if not s or s[0] == 'open':
        return False
    return fetched.astimezone(dt.timezone.utc) >= s[1] + dt.timedelta(minutes=SETTLE_MINUTES)


# ---------------------------------------------------------------- TradingView
class RateLimited(RuntimeError):
    pass


_fetch_lock = threading.Lock()   # one request at a time
_last_call = [0.0]
# When TradingView refuses a request (rate limit), the WHOLE app pauses all requests for a cool-down.
# Repeated refusals make the cool-down longer; the first successful request resets it.
# (Retrying straight away keeps the block going, so during a cool-down nothing is sent at all.)
COOLDOWNS = (60, 120, 300, 600, 900)            # seconds: 1, 2, 5, 10, then 15 minutes
RATE_LIMIT = {'until': 0.0, 'strikes': 0}


def rate_limit_wait():
    """Seconds until the app will try TradingView again, if it is cooling down after a rate limit; else 0."""
    return max(0, int(RATE_LIMIT['until'] - time.time() + 0.999))


# Extra values asked for on top of the library's defaults, for the Composite Opportunity Score.
# NEVER list a name the library already requests (e.g. 'volume', 'Recommend.All', 'SMA50'): tradingview_ta matches
# values to names by position, and a repeated name shifts every value after it into the wrong field.
# 'SMA200[1]' is deliberately last - if it's missing, the extras didn't line up and the score is not trusted.
EXTRA_FIELDS = ['ATR', 'MACD.hist', 'MACD.hist[1]', 'ROC', 'Perf.3M', 'average_volume_10d_calc',
                'average_volume_30d_calc', 'SMA20[1]', 'SMA50[1]', 'close[1]',
                # also used by Exit targets and the Business column, so on the 1 Day chart those need no extra
                # request (on other timeframes TradingView returns these empty, harmlessly)
                'price_52_week_high', 'price_target_average', 'price_target_high', 'price_earnings_ttm',
                'earnings_per_share_diluted_yoy_growth_ttm', 'dividends_yield_current', 'net_margin',
                'Perf.1M',                       # short-term relative strength for the Early Entry Score
                'description',                   # the company / coin name, shown next to the code
                'SMA200[1]']


class _Refused(RuntimeError):
    """TradingView answered 'too many requests'."""


def _http_scan(screener, body):
    """One query to TradingView's screener (finds symbols matching filters). Returns the parsed reply."""
    import requests                       # installed with tradingview-ta
    r = requests.post(f'https://scanner.tradingview.com/{screener}/scan', json=body, timeout=30,
                      headers={'User-Agent': f'tradingview_ta/{tradingview_ta.__version__}'})
    if r.status_code == 429:
        raise _Refused()
    r.raise_for_status()
    return r.json()


tv_scan = _http_scan                      # the tests swap this for a fake screener


def fetch(screener, interval, tickers):
    """Ask TradingView for several symbols at once (one request), pausing between requests.
    During a rate-limit cool-down nothing is sent and RateLimited is raised straight away."""
    return _guarded(lambda: tv_get(screener=screener, interval=interval, symbols=list(tickers),
                                   additional_indicators=list(EXTRA_FIELDS)))


def scan(screener, body):
    """A screener query, with the same pacing and rate-limit protection as fetch()."""
    return _guarded(lambda: tv_scan(screener, body))


def _guarded(call):
    """Run one TradingView request: one at a time, paced, and nothing at all during a rate-limit cool-down."""
    with _fetch_lock:
        wait = rate_limit_wait()
        if wait:
            raise RateLimited(f'TradingView is rate-limiting this connection - the app will try again in {wait} seconds.')
        pause = S.PAUSE_BETWEEN_REQUESTS - (time.time() - _last_call[0])
        if pause > 0:
            _sleep(pause)
        try:
            result = call()
        except (json.JSONDecodeError, _Refused):   # TradingView sends an empty reply (or a 429) when it rate-limits
            cool = COOLDOWNS[min(RATE_LIMIT['strikes'], len(COOLDOWNS) - 1)]
            RATE_LIMIT['strikes'] += 1
            RATE_LIMIT['until'] = time.time() + cool
            raise RateLimited(f'TradingView is rate-limiting this connection (too many requests) - the app will '
                              f'try again in {cool} seconds.') from None
        finally:
            _last_call[0] = time.time()
        RATE_LIMIT['strikes'], RATE_LIMIT['until'] = 0, 0.0
        return result


def analyse(market, interval=None, extra=()):
    """Ratings for a market's watchlist (+ extra tickers such as your holdings, and the market's benchmark and
    regime symbols, which ride along in the same request). Returns (table, raw, missing)."""
    cfg = S.MARKETS[market]
    tickers = list(dict.fromkeys([to_ticker(market, s) for s in cfg['watchlist']] + reference_tickers(market)
                                 + list(extra)))
    results = fetch(cfg['screener'], interval or S.INTERVAL, tickers)
    rows, raw, missing = [], {}, []
    for ticker, a in results.items():
        if a is None:
            missing.append(ticker)
            continue
        s, o, m = a.summary, a.oscillators, a.moving_averages
        total = s['BUY'] + s['NEUTRAL'] + s['SELL']
        rows.append({
            'Market': market, 'Symbol': ticker, 'Price': a.indicators.get('close'),
            'Rating': LABELS[s['RECOMMENDATION']], 'Buy': s['BUY'], 'Neutral': s['NEUTRAL'], 'Sell': s['SELL'],
            'Metrics': total, 'Score': round((s['BUY'] - s['SELL']) / total, 2) if total else 0.0,
            'Oscillators': LABELS[o['RECOMMENDATION']], 'Osc B/N/S': f"{o['BUY']}/{o['NEUTRAL']}/{o['SELL']}",
            'Moving Avgs': LABELS[m['RECOMMENDATION']], 'MA B/N/S': f"{m['BUY']}/{m['NEUTRAL']}/{m['SELL']}",
        })
        raw[ticker] = a
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
    return df, raw, missing


# ---------------------------------------------------------------- holding risk (ATR trailing level)
# Decision support only: the app never trades. It always uses the DAILY chart's ATR(14), whatever timeframe the
# Dashboard is set to, so switching timeframe can't move the level (and a short-timeframe ATR can't ratchet it up).
RISK_INTERVAL = Interval.INTERVAL_1_DAY
ATR_MULT = 2
ATR_STATUSES = ['NORMAL', 'WATCH', 'WARNING', 'BREACHED']
ATR_COLOURS = {'NORMAL': TONE['good'], 'WATCH': TONE['caution'], 'WARNING': TONE['warn'], 'BREACHED': TONE['bad+']}
RECOMMENDATIONS = ['HOLD', 'HOLD / WATCH', 'REVIEW EXIT', 'EXIT WARNING', 'STRONG EXIT WARNING']
REC_COLOURS = {'HOLD': TONE['good+'], 'HOLD / WATCH': TONE['good'], 'REVIEW EXIT': TONE['warn'],
               'EXIT WARNING': TONE['bad'], 'STRONG EXIT WARNING': TONE['bad+']}
# What the screens show a beginner: the five recommendations grouped into three plain instructions (the reason
# line under each holding says how strong the warning is), and the safety-level check in everyday words.
PLAIN_REC = {'HOLD': 'All fine', 'HOLD / WATCH': 'Keep an eye on it', 'REVIEW EXIT': 'Think about selling',
             'EXIT WARNING': 'Think about selling', 'STRONG EXIT WARNING': 'Think about selling'}
PLAIN_REC_ORDER = ['Think about selling', 'Keep an eye on it', 'All fine']          # most urgent first
PLAIN_REC_COLOURS = {'All fine': TONE['good+'], 'Keep an eye on it': TONE['caution'],
                     'Think about selling': TONE['bad']}
PLAIN_ATR = {'NORMAL': 'Comfortable', 'WATCH': 'Getting close', 'WARNING': 'Very close', 'BREACHED': 'Fallen below'}
PLAIN_ATR_COLOURS = {PLAIN_ATR[k]: v for k, v in ATR_COLOURS.items()}
PLAIN_REGIME = {'Strong bull': 'rising strongly', 'Bullish': 'rising', 'Mixed': 'mixed (no clear direction)',
                'Bearish': 'falling', 'n/a': 'unknown'}
CURRENCY_NAMES = {'USD': 'US dollar', 'EUR': 'euro', 'JPY': 'Japanese yen', 'GBP': 'British pound',
                  'CHF': 'Swiss franc', 'AUD': 'Australian dollar', 'NZD': 'NZ dollar', 'CAD': 'Canadian dollar'}


def pair_meaning(ticker, rating=None):
    """A forex pair in plain words, e.g. 'US dollar vs Swiss franc: the US dollar is getting stronger'."""
    s = short(ticker)
    b, q = CURRENCY_NAMES.get(s[:3], s[:3]), CURRENCY_NAMES.get(s[3:6], s[3:6])
    if rating in ('Buy', 'Strong Buy'):
        trend = f': the {b} is getting stronger against the {q}'
    elif rating in ('Sell', 'Strong Sell'):
        trend = f': the {b} is getting weaker against the {q}'
    elif rating:
        trend = ': no clear direction'
    else:
        trend = ''
    return f'{b} vs {q}{trend}'
# Technical rating x ATR status (NORMAL, WATCH, WARNING, BREACHED) -> holding recommendation
RISK_MATRIX = {
    'Strong Buy':  ['HOLD', 'HOLD', 'HOLD / WATCH', 'REVIEW EXIT'],
    'Buy':         ['HOLD', 'HOLD', 'HOLD / WATCH', 'REVIEW EXIT'],
    'Neutral':     ['HOLD', 'HOLD / WATCH', 'REVIEW EXIT', 'EXIT WARNING'],
    'Sell':        ['HOLD / WATCH', 'REVIEW EXIT', 'EXIT WARNING', 'STRONG EXIT WARNING'],
    'Strong Sell': ['REVIEW EXIT', 'EXIT WARNING', 'STRONG EXIT WARNING', 'STRONG EXIT WARNING'],
}


def atr_status(price, stop, atr):
    """NORMAL: more than 1 ATR above the level. WATCH: within 1 ATR. WARNING: within 0.5 ATR. BREACHED: at/below it."""
    if price <= stop:
        return 'BREACHED'
    if price <= stop + 0.5 * atr:
        return 'WARNING'
    if price <= stop + atr:
        return 'WATCH'
    return 'NORMAL'


def recommend(rating, status):
    return RISK_MATRIX[rating][ATR_STATUSES.index(status)]


def trail(h, atr, prev_close, today_utc):
    """New (high_close, atr_stop, initial_stop) for a holding. The level only ever moves UP:
    stop = max(previous stop, highest close since entry - 2 x ATR). 'Close' is the last COMPLETED daily close, and
    only counts once a new day has started after the holding was added (so it can't be a close from before you bought)."""
    high = h.get('high_close') or h['buy_price']
    if prev_close is not None and today_utc > h.get('added', '')[:10] and prev_close > high:
        high = prev_close
    initial = h.get('initial_stop')
    if initial is None:
        initial = h['buy_price'] - ATR_MULT * atr
    stop = max(x for x in (h.get('atr_stop'), initial, high - ATR_MULT * atr) if x is not None)
    return high, stop, initial


# ---------------------------------------------------------------- portfolio
def _valid_holding(h):
    return (isinstance(h, dict) and isinstance(h.get('ticker'), str) and isinstance(h.get('market'), str)
            and is_num(h.get('qty')) and h['qty'] > 0 and is_num(h.get('buy_price')) and h['buy_price'] > 0)


def _valid_sale(t):
    return (isinstance(t, dict) and isinstance(t.get('ticker'), str) and isinstance(t.get('ccy'), str)
            and all(is_num(t.get(k)) for k in ('qty', 'buy_price', 'sell_price', 'pl')))


class Portfolio:
    """Holdings, sales and P/L, saved to a JSON file (with a .bak copy and safe write-then-swap saving)."""

    def __init__(self, path=None):
        self.path = path or S.PORTFOLIO_FILE
        self.lock = threading.RLock()
        self.retired = False
        self.warnings = []
        self.holdings, self.realised, self.meta = self._load()

    def _backup(self, tag):
        name = f"{self.path}.{tag}-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(self.path, name)
        return name

    def _load(self):
        try:
            with open(self.path, encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            return [], [], {}
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            backup = self._backup('broken')
            self.warnings.append(f'{self.path} could not be read ({type(e).__name__}). It was copied to {backup} '
                                 'and the app started with an empty portfolio.')
            return [], [], {}
        if isinstance(data, list):                   # older format: just a list of holdings
            data = {'holdings': data}
        if not isinstance(data, dict):
            data = {}
        holdings = data.get('holdings') if isinstance(data.get('holdings'), list) else []
        realised = data.get('realised') if isinstance(data.get('realised'), list) else []
        meta = data.get('meta') if isinstance(data.get('meta'), dict) else {}
        good_h = [h for h in holdings if _valid_holding(h)]
        good_r = [t for t in realised if _valid_sale(t)]
        dropped = (len(holdings) - len(good_h)) + (len(realised) - len(good_r))
        if dropped:
            backup = self._backup('original')
            self.warnings.append(f'{dropped} damaged entr{"y was" if dropped == 1 else "ies were"} skipped in '
                                 f'{self.path}. The original file was kept as {backup}.')
        for h in good_h:
            h.setdefault('id', uuid.uuid4().hex[:8])
            # Risk tracking (added by the app). Holdings from before it existed start tracking from today.
            if not isinstance(h.get('added'), str):
                h['added'] = _utc_now().strftime('%Y-%m-%d %H:%M')
            for k in ('high_close', 'atr_stop', 'initial_stop'):
                if k in h and not is_num(h[k]):
                    del h[k]
            if h.get('pending') and not (isinstance(h.get('candidates'), list)
                                         and all(isinstance(c, str) for c in h['candidates']) and h['candidates']):
                h['candidates'] = [h['ticker']]
            if h['market'] not in S.MARKETS:
                self.warnings.append(f"Holding {h['ticker']} is in market '{h['market']}', which isn't in settings.py.")
        return good_h, good_r, meta

    def save(self):
        # A retired copy (replaced when the app reloaded its program files) must never write: a background refresh
        # finishing late would otherwise overwrite holdings added through the new copy.
        if self.retired:
            return
        with self.lock:
            if os.path.exists(self.path):
                shutil.copy2(self.path, self.path + '.bak')
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump({'holdings': self.holdings, 'realised': self.realised, 'meta': self.meta}, f, indent=2)
            # On Windows the swap is refused while anything else (antivirus, OneDrive, a backup tool) briefly has
            # the file open - so try again for up to ~2 seconds before giving up.
            for attempt in range(20):
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(0.1)

    def tickers(self, market):
        """Tickers to fetch for this market's holdings - for an unchecked holding, every exchange it might be on."""
        out = []
        for h in list(self.holdings):
            if h['market'] == market:
                out += h['candidates'] if h.get('pending') else [h['ticker']]
        return out

    def resolve_pending(self, market, raw, requested):
        """Confirm holdings that were saved while TradingView couldn't be reached, using a normal market refresh.
        Found -> the right exchange is filled in. Every exchange asked and none found -> flagged 'not_found'."""
        changed = False
        with self.lock:
            for h in self.holdings:
                if h['market'] != market or not h.get('pending'):
                    continue
                t = next((c for c in h['candidates'] if raw.get(c) is not None), None)
                if t is not None:
                    h['ticker'] = t
                    for k in ('pending', 'candidates', 'not_found'):
                        h.pop(k, None)
                    changed = True
                elif all(c in requested for c in h['candidates']) and not h.get('not_found'):
                    h['not_found'] = True
                    changed = True
            if changed:
                self.save()
        return changed

    def get(self, hid):
        return next((h for h in self.holdings if h['id'] == hid), None)

    def add(self, market, symbol, price, qty, store=None):
        """Check the symbol with TradingView, then save it. Returns (ok, message).
        If TradingView can't be reached (busy/rate-limited, offline), the holding is still saved, marked as waiting
        to be checked, and confirmed by the next normal refresh - so nothing you typed is lost."""
        symbol = (symbol or '').strip()
        if not symbol or not is_num(price) or price <= 0 or not is_num(qty) or qty <= 0:
            return False, 'Enter a symbol, a buy price and a quantity (all above 0).'
        cands = candidates(market, symbol)
        interval = store.interval if store is not None else S.INTERVAL   # same timeframe as the rest of the app
        try:
            res = fetch(S.MARKETS[market]['screener'], interval, cands)
        except Exception as e:
            with self.lock:
                self.holdings.append({'id': uuid.uuid4().hex[:8], 'market': market, 'ticker': cands[0],
                                      'buy_price': float(price), 'qty': float(qty),
                                      'added': _utc_now().strftime('%Y-%m-%d %H:%M'),
                                      'pending': True, 'candidates': cands})
                self.save()
            why = 'TradingView is busy' if isinstance(e, RateLimited) else 'TradingView could not be reached'
            return True, (f'Saved {symbol.upper()}: {qty:,.8g} @ {price:,.8g}. {why}, so the symbol will be checked '
                          'automatically on the next refresh.')
        t = next((c for c in cands if res.get(c) is not None), None)
        if t is None:
            return False, (f'{symbol.upper()} was not found on TradingView ({", ".join(cands)}). '
                           'Check the symbol and market.')
        with self.lock:
            self.holdings.append({'id': uuid.uuid4().hex[:8], 'market': market, 'ticker': t,
                                  'buy_price': float(price), 'qty': float(qty),
                                  'added': _utc_now().strftime('%Y-%m-%d %H:%M')})
            self.save()
        if store is not None:
            store.add_analysis(market, t, res[t])
        if interval == RISK_INTERVAL:
            self.update_risk(market, {t: res[t]})
        return True, f'Added {t}: {qty:,.8g} @ {price:,.8g}'

    def add_known(self, market, ticker, price, qty):
        """Add a holding whose ticker the app already knows is valid (e.g. a practice buy from Top Picks)."""
        if not is_num(price) or price <= 0 or not is_num(qty) or qty <= 0:
            return False, 'Enter an amount above 0.'
        with self.lock:
            self.holdings.append({'id': uuid.uuid4().hex[:8], 'market': market, 'ticker': ticker,
                                  'buy_price': float(price), 'qty': float(qty),
                                  'added': _utc_now().strftime('%Y-%m-%d %H:%M')})
            self.save()
        return True, f'Added {short(ticker)} to the Practice portfolio: {qty:,.6g} @ {price:,.6g}'

    def update_risk(self, market, raw):
        """Move each holding's trailing ATR level up from new DAILY data (never down). Saves only if something changed."""
        today = _utc_now().strftime('%Y-%m-%d')
        changed = False
        with self.lock:
            for h in self.holdings:
                a = raw.get(h['ticker']) if h['market'] == market else None
                atr = _num(a.indicators, 'ATR') if a is not None and extras_ok(a.indicators) else None
                if atr is None:
                    continue
                high, stop, initial = trail(h, atr, _num(a.indicators, 'close[1]'), today)
                new = {'high_close': high, 'atr_stop': stop, 'initial_stop': initial}
                if any(h.get(k) != v for k, v in new.items()):
                    h.update(new)
                    changed = True
            if changed:
                self.save()
        return changed

    def sell(self, hid, qty, price=None, current_price=None):
        """Sell all or part of a holding and record the realised P/L. Returns (ok, message)."""
        h = self.get(hid)
        if h is None:
            return False, 'Pick a holding to sell.'
        if not is_num(qty) or qty <= 0:
            return False, 'Enter how much to sell (or tick "Sell everything").'
        if qty > h['qty'] * (1 + 1e-9):
            return False, f"You only hold {h['qty']:,.8g} {short(h['ticker'])}."
        price = price if is_num(price) and price > 0 else current_price
        if not is_num(price) or price <= 0:
            return False, 'No current price yet. Enter the sell price.'
        ccy = quote_ccy(h['market'], h['ticker'])
        pl = (price - h['buy_price']) * qty
        with self.lock:
            self.realised.append({'date': dt.datetime.now().strftime('%Y-%m-%d %H:%M'), 'market': h['market'],
                                  'ticker': h['ticker'], 'qty': float(qty), 'buy_price': h['buy_price'],
                                  'sell_price': float(price), 'pl': pl, 'ccy': ccy})
            remaining = round(h['qty'] - qty, 10)
            if remaining <= 0:
                self.holdings.remove(h)
            else:
                h['qty'] = remaining
            self.save()
        left = 'position closed' if remaining <= 0 else f'{remaining:,.8g} left'
        return True, f"Sold {qty:,.8g} {short(h['ticker'])} @ {price:,.8g}: realised {pl:+,.2f} {ccy} ({left})"

    def delete(self, hid):
        h = self.get(hid)
        if h is None:
            return False, 'Pick a holding to delete.'
        with self.lock:
            self.holdings.remove(h)
            self.save()
        return True, f"Deleted {short(h['ticker'])} (no P/L recorded)."

    def reset_pl(self):
        with self.lock:
            self.realised.clear()
            self.meta['pl_since'] = dt.datetime.now().strftime('%Y-%m-%d %H:%M')
            self.save()
        return True, 'P/L reset.'


# ---------------------------------------------------------------- remembered settings (optional)
# Off by default: every start begins on the default timeframe with all auto-refresh switched off. If you switch
# "Remember these settings" on (Dashboard), your timeframe and auto-refresh choices are saved and restored next time.
def prefs_path():
    return os.path.join(os.path.dirname(os.path.abspath(S.PORTFOLIO_FILE)), 'preferences.json')


def practice_path():
    """The Practice portfolio (pretend money) lives next to the real one, in its own file."""
    return os.path.join(os.path.dirname(os.path.abspath(S.PORTFOLIO_FILE)), 'practice_portfolio.json')


def load_prefs():
    try:
        with open(prefs_path(), encoding='utf-8') as f:
            p = json.load(f)
        return p if isinstance(p, dict) else {}
    except (OSError, ValueError):
        return {}


def save_prefs(store):
    """Save the store's settings if 'remember' is on (otherwise just record that it's off)."""
    # Beginner mode and the "total invested" figure are always kept: they are about you, not a screen setting.
    data = {'remember': bool(store.remember), 'beginner': bool(store.beginner),
            'total_invested': float(store.total_invested)}
    if store.remember:
        data.update(interval=store.interval, auto={mk: dict(c) for mk, c in store.auto.items()})
    try:
        tmp = prefs_path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, prefs_path())
    except OSError:
        pass                                    # not being able to save a preference must never break the app


def apply_prefs(store, prefs):
    """Restore remembered settings onto a new store (anything odd in the file is ignored)."""
    store.remember = bool(prefs.get('remember'))
    store.beginner = bool(prefs.get('beginner', getattr(S, 'BEGINNER_MODE', False)))
    if is_num(prefs.get('total_invested')) and prefs['total_invested'] > 0:
        store.total_invested = float(prefs['total_invested'])
    if not store.remember:
        return
    if prefs.get('interval') in DASH_TIMEFRAMES.values():
        store.interval = prefs['interval']
    for mk, c in (prefs.get('auto') or {}).items():
        if mk in store.auto and isinstance(c, dict) and c.get('minutes') in AUTO_CHOICES.values():
            store.auto[mk] = {'on': bool(c.get('on')), 'minutes': c['minutes']}
    if store.beginner:                             # Beginner mode always uses the 1 Day chart
        store.interval = RISK_INTERVAL


# ---------------------------------------------------------------- live market data
AUTO_CHOICES ={'1 min': 1, '5 min': 5, '15 min': 15, '30 min': 30, '1 hour': 60, '4 hours': 240}
AUTO_DEFAULT_MINUTES = 5     # interval shown when a market's auto-refresh is first switched on
AUTO_TICK = 5                # seconds between the background refresher's checks (it sends nothing unless due)
RETRY_SECONDS = 60           # after a fetch starts (or fails), the background refresher waits this long to retry


class MarketStore:
    """Latest ratings for every market. Each market refreshes in the background only if its own auto-refresh is
    switched on (Dashboard), at its own interval; missing data is always loaded once.

    Results are remembered per timeframe, so switching back to a timeframe loaded in the last few minutes
    is instant and costs no requests (TradingView limits how many requests we can make)."""

    def __init__(self, portfolio, practice=None):
        self.portfolio = portfolio
        self.practice = practice     # the Practice (pretend money) portfolio, kept up to date from the same data
        self.portfolios = [p for p in (portfolio, practice) if p is not None]
        self.interval = S.INTERVAL   # chart timeframe for the ratings (changed from the Dashboard)
        self._data = {}              # timeframe -> market -> {'df', 'raw', 'requested', 'missing', 'time'}
        self._errors = {}            # timeframe -> market -> last error message
        self._held = {}              # timeframe -> ticker -> analysis, for holdings added before their market loaded
        self._loading = set()        # (timeframe, market) currently being fetched
        self._lock = threading.Lock()
        self._tried = {}             # (timeframe, market) -> when a fetch was last started
        self.alerts = []             # newest last: {'id', 'time', 'level' ('warn' / 'good'), 'text'}
        self._alert_base = {}        # timeframe -> what was last seen: {'recs': {holding id: rec}, 'qualified': set}
        self._alert_lock = threading.Lock()
        self.auto = {mk: {'on': False, 'minutes': AUTO_DEFAULT_MINUTES} for mk in S.MARKETS}   # per-market auto-refresh
        self.remember = False        # keep the timeframe and auto-refresh choices for next time (Dashboard switch)
        # Beginner mode (Home page switch): the 1 Day chart only, every market refreshing by itself while it trades,
        # and Market Scan limited to larger companies. The website turns it on from settings.BEGINNER_MODE.
        self.beginner = False
        self.total_invested = 10000.0   # NZ$, for the "how much?" answer on idea cards (set on the Home page)
        self.tf_checks = {}          # Symbol Details timeframe check: ticker -> {timeframe: analysis, '_time': when}
        self._stop = threading.Event()
        # Top Picks market scan: one market at a time. 'running' = the market being scanned (or None);
        # 'results' = latest result per market.
        self.scan = {'running': None, 'progress': '', 'results': {}}

    def start_scan(self, market, background=True):
        """Scan ONE market on the current timeframe. Returns False if a scan is already running
        (only one at a time, to go easy on TradingView)."""
        with self._lock:
            if self.scan['running']:
                return False
            self.scan.update(running=market, progress='Starting...')
        interval = self.interval
        loaded = self.state.get(market)            # the Dashboard's data already has the benchmark - no extra request
        reference = {market: dict(loaded['raw'])} if loaded else None
        min_cap = self.scan_min_cap()

        def run():
            try:
                res = full_scan(interval, markets=[market], progress=lambda m: self.scan.update(progress=m),
                                reference=reference, min_cap=min_cap)
            except Exception as e:                      # (full_scan reports problems itself; this is a safety net)
                res = {'interval': interval, 'time': dt.datetime.now(), 'df': pd.DataFrame(),
                       'early': pd.DataFrame(), 'found': {},
                       'errors': {market: str(e)}}
            self.scan['results'][market] = res
            self.scan.update(running=None, progress='')
        if background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
        return True

    def scan_min_cap(self):
        """Smallest US company (USD market value) Market Scan includes: larger only in Beginner mode."""
        if self.beginner:
            return max(S.SCAN_MIN_MARKET_CAP, getattr(S, 'BEGINNER_MIN_MARKET_CAP', 0))
        return S.SCAN_MIN_MARKET_CAP

    def set_beginner(self, on):
        """Switch Beginner mode on or off. On: back to the 1 Day chart (the scores are designed for it)."""
        self.beginner = bool(on)
        if self.beginner and self.set_interval(RISK_INTERVAL):
            self.refresh_stale()

    def auto_cfg(self, mk):
        """A market's auto-refresh as it applies now: in Beginner mode every market refreshes by itself."""
        if self.beginner:
            return {'on': True, 'minutes': getattr(S, 'BEGINNER_AUTO_MINUTES', 15)}
        return self.auto.get(mk)

    @property
    def state(self):                 # ratings for the timeframe currently selected
        return self._data.setdefault(self.interval, {})

    @property
    def errors(self):
        return self._errors.setdefault(self.interval, {})

    def is_loading(self, mk):
        return (self.interval, mk) in self._loading

    def is_fresh(self, mk, interval=None):
        """Loaded recently - or loaded after its market closed (then nothing can have changed)."""
        s = self._data.get(interval or self.interval, {}).get(mk)
        return bool(s) and ((dt.datetime.now() - s['time']).total_seconds() < S.POLL_MINUTES * 60
                            or is_settled(mk, s['time']))

    def is_settled(self, mk, interval=None):
        s = self._data.get(interval or self.interval, {}).get(mk)
        return bool(s) and is_settled(mk, s['time'])

    def set_interval(self, interval):
        """Switch to another chart timeframe. Remembered results show straight away; call refresh_stale() next."""
        if interval == self.interval:
            return False
        self.interval = interval
        return True

    def refresh(self, mk, interval=None, manual=False):
        """Fetch one market. manual=True (a Refresh button) also drops that market's separately-fetched extras
        (exit targets, company figures), so they're fetched fresh the next time they're looked at."""
        interval = interval or self.interval
        if manual:
            forget_market(mk)
        key = (interval, mk)
        with self._lock:
            if key in self._loading:       # already being fetched (e.g. by the background refresher)
                busy = True
            else:
                busy = False
                self._loading.add(key)
        if busy:
            while key in self._loading:
                time.sleep(0.05)
            return mk in self._data.get(interval, {}) and mk not in self._errors.get(interval, {})
        self._tried[key] = time.time()
        try:
            try:
                df, raw, missing = analyse(mk, interval=interval, extra=self.held_tickers(mk))
            except Exception as e:
                self._errors.setdefault(interval, {})[mk] = str(e)
                return False
            watch = {to_ticker(mk, s) for s in S.MARKETS[mk]['watchlist']}
            if not df.empty:
                df = df[df['Symbol'].isin(watch)].reset_index(drop=True)   # holdings are shown on the portfolio page
            self._data.setdefault(interval, {})[mk] = {'df': df, 'raw': raw, 'requested': set(raw) | set(missing),
                                                      'missing': [t for t in missing if t in watch],
                                                      'time': dt.datetime.now()}
            self._errors.setdefault(interval, {}).pop(mk, None)
            for p in self.portfolios:
                p.resolve_pending(mk, raw, set(raw) | set(missing))
                if interval == RISK_INTERVAL:
                    p.update_risk(mk, raw)
            self.log_track_record()
            if interval in (self.interval, RISK_INTERVAL):
                self.check_alerts()
            return True
        finally:
            self._loading.discard(key)

    def refresh_all(self, manual=False):
        """Refresh every market - except closed ones already fetched since their close (it would be the same data)."""
        return all([True if self.is_settled(mk) else self.refresh(mk, manual=manual) for mk in S.RUN_MARKETS])

    def risk_stale(self):
        """Markets with holdings that have NO daily data yet (needed for the ATR risk levels). Only matters when the
        Dashboard is on another timeframe. Data that's merely old is kept; it updates with auto-refresh or Refresh."""
        if self.interval == RISK_INTERVAL:
            return []
        return [mk for mk in S.RUN_MARKETS if self.held_tickers(mk) and mk not in self._data.get(RISK_INTERVAL, {})]

    def held_tickers(self, mk):
        """Every ticker held in this market, in the real and the Practice portfolio."""
        return list(dict.fromkeys(t for p in self.portfolios for t in p.tickers(mk)))

    def refresh_stale(self, background=True):
        """After a timeframe switch: fetch only the markets with NO results on that timeframe yet (then any daily
        data the holdings' risk levels need). Results already loaded - even older ones - are shown as they are
        (with their time) and only refreshed by Refresh or auto-refresh. Returns the markets fetched."""
        interval = self.interval
        todo = [mk for mk in S.RUN_MARKETS if mk not in self._data.get(interval, {})]

        def run():
            for mk in todo:
                if self.interval != interval:   # user moved on to another timeframe - stop fetching this one
                    return
                self.refresh(mk, interval)
            for mk in self.risk_stale():
                self.refresh(mk, RISK_INTERVAL)
        if background:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()
        return todo

    # ---- alerts: things worth knowing about, noticed after each refresh ----
    def check_alerts(self):
        """Compare the latest results with the previous ones (on this timeframe) and record an alert when
        - a holding's recommendation gets WORSE and reaches Review exit or beyond, or
        - a watchlist symbol newly QUALIFIES on Top Picks.
        The first look on a timeframe - once EVERY market has loaded - only sets the starting point (no alerts for
        what was already true, and none while markets are still arriving one by one at start-up)."""
        interval = self.interval
        if not self.ready():
            return
        try:
            tbl = portfolio_table(self.portfolio, self)
            opp, _, _ = opportunities(self)
        except Exception:
            return
        recs = ({r['id']: (r['Symbol'], r['Recommendation']) for _, r in tbl.iterrows()
                 if r['Recommendation'] in RECOMMENDATIONS} if not tbl.empty else {})
        qualified = set(opp.loc[opp['Status'] == 'QUALIFIED', 'Symbol']) if not opp.empty else set()
        try:
            early = early_opportunities(self)
        except Exception:
            early = pd.DataFrame()
        # an EARLY alert only for symbols not already qualifying on the main score (those are no longer early)
        early_set = (set(early.loc[(early['Status'] == 'EARLY') & (early['Main'] != 'QUALIFIED'), 'Symbol'])
                     if not early.empty else set())
        with self._alert_lock:
            before = self._alert_base.get(interval)
            self._alert_base[interval] = {'recs': {k: v[1] for k, v in recs.items()}, 'qualified': qualified,
                                          'early': early_set}
            if before is None:
                return
            for hid, (sym, rec) in recs.items():
                old = before['recs'].get(hid)
                worse = old and RECOMMENDATIONS.index(rec) > RECOMMENDATIONS.index(old)
                if worse and RECOMMENDATIONS.index(rec) >= RECOMMENDATIONS.index('REVIEW EXIT'):
                    if PLAIN_REC[old] != PLAIN_REC[rec]:
                        self._alert('warn', f'{sym}: now "{PLAIN_REC[rec]}" (was "{PLAIN_REC[old]}")')
                    else:
                        self._alert('warn', f'{sym}: the warning signs are getting stronger - {PLAIN_REC[rec]}')
            for sym in sorted(qualified - before['qualified']):
                self._alert('good', f'{sym} is a new buy idea (passes every check on Top Picks)')
            for sym in sorted(early_set - before.get('early', set())):
                self._alert('good', f'{sym}: riskier early idea - its trend is turning up (Top Picks)')

    def log_track_record(self):
        """After each refresh: log today's QUALIFIED and EARLY picks from the DAILY chart's data (whatever timeframe
        is on screen), then bring every logged pick's price history up to date. Never breaks a refresh."""
        try:
            if self._data.get(RISK_INTERVAL):
                opp, _, _ = opportunities(self, RISK_INTERVAL)
                early = early_opportunities(self, RISK_INTERVAL)
                log_signals(self, opp, interval=RISK_INTERVAL)
                log_signals(self, early, kind='early', interval=RISK_INTERVAL)
                news = sys.modules.get('tvbot_news')       # fetch news for today's picks (background, cached),
                if news is not None:                       # so their sentiment is recorded with them
                    for d in (opp, early):
                        if d.empty or 'Ticker' not in d.columns:
                            continue
                        for mk, g in d[d['Status'].isin(['QUALIFIED', 'EARLY'])].groupby('Market'):
                            news.request(mk, list(g['Ticker']))
            update_signal_history(self)
        except Exception:
            pass

    def _track_due(self, mk):
        """The track record logs from the daily chart. While another timeframe is on screen, each market's daily
        data is fetched once at start-up and then every TRACK_DAILY_HOURS while it trades (one request each)."""
        key = (RISK_INTERVAL, mk)
        if key in self._loading or time.time() - self._tried.get(key, 0) < RETRY_SECONDS:
            return False
        s = self._data.get(RISK_INTERVAL, {}).get(mk)
        if s is None:
            return True
        return (not is_settled(mk, s['time'])
                and (dt.datetime.now() - s['time']).total_seconds() >= TRACK_DAILY_HOURS * 3600)

    def _alert(self, level, text):
        n = self.alerts[-1]['id'] + 1 if self.alerts else 1
        self.alerts.append({'id': n, 'time': dt.datetime.now(), 'level': level, 'text': text})
        del self.alerts[:-50]                          # keep the last 50

    # ---- per-market auto-refresh (each Dashboard box has its own switch and interval; all OFF by default) ----
    def set_auto(self, mk, on=None, minutes=None):
        cfg = self.auto[mk]
        if on is not None:
            cfg['on'] = bool(on)
        if minutes is not None:
            cfg['minutes'] = minutes

    def next_auto(self, mk):
        """When this market will next refresh by itself (None if its auto-refresh is off or it has no data yet)."""
        cfg, s = self.auto_cfg(mk), self.state.get(mk)
        if not cfg or not cfg['on'] or not s:
            return None
        return s['time'] + dt.timedelta(minutes=cfg['minutes'])

    def _due(self, mk, interval):
        """Should the background refresher fetch this market (on this timeframe) now?"""
        s = self._data.get(interval, {}).get(mk)
        if (interval, mk) in self._loading:
            return False
        if time.time() - self._tried.get((interval, mk), 0) < RETRY_SECONDS:
            return False                              # tried very recently (e.g. it failed) - don't hammer TradingView
        if s is None:
            return True                               # never loaded: load it once (start-up, new holding market...)
        cfg = self.auto_cfg(mk)
        if not cfg or not cfg['on'] or is_settled(mk, s['time']):
            return False                              # auto-refresh off, or a closed market with its final data
        return (dt.datetime.now() - s['time']).total_seconds() >= cfg['minutes'] * 60

    def start(self):
        """Start the background refresher: it loads any missing data, then refreshes each market whose
        auto-refresh is switched on, at that market's own interval."""
        self._stop.set()
        self._stop = ev = threading.Event()
        threading.Thread(target=self._run, args=(ev,), daemon=True).start()

    def stop(self):
        self._stop.set()

    def _run(self, ev):
        while not ev.is_set():
            if not rate_limit_wait():                 # during a cool-down, send nothing
                interval = self.interval
                for mk in S.RUN_MARKETS:
                    if ev.is_set():
                        return
                    if self._due(mk, interval):
                        self.refresh(mk, interval)
                    # holdings' risk levels need the daily chart; kept up to date with the same switch and interval
                    if (interval != RISK_INTERVAL and self.held_tickers(mk)
                            and self._due(mk, RISK_INTERVAL)):
                        self.refresh(mk, RISK_INTERVAL)
                    # the track record logs from the daily chart too, so keep it loaded (a few requests a day)
                    elif interval != RISK_INTERVAL and self._track_due(mk):
                        self.refresh(mk, RISK_INTERVAL)
            ev.wait(AUTO_TICK)

    def ready(self):
        return all(mk in self.state for mk in S.RUN_MARKETS)

    def wait_ready(self, timeout=60):
        end = time.time() + timeout
        while not self.ready() and time.time() < end:
            time.sleep(0.1)
        return self.ready()

    def analysis(self, ticker, interval=None):
        interval = interval or self.interval
        for s in list(self._data.get(interval, {}).values()):
            if ticker in s['raw']:
                return s['raw'][ticker]
        return self._held.get(interval, {}).get(ticker)

    def add_analysis(self, mk, ticker, a):      # (a new holding, fetched on the current timeframe)
        s = self.state.get(mk)
        if not s:                                # market not loaded yet (e.g. TradingView busy) - keep it anyway
            self._held.setdefault(self.interval, {})[ticker] = a
        if s:
            s['raw'][ticker] = a
            s['requested'].add(ticker)

    def current_price(self, h):
        a = self.analysis(h['ticker']) if h else None
        return a.indicators.get('close') if a else None

    def all_symbols(self):
        return sorted({t for s in list(self.state.values()) for t in s['raw']})

    def combined(self):
        frames = [s['df'] for s in list(self.state.values()) if not s['df'].empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ---------------------------------------------------------------- reports used by the pages
def holding_reason(h, price, rating, status, stop, atr, rec):
    """Plain-English reason for a holding's recommendation (written for someone new to investing)."""
    pl = (price / h['buy_price'] - 1) * 100
    if status == 'BREACHED':
        where = (f'The price ({price:,.6g}) has fallen {(stop - price) / stop * 100:.1f}% below your safety level '
                 f'({stop:,.6g})')
    else:
        where = (f'The price can fall {(price - stop) / price * 100:.1f}% (to {stop:,.6g}) before it reaches your '
                 'safety level')
    lock = (f' Selling at the safety level would still lock in a {(stop / h["buy_price"] - 1) * 100:+.1f}% gain.'
            if stop > h['buy_price'] else '')
    advice = {'HOLD': '',
              'HOLD / WATCH': ' Nothing to do now - just check it now and then.',
              'REVIEW EXIT': ' Take a look and decide whether to sell.',
              'EXIT WARNING': ' The price and the chart signals are both weakening - consider selling.',
              'STRONG EXIT WARNING': ' The price is below your safety level and the signals point down - '
                                     'this is the strongest warning: selling is worth serious thought.'}[rec]
    return (f'{where}. You are {"up" if pl >= 0 else "down"} {abs(pl):.1f}% on what you paid. '
            f'Chart signal: {rating}.{lock}{advice}')


def portfolio_table(portfolio, store):
    """One row per holding: P/L, rating (current timeframe), opportunity score (Strong Buy only), and the daily
    ATR trailing risk level with a recommendation. Nothing here ever buys or sells."""
    rows = []
    contexts = {}
    for h in list(portfolio.holdings):
        mk, t = h['market'], h['ticker']
        s = store.state.get(mk)
        a = store.analysis(t)
        d = store.analysis(t, RISK_INTERVAL)
        cost = h['buy_price'] * h['qty']
        row = {'id': h['id'], 'Ticker': t, 'Market': mk, 'Symbol': short(t), 'Qty': h['qty'], 'Bought': h['buy_price'], 'Now': None,
               'Ccy': quote_ccy(mk, t), 'Value': None, 'P/L': None, 'P/L %': None, 'Rating': '', 'Opp. score': None,
               'ATR': None, 'ATR %': None, 'High close': h.get('high_close'), 'Initial level': h.get('initial_stop'),
               'Trailing level': h.get('atr_stop'), 'To level %': None, 'At risk': None, 'ATR status': '',
               'Recommendation': '', 'Reason': ''}
        if h.get('pending'):                     # saved while TradingView couldn't be reached
            if h.get('not_found'):
                row.update({'Recommendation': 'Not found',
                            'Reason': f"Not found on TradingView ({', '.join(h['candidates'])}). Check the symbol and "
                                      'market, then delete this holding and add it again.'})
            else:
                row.update({'Recommendation': 'Checking...',
                            'Reason': 'Saved while TradingView was busy. The symbol is checked automatically on the '
                                      'next refresh.'})
            rows.append(row)
            continue
        if a is None:
            row['Recommendation'] = 'Loading...' if s is None or t not in s['requested'] else 'Not found'
            rows.append(row)
            continue
        price = a.indicators.get('close')
        rating = LABELS[a.summary['RECOMMENDATION']]
        row.update({'Now': price, 'Value': price * h['qty'], 'P/L': price * h['qty'] - cost,
                    'P/L %': (price / h['buy_price'] - 1) * 100, 'Rating': rating})
        if rating == 'Strong Buy' and mk in store.state:
            if mk not in contexts:
                contexts[mk] = _market_context(store, mk)
            row['Opp. score'] = score_symbol(mk, t, a, store.interval, *contexts[mk])['Score']
        atr = _num(d.indicators, 'ATR') if d is not None else None
        stop = h.get('atr_stop')
        if atr is None or stop is None:
            row['Reason'] = 'Waiting for daily data to set the ATR risk level.'
            rows.append(row)
            continue
        status = atr_status(price, stop, atr)
        rec = recommend(rating, status)
        row.update({'ATR': atr, 'ATR %': atr / price * 100, 'To level %': (price - stop) / price * 100,
                    'At risk': max(0.0, (price - stop) * h['qty']), 'ATR status': status, 'Recommendation': rec,
                    'Reason': holding_reason(h, price, rating, status, stop, atr, rec)})
        rows.append(row)
    return pd.DataFrame(rows)


def pl_summary(portfolio, table):
    realised = {}
    for t in portfolio.realised:
        realised[t['ccy']] = realised.get(t['ccy'], 0.0) + t['pl']
    unrealised, held = {}, {}
    if not table.empty:
        for ccy, g in table[table['Value'].notna()].groupby('Ccy'):
            unrealised[ccy] = float(g['P/L'].sum())
            held[ccy] = float(g['Value'].sum())
    rows = [{'Ccy': c, 'Value held': held.get(c, 0.0), 'Realised': realised.get(c, 0.0),
             'Unrealised': unrealised.get(c, 0.0), 'Total': realised.get(c, 0.0) + unrealised.get(c, 0.0)}
            for c in sorted(set(realised) | set(unrealised))]
    return pd.DataFrame(rows)


USD_LIKE = ('USD', 'USDT', 'USDC', 'FDUSD')      # US dollar and the dollar 'stablecoins' crypto is priced in


def nzd_rates(store):
    """NZ dollars per unit of each currency, worked out from prices the app has ALREADY fetched (no extra requests):
    NZDUSD from the Forex market, and for crypto-priced holdings (e.g. ETHBTC) the coin's USDT price.
    Returns ({currency: NZD per 1}, 'as of' time or None, the NZDUSD ticker used or None)."""
    prices, when = {}, {}
    for interval in [store.interval] + [iv for iv in list(store._data) if iv != store.interval]:
        for mk_data in list(store._data.get(interval, {}).values()):
            for t, a in mk_data['raw'].items():
                c = a.indicators.get('close') if a is not None else None
                if is_num(c) and c > 0 and short(t) not in prices:
                    prices[short(t)], when[short(t)] = c, mk_data['time']
    if not 0.2 < prices.get('NZDUSD', 0) < 2:      # missing, or not a believable NZDUSD rate: don't convert
        return {'NZD': 1.0}, None, None
    usd = 1 / prices['NZDUSD']
    rates = {'NZD': 1.0, **{c: usd for c in USD_LIKE}}
    for pair, c in prices.items():
        if len(pair) == 6 and pair.isalpha():     # other forex pairs, via NZD or USD
            a, b = pair[:3], pair[3:]
            if b == 'NZD':
                rates.setdefault(a, c)
            elif a == 'NZD':
                rates.setdefault(b, 1 / c)
            elif b == 'USD':
                rates.setdefault(a, c * usd)
            elif a == 'USD':
                rates.setdefault(b, usd / c)
        if pair.endswith('USDT') and len(pair) > 4:   # coins, for holdings priced in BTC/ETH
            rates.setdefault(pair[:-4], c * usd)
    return rates, when['NZDUSD'], 'NZDUSD'


def nzd_totals(summary, rates):
    """Add up the per-currency profit/loss summary in NZD. Returns (totals dict, currencies that couldn't be
    converted)."""
    tot = {'Value held': 0.0, 'Realised': 0.0, 'Unrealised': 0.0, 'Total': 0.0}
    missing = []
    for _, r in summary.iterrows():
        rate = rates.get(r['Ccy'])
        if rate is None:
            missing.append(r['Ccy'])
            continue
        for k in tot:
            tot[k] += r[k] * rate
    return tot, missing


def sales_table(portfolio, n=15):
    if not portfolio.realised:
        return pd.DataFrame()
    df = pd.DataFrame(portfolio.realised[::-1][:n])[['date', 'ticker', 'qty', 'buy_price', 'sell_price', 'pl', 'ccy']]
    df['ticker'] = df['ticker'].map(short)
    df.columns = ['Date', 'Symbol', 'Qty', 'Bought', 'Sold', 'P/L', 'Ccy']
    return df


def top_picks(store, n=10):
    df = store.combined()
    if df.empty:
        return df, df
    ranked = df.sort_values('Score', ascending=False)[['Market', 'Symbol', 'Rating', 'Buy', 'Neutral', 'Sell', 'Score']].copy()
    ranked['Symbol'] = ranked['Symbol'].map(short)
    return ranked.head(n).reset_index(drop=True), ranked.tail(n).iloc[::-1].reset_index(drop=True)


# ---------------------------------------------------------------- Composite Opportunity Score (Top Picks page)
# A 0-100 score built from 8 parts. It ranks candidates; it never overrides the entry rules in entry_check().
WEIGHTS = {'Indicators': 30, 'Trend': 20, 'Rel. strength': 15, 'Momentum': 10,
           'Volume': 10, 'Regime': 5, 'Risk': 5, 'Entry': 5}
def bands():
    """(lowest score, label), best first. 'Qualifies' starts at ENTRY_MIN_SCORE; 'Watchlist' is the 10 points below it."""
    m = S.ENTRY_MIN_SCORE
    return [(90, 'Exceptional'), (80, 'Very strong'), (m, 'Qualifies'), (m - 10, 'Watchlist'), (0, 'Ignore')]



BAND_COLOURS = {'Exceptional': TONE['good+'], 'Very strong': TONE['good+'], 'Qualifies': TONE['good'],
                'Watchlist': TONE['neutral'], 'Ignore': ''}
STATUS_COLOURS = {'QUALIFIED': TONE['good+'], 'REJECTED': 'color:#b3261e;font-weight:600'}
_BAR_SECONDS = {'1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '2h': 7200, '4h': 14400,
                '1d': 86400, '1W': 604800}


def _num(ind, key):
    v = ind.get(key)
    return float(v) if is_num(v) else None


def extras_ok(ind):
    """True if the EXTRA_FIELDS lined up: the last one (SMA200 one bar ago) is present and close to today's SMA200.
    (A brand-new coin with no 200-bar history has neither - that's fine, it just scores fewer parts.)"""
    if 'SMA200[1]' not in ind:
        return False
    now, prev = _num(ind, 'SMA200'), _num(ind, 'SMA200[1]')
    return now is None or prev is None or abs(prev / now - 1) < 0.05


def band(score):
    return next(label for lo, label in bands() if score >= lo) if is_num(score) else ''


def pts_indicators(ind):
    """TradingView's overall rating (-1..+1) x 30. Bearish ratings score 0."""
    r = _num(ind, 'Recommend.All')
    return None if r is None else round(max(0.0, r) * 30, 1)


def pts_trend(ind):
    """Moving-average structure, 20 max. 'Rising' = higher than on the previous bar."""
    c, s20, s50, s200 = (_num(ind, k) for k in ('close', 'SMA20', 'SMA50', 'SMA200'))
    s50p, s200p = _num(ind, 'SMA50[1]'), _num(ind, 'SMA200[1]')
    if None in (c, s20, s50, s200, s50p, s200p):
        return None
    return ((c > s200) * 5 + (s50 > s200) * 5 + (c > s50) * 3 + (s20 > s50) * 3
            + (s50 > s50p) * 2 + (s200 > s200p) * 2)


def period_return(ind):
    """% change used for relative strength: 3-month performance (daily chart only), else the 9-bar ROC."""
    v = _num(ind, 'Perf.3M')
    return v if v is not None else _num(ind, 'ROC')


def pts_relative(outperformance):
    """Out-performance vs the benchmark in percentage points, 15 max."""
    if outperformance is None:
        return None
    o = outperformance
    return 15 if o > 15 else 13 if o >= 10 else 10 if o >= 5 else 7 if o >= 0 else 0


def pts_momentum(ind):
    """Is momentum building? 10 max. RSI above 80 costs 2 points (over-extended - don't chase)."""
    rsi = _num(ind, 'RSI')
    if rsi is None:
        return None
    hist, hist1, roc = _num(ind, 'MACD.hist'), _num(ind, 'MACD.hist[1]'), _num(ind, 'ROC')
    adx, pdi, mdi = _num(ind, 'ADX'), _num(ind, 'ADX+DI'), _num(ind, 'ADX-DI')
    p = -2 if rsi > 80 else 3 if 50 <= rsi <= 70 else 0
    p += 3 if hist is not None and hist1 is not None and hist > hist1 else 0
    p += 2 if roc is not None and roc > 0 else 0
    # ADX only counts when the strong trend is UP (+DI above -DI); a strong downtrend earns nothing.
    p += 2 if adx is not None and adx > 25 and (pdi is None or mdi is None or pdi > mdi) else 0
    return max(0, min(10, p))


def bar_progress(interval, when_utc):
    """How far through the current bar we are (0..1), for 24/7 markets whose bars start on UTC boundaries."""
    if interval == '1M':
        start = when_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = (start + dt.timedelta(days=32)).replace(day=1)
        return (when_utc - start) / (end - start)
    secs = _BAR_SECONDS.get(interval)
    if not secs:
        return None
    offset = 4 * 86400 if interval == '1W' else 0      # weekly bars start Monday; 1 Jan 1970 was a Thursday
    return ((when_utc.timestamp() - offset) % secs) / secs


def volume_ratio(market, ind, interval, when_utc):
    """This bar's volume / average volume (avg of the 10- and 30-bar averages, i.e. roughly 20 bars).
    A bar that is still filling up has its volume projected to a full bar: crypto's (24/7, UTC bars) and, on the
    daily chart, a share market's while it is trading (by how much of the session has passed). Forex has no real
    volume."""
    if market == 'Forex':
        return None
    vol = _num(ind, 'volume')
    avgs = [v for v in (_num(ind, 'average_volume_10d_calc'), _num(ind, 'average_volume_30d_calc')) if v]
    if vol is None or not avgs:
        return None
    if market == 'Crypto':
        p = bar_progress(interval, when_utc)
        if p is None or p < 0.15:                      # too early in the bar to judge
            return None
        vol /= p
    elif interval == '1d':
        p = session_progress(market, when_utc)         # None = not trading now: today's bar is complete
        if p is not None:
            if p < 0.15:                               # too early in the session to judge
                return None
            vol /= p
    return vol / (sum(avgs) / len(avgs))


def pts_volume(ratio):
    if ratio is None:
        return None
    return 0 if ratio < 0.8 else 2 if ratio < 1.0 else 4 if ratio < 1.2 else 7 if ratio <= 1.5 else 10


def market_regime(market, raw):
    """(points out of 5, label) from the market's regime symbols, e.g. S&P 500 and Nasdaq ETFs, or BTC."""
    tickers = [to_ticker(market, s) for s in S.MARKETS[market].get('regime', [])]
    if not tickers:
        return None, 'n/a'
    checks = []
    for n, t in enumerate(tickers):
        a = raw.get(t)
        ind = a.indicators if a is not None else {}
        c, s50, s200 = _num(ind, 'close'), _num(ind, 'SMA50'), _num(ind, 'SMA200')
        if None in (c, s50, s200):
            return None, 'n/a'
        checks.append(c > s200)
        if n == 0:
            checks.append(s50 > s200)
            lead_above_50 = c > s50
    if all(checks):
        return (5, 'Strong bull') if lead_above_50 else (4, 'Bullish')
    return (0, 'Bearish') if not any(checks) else (2, 'Mixed')


def pts_risk(ind):
    """Calmer is better: ATR(14) as % of price, 5 max."""
    atr, c = _num(ind, 'ATR'), _num(ind, 'close')
    if atr is None or not c:
        return None
    pct = atr / c * 100
    return 5 if pct <= 3 else 4 if pct <= 5 else 2 if pct <= 7 else 0


def extension(ind):
    """% the price is above its 20-bar average (negative = below it)."""
    c, s20 = _num(ind, 'close'), _num(ind, 'SMA20')
    return None if c is None or not s20 else (c - s20) / s20 * 100


def pts_entry(ext):
    """Don't chase: the closer to the 20-bar average, the better. 5 max. Below the average scores 3."""
    if ext is None:
        return None
    return 3 if ext < 0 else 5 if ext <= 3 else 4 if ext <= 6 else 2 if ext <= 9 else 1 if ext <= 12 else 0


def daily_dollar_volume(market, ind, interval):
    """Average traded value per day (price x average volume per bar x bars per day)."""
    c = _num(ind, 'close')
    avg = _num(ind, 'average_volume_30d_calc') or _num(ind, 'average_volume_10d_calc')
    if not c or not avg:
        return None
    crypto = market == 'Crypto'
    if interval == '1d':
        per_day = 1
    elif interval == '1W':
        per_day = 1 / (7 if crypto else 5)
    elif interval == '1M':
        per_day = 1 / (30 if crypto else 21)
    else:
        per_day = (24 if crypto else 6.5) * 3600 / _BAR_SECONDS.get(interval, 86400)
    return c * avg * per_day


def composite(parts, weights=None):
    """0-100 from the parts that could be worked out. Parts with no data are left out and the rest scaled up to
    100. Returns None when less than 60 points' worth of parts are available. (Forex has its own weights.)"""
    weights = weights or WEIGHTS
    have = {k: v for k, v in parts.items() if v is not None}
    available = sum(weights[k] for k in have)
    if available < 60:
        return None
    return round(sum(have.values()) / available * 100, 1)


# Rule failures read "Short label: the numbers", e.g. "Score too low: 66.2, needs 70". The label (before the colon)
# is what the scan page counts up ("most common reasons").
INCOMPLETE = "Not enough data: TradingView's values didn't line up, so it isn't scored"
WHY_SEP = '  ·  '          # between reasons in the Why column (reasons contain commas themselves)


def why_labels(why):
    """The short labels of a Why text, e.g. ['Score too low', 'Price too stretched']."""
    return [r.split(':')[0].strip() for r in (why or '').split(WHY_SEP.strip()) if r.strip()]


def _short_money(v):
    return f'{v / 1e9:,.1f}B' if v >= 1e9 else f'{v / 1e6:,.1f}M' if v >= 1e6 else f'{v / 1e3:,.0f}K'


def _common_rules(why, ind, market, interval, ext):
    """The liquidity and 'not chasing' rules, shared by the main and early checks."""
    if market != 'Forex':
        need = S.MARKETS.get(market, {}).get('min_daily_value', S.MIN_DAILY_DOLLAR_VOLUME)
        dv = daily_dollar_volume(market, ind, interval)
        ccy = S.MARKETS.get(market, {}).get('currency', 'USD')
        if dv is None:
            why.append('Too little trading: no volume figures from TradingView')
        elif dv < need:
            have = _short_money(dv)
            if have == _short_money(need):           # e.g. 1.98M would read '2.0M, needs 2.0M'
                have = f'{dv / 1e6:,.2f}M' if dv >= 1e6 else f'{dv / 1e3:,.1f}K'
            why.append(f'Too little trading: about {have} {ccy} a day, needs {_short_money(need)}')
    limit = max_extension(market)
    if ext is not None and ext > limit:
        num = f'{ext:.1f}' if market == 'Forex' else f'{ext:.0f}'
        why.append(f'Price too stretched: {num}% above its 20-day average, the limit is {limit}% (don\'t chase)')


def entry_check(rating, score, ind, market, interval, ext, regime_label):
    """The safety rules for a NEW position. Returns a list of reasons it fails (empty = qualifies)."""
    bear = regime_label == 'Bearish'
    need = S.BEAR_MIN_SCORE if bear else S.ENTRY_MIN_SCORE
    why = []
    if rating != 'Strong Buy':
        why.append(f'Not Strong Buy: TradingView rates it {rating}')
    if score is None:
        why.append('Not enough data: too few parts of the score could be worked out')
    elif score < need:
        why.append(f'Score too low: {score:.1f}, needs {need}' + (' because its market is bearish' if bear else ''))
    c, s200 = _num(ind, 'close'), _num(ind, 'SMA200')
    if c is not None and s200 is not None and c <= s200:
        why.append(f'Below 200-day average: price is {(1 - c / s200) * 100:.1f}% under it (long-term downtrend)')
    _common_rules(why, ind, market, interval, ext)
    return why


def allocation(score, margin):
    """Share of the budget to put in, from the score and its lead over the next-best qualifier.
    ENTRY_MIN_SCORE-79 -> 50%, 80-89 -> 75%, 90+ -> 100%; a lead under WIN_MARGIN points caps it at 50%."""
    if not is_num(score) or score < S.ENTRY_MIN_SCORE:
        return 0.0
    pct = 1.0 if score >= 90 else 0.75 if score >= 80 else 0.5
    if margin is not None and margin < S.WIN_MARGIN:
        pct = min(pct, 0.5)
    return pct


def _state(store, interval=None):
    """One timeframe's loaded markets: the one on screen, or another (e.g. the daily chart, for the track record)."""
    if interval is None or interval == store.interval:
        return store.state
    return store._data.get(interval, {})


def _market_context(store, mk, interval=None):
    data = _state(store, interval)[mk]
    return context_from(mk, data['raw'], data['time'])


def reference_tickers(market):
    """The symbols fetched alongside a market's watchlist to score it: its benchmark and regime symbols, and for
    forex the 28 major pairs (for currency strength)."""
    cfg = S.MARKETS[market]
    refs = ([cfg['benchmark']] if cfg.get('benchmark') else []) + list(cfg.get('regime', []))
    if cfg['screener'] == 'forex':
        refs += FX_MAJOR_PAIRS
    return list(dict.fromkeys(to_ticker(market, s) for s in refs))


def context_from(mk, raw, when):
    """(fetch time in UTC, benchmark ticker, benchmark return, regime, currency strength or None) for scoring one
    market's symbols, from a set of results that includes the market's reference symbols."""
    cfg = S.MARKETS[mk]
    bench_t = to_ticker(mk, cfg['benchmark']) if cfg.get('benchmark') else None
    bench_a = raw.get(bench_t) if bench_t else None
    bench_ret = period_return(bench_a.indicators) if bench_a is not None else None
    strength = fx_strength(raw) if cfg['screener'] == 'forex' else None
    return when.astimezone(dt.timezone.utc), bench_t, bench_ret, market_regime(mk, raw), strength


def score_symbol(market, ticker, a, interval, when_utc, bench_t, bench_ret, regime, strength=None):
    if ticker == bench_t:                 # the benchmark itself (e.g. BTC) is judged on its own absolute return
        bench_ret = 0.0
    ind = a.indicators
    rating = LABELS[a.summary['RECOMMENDATION']]
    regime_pts, regime_label = regime
    row = {'Market': market, 'Symbol': short(ticker), 'Rating': rating, 'Score': None, 'Band': '', 'Status': 'REJECTED',
           'Ticker': ticker}
    if not extras_ok(ind):                # extra values didn't line up - don't score on shifted data
        return {**row, **dict.fromkeys(WEIGHTS), 'Why': INCOMPLETE}
    ret = period_return(ind)
    rel = None if ret is None or bench_ret is None else ret - bench_ret
    ext = extension(ind)
    if market == 'Forex':                          # forex has its own score (FX_WEIGHTS, out of 100)
        parts = fx_parts(ind, ext, strength, ticker)
        score = composite(parts, FX_WEIGHTS)
    else:
        parts = {'Indicators': pts_indicators(ind), 'Trend': pts_trend(ind), 'Rel. strength': pts_relative(rel),
                 'Momentum': pts_momentum(ind), 'Volume': pts_volume(volume_ratio(market, ind, interval, when_utc)),
                 'Regime': regime_pts, 'Risk': pts_risk(ind), 'Entry': pts_entry(ext)}
        score = composite(parts)
    why = entry_check(rating, score, ind, market, interval, ext, regime_label)
    return {**row, 'Score': score, 'Band': band(score), 'Status': 'REJECTED' if why else 'QUALIFIED', **parts,
            'Why': WHY_SEP.join(why)}


def opportunities(store, interval=None):
    """Every Strong Buy watchlist symbol scored and checked (nothing else is scored), on the timeframe on screen
    (or another one already loaded, e.g. the daily chart for the track record).
    Returns (table best-first, best pick or None, {market: regime})."""
    rows, regimes = [], {}
    iv = interval or store.interval
    for mk, data in list(_state(store, interval).items()):
        if data['df'].empty:
            continue
        ctx = _market_context(store, mk, interval)
        regimes[mk] = ctx[3]
        for t in data['df']['Symbol']:
            a = data['raw'].get(t)
            if a is None or a.summary['RECOMMENDATION'] != 'STRONG_BUY':
                continue
            rows.append(score_symbol(mk, t, a, iv, *ctx))
    df = pd.DataFrame(rows)
    if df.empty:
        return df, None, regimes
    df = df.sort_values('Score', ascending=False, na_position='last').reset_index(drop=True)
    ok = df[df['Status'] == 'QUALIFIED']
    best = None
    if not ok.empty:
        w = ok.iloc[0]
        runner = ok.iloc[1] if len(ok) > 1 else None
        margin = None if runner is None else round(w['Score'] - runner['Score'], 1)
        pct = allocation(w['Score'], margin)
        best = {'Symbol': w['Symbol'], 'Market': w['Market'], 'Score': w['Score'], 'Band': w['Band'],
                'Runner': None if runner is None else runner['Symbol'], 'Margin': margin, 'Pct': pct}
    return df, best, regimes


# ---------------------------------------------------------------- Early Entry Score (Top Picks, "Early" table)
# The main score is built mostly from things that only switch on once a run is mature (Strong Buy rating, SMA50 above
# SMA200, 3-month out-performance), so it tends to qualify symbols late. This separate score looks for a trend that is
# TURNING: fresh crossovers, oscillators leading the moving averages, and a run that isn't already stretched.
# It is logged separately in the track record so the two can be compared honestly.
EARLY_WEIGHTS = {'Turn': 30, 'Shift': 20, 'Not late': 20, 'Rel. 1M': 10, 'Volume': 10, 'Regime': 5, 'Risk': 5}
EARLY_STATUS_COLOURS = {'EARLY': TONE['good+'], 'REJECTED': 'color:#b3261e;font-weight:600'}


def pts_turn(ind):
    """Fresh crossovers on this bar or the last one, 30 max."""
    c, c1 = _num(ind, 'close'), _num(ind, 'close[1]')
    s20, s20p, s50, s50p = (_num(ind, k) for k in ('SMA20', 'SMA20[1]', 'SMA50', 'SMA50[1]'))
    if None in (c, s20, s50):
        return None
    p = 0
    if c > s20:                                                       # price back above its 20-bar average
        p += 8 if c1 is not None and s20p is not None and c1 <= s20p else 4
    if s20 > s50:                                                     # SMA20 crossing above SMA50
        p += 8 if s20p is not None and s50p is not None and s20p <= s50p else 2
    elif s20p is not None and s20 > s20p and (s50 - s20) / s50 < 0.01:
        p += 4                                                        # ... or rising and about to cross
    macd, sig = _num(ind, 'MACD.macd'), _num(ind, 'MACD.signal')
    hist, hist1 = _num(ind, 'MACD.hist'), _num(ind, 'MACD.hist[1]')
    if macd is not None and sig is not None and macd > sig and macd < 0:
        p += 7                                                        # MACD bullish cross still below zero = early
    elif hist is not None and hist1 is not None and hist > hist1 and hist1 <= 0:
        p += 5                                                        # histogram turning up from below zero
    rsi, rsi1 = _num(ind, 'RSI'), _num(ind, 'RSI[1]')
    if rsi is not None and rsi1 is not None:
        p += 7 if rsi > 50 >= rsi1 else 4 if 45 <= rsi <= 62 and rsi > rsi1 else 0
    return min(30, p)


def pts_shift(ind):
    """Oscillators lead moving averages: momentum turning before the trend rating does. 20 max."""
    osc = _num(ind, 'Recommend.Other')
    if osc is None:
        return None
    p = max(0.0, osc) * 10                                            # oscillator rating, up to 10
    pdi, mdi, pdi1, mdi1 = (_num(ind, k) for k in ('ADX+DI', 'ADX-DI', 'ADX+DI[1]', 'ADX-DI[1]'))
    if None not in (pdi, mdi) and pdi > mdi:
        p += 5 if pdi1 is not None and mdi1 is not None and pdi1 <= mdi1 else 2   # +DI crossing above -DI
    ao, ao1 = _num(ind, 'AO'), _num(ind, 'AO[1]')
    if ao is not None and ao1 is not None and ao > ao1:
        p += 5 if ao1 <= 0 else 2                                     # Awesome Oscillator rising (from below zero)
    return round(min(20.0, p), 1)


def pts_not_late(ind, ext):
    """Starts at 20 and loses points for signs the move is already well advanced."""
    rsi = _num(ind, 'RSI')
    if rsi is None:
        return None
    p = 20
    run = _num(ind, 'Perf.3M')
    if run is None:
        run = _num(ind, 'ROC')
    if run is not None:
        p -= 10 if run > 40 else 6 if run > 25 else 3 if run > 15 else 0
    p -= 8 if rsi > 75 else 4 if rsi > 68 else 0
    if ext is not None:
        p -= 6 if ext > 9 else 3 if ext > 6 else 0
    return max(0, p)


def short_return(ind):
    """% change used for short-term relative strength: 1-month performance (daily chart), else the 9-bar ROC."""
    v = _num(ind, 'Perf.1M')
    return v if v is not None else _num(ind, 'ROC')


def pts_relative_short(outperformance):
    if outperformance is None:
        return None
    o = outperformance
    return 10 if o > 5 else 7 if o >= 2 else 5 if o >= 0 else 0


# ---------------------------------------------------------------- forex: its own scores, out of 100
# Forex has no volume, no benchmark and no market regime, and currencies move about a tenth as much as shares, so
# it gets its own two scores (main and early). Both add up to exactly 100 - nothing is missing or scaled up.
# In place of relative strength and regime it uses CURRENCY STRENGTH: how each currency is doing against all the
# others, worked out from the 28 major pairs (which ride along in the forex watchlist's request).
FX_WEIGHTS = {'Indicators': 30, 'Trend': 20, 'Rel. strength': 20, 'Momentum': 15, 'Entry': 10, 'Risk': 5}
FX_EARLY_WEIGHTS = {'Turn': 30, 'Shift': 20, 'Rel. 1M': 20, 'Not late': 15, 'Regime': 10, 'Risk': 5}
FX_PART_NAMES = {'Rel. strength': 'currency strength (3 months)', 'Rel. 1M': 'currency strength (1 month)',
                 'Regime': "the pair's own trend", 'Risk': 'volatility'}


def currency_strength(raw, field):
    """{currency: average % move against the other majors} from whichever of the 28 major pairs are in raw.
    field(indicators) -> the pair's % change. A currency needs at least 3 pairs to get a reading."""
    moves = {}
    for t, a in raw.items():
        sym = short(t)
        if sym not in FX_MAJOR_PAIRS or a is None:
            continue
        v = field(a.indicators)
        if v is None:
            continue
        moves.setdefault(sym[:3], []).append(v)               # the base currency gains what the pair gains
        moves.setdefault(sym[3:], []).append(-v)              # the quote currency loses it
    return {c: sum(v) / len(v) for c, v in moves.items() if len(v) >= 3}


def fx_strength(raw):
    """Currency strength over 3 months and 1 month (on charts other than 1 Day both use the 9-bar change, and
    there is no separate 3-month reading)."""
    return {'3M': currency_strength(raw, period_return), '1M': currency_strength(raw, short_return),
            '1M_vs_3M': any(_num(a.indicators, 'Perf.3M') is not None for a in raw.values() if a is not None)}


def pair_strength(strength, ticker, key):
    """Base currency's strength minus the quote currency's, in % (e.g. EURUSD: EUR strength - USD strength)."""
    s, sym = (strength or {}).get(key) or {}, short(ticker)
    b, q = s.get(sym[:3]), s.get(sym[3:])
    return None if b is None or q is None else b - q


def pts_fx_strength(diff):
    """Main score: currency strength gap over 3 months, 20 max."""
    if diff is None:
        return None
    return 20 if diff > 3 else 15 if diff >= 1.5 else 10 if diff >= 0.5 else 6 if diff >= 0 else 0


def pts_fx_strength_early(diff_1m, diff_3m):
    """Early score: currency strength gap over 1 month (12 max), +8 if the base currency is gaining FASTER lately
    than over 3 months (a turn in its favour). 20 max."""
    if diff_1m is None:
        return None
    p = 12 if diff_1m > 1.5 else 9 if diff_1m >= 0.75 else 6 if diff_1m >= 0.25 else 3 if diff_1m >= 0 else 0
    if diff_3m is not None and diff_1m > 0 and diff_1m > diff_3m / 3:
        p += 8
    return min(20, p)


def pts_fx_entry(ext):
    """Don't chase, forex-sized: 10 max. 0-0.5% above SMA20 = 10 ... over 2.5% = 0. Below it = 6."""
    if ext is None:
        return None
    return 6 if ext < 0 else 10 if ext <= 0.5 else 8 if ext <= 1 else 5 if ext <= 1.5 else 2 if ext <= 2.5 else 0


def pts_fx_volatility(ind):
    """Calmer is better, forex-sized: ATR(14) up to 0.6% of the price = 5, 0.9% = 4, 1.3% = 2. 5 max."""
    atr, c = _num(ind, 'ATR'), _num(ind, 'close')
    if atr is None or not c:
        return None
    pct = atr / c * 100
    return 5 if pct <= 0.6 else 4 if pct <= 0.9 else 2 if pct <= 1.3 else 0


def pts_fx_not_late(ind, ext):
    """Starts at 15, forex-sized: a 3-month move over 2.5/4/6% costs 2/5/8, RSI over 68/75 costs 3/6, price over
    1.2/2% above SMA20 costs 2/4."""
    rsi = _num(ind, 'RSI')
    if rsi is None:
        return None
    p = 15
    run = period_return(ind)
    if run is not None:
        p -= 8 if run > 6 else 5 if run > 4 else 2 if run > 2.5 else 0
    p -= 6 if rsi > 75 else 3 if rsi > 68 else 0
    if ext is not None:
        p -= 4 if ext > 2 else 2 if ext > 1.2 else 0
    return max(0, p)


def pts_own_trend(ind):
    """Forex has no market regime: does the pair's own bigger trend back the turn? 10 max. Price above SMA200 and
    SMA50 rising = 10, one of the two = 4, neither = 0."""
    c, s200, s50, s50p = (_num(ind, k) for k in ('close', 'SMA200', 'SMA50', 'SMA50[1]'))
    if None in (c, s200, s50, s50p):
        return None
    above, rising = c > s200, s50 > s50p
    return 10 if above and rising else 4 if above or rising else 0


def fx_parts(ind, ext, strength, ticker):
    """The forex main score's 6 parts (FX_WEIGHTS)."""
    mom = pts_momentum(ind)
    return {'Indicators': pts_indicators(ind), 'Trend': pts_trend(ind),
            'Rel. strength': pts_fx_strength(pair_strength(strength, ticker, '3M')),
            'Momentum': None if mom is None else round(mom * 1.5, 1), 'Entry': pts_fx_entry(ext),
            'Risk': pts_fx_volatility(ind)}


def fx_early_parts(ind, ext, strength, ticker):
    """The forex early score's 6 parts (FX_EARLY_WEIGHTS)."""
    d3 = pair_strength(strength, ticker, '3M') if (strength or {}).get('1M_vs_3M') else None
    return {'Turn': pts_turn(ind), 'Shift': pts_shift(ind),
            'Rel. 1M': pts_fx_strength_early(pair_strength(strength, ticker, '1M'), d3),
            'Not late': pts_fx_not_late(ind, ext), 'Regime': pts_own_trend(ind), 'Risk': pts_fx_volatility(ind)}


def max_extension(market):
    return S.MAX_EXTENSION_PCT_FX if market == 'Forex' else S.MAX_EXTENSION_PCT


def early_check(rating, score, ind, market, interval, ext, regime_label):
    """The rules for an EARLY signal. Returns a list of reasons it fails (empty = EARLY)."""
    bear = regime_label == 'Bearish'
    need = S.EARLY_BEAR_MIN_SCORE if bear else S.EARLY_MIN_SCORE
    why = []
    if rating not in ('Buy', 'Strong Buy'):
        why.append(f'Not Buy or Strong Buy: TradingView rates it {rating}')
    if score is None:
        why.append('Not enough data: too few parts of the score could be worked out')
    elif score < need:
        why.append(f'Early score too low: {score:.1f}, needs {need}' + (' because its market is bearish' if bear else ''))
    c, s20 = _num(ind, 'close'), _num(ind, 'SMA20')
    if c is not None and s20 is not None and c <= s20:
        why.append(f'Not turned up yet: price is {(1 - c / s20) * 100:.1f}% under its 20-day average')
    _common_rules(why, ind, market, interval, ext)
    return why


def early_composite(parts, weights=None):
    weights = weights or EARLY_WEIGHTS
    have = {k: v for k, v in parts.items() if v is not None}
    available = sum(weights[k] for k in have)
    if available < 60:
        return None
    return round(sum(have.values()) / available * 100, 1)


def early_score_symbol(market, ticker, a, interval, when_utc, bench_t, bench_a):
    ind = a.indicators
    rating = LABELS[a.summary['RECOMMENDATION']]
    regime_pts, regime_label = bench_a['regime']
    row = {'Market': market, 'Symbol': short(ticker), 'Rating': rating, 'Score': None, 'Status': 'REJECTED',
           'Ticker': ticker}
    if not extras_ok(ind):
        return {**row, **dict.fromkeys(EARLY_WEIGHTS), 'Why': INCOMPLETE}
    bench_ret = 0.0 if ticker == bench_t else bench_a['ret']
    ret = short_return(ind)
    rel = None if ret is None or bench_ret is None else ret - bench_ret
    ext = extension(ind)
    if market == 'Forex':                          # forex has its own early score (FX_EARLY_WEIGHTS, out of 100)
        parts = fx_early_parts(ind, ext, bench_a.get('strength'), ticker)
        score = early_composite(parts, FX_EARLY_WEIGHTS)
    else:
        parts = {'Turn': pts_turn(ind), 'Shift': pts_shift(ind), 'Not late': pts_not_late(ind, ext),
                 'Rel. 1M': pts_relative_short(rel),
                 'Volume': pts_volume(volume_ratio(market, ind, interval, when_utc)),
                 'Regime': regime_pts, 'Risk': pts_risk(ind)}
        score = early_composite(parts)
    why = early_check(rating, score, ind, market, interval, ext, regime_label)
    return {**row, 'Score': score, 'Status': 'REJECTED' if why else 'EARLY', **parts, 'Why': WHY_SEP.join(why)}


def early_opportunities(store, interval=None):
    """Every Buy / Strong Buy watchlist symbol scored with the Early Entry Score. Returns a table, best first.
    'Main' says whether the symbol ALSO qualifies on the main score today (if so, it is no longer early)."""
    main, _, _ = opportunities(store, interval)
    main_ok = set(main.loc[main['Status'] == 'QUALIFIED', 'Ticker']) if not main.empty else set()
    rows = []
    iv = interval or store.interval
    for mk, data in list(_state(store, interval).items()):
        if data['df'].empty:
            continue
        when, bench_t, _, regime, strength = _market_context(store, mk, interval)
        bench = data['raw'].get(bench_t) if bench_t else None
        ctx = {'ret': short_return(bench.indicators) if bench is not None else None, 'regime': regime,
               'strength': strength}
        refs = set(reference_tickers(mk))
        watch = {to_ticker(mk, s) for s in S.MARKETS[mk]['watchlist']}
        for t in data['df']['Symbol']:
            a = data['raw'].get(t)
            if a is None or (t in refs and t not in watch):
                continue
            if a.summary['RECOMMENDATION'] not in ('BUY', 'STRONG_BUY'):
                continue
            row = early_score_symbol(mk, t, a, iv, when, bench_t, ctx)
            row['Main'] = 'QUALIFIED' if t in main_ok else ''
            rows.append(row)
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('Score', ascending=False, na_position='last').reset_index(drop=True)
    return df


# ---------------------------------------------------------------- full market scan (Top Picks)
# Finds every Strong Buy in each market that ISN'T in your watchlist, scores it with the same composite score,
# and keeps those at SCAN_MIN_SCORE or more. Run on demand (it costs a handful of requests).
_SCAN_SUFFIX = {'1m': '|1', '5m': '|5', '15m': '|15', '30m': '|30', '1h': '|60', '2h': '|120', '4h': '|240',
                '1d': '', '1W': '|1W', '1M': '|1M'}
_MAJORS = ['EUR', 'GBP', 'AUD', 'NZD', 'USD', 'CAD', 'CHF', 'JPY']    # usual quoting order
FX_MAJOR_PAIRS = [a + b for i, a in enumerate(_MAJORS) for b in _MAJORS[i + 1:]]   # the 28 standard pairs
SCAN_MAX_WAIT = 130                       # if rate-limited, wait out a cool-down this long (or shorter) and retry once
# Every value the Composite Opportunity Score uses. The screener returns them in the SAME reply as the search,
# so a whole market (e.g. ~600 US Strong Buys) is found and scored with ONE request.
SCAN_COLUMNS = ['close', 'Recommend.All', 'SMA20', 'SMA50', 'SMA200', 'SMA50[1]', 'SMA200[1]', 'RSI', 'MACD.hist',
                'MACD.hist[1]', 'ROC', 'ADX', 'ADX+DI', 'ADX-DI', 'ATR', 'Perf.3M', 'volume',
                'average_volume_10d_calc', 'average_volume_30d_calc',
                # kept with the scan result, so Exit targets and the Business column need no extra request
                'BB.upper', 'Pivot.M.Classic.R1', 'Pivot.M.Classic.R2', 'Pivot.M.Classic.R3', 'price_52_week_high',
                'price_target_average', 'price_target_high', 'price_earnings_ttm',
                'earnings_per_share_diluted_yoy_growth_ttm', 'dividends_yield_current', 'net_margin',
                # the extra values the Early Entry Score uses
                'Recommend.Other', 'MACD.macd', 'MACD.signal', 'RSI[1]', 'ADX+DI[1]', 'ADX-DI[1]', 'AO', 'AO[1]',
                'SMA20[1]', 'close[1]', 'Perf.1M',
                'description']           # the company / coin name, for the news search (no extra request)
_scanned = {}                # ticker -> (fetched, timeframe, values) from market scans, reused by other pages


class Snapshot:
    """One screener row, shaped like a tradingview_ta analysis (summary + indicators) so the score can use it."""

    def __init__(self, values):
        self.indicators = values
        self.summary = {'RECOMMENDATION': Compute.Recommend(values['Recommend.All'])}   # same rule as the library


def scan_query(market, interval, min_cap=None):
    """The screener query for one market: every Buy or Strong Buy (Strong Buys for the main score, both for the Early
    Entry Score), with all the values needed to score them. The main score's 'above SMA200' rule is applied after."""
    cfg = S.MARKETS[market]
    sfx = _SCAN_SUFFIX.get(interval, '')
    rule = [{'left': 'Recommend.All' + sfx, 'operation': 'greater', 'right': 0.1}]   # > 0.1 = Buy (library's rule)
    sort = 'market_cap_basic'
    if cfg['screener'] == 'america':      # real shares and ADRs on the main exchanges (any size, unless a floor is set)
        rule += [{'left': 'type', 'operation': 'in_range', 'right': ['stock', 'dr']},
                 {'left': 'exchange', 'operation': 'in_range', 'right': ['NASDAQ', 'NYSE', 'AMEX']}]
        cap = S.SCAN_MIN_MARKET_CAP if min_cap is None else min_cap
        if cap:
            rule.append({'left': 'market_cap_basic', 'operation': 'egreater', 'right': cap})
    elif cfg['screener'] == 'newzealand':  # every company listed on the NZX (not funds), any size
        rule += [{'left': 'type', 'operation': 'equal', 'right': 'stock'},
                 {'left': 'exchange', 'operation': 'equal', 'right': cfg['exchange']}]
    elif cfg['screener'] == 'crypto':     # coins (not futures) on the market's exchange, priced in USDT
        rule += [{'left': 'exchange', 'operation': 'equal', 'right': cfg['exchange']},
                 {'left': 'currency', 'operation': 'equal', 'right': 'USDT'},
                 {'left': 'type', 'operation': 'equal', 'right': 'spot'}]
        sort = 'volume'
    elif cfg['screener'] == 'forex':      # the 28 pairs between the 8 major currencies
        rule += [{'left': 'exchange', 'operation': 'equal', 'right': cfg['exchange']},
                 {'left': 'name', 'operation': 'in_range', 'right': FX_MAJOR_PAIRS}]
        sort = 'name'
    return {'filter': rule, 'columns': [c + sfx for c in SCAN_COLUMNS], 'sort': {'sortBy': sort, 'sortOrder': 'desc'},
            'range': [0, int(S.SCAN_MAX_PER_MARKET)]}


def scan_market(market, interval, progress=None, reference=None, min_cap=None):
    """Scan one market with ONE screener request. Returns (main rows scoring SCAN_MIN_SCORE+, Buys and Strong Buys
    found outside the watchlist, early rows scoring SCAN_EARLY_MIN_SCORE+). reference: results that already include
    the market's benchmark/regime symbols on this timeframe (the Dashboard's data); without it, one extra request
    fetches them."""
    cfg = S.MARKETS[market]
    say = progress or (lambda msg: None)
    say(f'{market}: searching for Buys and Strong Buys and scoring them...')
    reply = scan(cfg['screener'], scan_query(market, interval, min_cap))
    watch = {to_ticker(market, s) for s in cfg['watchlist']}
    snaps = {}
    for r in reply.get('data') or []:
        t, d = (r.get('s'), r.get('d')) if isinstance(r, dict) else (None, None)
        if not t or t in watch or t in snaps or not isinstance(d, list) or len(d) != len(SCAN_COLUMNS):
            continue                               # (a row of the wrong length could be misaligned - skip it)
        values = dict(zip(SCAN_COLUMNS, d))
        if is_num(values['Recommend.All']):
            snaps[t] = Snapshot(values)
            _scanned[t] = (dt.datetime.now(), interval, values)
    if not snaps:
        return [], 0, []
    refs = reference_tickers(market)
    raw = dict(reference or {})
    if any(t not in raw for t in refs):
        say(f'{market}: fetching the benchmark...')
        raw.update({t: a for t, a in fetch(cfg['screener'], interval, refs).items() if a is not None})
    ctx = context_from(market, raw, dt.datetime.now())
    when, bench_t, _, regime, strength = ctx
    bench = raw.get(bench_t) if bench_t else None
    early_ctx = {'ret': short_return(bench.indicators) if bench is not None else None, 'regime': regime,
                 'strength': strength}
    rows, early = [], []
    for t, a in snaps.items():
        rec = a.summary['RECOMMENDATION']
        if rec not in ('BUY', 'STRONG_BUY'):
            continue
        c, s200 = _num(a.indicators, 'close'), _num(a.indicators, 'SMA200')
        if rec == 'STRONG_BUY' and not (c is not None and s200 is not None and c <= s200):
            row = score_symbol(market, t, a, interval, *ctx)   # (below SMA200 can never qualify - left out)
            if is_num(row['Score']) and row['Score'] >= S.SCAN_MIN_SCORE:
                rows.append(row)
        row = early_score_symbol(market, t, a, interval, when, bench_t, early_ctx)
        if is_num(row['Score']) and row['Score'] >= S.SCAN_EARLY_MIN_SCORE:
            early.append(row)
    main_ok = {r['Ticker'] for r in rows if r['Status'] == 'QUALIFIED'}
    for r in early:
        r['Main'] = 'QUALIFIED' if r['Ticker'] in main_ok else ''
    return rows, len(snaps), early


def full_scan(interval, markets=None, progress=None, reference=None, min_cap=None):
    """Scan every market. Returns {'interval', 'time', 'df' (best first), 'early' (Early Entry Score, best first),
    'found': {market: n}, 'errors': {market: msg}}.
    If TradingView starts rate-limiting part-way, the markets already done are kept and the rest are reported."""
    rows, early, found, errors = [], [], {}, {}
    say = progress or (lambda msg: None)
    for mk in markets or S.RUN_MARKETS:
        for attempt in (1, 2):
            try:
                r, n, e = scan_market(mk, interval, progress, (reference or {}).get(mk), min_cap)
                rows += r
                early += e
                found[mk] = n
                errors.pop(mk, None)
                break
            except RateLimited as e:
                errors[mk] = str(e)
                wait = rate_limit_wait()
                if attempt == 2 or not wait or wait > SCAN_MAX_WAIT:
                    break
                say(f'{mk}: TradingView is busy - waiting {wait} seconds, then trying once more...')
                _sleep(wait + 1)
            except Exception as e:
                errors[mk] = str(e) or type(e).__name__
                break
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
    edf = pd.DataFrame(early)
    if not edf.empty:
        edf = edf.sort_values('Score', ascending=False).reset_index(drop=True)
    return {'interval': interval, 'time': dt.datetime.now(), 'df': df, 'early': edf, 'found': found,
            'errors': errors}


def fetch_timeframes(market, intervals, tickers=None):
    """Ratings on SEVERAL timeframes with ONE request (default: the market's watchlist): TradingView's screener
    returns every timeframe's raw values side by side, and the library's own calculation turns each set into a
    rating. Returns {interval: {ticker: analysis or None}}."""
    from tradingview_ta.main import calculate, TradingView
    cfg = S.MARKETS[market]
    keys = list(TradingView.indicators)
    tickers = list(dict.fromkeys(tickers or [to_ticker(market, s) for s in cfg['watchlist']]))
    cols = [k + _SCAN_SUFFIX.get(iv, '') for iv in intervals for k in keys]
    reply = scan(cfg['screener'], {'symbols': {'tickers': tickers, 'query': {'types': []}}, 'columns': cols})
    out = {iv: dict.fromkeys(tickers) for iv in intervals}
    for row in reply.get('data') or []:
        t, d = row.get('s'), row.get('d')
        if t not in tickers or not isinstance(d, list) or len(d) != len(cols):
            continue                                 # unknown or misaligned row: leave it as 'no data'
        ex, sym = t.split(':', 1)
        for n, iv in enumerate(intervals):
            values = dict(zip(keys, d[n * len(keys):(n + 1) * len(keys)]))
            out[iv][t] = calculate(indicators=values, indicators_key=keys, screener=cfg['screener'],
                                   symbol=sym, exchange=ex, interval=iv)
    return out


# ---------------------------------------------------------------- track record (forward test of the signals)
# Every QUALIFIED (and, separately, EARLY) watchlist pick on the daily chart is written down with its price and its
# benchmark's price, so you can later see whether following the signals would actually have beaten the market.
# While the app runs it also keeps, per pick: the latest price seen (so a pick never drops out of the table just
# because its market hasn't loaded yet), the lowest price seen (did it fall through its protective level?) and its
# price at fixed ages, so picks of different ages are compared like with like.
SIGNAL_GAP_DAYS = 7          # the same symbol is logged again at most once a week (a long run = one idea)
SIGNAL_HORIZONS = {'1 week': 7, '4 weeks': 28, '12 weeks': 84}   # calendar days: about 5, 20 and 60 trading days
TRACK_DAILY_HOURS = 6        # while another timeframe is on screen, re-fetch the daily chart this often (per market)
BENCH_NAMES = {'AMEX:SPY': 'S&P 500', 'NZX:NZ50G': 'S&P/NZX 50', 'BINANCE:BTCUSDT': 'Bitcoin'}
CASH = 'Cash (0%)'           # what a pick with no benchmark (forex, or Bitcoin itself) is compared with
_signal_lock = threading.Lock()


def signals_path():
    return os.path.join(os.path.dirname(os.path.abspath(S.PORTFOLIO_FILE)), 'signals.json')


def load_signals():
    try:
        with open(signals_path(), encoding='utf-8') as f:
            data = json.load(f)
        return [s for s in data if isinstance(s, dict) and is_num(s.get('price'))] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _values(store, ticker):
    """The latest indicator values the app has for a ticker (daily chart preferred), or None."""
    a = store.analysis(ticker, RISK_INTERVAL) or store.analysis(ticker)
    return a.indicators if a is not None else None


def _price(store, ticker):
    ind = _values(store, ticker)
    return _num(ind, 'close') if ind is not None else None


def _save_signals(log):
    tmp = signals_path() + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(log, f, indent=1)
        os.replace(tmp, signals_path())
        return True
    except OSError:
        return False                           # a failed log write must never break the app


def bench_name(ticker):
    return BENCH_NAMES.get(ticker, short(ticker)) if ticker else CASH


SIGNAL_KINDS = {'qualified': 'QUALIFIED', 'early': 'EARLY'}       # log kind -> the Status it records


def log_signals(store, opp, kind='qualified', interval=None):
    """Write down today's QUALIFIED (or, with kind='early', EARLY) picks - daily chart only, so every entry means
    the same thing. Each kind has its own once-a-week limit, so the two track records stay comparable.
    interval: the timeframe opp was scored on (default: the one on screen)."""
    if (interval or store.interval) != RISK_INTERVAL or opp.empty or 'Ticker' not in opp.columns:
        return 0
    picks = opp[opp['Status'] == SIGNAL_KINDS[kind]]
    if picks.empty:
        return 0
    with _signal_lock:
        log = load_signals()
        now = dt.datetime.now()
        recent = {s['ticker'] for s in log if s.get('kind', 'qualified') == kind
                  and (now - dt.datetime.fromisoformat(s['date'])).days < SIGNAL_GAP_DAYS}
        added = 0
        for _, r in picks.iterrows():
            t = r['Ticker']
            price = _price(store, t)
            if t in recent or price is None:
                continue
            bench = S.MARKETS[r['Market']].get('benchmark')
            bench_t = to_ticker(r['Market'], bench) if bench else None
            ind = _values(store, t) or {}
            atr = _num(ind, 'ATR') if extras_ok(ind) else None
            news = sys.modules.get('tvbot_news')          # news sentiment, if the app already has it (no fetch)
            news_score, news_n = news.summary_for_log(t) if news else (None, 0)
            log.append({'date': now.isoformat(timespec='minutes'), 'kind': kind, 'market': r['Market'], 'ticker': t,
                        'symbol': r['Symbol'], 'score': float(r['Score']), 'price': price,
                        'bench': bench_t if bench_t != t else None,
                        'bench_price': _price(store, bench_t) if bench_t and bench_t != t else None,
                        # the protective level the app would suggest on the day: 2 x the daily ATR below the price
                        'stop': price - ATR_MULT * atr if atr else None,
                        'news': news_score, 'news_n': news_n})
            added += 1
        if added and not _save_signals(log):
            return 0
        return added


def update_signal_history(store, now=None):
    """Bring every logged pick's own history up to date from data the app ALREADY has (no requests): its latest
    price, the lowest price seen since it was logged, and its price when it reached each SIGNAL_HORIZONS age.
    Only what the app sees while running is recorded. Returns True if anything changed."""
    now = now or dt.datetime.now()
    stamp = now.isoformat(timespec='minutes')
    with _signal_lock:
        log = load_signals()
        seen, changed = {}, False

        def values(t):
            if t not in seen:
                seen[t] = _values(store, t)
            return seen[t]
        for s in log:
            ind = values(s['ticker'])
            price = _num(ind, 'close') if ind is not None else None
            if price is None:
                continue
            bind = values(s['bench']) if s.get('bench') else None
            bprice = _num(bind, 'close') if bind is not None else None
            try:
                logged = dt.datetime.fromisoformat(s['date'])
            except (KeyError, TypeError, ValueError):
                continue
            if s.get('last') != price or (bprice is not None and s.get('bench_last') != bprice):
                s.update(last=price, last_date=stamp)
                if bprice is not None:
                    s['bench_last'] = bprice
                changed = True
            low = price
            day_low = _num(ind, 'low')
            if day_low is not None and now.date() > logged.date():   # (on the day itself: the low may predate the pick)
                low = min(low, day_low)
            if not is_num(s.get('low')) or low < s['low']:
                s.update(low=low, low_date=stamp)
                changed = True
            age = (now - logged).days
            if s.get('news') is None and now.date() == logged.date() and sys.modules.get('tvbot_news'):
                score, n = sys.modules['tvbot_news'].summary_for_log(s['ticker'])   # arrived after it was logged
                if score is not None:
                    s.update(news=score, news_n=n)
                    changed = True
            at = s.get('at') if isinstance(s.get('at'), dict) else {}
            for label, days in SIGNAL_HORIZONS.items():
                if age >= days and label not in at:
                    at[label] = {'date': stamp, 'price': price, 'bench': bprice}
                    changed = True
            if at:
                s['at'] = at
        if changed:
            _save_signals(log)
    return changed


def _pct(now, then):
    return (now / then - 1) * 100 if is_num(now) and is_num(then) and then else None


def track_record(store, kind='qualified'):
    """(table of logged picks of one kind with their return since, summary dict) using prices the app already has.
    A pick whose market isn't loaded uses the last prices saved for it, or shows 'no price yet': it never drops out.
    'With exit %' is what following the protective level would have returned: the level's return if the price was
    seen at or below it, otherwise today's return. Picks with no benchmark are compared with cash (0%)."""
    rows, horizon = [], {label: [] for label in SIGNAL_HORIZONS}     # label -> [(return, benchmark return)]
    now = dt.datetime.now()
    for s in load_signals():
        if s.get('kind', 'qualified') != kind:              # entries logged before 'kind' existed are QUALIFIED
            continue
        try:
            days = (now - dt.datetime.fromisoformat(s['date'])).days
        except (KeyError, TypeError, ValueError):
            continue
        live = _price(store, s['ticker'])
        if live is not None:                                 # today's prices, both from the same data
            price, source = live, 'live'
            bnow = _price(store, s['bench']) if s.get('bench') else None
        elif is_num(s.get('last')):                          # not loaded yet: the last prices the app saw
            price, source = s['last'], f"saved {str(s.get('last_date', ''))[:10]}"
            bnow = s.get('bench_last') if s.get('bench') else None
        else:
            price, source, bnow = None, 'no price yet', None
        ret = _pct(price, s['price'])
        if s.get('bench'):
            bench = _pct(bnow, s.get('bench_price'))
        else:
            bench = 0.0 if ret is not None else None         # nothing to compare with: judged against holding cash
        stop = s['stop'] if is_num(s.get('stop')) else None
        low = s['low'] if is_num(s.get('low')) else None
        hit = None if stop is None or low is None else low <= stop
        exit_ret = _pct(stop, s['price']) if hit else ret
        row = {'Date': s['date'][:10], 'Market': s['market'], 'Symbol': s['symbol'], 'Score': s['score'],
               'Then': s['price'], 'Now': price, 'Return %': ret, 'Compared with': bench_name(s.get('bench')),
               'Benchmark %': bench, 'Beat it': None if ret is None or bench is None else ret > bench}
        at = s.get('at') if isinstance(s.get('at'), dict) else {}
        for label in SIGNAL_HORIZONS:
            a = at.get(label) if isinstance(at.get(label), dict) else {}
            r = _pct(a.get('price'), s['price'])
            row[f'After {label} %'] = r
            if r is not None:
                b = _pct(a.get('bench'), s.get('bench_price')) if s.get('bench') else 0.0
                horizon[label].append((r, b))
        row.update({'Lowest %': _pct(low, s['price']), 'Protective': stop,
                    'Hit it': hit, 'With exit %': exit_ret, 'Days': days, 'Price from': source,
                    'Ticker': s['ticker']})
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df, None
    priced = df[df['Return %'].notna()]
    done = priced[priced['Days'] >= 1]
    compared = done[done['Benchmark %'].notna()]
    exits = done['With exit %'].dropna()

    def h_summary(pairs):
        beat = [r > b for r, b in pairs if b is not None]
        return {'n': len(pairs), 'avg': sum(r for r, _ in pairs) / len(pairs) if pairs else None,
                'beat_pct': sum(beat) / len(beat) * 100 if beat else None}
    summary = {'n': len(df), 'n_missing': len(df) - len(priced), 'n_aged': len(done),
               'avg': float(done['Return %'].mean()) if len(done) else None,
               'bench_avg': float(compared['Benchmark %'].mean()) if len(compared) else None,
               'beat_pct': float(compared['Beat it'].astype(bool).mean() * 100) if len(compared) else None,
               'win_pct': float((done['Return %'] > 0).mean() * 100) if len(done) else None,
               'exit_avg': float(exits.mean()) if len(exits) else None,
               'n_hit': int(df['Hit it'].eq(True).sum()),
               'horizons': {label: h_summary(p) for label, p in horizon.items()},
               'since': df['Date'].min()}
    return df.sort_values('Date', ascending=False).reset_index(drop=True), summary


# ---------------------------------------------------------------- business fundamentals (shares only)
# A chart signal knows nothing about the company. These few numbers give a beginner a quick sense check.
FUND_COLUMNS = ['price_earnings_ttm', 'earnings_per_share_diluted_yoy_growth_ttm', 'dividends_yield_current',
                'net_margin', 'sector']
STOCK_SCREENERS = ('america', 'newzealand')
_fund_cache = {}             # ticker -> (fetched, values, market): kept until that market is refreshed by hand


def fundamentals(market, tickers, store=None):
    """{ticker: values} for shares. Uses the figures already in the Dashboard's daily data or a market scan;
    only tickers the app knows nothing about cost a request (one for all of them), kept until a manual refresh."""
    cfg = S.MARKETS.get(market, {})
    if cfg.get('screener') not in STOCK_SCREENERS:
        return {}
    out, need = {}, []
    for t in dict.fromkeys(tickers):
        kv = known_values(store, t)
        if kv and any(_num(kv[0], k) is not None for k in FUND_COLUMNS if k != 'sector'):
            out[t] = kv[0]
        elif t in _fund_cache:
            out[t] = _fund_cache[t][1]
        else:
            need.append(t)
    if need:
        now = dt.datetime.now()
        reply = scan(cfg['screener'], {'symbols': {'tickers': need, 'query': {'types': []}}, 'columns': FUND_COLUMNS})
        got = {r.get('s'): r.get('d') for r in reply.get('data') or []}
        for t in need:
            d = got.get(t)
            _fund_cache[t] = (now, dict(zip(FUND_COLUMNS, d)) if isinstance(d, list) and len(d) == len(FUND_COLUMNS)
                              else {}, market)
            out[t] = _fund_cache[t][1]
    return out


def business_summary(f):
    """A one-line plain-English look at the company, e.g. 'P/E 40 · earnings +20% · dividend 0.3%'."""
    if not f or all(_num(f, k) is None for k in FUND_COLUMNS if k != 'sector'):
        return '–'                        # no company figures at all: say nothing rather than 'no P/E'
    pe, eps = _num(f, 'price_earnings_ttm'), _num(f, 'earnings_per_share_diluted_yoy_growth_ttm')
    div, margin = _num(f, 'dividends_yield_current'), _num(f, 'net_margin')
    parts = [f'P/E {pe:.0f}' if pe and pe > 0 else 'losing money' if margin is not None and margin < 0 else 'no P/E']
    if eps is not None:
        parts.append(f'earnings {eps:+.0f}%')
    parts.append(f'dividend {div:.1f}%' if div else 'no dividend')
    return ' · '.join(parts)


# ---------------------------------------------------------------- exit targets (Top Picks / Market Scan)
# Staged take-profit levels for a symbol you're considering, worked out from TradingView's own numbers (no AI, no
# guessing): resistance levels above today's price, grouped by how far away they are in typical daily moves (ATR).
TARGET_COLUMNS = ['close', 'ATR', 'BB.upper', 'Pivot.M.Classic.R1', 'Pivot.M.Classic.R2', 'Pivot.M.Classic.R3',
                  'price_52_week_high', 'price_target_average', 'price_target_high']
STAGES = [('Short-term', 0, 3, 'days'), ('Medium-term', 3, 10, 'weeks'), ('Stretch', 10, None, 'months')]
_target_cache = {}           # ticker -> (fetched, values, market): kept until that market is refreshed by hand


def known_values(store, ticker):
    """The newest DAILY-chart values the app already has for a ticker - from the Dashboard's data or a market
    scan - as (values, when), or None. Lets other pages reuse data instead of asking TradingView again."""
    best = None
    if store is not None:
        for mk_data in list(store._data.get(RISK_INTERVAL, {}).values()):
            a = mk_data['raw'].get(ticker)
            if a is not None:
                best = (dict(a.indicators), mk_data['time'])
                break
    hit = _scanned.get(ticker)
    if hit and hit[1] == RISK_INTERVAL and (best is None or hit[0] > best[1]):
        best = (hit[2], hit[0])
    return best


def target_data_if_known(ticker, store=None):
    """Exit-target values WITHOUT any request: loaded data (Dashboard / scan) or an earlier fetch. None if neither."""
    kv = known_values(store, ticker)
    hit = _target_cache.get(ticker)
    options = [x for x in (kv if kv and _num(kv[0], 'close') and _num(kv[0], 'ATR') else None,
                           (hit[1], hit[0]) if hit else None) if x]
    return max(options, key=lambda x: x[1]) if options else None


def fetch_target_data(market, ticker, store=None, force=False):
    """Daily-chart values for one symbol's exit targets. Uses data the app already has unless `force`
    (the Refresh button); otherwise ONE request, kept until you refresh that market by hand."""
    if not force:
        known = target_data_if_known(ticker, store)
        if known:
            return known
    reply = scan(S.MARKETS[market]['screener'],
                 {'symbols': {'tickers': [ticker], 'query': {'types': []}}, 'columns': TARGET_COLUMNS})
    row = next((r for r in reply.get('data') or [] if r.get('s') == ticker), None)
    if row is None or len(row.get('d') or []) != len(TARGET_COLUMNS):
        raise RuntimeError(f'TradingView returned no data for {ticker}')
    values, now = dict(zip(TARGET_COLUMNS, row['d'])), dt.datetime.now()
    _target_cache[ticker] = (now, values, market)
    return values, now


def forget_market(market):
    """A market was refreshed by hand: drop its separately-fetched extras so the next look gets fresh ones."""
    for cache in (_target_cache, _fund_cache):
        for t in [t for t, v in cache.items() if v[-1] == market]:
            cache.pop(t, None)


def exit_plan(values):
    """Staged exit targets from one symbol's values. Returns None without a price and ATR, else
    {'price', 'atr', 'stages': [{'name', 'horizon', 'low', 'high', 'reasons', 'estimated'}], 'protect', 'notes'}."""
    price, atr = _num(values, 'close'), _num(values, 'ATR')
    if not price or not atr:
        return None
    levels, notes = [], []

    def add(key, label, stage=None):
        v = _num(values, key)
        if v is not None and v > price * 1.001:
            levels.append((v, label, stage))
        return v
    add('BB.upper', 'the top of its usual price range lately (upper Bollinger band)')
    for n in (1, 2, 3):
        add(f'Pivot.M.Classic.R{n}', f'a monthly price level where rises often stall (pivot R{n})')
    high52 = add('price_52_week_high', 'its highest price of the past year (52-week high)')
    avg = add('price_target_average', 'the average analyst forecast for 12 months\' time')
    add('price_target_high', 'the most optimistic forecast (Street-high analyst target)', stage='Stretch')
    if high52 is not None and high52 <= price * 1.005:
        notes.append(('at_high', None))
    if avg is not None and avg < price:
        notes.append(('above_consensus', avg))
    stages = []
    for name, lo, hi, horizon in STAGES:
        inside = sorted((v, why) for v, why, forced in levels
                        if forced == name or (forced is None and
                                              lo < (v - price) / atr <= (hi if hi is not None else float('inf'))))
        estimated = not inside
        if estimated:                      # no chart level in this band: use typical daily moves instead
            k = {'Short-term': 2, 'Medium-term': 6, 'Stretch': 12}[name]
            inside = [(price + k * atr, f'{k} typical daily moves above today\'s price')]
        stages.append({'name': name, 'horizon': horizon, 'low': inside[0][0], 'high': inside[-1][0],
                       'levels': inside, 'estimated': estimated})
    return {'price': price, 'atr': atr, 'stages': stages, 'protect': price - ATR_MULT * atr, 'notes': notes}


def position_size(total, risk_pct, price, stop, cap_pct=None):
    """How much to buy, using two rules and taking the SMALLER answer:
    1. risk rule - if the price falls from `price` to the protective level `stop`, lose at most `risk_pct`% of `total`;
    2. cap rule  - never put more than `cap_pct`% of `total` into one idea (None = no cap).
    Returns None if the stop isn't below the price, else
    {'units', 'cost', 'loss', 'share_pct', 'loss_pct', 'limited_by' ('risk' or 'cap'), 'risk_cost', 'cap_cost'}."""
    if not (is_num(price) and is_num(stop) and is_num(total)) or price <= 0 or stop >= price or total <= 0:
        return None
    risk_units = total * risk_pct / 100 / (price - stop)
    cap_units = total * cap_pct / 100 / price if cap_pct else None
    units = risk_units if cap_units is None else min(risk_units, cap_units)
    cost, loss = units * price, units * (price - stop)
    return {'units': units, 'cost': cost, 'loss': loss, 'share_pct': cost / total * 100,
            'loss_pct': loss / total * 100, 'limited_by': 'cap' if cap_units is not None and cap_units < risk_units
            else 'risk', 'risk_cost': risk_units * price, 'cap_cost': None if cap_units is None else cap_units * price}


def money(v, ccy):
    s = f'{v:,.2f}' if abs(v) >= 1 else f'{v:.6g}'
    return {'USD': f'${s}', 'USDT': f'${s}', 'NZD': f'NZ${s}'}.get(ccy, f'{s} {ccy}')


def exit_write_up(symbol, rating, plan, ccy):
    """The plan in plain English, in the style of an analyst note."""
    if plan is None:
        return f'Not enough data to work out exit targets for {symbol}.'
    m = lambda v: money(v, ccy)
    lines = [f"**{symbol}** is now {m(plan['price'])} (chart signal: {rating}). If the price keeps rising, these are "
             'prices where rises often pause - good places to think about **taking some profit**:']
    for s in plan['stages']:
        rng = m(s['low']) if abs(s['high'] - s['low']) < 1e-9 else f"{m(s['low'])} to {m(s['high'])}"
        gain = (s['low'] / plan['price'] - 1) * 100
        why = '; '.join(f'{label} at {m(v)}' for v, label in s['levels'])
        tail = (' There is no past price level in this range, so this is based on how far the price typically moves.'
                if s['estimated'] else ' Rises often stall or pause around here.'
                if s['name'] == 'Short-term' else '')
        lines.append(f"- **{s['name']} ({rng})**, about {gain:+.1f}%, likely to take {s['horizon']}. Based on: "
                     f"{why}.{tail}")
    lines.append(f'- **Safety level ({m(plan["protect"])})**, about '
                 f'{(plan["protect"] / plan["price"] - 1) * 100:+.1f}%: if the price closes below this, the rise has '
                 'probably failed. Decide now that this is where you would sell. (It is 2 × the typical daily move '
                 'below today\'s price.)')
    for kind, v in plan['notes']:
        if kind == 'at_high':
            lines.append('\n> It is at (or near) its 52-week high - the highest price of the past year - so there are '
                         'no past prices above it to aim for. The targets come from how much it usually moves, '
                         'monthly price levels and analysts\' forecasts instead.')
        elif kind == 'above_consensus':
            lines.append(f'\n> On average, analysts expect {m(v)}, which is **below** today\'s price. So any further '
                         'rise depends on the current buying carrying on.')
    return '\n'.join(lines)


CHECK_TIMEFRAMES = {'1 Hour': '1h', '4 Hours': '4h', '1 Day': '1d', '1 Week': '1W'}


def timeframe_check(store, market, ticker, fetch=False, force=False):
    """One symbol's rating on 1h / 4h / 1 Day / 1 Week. Uses ratings the app already has (e.g. the Dashboard's
    timeframe, or an earlier check). fetch=True gets any that are missing in ONE request; force=True (Refresh)
    re-gets all four. Returns ({label: analysis or None}, when the fetched ones were fetched or None)."""
    cache = store.tf_checks.setdefault(ticker, {})
    when = cache.get('_time')
    if fetch or force:
        missing = [iv for iv in CHECK_TIMEFRAMES.values()
                   if force or (store.analysis(ticker, iv) is None and iv not in cache)]
        if missing:
            got = fetch_timeframes(market, missing, tickers=[ticker])
            cache.update({iv: got[iv].get(ticker) for iv in missing})
            cache['_time'] = when = dt.datetime.now()
    out = {}
    for label, iv in CHECK_TIMEFRAMES.items():          # the newer of: the Dashboard's copy, this check's copy
        options = [a for a in (cache.get(iv), store.analysis(ticker, iv)) if a is not None]
        out[label] = max(options, key=lambda a: getattr(a, 'time', None) or dt.datetime.min) if options else None
    return out, when


def agreement(ratings):
    """Plain-English summary of how many timeframes agree, e.g. '3 of 4 timeframes are Buy or Strong Buy'."""
    labels = [LABELS[a.summary['RECOMMENDATION']] for a in ratings.values() if a is not None]
    if not labels:
        return ''
    up = sum(r in ('Buy', 'Strong Buy') for r in labels)
    down = sum(r in ('Sell', 'Strong Sell') for r in labels)
    n = len(labels)
    if up == n:
        return f'All {n} timeframes are Buy or Strong Buy: short and long-term trends agree.'
    if down == n:
        return f'All {n} timeframes are Sell or Strong Sell: short and long-term trends agree (downwards).'
    return (f'{up} of {n} timeframes are Buy or Strong Buy and {down} are Sell or Strong Sell: the trends are mixed, '
            'so the signal is less reliable.')


# ---------------------------------------------------------------- start-up health check
def health_check(portfolio):
    """Returns [(status, name, detail)] with status 'ok', 'warn' or 'fail'. 'fail' means the app must not start."""
    checks = []

    def check(name, fn, critical=True):
        try:
            checks.append(('ok', name, fn() or ''))
        except Exception as e:
            checks.append(('fail' if critical else 'warn', name, str(e) or type(e).__name__))

    def python():
        assert sys.version_info >= (3, 9), f'Python {platform.python_version()} is too old - 3.9 or newer is needed'
        return f'Python {platform.python_version()} on {platform.system()}'

    def packages():
        return ', '.join(f'{p} {md.version(p)}' for p in ('tradingview-ta', 'pandas', 'streamlit'))

    def settings_ok():
        problems = []
        if not S.RUN_MARKETS:
            problems.append('RUN_MARKETS is empty')
        for mk in S.RUN_MARKETS:
            cfg = S.MARKETS.get(mk)
            if cfg is None:
                problems.append(f"RUN_MARKETS includes '{mk}' but there is no such market in MARKETS")
                continue
            for key in ('screener', 'exchange', 'watchlist'):
                if not cfg.get(key):
                    problems.append(f"{mk}: '{key}' is missing or empty")
            if cfg.get('hours'):
                try:
                    ZoneInfo(cfg['hours']['tz'])
                    assert _hhmm(cfg['hours']['open']) < _hhmm(cfg['hours']['close'])
                except Exception:
                    problems.append(f"{mk}: 'hours' must look like {{'tz': 'Pacific/Auckland', 'open': '10:00', "
                                    "'close': '16:45'}")
        valid = {v for k, v in vars(Interval).items() if k.startswith('INTERVAL_')}
        if S.INTERVAL not in valid:
            problems.append(f"INTERVAL '{S.INTERVAL}' is not a valid timeframe")
        if not (is_num(S.POLL_MINUTES) and S.POLL_MINUTES >= 1):
            problems.append('POLL_MINUTES must be a number, 1 or more')
        if not (is_num(S.PAUSE_BETWEEN_REQUESTS) and S.PAUSE_BETWEEN_REQUESTS >= 0):
            problems.append('PAUSE_BETWEEN_REQUESTS must be a number, 0 or more')
        for name in ('ENTRY_MIN_SCORE', 'BEAR_MIN_SCORE', 'WIN_MARGIN', 'MAX_EXTENSION_PCT', 'MAX_EXTENSION_PCT_FX',
                     'MIN_DAILY_DOLLAR_VOLUME', 'SCAN_MIN_SCORE', 'SCAN_MIN_MARKET_CAP', 'SCAN_MAX_PER_MARKET'):
            v = getattr(S, name, None)
            if not (is_num(v) and v >= 0):
                problems.append(f'{name} is missing or not a number (0 or more)')
        assert not problems, '; '.join(problems)
        n = sum(len(S.MARKETS[m]['watchlist']) for m in S.RUN_MARKETS)
        return f'{len(S.RUN_MARKETS)} markets, {n} symbols, auto-refresh set per market on the Dashboard'

    def rate():
        assert S.PAUSE_BETWEEN_REQUESTS >= 1, (f'PAUSE_BETWEEN_REQUESTS is {S.PAUSE_BETWEEN_REQUESTS}s - '
                                               'below 1s TradingView may block you')
        return f'{S.PAUSE_BETWEEN_REQUESTS}s between requests'

    def logic():
        assert [atr_status(p, 100, 10) for p in (111, 110, 105, 100)] == ATR_STATUSES, 'ATR status levels are wrong'
        assert recommend('Strong Buy', 'NORMAL') == 'HOLD' and recommend('Sell', 'BREACHED') == 'STRONG EXIT WARNING', \
            'holding recommendation matrix is wrong'
        h = {'buy_price': 200.0, 'added': '2000-01-01', 'atr_stop': 214.0}
        assert trail(h, 8, 230, '2026-01-01')[1] == 214 and trail(h, 8, 240, '2026-01-01')[1] == 224, \
            'trailing ATR level is wrong (it must never move down)'
        if 'Crypto' in S.MARKETS:
            ex = S.MARKETS['Crypto']['exchange']
            assert to_ticker('Crypto', 'btc') == f'{ex}:BTCUSDT', 'crypto symbol conversion is wrong'
            assert quote_ccy('Crypto', f'{ex}:BTCUSDT') == 'USDT', 'crypto currency detection is wrong'
        if 'Forex' in S.MARKETS:
            assert quote_ccy('Forex', 'FX_IDC:NZDUSD') == 'USD', 'forex currency detection is wrong'
        assert abs((400 - 349.34) * 5 - 253.30) < 1e-6, 'P/L arithmetic is wrong'
        perfect = {'close': 110, 'SMA20': 105, 'SMA50': 100, 'SMA200': 90, 'SMA50[1]': 99, 'SMA200[1]': 89}
        assert pts_trend(perfect) == 20, 'opportunity score: trend points are wrong'
        assert composite(dict.fromkeys(WEIGHTS, 0) | {'Indicators': 30}) == 30, 'opportunity score: total is wrong'
        return 'symbol handling, currencies, P/L, ATR risk rules and opportunity-score maths OK'

    def storage():
        probe = os.path.join(os.path.dirname(os.path.abspath(portfolio.path)), '.write_test')
        with open(probe, 'w') as f:
            f.write('ok')
        os.remove(probe)
        return f'{len(portfolio.holdings)} holdings and {len(portfolio.realised)} sales loaded; folder is writable'

    def contents():
        assert not portfolio.warnings, ' '.join(portfolio.warnings)
        return 'no problems found'

    def tradingview():
        mk = S.RUN_MARKETS[0]
        t = to_ticker(mk, S.MARKETS[mk]['watchlist'][0])
        a = fetch(S.MARKETS[mk]['screener'], S.INTERVAL, [t]).get(t)
        assert a is not None, f'TradingView returned no data for {t}'
        s = a.summary
        total = s['BUY'] + s['NEUTRAL'] + s['SELL']
        assert s['RECOMMENDATION'] in LABELS, f"unexpected rating '{s['RECOMMENDATION']}' - TradingView may have changed"
        assert total >= 20 and a.indicators.get('close'), 'the response is missing data - TradingView may have changed'
        if not extras_ok(a.indicators):
            raise RuntimeError('extra values for the opportunity score came back misaligned - Top Picks scores '
                               'will show as "incomplete data"')
        return f"reachable - {short(t)} is {LABELS[s['RECOMMENDATION']]} ({total} metrics)"

    check('Python', python)
    check('Packages', packages)
    check('Settings', settings_ok)
    failed_settings = checks[-1][0] == 'fail'
    check('Request rate', rate, critical=False)
    if not failed_settings:
        check('Core calculations', logic)
    check('Portfolio file', storage)
    check('Portfolio contents', contents, critical=False)
    if not failed_settings:
        check('TradingView connection', tradingview, critical=False)
    return checks
