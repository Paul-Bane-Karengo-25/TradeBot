"""
Full automated test of the TradingView Analysis Bot.

  * Uses a FAKE TradingView, so it's fast, works offline and doesn't use up your request limit.
  * Uses a temporary portfolio file, so your real portfolio.json is never touched.
  * Part 1 tests the logic (tvbot_core.py). Part 2 draws every web page with Streamlit's built-in
    tester (no browser needed) and clicks through the portfolio forms.

Run it with  run_tests.bat  (Windows)  or  bash run_tests.sh  (Mac),  or:  python tests/run_tests.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import warnings
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPORT = os.path.join(HERE, 'last_test_report.txt')
sys.path.insert(0, ROOT)
warnings.filterwarnings('ignore')


def ensure_packages():
    need = {'tradingview_ta': 'tradingview-ta', 'pandas': 'pandas', 'streamlit': 'streamlit'}
    missing = [p for m, p in need.items() if importlib.util.find_spec(m) is None]
    if missing:
        print('Installing:', ', '.join(missing))
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--quiet', '-r', os.path.join(ROOT, 'requirements.txt')])


# ------------------------------------------------------------------ fake TradingView
_OSC = ['RSI', 'STOCH.K', 'CCI', 'ADX', 'AO', 'Mom', 'MACD', 'Stoch.RSI', 'W%R', 'BBP', 'UO']
_MA = ['EMA10', 'SMA10', 'EMA20', 'SMA20', 'EMA30', 'SMA30', 'EMA50', 'SMA50', 'EMA100', 'SMA100',
       'EMA200', 'SMA200', 'Ichimoku', 'VWMA', 'HullMA']
_PATTERNS = {'STRONG_BUY': ((8, 2, 1), (12, 3, 0)), 'BUY': ((5, 5, 1), (9, 4, 2)), 'NEUTRAL': ((3, 6, 2), (5, 4, 6)),
             'SELL': ((1, 6, 4), (2, 3, 10)), 'STRONG_SELL': ((0, 7, 4), (1, 3, 11))}
_NYSE = {'JPM', 'KO', 'V', 'MA', 'LLY', 'BRK.B', 'JNJ', 'XOM', 'ABBV', 'SPY'}   # (SPY is on AMEX)
FAKE = {'calls': 0, 'fail_next': 0, 'down': False,
        'prices': {'BINANCE:BTCUSDT': 70000.0, 'NYSE:JPM': 320.0, 'BINANCE:ETHUSDT': 2500.0, 'BINANCE:SOLUSDT': 150.0}}
_fake_lock = threading.Lock()


def _group(names, counts, rec):
    b, n, s = counts
    return {'RECOMMENDATION': rec, 'BUY': b, 'NEUTRAL': n, 'SELL': s,
            'COMPUTE': dict(zip(names, ['BUY'] * b + ['NEUTRAL'] * n + ['SELL'] * s))}


class FakeAnalysis:
    def __init__(self, ticker):
        h = zlib.crc32(ticker.encode())
        rec = list(_PATTERNS)[h % 5]
        osc, ma = _PATTERNS[rec]
        self.summary = {'RECOMMENDATION': rec, 'BUY': osc[0] + ma[0], 'NEUTRAL': osc[1] + ma[1], 'SELL': osc[2] + ma[2]}
        self.oscillators, self.moving_averages = _group(_OSC, osc, rec), _group(_MA, ma, rec)
        c = float(FAKE['prices'].get(ticker, 10 + h % 1000))
        k = 1 if rec in ('STRONG_BUY', 'BUY') else -1          # bullish symbols get a bullish chart, and vice versa
        self.indicators = {
            'close': c, 'Recommend.All': {'STRONG_BUY': 0.7, 'BUY': 0.3, 'NEUTRAL': 0.0, 'SELL': -0.3, 'STRONG_SELL': -0.7}[rec],
            'Recommend.Other': 0.2 * k, 'Recommend.MA': 0.4 * k,
            'SMA20': c / (1 + 0.02 * k), 'SMA50': c / (1 + 0.05 * k), 'SMA200': c / (1 + 0.12 * k),
            'SMA20[1]': c / (1 + 0.021 * k), 'SMA50[1]': c / (1 + 0.051 * k), 'SMA200[1]': c / (1 + 0.121 * k),
            'RSI': 60.0 if k > 0 else 40.0, 'MACD.hist': 1.0 * k, 'MACD.hist[1]': 0.5 * k, 'ROC': 3.0 * k,
            'ADX': 30.0, 'ADX+DI': 25.0 if k > 0 else 15.0, 'ADX-DI': 15.0 if k > 0 else 25.0, 'ATR': c * 0.02,
            'Perf.3M': (5.0 + h % 20) * k, 'close[1]': c, 'volume': 6e6, 'average_volume_10d_calc': 5e6, 'average_volume_30d_calc': 5e6}
        if rec == 'BUY':                                         # Buys look like a trend just turning up (early score)
            self.indicators.update({'RSI[1]': 48.0, 'MACD.macd': -0.1, 'MACD.signal': -0.3, 'AO': 0.2, 'AO[1]': -0.1,
                                    'ADX+DI[1]': 14.0, 'ADX-DI[1]': 16.0, 'Perf.1M': 8.0})


def fake_scan(screener, body):
    """Fake TradingView screener: some symbols outside the watchlists, plus one that IS in a watchlist."""
    with _fake_lock:
        FAKE['calls'] += 1
        FAKE['scans'] = FAKE.get('scans', []) + [(screener, body)]
        if FAKE['down'] or FAKE['fail_next'] > 0:
            FAKE['fail_next'] = max(0, FAKE['fail_next'] - 1)
            raise json.JSONDecodeError('Expecting value', '', 0)
    if 'symbols' in body:                                    # asking for named symbols (e.g. several timeframes)
        names = [t for t in body['symbols']['tickers'] if _exists(t)]
    else:                                                    # a search
        names = {'america': ['NASDAQ:AAPL'] + [f'NASDAQ:SCAN{i}' for i in range(FAKE.get('us_scan_size', 40))],
                 'crypto': [f'BINANCE:SCAN{i}USDT' for i in range(15)],
                 'newzealand': ['NZX:FPH'] + [f'NZX:NZSCAN{i}' for i in range(10)],
                 'forex': ['FX_IDC:EURCHF', 'FX_IDC:GBPCAD', 'FX_IDC:AUDJPY', 'FX_IDC:NZDCHF']}[screener]
    cols = [c.split('|')[0] for c in body['columns']]       # the values asked for, in order (timeframe suffix removed)
    return {'totalCount': len(names),
            'data': [{'s': n, 'd': [FakeAnalysis(n).indicators.get(c) for c in cols]} for n in names]}


NEWS_CALLS = []


class _Reply:
    def __init__(self, content=b'', data=None): self.content, self._data = content, data
    def json(self): return self._data


def fake_news_get(url, params=None):
    """Fake Google News RSS / Finnhub: a few headlines per search (one repeated, one too old)."""
    import email.utils as eu
    import datetime as dt
    NEWS_CALLS.append((url, dict(params or {})))
    now = dt.datetime.now(dt.timezone.utc)
    if 'finnhub' in url:
        return _Reply(data=[{'headline': f"{params['symbol']} beats forecasts", 'source': 'Reuters',
                             'url': 'https://example.com/1', 'datetime': (now - dt.timedelta(hours=2)).timestamp()}])
    import re
    q = re.search(r'"([^"]+)"', params['q']).group(1)          # the name or symbol searched for
    items = [(f'{q} beats forecasts', 'Reuters', 2), (f'{q} shares surge on demand', 'Bloomberg', 26),
             (f'{q} beats forecasts', 'Yahoo Finance', 5), (f'{q} falls after guidance cut', 'CNBC', 3),
             (f'{q} old story', 'Old Times', 24 * 10)]
    from xml.sax.saxutils import escape                     # (a real feed escapes '&' etc.)
    xml = ''.join(f'<item><title>{escape(t)} - {s}</title><link>https://example.com/{n}</link>'
                  f'<pubDate>{eu.format_datetime(now - dt.timedelta(hours=h))}</pubDate>'
                  f'<source url="https://example.com">{s}</source></item>' for n, (t, s, h) in enumerate(items))
    return _Reply(f'<rss><channel>{xml}</channel></rss>'.encode())


def fake_finbert():
    """Fake FinBERT: 'beats'/'surge' positive, 'falls'/'cut' negative, otherwise neutral."""
    def classify(texts):
        out = []
        for t in texts:
            t = t.lower()
            pos = 0.9 if ('beats' in t or 'surge' in t) else 0.05
            neg = 0.9 if ('falls' in t or 'cut' in t) else 0.05
            out.append({'positive': pos, 'negative': neg, 'neutral': max(0.0, 1 - pos - neg)})
        return out
    return classify


def _exists(ticker):
    ex, sym = ticker.split(':', 1)
    if 'NOTREAL' in sym:
        return False
    if ex == 'NASDAQ' and sym in _NYSE:
        return False
    return not (ex in ('NYSE', 'AMEX') and sym not in _NYSE)


def fake_tv(screener, interval, symbols, **_):
    with _fake_lock:
        FAKE['calls'] += 1
        FAKE['intervals'] = FAKE.get('intervals', []) + [interval]
        if FAKE['down'] or FAKE['fail_next'] > 0:
            FAKE['fail_next'] = max(0, FAKE['fail_next'] - 1)
            raise json.JSONDecodeError('Expecting value', '', 0)
    return {t: (FakeAnalysis(t) if _exists(t) else None) for t in symbols}


# ------------------------------------------------------------------ tiny test framework
RESULTS = []


def test(name):
    def deco(fn):
        try:
            fn()
            RESULTS.append(('PASS', name, ''))
        except Exception as e:
            RESULTS.append(('FAIL', name, f'{type(e).__name__}: {e}'))
        return fn
    return deco


def main():
    ensure_packages()
    tmp = tempfile.mkdtemp(prefix='tvbot_test_')
    t0 = time.time()
    try:
        run_all(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    width = max(len(n) for _, n, _ in RESULTS)
    lines = [f'  [{s}]  {n.ljust(width)}' + (f'\n           -> {d}' if d else '') for s, n, d in RESULTS]
    passed = sum(s == 'PASS' for s, _, _ in RESULTS)
    ok = passed == len(RESULTS)
    report = '\n'.join(lines) + (f'\n\n{passed}/{len(RESULTS)} tests passed in {time.time() - t0:.0f}s - '
                                 + ('ALL GOOD, the app is ready to use.' if ok else 'SOME TESTS FAILED, see above.'))
    print('TradingView Analysis Bot - full test run')
    print('Fake TradingView, temporary portfolio (your real portfolio is not touched).\n')
    print(report)
    with open(REPORT, 'w', encoding='utf-8') as f:
        f.write(time.strftime('%Y-%m-%d %H:%M:%S') + '\n' + report + '\n')
    print(f'\n(Report saved to {os.path.relpath(REPORT, ROOT)})')
    return 0 if ok else 1


def run_all(tmp):
    import settings as S
    import tvbot_core as core

    import tradingview_ta
    S.PAUSE_BETWEEN_REQUESTS = 0
    S.PORTFOLIO_FILE = os.path.join(tmp, 'portfolio.json')
    tradingview_ta.get_multiple_analysis = fake_tv    # also covers tvbot_core being reloaded during the tests
    core.tv_get = fake_tv
    core.tv_scan = fake_scan
    import tvbot_news as news                          # news: fake headlines and a fake FinBERT (offline, no download)
    news.http_get = fake_news_get
    news.make_pipeline = fake_finbert
    news.PAUSE_SECONDS = 0
    core.AUTO_TICK = 0.05                              # background refresher checks often, so tests are quick
    real_sleep = core._sleep

    # ============================== Part 1: logic ==============================
    pf = core.Portfolio()
    store = core.MarketStore(pf)

    @test('Startup health check passes')
    def _():
        fails = [c for c in core.health_check(pf) if c[0] == 'fail']
        assert not fails, fails

    @test('Every market loads, every symbol rated on 26 metrics, sorted best first')
    def _():
        assert store.refresh_all(), store.errors
        for mk in S.RUN_MARKETS:
            df = store.state[mk]['df']
            assert len(df) == len(S.MARKETS[mk]['watchlist']), mk
            assert (df['Metrics'] == 26).all() and (df['Buy'] + df['Neutral'] + df['Sell'] == 26).all()
            assert df['Score'].tolist() == sorted(df['Score'], reverse=True)

    @test('Symbol conversion and currency detection')
    def _():
        assert core.to_ticker('Crypto', 'btc') == 'BINANCE:BTCUSDT'
        assert core.to_ticker('Crypto', 'ETHBTC') == 'BINANCE:ETHBTC'
        assert core.to_ticker('US Stocks', 'nyse:jpm') == 'NYSE:JPM'
        assert core.to_ticker('Forex', 'nzd/usd') == 'FX_IDC:NZDUSD'
        assert core.quote_ccy('Crypto', 'BINANCE:ETHBTC') == 'BTC'
        assert core.quote_ccy('Forex', 'FX_IDC:EURJPY') == 'JPY'
        assert core.quote_ccy('US Stocks', 'NASDAQ:AAPL') == 'USD'

    @test('ATR status levels (Normal / Watch / Warning / Breached) and the recommendation matrix')
    def _():
        # stop 100, ATR 10: more than 1 ATR above = NORMAL, within 1 = WATCH, within 0.5 = WARNING, at/below = BREACHED
        assert [core.atr_status(p, 100, 10) for p in (110.01, 110, 105.01, 105, 100.01, 100, 90)] == \
            ['NORMAL', 'WATCH', 'WATCH', 'WARNING', 'WARNING', 'BREACHED', 'BREACHED']
        assert core.atr_status(235, 225, 8) == 'NORMAL'               # the +17.5% profit-protection example
        want = {'Strong Buy': ['HOLD', 'HOLD', 'HOLD / WATCH', 'REVIEW EXIT'],
                'Neutral': ['HOLD', 'HOLD / WATCH', 'REVIEW EXIT', 'EXIT WARNING'],
                'Sell': ['HOLD / WATCH', 'REVIEW EXIT', 'EXIT WARNING', 'STRONG EXIT WARNING'],
                'Strong Sell': ['REVIEW EXIT', 'EXIT WARNING', 'STRONG EXIT WARNING', 'STRONG EXIT WARNING']}
        for rating, recs in want.items():
            assert [core.recommend(rating, s) for s in core.ATR_STATUSES] == recs, rating
        assert core.RISK_MATRIX['Buy'] == core.RISK_MATRIX['Strong Buy']

    @test('Trailing ATR level: starts at entry - 2 ATR, follows the highest close up, never moves down, is saved')
    def _():
        class D:
            def __init__(self, prev_close, atr):
                self.indicators = {'close[1]': prev_close, 'ATR': atr, 'SMA200': 100.0, 'SMA200[1]': 100.0}
        path = os.path.join(tmp, 'risk.json')
        p = core.Portfolio(path)
        p.holdings.append({'id': 'old', 'market': 'US Stocks', 'ticker': 'NASDAQ:NVDA', 'buy_price': 200.0,
                           'qty': 2.0, 'added': '2000-01-01 00:00'})
        stops = []
        for prev, atr in [(200, 7), (230, 8), (220, 10), (240, 8)]:
            p.update_risk('US Stocks', {'NASDAQ:NVDA': D(prev, atr)})
            stops.append(p.holdings[0]['atr_stop'])
        assert stops == [186, 214, 214, 224], stops                  # 220 - 2x10 = 200 would be lower: ignored
        again = core.Portfolio(path).holdings[0]
        assert (again['atr_stop'], again['high_close'], again['initial_stop']) == (224, 240, 186), again
        # A holding added today ignores yesterday's close (it may be from before you bought)
        p.holdings.append({'id': 'new', 'market': 'US Stocks', 'ticker': 'NASDAQ:AMD', 'buy_price': 100.0,
                           'qty': 1.0, 'added': core._utc_now().strftime('%Y-%m-%d %H:%M')})
        p.update_risk('US Stocks', {'NASDAQ:AMD': D(150, 5)})
        assert (p.holdings[1]['high_close'], p.holdings[1]['atr_stop']) == (100, 90), p.holdings[1]
        assert not p.update_risk('US Stocks', {'NASDAQ:AMD': D(150, 5)}), 'nothing changed, so nothing to save'

    @test('Add holdings (crypto shorthand, NYSE found without prefix)')
    def _():
        ok, msg = pf.add('Crypto', 'btc', 60000, 0.5, store)
        assert ok and 'BINANCE:BTCUSDT' in msg, msg
        ok, msg = pf.add('US Stocks', 'jpm', 300, 5, store)
        assert ok and 'NYSE:JPM' in msg, msg

    @test('Unknown symbols and bad inputs are rejected and not saved')
    def _():
        n = len(pf.holdings)
        ok, msg = pf.add('Crypto', 'NOTREALCOIN', 1, 1, store)
        assert not ok and 'not found' in msg, msg
        for args in [('Crypto', '', 1, 1), ('Crypto', 'eth', 0, 1), ('Crypto', 'eth', 1, -2), ('Crypto', 'eth', None, 1)]:
            ok, msg = pf.add(*args, store)
            assert not ok and 'Enter a symbol' in msg, (args, msg)
        assert len(pf.holdings) == n

    def held(t):
        return [h for h in pf.holdings if h['ticker'] == t]

    @test('Plain words: forex pairs explained; the five warnings grouped into three')
    def _():
        assert core.pair_meaning('FX_IDC:NZDUSD', 'Buy') == \
            'NZ dollar vs US dollar: the NZ dollar is getting stronger against the US dollar'
        assert core.pair_meaning('FX_IDC:USDJPY', 'Strong Sell').endswith('getting weaker against the Japanese yen')
        assert core.pair_meaning('FX_IDC:EURGBP') == 'euro vs British pound'
        assert set(core.PLAIN_REC.values()) == set(core.PLAIN_REC_ORDER)
        assert core.PLAIN_REC['REVIEW EXIT'] == core.PLAIN_REC['STRONG EXIT WARNING'] == 'Think about selling'
        assert set(core.PLAIN_ATR) == set(core.ATR_STATUSES)

    @test('Holdings show price, profit/loss, ATR risk level and a recommendation')
    def _():
        tbl = core.portfolio_table(pf, store)
        row = tbl[tbl['Symbol'] == 'BTCUSDT'].iloc[0]
        assert row['Now'] == 70000.0 and abs(row['P/L'] - 5000) < 1e-6 and abs(row['P/L %'] - 16.6666667) < 1e-4
        # fake ATR = 2% of 70000 = 1400; bought at 60000 today -> level 60000 - 2 x 1400 = 57200
        assert row['ATR'] == 1400 and row['Trailing level'] == 57200 and row['Initial level'] == 57200
        assert row['ATR status'] == 'NORMAL' and row['Recommendation'] in core.RECOMMENDATIONS
        assert abs(row['At risk'] - (70000 - 57200) * 0.5) < 1e-6 and 'your safety level' in row['Reason']
        assert row['Market'] == 'Crypto' and core.PLAIN_REC[row['Recommendation']] in core.PLAIN_REC_ORDER
        for _, r in tbl.iterrows():
            has_score = r['Opp. score'] is not None and r['Opp. score'] == r['Opp. score']   # (NaN != NaN)
            assert (r['Rating'] == 'Strong Buy') == has_score, 'score for Strong Buy only'

    @test('Totals in NZ dollars: every currency converted with prices already loaded')
    def _():
        class A:
            def __init__(self, c): self.indicators = {'close': c}

        class Store:
            interval = '1d'
            _data = {'1d': {'Forex': {'raw': {'FX_IDC:NZDUSD': A(0.5), 'FX_IDC:EURUSD': A(1.2),
                                              'FX_IDC:GBPNZD': A(2.1)}, 'time': core.dt.datetime.now()},
                            'Crypto': {'raw': {'BINANCE:BTCUSDT': A(50000.0), 'BINANCE:NOPE': None},
                                       'time': core.dt.datetime.now()}}}
        rates, as_of, used = core.nzd_rates(Store)
        assert used == 'NZDUSD' and as_of is not None
        assert rates['NZD'] == 1 and rates['USD'] == rates['USDT'] == 2.0      # 1 USD = 1/0.5 NZD
        assert rates['EUR'] == 2.4 and rates['GBP'] == 2.1 and rates['BTC'] == 100000.0
        summary = core.pd.DataFrame([
            {'Ccy': 'USD', 'Value held': 100.0, 'Realised': 10.0, 'Unrealised': 20.0, 'Total': 30.0},
            {'Ccy': 'NZD', 'Value held': 50.0, 'Realised': 0.0, 'Unrealised': -5.0, 'Total': -5.0},
            {'Ccy': 'XYZ', 'Value held': 1.0, 'Realised': 0.0, 'Unrealised': 0.0, 'Total': 0.0}])
        tot, missing = core.nzd_totals(summary, rates)
        assert tot == {'Value held': 250.0, 'Realised': 20.0, 'Unrealised': 35.0, 'Total': 55.0} and missing == ['XYZ']
        Store._data = {'1d': {}}
        assert core.nzd_rates(Store) == ({'NZD': 1.0}, None, None), 'no NZDUSD loaded: nothing converted'
        Store._data = {'1d': {'Forex': {'raw': {'FX_IDC:NZDUSD': A(523.0)}, 'time': core.dt.datetime.now()}}}
        assert core.nzd_rates(Store)[0] == {'NZD': 1.0}, 'an unbelievable rate is not used'

    @test('Sell part of a holding at a chosen price')
    def _():
        h = held('NYSE:JPM')[0]
        ok, msg = pf.sell(h['id'], 2, 350)
        assert ok and abs(pf.realised[-1]['pl'] - 100) < 1e-6 and h['qty'] == 3, msg

    @test('Cannot sell more than you hold, or zero')
    def _():
        h = held('NYSE:JPM')[0]
        n = len(pf.realised)
        assert not pf.sell(h['id'], 10, 350)[0] and not pf.sell(h['id'], 0)[0]
        assert len(pf.realised) == n and h['qty'] == 3

    @test('Sell everything at the current market price')
    def _():
        h = held('NYSE:JPM')[0]
        ok, msg = pf.sell(h['id'], h['qty'], 0, store.current_price(h))
        assert ok and not held('NYSE:JPM'), msg
        assert pf.realised[-1]['sell_price'] == 320.0 and abs(pf.realised[-1]['pl'] - 60) < 1e-6

    @test('Delete removes a holding without recording profit/loss')
    def _():
        pf.add('Crypto', 'eth', 2000, 1, store)
        n = len(pf.realised)
        ok, _ = pf.delete(held('BINANCE:ETHUSDT')[0]['id'])
        assert ok and not held('BINANCE:ETHUSDT') and len(pf.realised) == n

    @test('Total profit/loss adds up (realised + unrealised, per currency)')
    def _():
        s = core.pl_summary(pf, core.portfolio_table(pf, store)).set_index('Ccy')
        assert abs(s.loc['USD', 'Realised'] - 160) < 1e-6
        assert abs(s.loc['USDT', 'Unrealised'] - 5000) < 1e-6
        assert len(core.sales_table(pf)) == 2

    @test('Everything is saved, reloads correctly, and a .bak backup is kept')
    def _():
        again = core.Portfolio()
        assert [(h['ticker'], h['qty']) for h in again.holdings] == [(h['ticker'], h['qty']) for h in pf.holdings]
        assert len(again.realised) == 2 and abs(sum(t['pl'] for t in again.realised) - 160) < 1e-6
        json.load(open(S.PORTFOLIO_FILE + '.bak', encoding='utf-8'))

    @test('Reset P/L clears sales but keeps holdings')
    def _():
        pf.reset_pl()
        again = core.Portfolio()
        assert not again.realised and again.meta.get('pl_since') and again.holdings

    def load_file(content):
        p = os.path.join(tmp, 'other.json')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(content)
        return core.Portfolio(p)

    @test('Old portfolio format still loads')
    def _():
        p = load_file('[{"id":"a","market":"US Stocks","ticker":"NASDAQ:AAPL","buy_price":10,"qty":2}]')
        assert len(p.holdings) == 1 and not p.warnings

    @test('Damaged portfolio file is backed up and the app still starts')
    def _():
        p = load_file('{this is not valid json')
        assert p.holdings == [] and p.warnings and any('.broken-' in f for f in os.listdir(tmp))

    @test('Damaged entries are skipped, good ones kept, original backed up')
    def _():
        p = load_file(json.dumps({'holdings': [
            {'market': 'Crypto', 'ticker': 'BINANCE:BTCUSDT', 'buy_price': 1, 'qty': 1},
            {'market': 'Crypto', 'ticker': 'BINANCE:ETHUSDT', 'buy_price': -5, 'qty': 1},
            {'market': 'Crypto', 'ticker': 'BINANCE:SOLUSDT', 'qty': 'lots'}]}))
        assert [h['ticker'] for h in p.holdings] == ['BINANCE:BTCUSDT'] and 'skipped' in p.warnings[0]

    def end_cooldown():                     # pretend the cool-down time has passed
        core.RATE_LIMIT['until'] = 0.0

    def reset_rate_limit():
        core.RATE_LIMIT['until'], core.RATE_LIMIT['strikes'] = 0.0, 0

    @test('Rate-limit: one refusal pauses ALL requests (nothing is sent during the cool-down)')
    def _():
        reset_rate_limit()
        try:
            FAKE['fail_next'] = 1
            before = FAKE['calls']
            for mk in S.RUN_MARKETS:               # every market, plus a second round
                store.refresh(mk)
            for mk in S.RUN_MARKETS:
                store.refresh(mk)
            assert FAKE['calls'] - before == 1, f'{FAKE["calls"] - before} requests sent - should stop after the refusal'
            assert 55 <= core.rate_limit_wait() <= 60, core.rate_limit_wait()
            assert all('try again' in store.errors[mk] for mk in S.RUN_MARKETS)
        finally:
            reset_rate_limit()

    @test('Rate-limit: repeated refusals make the cool-down longer (1, 2, 5, 10, 15 minutes)')
    def _():
        reset_rate_limit()
        FAKE['down'] = True
        try:
            waits = []
            for _ in range(6):
                try:
                    core.fetch('crypto', S.INTERVAL, ['BINANCE:BTCUSDT'])
                except core.RateLimited:
                    pass
                waits.append(core.rate_limit_wait())
                end_cooldown()
            assert [round(w / 60) for w in waits] == [1, 2, 5, 10, 15, 15], waits
        finally:
            FAKE['down'] = False
            reset_rate_limit()

    @test('Rate-limit: old data kept during the cool-down; recovers by itself afterwards')
    def _():
        reset_rate_limit()
        old = store.state['Crypto']['df'].copy()
        FAKE['fail_next'] = 1
        try:
            assert not store.refresh('Crypto') and 'rate-limiting' in store.errors['Crypto']
            assert store.state['Crypto']['df'].equals(old), 'last good data must stay on screen'
            end_cooldown()
            assert store.refresh('Crypto') and 'Crypto' not in store.errors
            assert core.RATE_LIMIT['strikes'] == 0 and core.rate_limit_wait() == 0, 'success resets the cool-down'
        finally:
            reset_rate_limit()

    @test('Rate-limit: the background refresher waits out the cool-down, then catches up')
    def _():
        reset_rate_limit()
        s2 = core.MarketStore(pf)
        core.RATE_LIMIT['until'] = time.time() + 1.5      # a short cool-down is already running
        before = FAKE['calls']
        s2.start()
        try:
            time.sleep(0.5)
            assert FAKE['calls'] == before, 'nothing may be sent during the cool-down'
            assert s2.wait_ready(10), 'should catch up once the cool-down ends'
        finally:
            s2.stop()
            reset_rate_limit()

    @test('Adding a holding while TradingView is busy still saves it; the next refresh confirms it')
    def _():
        reset_rate_limit()
        core.RATE_LIMIT['until'] = time.time() + 60          # a cool-down is running
        try:
            before = FAKE['calls']
            ok, msg = pf.add('US Stocks', 'xom', 100, 3, store)
            assert ok and 'busy' in msg and 'Saved XOM' in msg, msg
            assert FAKE['calls'] == before, 'nothing may be sent during the cool-down'
            h = pf.holdings[-1]
            assert h['pending'] and h['candidates'] == ['NASDAQ:XOM', 'NYSE:XOM', 'AMEX:XOM'], h
            assert core.Portfolio().holdings[-1]['pending'], 'it must be saved to the file'
            row = core.portfolio_table(pf, store).iloc[-1]
            assert row['Recommendation'] == 'Checking...' and 'busy' in row['Reason']
        finally:
            reset_rate_limit()
        try:
            assert store.refresh('US Stocks')                   # the normal refresh, once the cool-down is over
            assert h['ticker'] == 'NYSE:XOM' and 'pending' not in h and 'candidates' not in h, h
            assert h.get('atr_stop'), 'risk level is set once confirmed'
            saved = next(x for x in core.Portfolio().holdings if x['id'] == h['id'])
            assert saved['ticker'] == 'NYSE:XOM' and 'pending' not in saved
            row = core.portfolio_table(pf, store).set_index('id').loc[h['id']]
            assert row['Now'] is not None and row['Recommendation'] in core.RECOMMENDATIONS
        finally:
            pf.delete(h['id'])

    @test('A holding saved while busy that turns out not to exist is flagged "Not found"')
    def _():
        reset_rate_limit()
        core.RATE_LIMIT['until'] = time.time() + 60
        try:
            ok, _ = pf.add('Crypto', 'NOTREALCOIN', 1, 1, store)
            h = pf.holdings[-1]
            assert ok and h['pending']
        finally:
            reset_rate_limit()
        try:
            store.refresh('Crypto')
            assert h.get('not_found') and h['pending']
            row = core.portfolio_table(pf, store).set_index('id').loc[h['id']]
            assert row['Recommendation'] == 'Not found' and 'delete this holding' in row['Reason']
        finally:
            pf.delete(h['id'])

    @test('A holding added before its market has loaded still shows its price')
    def _():
        s2 = core.MarketStore(pf)                             # nothing loaded yet (e.g. busy at start-up)
        ok, _ = pf.add('Crypto', 'sol', 100, 1, s2)
        h = pf.holdings[-1]
        try:
            assert ok and s2.analysis('BINANCE:SOLUSDT') is not None
            row = core.portfolio_table(pf, s2).set_index('id').loc[h['id']]
            assert row['Now'] == 150.0 and row['Recommendation'] in core.RECOMMENDATIONS, row
        finally:
            pf.delete(h['id'])

    @test('Many things at once: refreshes and adds in parallel')
    def _():
        n = len(pf.holdings)
        ts = [threading.Thread(target=store.refresh, args=(mk,)) for mk in S.RUN_MARKETS * 3]
        ts += [threading.Thread(target=pf.add, args=('Crypto', 'sol', 100, 1, store)) for _ in range(5)]
        for t in ts: t.start()
        for t in ts: t.join(30)
        assert len(held('BINANCE:SOLUSDT')) == 5 and len(core.Portfolio().holdings) == n + 5

    @test('Auto-refresh is OFF for every market by default; data still loads once at start-up')
    def _():
        assert list(core.AUTO_CHOICES) == ['1 min', '5 min', '15 min', '30 min', '1 hour', '4 hours']
        assert list(core.AUTO_CHOICES.values()) == [1, 5, 15, 30, 60, 240]
        s2 = core.MarketStore(pf)
        assert all(not s2.auto[mk]['on'] for mk in S.RUN_MARKETS)
        s2.start()
        try:
            assert s2.wait_ready(20), 'everything loads once at start-up'
            times = {mk: s2.state[mk]['time'] for mk in S.RUN_MARKETS}
            before = FAKE['calls']
            time.sleep(0.6)                                  # many background checks go by...
            assert FAKE['calls'] == before, 'nothing is re-fetched while auto-refresh is off'
            assert all(s2.state[mk]['time'] == times[mk] for mk in S.RUN_MARKETS)
            assert all(s2.next_auto(mk) is None for mk in S.RUN_MARKETS)
        finally:
            s2.stop()
        assert s2._stop.is_set()

    @test('Auto-refresh: each market refreshes on its own interval, only when switched on')
    def _():
        s2 = core.MarketStore(pf)
        s2.refresh_all()
        saved = core.RETRY_SECONDS
        core.RETRY_SECONDS = 0.1
        try:
            s2.set_auto('Crypto', on=True, minutes=0.01)     # 0.6 seconds, so the test is quick
            s2.set_auto('Forex', on=False, minutes=1)
            first = {mk: s2.state[mk]['time'] for mk in S.RUN_MARKETS}
            assert s2.next_auto('Crypto') is not None and s2.next_auto('Forex') is None
            s2.start()
            end = time.time() + 10
            while s2.state['Crypto']['time'] == first['Crypto'] and time.time() < end:
                time.sleep(0.05)
            assert s2.state['Crypto']['time'] > first['Crypto'], 'Crypto (on) should have refreshed by itself'
            assert all(s2.state[mk]['time'] == first[mk] for mk in S.RUN_MARKETS if mk != 'Crypto'), \
                'markets with auto-refresh off must not refresh'
            s2.set_auto('Crypto', on=False)
            time.sleep(0.3)
            t = s2.state['Crypto']['time']
            time.sleep(1.0)
            assert s2.state['Crypto']['time'] == t, 'switching it off stops it'
        finally:
            s2.stop()
            core.RETRY_SECONDS = saved

    @test('Auto-refresh: a market that keeps failing is not retried more than once a minute')
    def _():
        s2 = core.MarketStore(pf)
        real_analyse = core.analyse
        tries = []

        def failing(mk, interval=None, extra=()):
            if mk == 'Forex':
                tries.append(time.time())
                raise ConnectionError('network down')
            return real_analyse(mk, interval=interval, extra=extra)
        core.analyse = failing
        s2.start()
        try:
            time.sleep(1.0)                                  # ~20 background checks
            assert len(tries) == 1, f'{len(tries)} attempts - should wait {core.RETRY_SECONDS}s between tries'
            assert 'network down' in s2.errors['Forex'] and 'Crypto' in s2.state
        finally:
            s2.stop()
            core.analyse = real_analyse

    @test('Changing the timeframe reloads every market on the new chart')
    def _():
        assert list(core.DASH_TIMEFRAMES) == ['1 Hour', '4 Hours', '1 Day', '1 Week', '4 Weeks']
        assert core.timeframe_label(S.INTERVAL) == '1 Day'
        try:
            assert store.set_interval(core.DASH_TIMEFRAMES['1 Week']) and store.state == {}
            FAKE['intervals'] = []
            assert store.refresh_all() and store.ready()
            assert set(FAKE['intervals']) == {'1W'}, FAKE['intervals']
            assert not store.set_interval(core.DASH_TIMEFRAMES['1 Week'])     # same choice again: no reload
            FAKE['intervals'] = []
            pf.add('Crypto', 'sol', 100, 1, store)                             # new holdings use it too
            assert FAKE['intervals'] == ['1W'], FAKE['intervals']
            pf.delete(held('BINANCE:SOLUSDT')[-1]['id'])
        finally:
            store.set_interval(S.INTERVAL)
            store.refresh_all()

    @test('Ratings that finish loading after a timeframe change are filed under their own timeframe')
    def _():
        s2 = core.MarketStore(pf)
        real_analyse = core.analyse

        def slow_analyse(mk, interval=None, extra=()):
            s2.set_interval(core.DASH_TIMEFRAMES['1 Hour'])                  # user changes it mid-load
            return real_analyse(mk, interval=interval, extra=extra)
        core.analyse = slow_analyse
        try:
            s2.refresh('Crypto')
            assert 'Crypto' not in s2.state, 'old-timeframe ratings must not show under the new timeframe'
            assert 'Crypto' in s2._data[S.INTERVAL], 'they should be remembered for their own timeframe'
        finally:
            core.analyse = real_analyse

    @test('Switching back to a recently loaded timeframe is instant (no requests)')
    def _():
        s2 = core.MarketStore(pf)
        s2.refresh_all()
        s2.set_interval(core.DASH_TIMEFRAMES['4 Hours'])
        s2.refresh_stale(background=False)
        before = FAKE['calls']
        s2.set_interval(S.INTERVAL)
        assert s2.refresh_stale(background=False) == [] and FAKE['calls'] == before
        assert s2.ready(), 'remembered ratings should show straight away'

    @test('Risk levels always use the daily chart, even when another timeframe is selected')
    def _():
        s2 = core.MarketStore(pf)
        s2.set_interval(core.DASH_TIMEFRAMES['4 Hours'])
        FAKE['intervals'] = []
        s2.refresh_stale(background=False)
        held_markets = {h['market'] for h in pf.holdings}
        assert held_markets and set(s2.risk_stale()) == set(), 'daily data for holdings should now be loaded'
        assert FAKE['intervals'].count('1d') == len(held_markets), FAKE['intervals']   # only markets you hold
        tbl = core.portfolio_table(pf, s2)
        assert tbl['ATR status'].isin(core.ATR_STATUSES).all(), tbl[['Symbol', 'ATR status', 'Reason']]

    @test('The same market is never fetched twice at the same time')
    def _():
        s2 = core.MarketStore(pf)
        real_analyse = core.analyse

        def slow_analyse(*a, **k):
            time.sleep(0.3)
            return real_analyse(*a, **k)
        core.analyse = slow_analyse
        try:
            before = FAKE['calls']
            ts = [threading.Thread(target=s2.refresh, args=('Forex',)) for _ in range(4)]
            for t in ts: t.start()
            for t in ts: t.join(10)
            assert FAKE['calls'] - before == 1, FAKE['calls'] - before
            assert 'Forex' in s2.state
        finally:
            core.analyse = real_analyse

    @test('Top picks: 10 most bullish and 10 most bearish')
    def _():
        bull, bear = core.top_picks(store)
        assert len(bull) == len(bear) == 10 and bull['Score'].iloc[0] >= bear['Score'].iloc[0]

    @test('Opportunity score: each part follows its scoring table')
    def _():
        nvda = {'close': 110, 'SMA20': 105, 'SMA50': 100, 'SMA200': 90, 'SMA50[1]': 99, 'SMA200[1]': 89}
        assert core.pts_trend(nvda) == 20
        assert core.pts_trend({**nvda, 'SMA50[1]': 101, 'SMA200[1]': 91, 'SMA20': 99}) == 13
        assert core.pts_indicators({'Recommend.All': 0.74}) == 22.2 and core.pts_indicators({'Recommend.All': -0.5}) == 0
        assert [core.pts_relative(x) for x in (18, 12, 6, 2, -1)] == [15, 13, 10, 7, 0]
        assert [core.pts_volume(x) for x in (0.75, 0.9, 1.1, 1.3, 1.8)] == [0, 2, 4, 7, 10]
        assert [core.pts_risk({'close': 100, 'ATR': a}) for a in (2.1, 4.8, 6.7, 9)] == [5, 4, 2, 0]
        assert [core.pts_entry(e) for e in (2, 5, 8, 11, 12.4, -1)] == [5, 4, 2, 1, 0, 3]
        mom = {'RSI': 60, 'MACD.hist': 2, 'MACD.hist[1]': 1, 'ROC': 1, 'ADX': 30, 'ADX+DI': 25, 'ADX-DI': 10}
        assert core.pts_momentum(mom) == 10
        assert core.pts_momentum({**mom, 'RSI': 85}) == 5, 'RSI over 80 should cost 2 instead of earning 3'
        assert core.pts_momentum({**mom, 'ADX+DI': 5}) == 8, 'a strong DOWNtrend should not earn ADX points'

    @test('Opportunity score: totals, bands and rescaling when parts are missing')
    def _():
        full = {'Indicators': 25, 'Trend': 19, 'Rel. strength': 14, 'Momentum': 10, 'Volume': 9, 'Regime': 5,
                'Risk': 4, 'Entry': 5}
        assert core.composite(full) == 91 and core.band(91) == 'Exceptional'
        m = S.ENTRY_MIN_SCORE                       # bands follow the setting
        assert [core.band(s) for s in (84, m, m - 1, m - 10, m - 11)] == \
            ['Very strong', 'Qualifies', 'Watchlist', 'Watchlist', 'Ignore']
        fx = {**full, 'Volume': None, 'Rel. strength': None, 'Regime': None}   # forex: 70 points available
        assert core.composite(fx) == round((25 + 19 + 10 + 4 + 5) / 70 * 100, 1)
        assert core.composite(dict.fromkeys(full)) is None

    @test('Opportunity score: entry rules come before the score (a Neutral 88 does not qualify)')
    def _():
        ind = {'close': 110, 'SMA200': 90, 'average_volume_30d_calc': 1e6}
        assert core.entry_check('Strong Buy', 88, ind, 'US Stocks', '1d', 4, 'Bullish') == []
        assert core.entry_check('Neutral', 88, ind, 'US Stocks', '1d', 4, 'Bullish') == \
            ['Not Strong Buy: TradingView rates it Neutral']
        assert core.entry_check('Strong Buy', 80, ind, 'US Stocks', '1d', 4, 'Bearish') == \
            ['Score too low: 80.0, needs 85 because its market is bearish']
        assert core.entry_check('Strong Buy', 66.2, ind, 'US Stocks', '1d', 4, 'Bullish') == \
            [f'Score too low: 66.2, needs {S.ENTRY_MIN_SCORE}']
        assert core.entry_check('Strong Buy', 88, {**ind, 'close': 85}, 'US Stocks', '1d', 4, 'Bullish') == \
            ['Below 200-day average: price is 5.6% under it (long-term downtrend)']
        assert core.entry_check('Strong Buy', 88, ind, 'US Stocks', '1d', 15, 'Bullish') == \
            ["Price too stretched: 15% above its 20-day average, the limit is 12% (don't chase)"]
        assert core.entry_check('Strong Buy', 88, {**ind, 'average_volume_30d_calc': 1000}, 'US Stocks', '1d', 4,
                                'Bullish') == ['Too little trading: about 110K USD a day, needs 2.0M']
        assert core.entry_check('Strong Buy', 88, {'close': 110, 'SMA200': 90}, 'US Stocks', '1d', 4, 'Bullish') == \
            ['Too little trading: no volume figures from TradingView']
        assert core.entry_check('Strong Buy', 88, {**ind, 'average_volume_30d_calc': 1.98e6 / 110}, 'US Stocks', '1d', 4,
                                'Bullish') == ['Too little trading: about 1.98M USD a day, needs 2.0M'], 'not "2.0M, needs 2.0M"'
        two = core.entry_check('Strong Buy', 66.2, ind, 'US Stocks', '1d', 15, 'Bullish')
        assert core.why_labels(core.WHY_SEP.join(two)) == ['Score too low', 'Price too stretched'], two
        assert core.why_labels('') == []

    @test('Opportunity score: suggested amount by score, capped at 50% without a clear lead')
    def _():
        m = S.ENTRY_MIN_SCORE
        assert [core.allocation(s, None) for s in (m - 1, m, 84, 91)] == [0, 0.5, 0.75, 1.0]
        assert core.allocation(91, 12) == 1.0 and core.allocation(91, 1) == 0.5 and core.allocation(81, 1) == 0.5

    @test('Opportunity score: market regime, volume timing and misaligned-data guard')
    def _():
        class A:
            def __init__(self, c, s50, s200): self.indicators = {'close': c, 'SMA50': s50, 'SMA200': s200}
        spy, qqq = 'AMEX:SPY', 'NASDAQ:QQQ'
        assert core.market_regime('US Stocks', {spy: A(110, 100, 90), qqq: A(110, 100, 90)}) == (5, 'Strong bull')
        assert core.market_regime('US Stocks', {spy: A(95, 100, 90), qqq: A(110, 100, 90)}) == (4, 'Bullish')
        assert core.market_regime('US Stocks', {spy: A(85, 100, 90), qqq: A(110, 100, 90)}) == (2, 'Mixed')
        assert core.market_regime('US Stocks', {spy: A(80, 85, 90), qqq: A(80, 100, 90)}) == (0, 'Bearish')
        assert core.market_regime('Forex', {}) == (None, 'n/a')
        import datetime as dt
        utc = dt.timezone.utc
        assert abs(core.bar_progress('1d', dt.datetime(2026, 11, 11, 6, tzinfo=utc)) - 0.25) < 1e-9
        assert abs(core.bar_progress('1W', dt.datetime(2026, 11, 9, 12, tzinfo=utc)) - 1 / 14) < 1e-9   # a Monday
        vol = {'volume': 500, 'average_volume_10d_calc': 1000, 'average_volume_30d_calc': 1000}
        assert abs(core.volume_ratio('Crypto', vol, '1d', dt.datetime(2026, 11, 11, 12, tzinfo=utc)) - 1.0) < 1e-9
        assert core.volume_ratio('Crypto', vol, '1d', dt.datetime(2026, 11, 11, 1, tzinfo=utc)) is None
        assert core.volume_ratio('Forex', vol, '1d', dt.datetime(2026, 11, 11, 12, tzinfo=utc)) is None
        # US shares while trading: half-way through the session (12:45 New York, a Wednesday) half a day's volume
        # is a normal day; after the close the bar is complete; in the first 15% of the session it's too early
        assert abs(core.session_progress('US Stocks', dt.datetime(2026, 11, 11, 17, 45, tzinfo=utc)) - 0.5) < 1e-9
        assert abs(core.volume_ratio('US Stocks', vol, '1d', dt.datetime(2026, 11, 11, 17, 45, tzinfo=utc)) - 1.0) < 1e-9
        assert abs(core.volume_ratio('US Stocks', vol, '1d', dt.datetime(2026, 11, 11, 22, tzinfo=utc)) - 0.5) < 1e-9
        assert core.volume_ratio('US Stocks', vol, '1d', dt.datetime(2026, 11, 11, 14, 40, tzinfo=utc)) is None
        assert core.session_progress('US Stocks', dt.datetime(2026, 11, 14, 17, 45, tzinfo=utc)) is None, 'Saturday'
        assert abs(core.volume_ratio('NZ Stocks', vol, '1d', dt.datetime(2026, 11, 11, 0, 22, 30, tzinfo=utc))
                   - 1.0) < 1e-9, 'NZX half-way (13:22:30 Auckland)'
        assert not core.extras_ok({'SMA200': 100.0}) and not core.extras_ok({'SMA200': 100.0, 'SMA200[1]': 3.2})
        assert core.extras_ok({'SMA200': 100.0, 'SMA200[1]': 99.9})
        assert core.EXTRA_FIELDS[-1] == 'SMA200[1]' and not set(core.EXTRA_FIELDS) & set(tradingview_ta.TradingView.indicators)

    @test('Opportunity score: only Strong Buy symbols are scored; best pick passes every rule')
    def _():
        opp, best, regimes = core.opportunities(store)
        strong = sum((store.state[m]['df']['Rating'] == 'Strong Buy').sum() for m in S.RUN_MARKETS)
        assert len(opp) == strong > 0 and (opp['Rating'] == 'Strong Buy').all()
        assert 'SPY' not in set(opp['Symbol']), 'benchmarks are not candidates'
        scores = opp['Score'].dropna().tolist()
        assert scores == sorted(scores, reverse=True)
        assert set(regimes) == set(S.RUN_MARKETS) and regimes['Forex'] == (None, 'n/a')
        assert best is not None, 'the fake data includes Strong Buy symbols that should qualify'
        w = opp[opp['Symbol'] == best['Symbol']].iloc[0]
        assert w['Status'] == 'QUALIFIED' and w['Rating'] == 'Strong Buy' and w['Score'] >= S.ENTRY_MIN_SCORE
        assert best['Pct'] in (0.5, 0.75, 1.0) and 'Amount' not in best and not hasattr(S, 'BUDGET')

    @test('Early score: a fresh turn outscores a mature, stretched run')
    def _():
        fresh = {'close': 102, 'close[1]': 99, 'SMA20': 100, 'SMA20[1]': 100.2, 'SMA50': 99.5, 'SMA50[1]': 100.5,
                 'MACD.macd': -0.2, 'MACD.signal': -0.4, 'MACD.hist': 0.2, 'MACD.hist[1]': -0.1, 'RSI': 55, 'RSI[1]': 48,
                 'Recommend.Other': 0.4, 'ADX+DI': 22, 'ADX-DI': 18, 'ADX+DI[1]': 17, 'ADX-DI[1]': 19,
                 'AO': 0.5, 'AO[1]': -0.2, 'Perf.3M': 4}
        late = {'close': 150, 'close[1]': 148, 'SMA20': 138, 'SMA20[1]': 137, 'SMA50': 125, 'SMA50[1]': 124,
                'MACD.macd': 5, 'MACD.signal': 4, 'MACD.hist': 1, 'MACD.hist[1]': 1.2, 'RSI': 78, 'RSI[1]': 77,
                'Recommend.Other': 0.1, 'ADX+DI': 35, 'ADX-DI': 10, 'ADX+DI[1]': 34, 'ADX-DI[1]': 11,
                'AO': 8, 'AO[1]': 8.5, 'Perf.3M': 55}
        assert core.pts_turn(fresh) == 30 and core.pts_turn(late) == 6
        assert core.pts_shift(fresh) == 14 and core.pts_shift(late) == 3
        assert core.pts_not_late(fresh, core.extension(fresh)) == 20
        assert core.pts_not_late(late, core.extension(late)) == 0
        assert [core.pts_relative_short(x) for x in (6, 3, 1, -1)] == [10, 7, 5, 0]
        ind = {'close': 110, 'SMA20': 105, 'average_volume_30d_calc': 1e6}
        assert core.early_check('Buy', 70, ind, 'US Stocks', '1d', 4, 'Bullish') == []
        assert core.early_check('Neutral', 70, ind, 'US Stocks', '1d', 4, 'Bullish') == \
            ['Not Buy or Strong Buy: TradingView rates it Neutral']
        assert core.early_check('Buy', 70, {**ind, 'close': 100}, 'US Stocks', '1d', -5, 'Bullish') == \
            ['Not turned up yet: price is 4.8% under its 20-day average']
        assert core.early_check('Buy', 70, ind, 'US Stocks', '1d', 4, 'Bearish') == \
            ['Early score too low: 70.0, needs 80 because its market is bearish']

    @test('Forex: currency strength from the major pairs (base minus quote)')
    def _():
        class A:
            def __init__(self, v): self.indicators = {'Perf.3M': v}
        raw = {f'FX_IDC:{p}': A(v) for p, v in
               {'EURUSD': 2, 'EURJPY': 3, 'EURGBP': 1, 'GBPUSD': 0, 'USDJPY': 1, 'GBPJPY': 2}.items()}
        s = core.currency_strength(raw, lambda ind: ind['Perf.3M'])
        assert abs(s['EUR'] - 2) < 1e-9 and abs(s['USD'] + 1 / 3) < 1e-9 and abs(s['JPY'] + 2) < 1e-9
        assert abs(core.pair_strength({'3M': s}, 'FX_IDC:EURUSD', '3M') - 7 / 3) < 1e-9
        assert core.pair_strength({'3M': s}, 'FX_IDC:NZDCAD', '3M') is None, 'too few pairs for NZD and CAD'
        assert [core.pts_fx_strength(x) for x in (4, 2, 1, 0.2, -1, None)] == [20, 15, 10, 6, 0, None]
        assert core.pts_fx_strength_early(1.2, 1.5) == 17 and core.pts_fx_strength_early(1.2, 6) == 9
        assert core.pts_fx_strength_early(1.2, None) == 9 and core.pts_fx_strength_early(-0.5, -3) == 0
        # the Dashboard's forex request carries all 28 majors, so every currency gets a reading
        ctx = core._market_context(store, 'Forex')
        assert set(ctx[4]['3M']) == {'EUR', 'GBP', 'AUD', 'NZD', 'USD', 'CAD', 'CHF', 'JPY'}, ctx[4]
        assert 'FX_IDC:EURCHF' in store.state['Forex']['raw'], 'a major pair outside the watchlist rides along'
        assert 'EURCHF' not in set(store.state['Forex']['df']['Symbol'].map(core.short)), '...but is not shown'

    @test('Forex: its own main and early scores, each out of exactly 100 (nothing scaled up)')
    def _():
        assert sum(core.FX_WEIGHTS.values()) == 100 and sum(core.FX_EARLY_WEIGHTS.values()) == 100
        assert [core.pts_fx_entry(e) for e in (0.3, 0.8, 1.2, 2, 3, -0.5)] == [10, 8, 5, 2, 0, 6]
        assert [core.pts_fx_volatility({'close': 1, 'ATR': a / 100}) for a in (0.5, 0.8, 1.2, 2)] == [5, 4, 2, 0]
        base = {'close': 1.10, 'SMA200': 1.05, 'SMA50': 1.08, 'SMA50[1]': 1.07}
        assert core.pts_own_trend(base) == 10 and core.pts_own_trend({**base, 'close': 1.0}) == 4
        # a pair just turning up, with EUR gaining on USD lately faster than over 3 months
        ind = {'close': 1.1020, 'close[1]': 1.0990, 'SMA20': 1.1000, 'SMA20[1]': 1.1001, 'SMA50': 1.0990,
               'SMA50[1]': 1.0985, 'SMA200': 1.0900, 'SMA200[1]': 1.0899, 'MACD.macd': -0.0004, 'MACD.signal': -0.0006,
               'RSI': 54, 'RSI[1]': 49, 'Recommend.Other': 0.3, 'Recommend.All': 0.6, 'ADX+DI': 22, 'ADX-DI': 18,
               'ADX+DI[1]': 17, 'ADX-DI[1]': 19, 'AO': 0.0002, 'AO[1]': -0.0001, 'Perf.1M': 0.8, 'Perf.3M': 1.5,
               'ATR': 0.006}
        strength = {'1M': {'EUR': 1.0, 'USD': -0.2}, '3M': {'EUR': 1.0, 'USD': -0.5}, '1M_vs_3M': True}
        now = core.dt.datetime.now(core.dt.timezone.utc)
        a = type('A', (), {'indicators': ind, 'summary': {'RECOMMENDATION': 'BUY'}})()
        e = core.early_score_symbol('Forex', 'FX_IDC:EURUSD', a, '1d', now, None,
                                    {'ret': None, 'regime': (None, 'n/a'), 'strength': strength})
        assert {k: e[k] for k in core.FX_EARLY_WEIGHTS} == {'Turn': 24, 'Shift': 13.0, 'Rel. 1M': 17, 'Not late': 15,
                                                             'Regime': 10, 'Risk': 5}, e
        assert e['Score'] == 84 and e['Status'] == 'EARLY' and 'Volume' not in e
        a.summary = {'RECOMMENDATION': 'STRONG_BUY'}
        m = core.score_symbol('Forex', 'FX_IDC:EURUSD', a, '1d', now, None, None, (None, 'n/a'), strength)
        assert {k: m[k] for k in core.FX_WEIGHTS} == {'Indicators': 18.0, 'Trend': 20, 'Rel. strength': 15,
                                                      'Momentum': 4.5, 'Entry': 10, 'Risk': 5}, m
        assert m['Score'] == 72.5 and m['Status'] == 'QUALIFIED' and 'Volume' not in m
        # forex's stretch limit is forex-sized
        assert core.entry_check('Strong Buy', 80, ind, 'Forex', '1d', 3.5, 'n/a') == \
            ["Price too stretched: 3.5% above its 20-day average, the limit is 3% (don't chase)"]
        assert core.early_check('Buy', 80, ind, 'Forex', '1d', 2.5, 'n/a') == []

    @test('Early score: Buy and Strong Buy watchlist symbols scored, logged separately from QUALIFIED')
    def _():
        early = core.early_opportunities(store)
        assert not early.empty and set(early['Rating']) <= {'Buy', 'Strong Buy'} and 'Buy' in set(early['Rating'])
        scores = early['Score'].dropna().tolist()
        assert scores == sorted(scores, reverse=True)
        assert set(early['Status']) <= {'EARLY', 'REJECTED'} and set(early['Main']) <= {'QUALIFIED', ''}
        path = core.signals_path()
        if os.path.exists(path):
            os.remove(path)

        class A:
            def __init__(self, c): self.indicators = {'close': c}

        class Store:
            interval = '1d'
            def analysis(self, t, interval=None): return A(100.0)
        row = {'Market': 'US Stocks', 'Symbol': 'JPM', 'Ticker': 'NYSE:JPM', 'Score': 80.0}
        assert core.log_signals(Store(), core.pd.DataFrame([{**row, 'Status': 'QUALIFIED'}])) == 1
        assert core.log_signals(Store(), core.pd.DataFrame([{**row, 'Status': 'EARLY'}]), kind='early') == 1, \
            'an EARLY pick is logged even if the same symbol was logged as QUALIFIED'
        assert core.log_signals(Store(), core.pd.DataFrame([{**row, 'Status': 'EARLY'}]), kind='early') == 0
        assert core.track_record(Store())[1]['n'] == 1 and core.track_record(Store(), 'early')[1]['n'] == 1
        os.remove(path)

    @test('Market scan: each market scanned on its own; Strong Buys at 65+ and early signals at 60+ kept')
    def _():
        s2 = core.MarketStore(pf)
        assert s2.refresh_all()                           # Dashboard data loaded (it holds the benchmarks)
        FAKE['scans'] = []
        found, frames = {}, []
        for mk in S.RUN_MARKETS:
            before = FAKE['calls']
            assert s2.start_scan(mk, background=False)
            assert FAKE['calls'] - before == 1, f'{mk}: found AND scored in a single request'
            res = s2.scan['results'][mk]
            assert not res['errors'] and set(res['found']) == {mk}, res
            assert res['df'].empty or set(res['df']['Market']) == {mk}, 'only that market'
            found.update(res['found'])
            frames.append(res['df'])
        assert found == {'Crypto': 15, 'US Stocks': 40, 'NZ Stocks': 10, 'Forex': 4}, found  # AAPL, FPH: watchlist
        assert [scr for scr, _ in FAKE['scans']] == ['crypto', 'america', 'newzealand', 'forex']
        df = core.pd.concat(frames, ignore_index=True)
        assert not df.empty and (df['Rating'] == 'Strong Buy').all() and (df['Score'] >= S.SCAN_MIN_SCORE).all()
        watch = {core.short(core.to_ticker(m, s)) for m in S.RUN_MARKETS for s in S.MARKETS[m]['watchlist']}
        assert not set(df['Symbol']) & watch, 'watchlist symbols are already scored above'
        for f in frames:
            assert f.empty or f['Score'].tolist() == sorted(f['Score'], reverse=True)
        q = {scr: body for scr, body in FAKE['scans']}
        lefts = {scr: {f['left']: f['right'] for f in body['filter']} for scr, body in q.items()}
        assert 'market_cap_basic' not in lefts['america'], 'every size of US share is scanned'
        assert all('close' not in lefts[s] for s in lefts), 'Buys below SMA200 are returned too (for the early score)'
        assert lefts['crypto']['type'] == 'spot' and lefts['forex']['name'] == core.FX_MAJOR_PAIRS
        assert lefts['newzealand']['exchange'] == 'NZX' and lefts['newzealand']['type'] == 'stock'
        assert lefts['america']['Recommend.All'] == 0.1 and not s2.scan['running'], 'Buy and Strong Buy'
        early = core.pd.concat([s2.scan['results'][m]['early'] for m in S.RUN_MARKETS], ignore_index=True)
        assert not early.empty and set(early['Rating']) <= {'Buy', 'Strong Buy'} and 'Buy' in set(early['Rating'])
        assert (early['Score'] >= S.SCAN_EARLY_MIN_SCORE).all() and not set(early['Symbol']) & watch
        assert set(early['Main']) <= {'QUALIFIED', ''}
        qual = set(df.loc[df['Status'] == 'QUALIFIED', 'Ticker'])
        assert set(early.loc[early['Main'] == 'QUALIFIED', 'Ticker']) <= qual
        s2.scan['running'] = 'Crypto'                     # a scan in progress blocks a second one
        assert not s2.start_scan('Forex', background=False)
        s2.scan['running'] = None

    @test('Market scan: the whole US market (2,000 symbols) in ONE request, on the selected timeframe')
    def _():
        q4 = core.scan_query('US Stocks', '4h')
        assert q4['filter'][0] == {'left': 'Recommend.All|240', 'operation': 'greater', 'right': 0.1}
        assert q4['columns'] == [c + '|240' for c in core.SCAN_COLUMNS]
        assert core.scan_query('US Stocks', '1d')['columns'] == core.SCAN_COLUMNS
        assert len(core.FX_MAJOR_PAIRS) == 28 and 'NZDUSD' in core.FX_MAJOR_PAIRS and 'USDNZD' not in core.FX_MAJOR_PAIRS
        FAKE['us_scan_size'] = 2000
        try:
            ref = {'US Stocks': store.state['US Stocks']['raw']}
            before = FAKE['calls']
            res = core.full_scan(S.INTERVAL, markets=['US Stocks'], reference=ref)
            assert res['found'] == {'US Stocks': 2000} and FAKE['calls'] - before == 1, (res['found'], FAKE['calls'] - before)
            before = FAKE['calls']                       # without the Dashboard's data: +1 request for the benchmark
            core.full_scan(S.INTERVAL, markets=['US Stocks'])
            assert FAKE['calls'] - before == 2
        finally:
            FAKE.pop('us_scan_size')

    @test('Market scan: Strong Buy decided exactly as the library does; misaligned rows are skipped')
    def _():
        from tradingview_ta.technicals import Compute
        for v in (0.49, 0.5, 0.51, 0.1, -0.6):
            assert core.Snapshot({'Recommend.All': v}).summary['RECOMMENDATION'] == Compute.Recommend(v)
        good = fake_scan('forex', core.scan_query('Forex', S.INTERVAL))
        good['data'][0]['d'] = good['data'][0]['d'][:-1]          # one row comes back a value short
        saved = core.tv_scan
        core.tv_scan = lambda screener, body: good
        try:
            _, n, _ = core.scan_market('Forex', S.INTERVAL)
            assert n == 3, n
        finally:
            core.tv_scan = saved

    @test('Full scan: a market refused part-way waits out the cool-down and is retried once')
    def _():
        reset_rate_limit()
        waited = []
        core._sleep = lambda s: (waited.append(s), end_cooldown())     # 'wait' instantly
        try:
            FAKE['fail_next'] = 1                                        # the first request is refused
            res = core.full_scan(S.INTERVAL, markets=['Forex'])
            assert not res['errors'] and res['found'] == {'Forex': 4}, res
            assert waited and 55 <= waited[0] <= 62, waited
        finally:
            core._sleep = real_sleep
            reset_rate_limit()

    @test('Full scan during a long rate limit: nothing is sent and every market says why')
    def _():
        reset_rate_limit()
        core.RATE_LIMIT['until'] = time.time() + 600                     # too long to wait out
        try:
            s2 = core.MarketStore(pf)
            before = FAKE['calls']
            for mk in S.RUN_MARKETS:
                s2.start_scan(mk, background=False)
                res = s2.scan['results'][mk]
                assert set(res['errors']) == {mk} and 'rate-limiting' in res['errors'][mk] and res['df'].empty, res
            assert FAKE['calls'] == before
        finally:
            reset_rate_limit()

    @test('Alerts: a holding getting worse (Review exit or beyond) and a new qualifier are flagged; nothing else')
    def _():
        s2 = core.MarketStore(pf)
        real_pt, real_opp = core.portfolio_table, core.opportunities
        state = {'recs': [('a', 'AAPL', 'HOLD'), ('b', 'JPM', 'HOLD'), ('c', 'FPH', 'EXIT WARNING')],
                 'qual': ['MSFT']}
        core.portfolio_table = lambda p, s: core.pd.DataFrame(
            [{'id': i, 'Symbol': sym, 'Recommendation': r} for i, sym, r in state['recs']])
        core.opportunities = lambda s: (core.pd.DataFrame(
            [{'Symbol': q, 'Status': 'QUALIFIED'} for q in state['qual']] + [{'Symbol': 'X', 'Status': 'REJECTED'}]),
            None, {})
        try:
            s2.check_alerts()                                   # markets still loading: no starting point yet
            assert s2.alerts == [] and not s2._alert_base
            s2.ready = lambda: True                             # every market loaded
            s2.check_alerts()
            assert s2.alerts == [], 'the first look only sets the starting point'
            state['recs'] = [('a', 'AAPL', 'EXIT WARNING'),       # worse, into exit territory -> alert
                             ('b', 'JPM', 'HOLD / WATCH'),       # worse but still mild -> no alert
                             ('c', 'FPH', 'HOLD')]               # better -> no alert
            state['qual'] = ['MSFT', 'NVDA']                     # NVDA is new -> alert
            s2.check_alerts()
            assert [(a['level'], a['text']) for a in s2.alerts] == [
                ('warn', 'AAPL: now "Think about selling" (was "All fine")'),
                ('good', 'NVDA is a new buy idea (passes every check on Top Picks)')], s2.alerts
            s2.check_alerts()
            assert len(s2.alerts) == 2, 'no repeats while nothing changes'
        finally:
            core.portfolio_table, core.opportunities = real_pt, real_opp

    @test('Alerts: none at start-up while the markets load one after another')
    def _():
        s2 = core.MarketStore(pf)
        s2.start()
        try:
            assert s2.wait_ready(20)
            time.sleep(0.3)
            assert s2.alerts == [], [a['text'] for a in s2.alerts]
        finally:
            s2.stop()

    @test('Remembered settings: off by default; when on, timeframe and auto-refresh come back after a restart')
    def _():
        path = core.prefs_path()
        if os.path.exists(path):
            os.remove(path)
        s1 = core.MarketStore(pf)
        core.apply_prefs(s1, core.load_prefs())
        assert not s1.remember and s1.interval == S.INTERVAL and not any(c['on'] for c in s1.auto.values())
        assert s1.beginner == S.BEGINNER_MODE, 'a first start uses Beginner mode from settings.py'
        s1.beginner = False                                       # (Beginner mode always uses 1 Day - see its test)
        s1.remember = True
        s1.interval = core.DASH_TIMEFRAMES['4 Hours']
        s1.set_auto('Crypto', on=True, minutes=15)
        core.save_prefs(s1)
        s2 = core.MarketStore(pf)                                 # "restart"
        core.apply_prefs(s2, core.load_prefs())
        assert s2.remember and s2.interval == '4h' and s2.auto['Crypto'] == {'on': True, 'minutes': 15}
        s1.remember = False                                       # switched off -> next start is back to defaults
        core.save_prefs(s1)
        s3 = core.MarketStore(pf)
        core.apply_prefs(s3, core.load_prefs())
        assert not s3.remember and s3.interval == S.INTERVAL and not s3.auto['Crypto']['on']
        with open(path, 'w') as f:                                # a damaged file is ignored
            f.write('{not json')
        s4 = core.MarketStore(pf)
        core.apply_prefs(s4, core.load_prefs())
        assert not s4.remember
        os.remove(path)

    @test('Exit targets: staged levels from the data (AAPL example), Street-high target is the stretch goal')
    def _():
        aapl = {'close': 355.63, 'ATR': 8.66, 'BB.upper': 354.75, 'Pivot.M.Classic.R1': 355.64,
                'Pivot.M.Classic.R2': 366.64, 'Pivot.M.Classic.R3': 392.56, 'price_52_week_high': 355.91,
                'price_target_average': 343.03, 'price_target_high': 405.0}
        plan = core.exit_plan(aapl)
        got = [(s['name'], round(s['low'], 2), round(s['high'], 2), s['estimated']) for s in plan['stages']]
        assert got == [('Short-term', 366.64, 366.64, False), ('Medium-term', 392.56, 392.56, False),
                       ('Stretch', 405.0, 405.0, False)], got
        assert abs(plan['protect'] - (355.63 - 2 * 8.66)) < 1e-9
        assert [k for k, _ in plan['notes']] == ['at_high', 'above_consensus']
        text = core.exit_write_up('AAPL', 'Strong Buy', plan, 'USD')
        for bit in ('Short-term ($366.64)', 'Medium-term ($392.56)', 'Stretch ($405.00)', 'Street-high analyst target',
                    'Safety level ($338.31)', '52-week high', 'expect $343.03, which is **below**'):
            assert bit in text, (bit, text)
        assert 'AI' not in text

    @test('Exit targets: no chart level in a range -> typical daily moves; NZ$; not enough data handled')
    def _():
        plan = core.exit_plan({'close': 10.0, 'ATR': 0.5})          # e.g. a coin with no pivots or analyst targets
        assert [(s['low'], s['estimated']) for s in plan['stages']] == [(11.0, True), (13.0, True), (16.0, True)]
        assert plan['notes'] == []
        text = core.exit_write_up('FPH', 'Strong Buy', core.exit_plan(
            {'close': 48.4, 'ATR': 1.0, 'Pivot.M.Classic.R1': 50.0, 'Pivot.M.Classic.R2': 47.0}), 'NZD')
        assert 'NZ$50.00' in text and 'NZ$47' not in text, 'levels below the price are ignored'
        assert 'typical daily moves' in text
        assert core.exit_plan({'close': 10.0}) is None
        assert 'Not enough data' in core.exit_write_up('X', 'Strong Buy', None, 'USD')
        assert core.money(0.004567, 'USDT') == '$0.004567' and core.money(1234.5, 'EUR') == '1,234.50 EUR'

    @test('Exit targets: one request per symbol not already loaded, then kept until refreshed')
    def _():
        core._target_cache.clear()
        before = FAKE['calls']
        v1, t1 = core.fetch_target_data('US Stocks', 'NYSE:JPM')
        v2, t2 = core.fetch_target_data('US Stocks', 'NYSE:JPM')
        assert FAKE['calls'] - before == 1 and t1 == t2 and v1['close'] == 320.0
        try:
            core.fetch_target_data('US Stocks', 'NASDAQ:NOTREAL')
            raise AssertionError('should have failed')
        except RuntimeError as e:
            assert 'no data' in str(e)

    @test('Fundamentals: a plain-English line for shares, fetched once and remembered; nothing for crypto/forex')
    def _():
        assert core.business_summary({'price_earnings_ttm': 39.6, 'earnings_per_share_diluted_yoy_growth_ttm': 20.3,
                                      'dividends_yield_current': 0.3, 'net_margin': 27.6}) == \
            'P/E 40 · earnings +20% · dividend 0.3%'
        assert core.business_summary({'price_earnings_ttm': None, 'net_margin': -5.0}) == 'losing money · no dividend'
        assert core.business_summary({}) == '–' and core.business_summary(None) == '–'
        assert core.business_summary(dict.fromkeys(core.FUND_COLUMNS)) == '–', 'no figures -> no claims'
        core._fund_cache.clear()
        before = FAKE['calls']
        core.fundamentals('US Stocks', ['NYSE:JPM', 'NASDAQ:AAPL'])
        core.fundamentals('US Stocks', ['NYSE:JPM', 'NASDAQ:AAPL'])
        assert FAKE['calls'] - before == 1, 'one request, then remembered'
        assert core.fundamentals('Crypto', ['BINANCE:BTCUSDT']) == {} and FAKE['calls'] - before == 1

    @test('Position-size calculator: a fall to the protective level costs only the chosen % of the total')
    def _():
        s = core.position_size(10000, 1, 100, 94)              # risk $100, $6 per unit, no cap
        assert abs(s['units'] - 100 / 6) < 1e-9 and abs(s['loss'] - 100) < 1e-9 and s['limited_by'] == 'risk'
        assert abs(s['cost'] - 100 / 6 * 100) < 1e-6 and abs(s['share_pct'] - s['cost'] / 100) < 1e-9
        assert core.position_size(10000, 1, 100, 100) is None and core.position_size(10000, 1, 100, 120) is None
        # The Learn page's worked example: $10,000, FPH $48.40, protective $46.20, 1% risk, 10% cap
        fph = core.position_size(10000, 1, 48.40, 46.20, cap_pct=10)
        assert fph['limited_by'] == 'cap' and abs(fph['cost'] - 1000) < 1e-6
        assert abs(fph['risk_cost'] - 100 / 2.2 * 48.4) < 1e-6 and round(fph['risk_cost'], -2) == 2200
        assert round(fph['loss']) == 45 and fph['loss_pct'] < 0.5
        wide = core.position_size(10000, 1, 100, 50, cap_pct=10)   # a far-away protective level: risk rule wins
        assert wide['limited_by'] == 'risk' and abs(wide['cost'] - 200) < 1e-6

    @test('Track record: QUALIFIED picks logged once a week on the daily chart, compared with their benchmark')
    def _():
        path = core.signals_path()
        if os.path.exists(path):
            os.remove(path)

        class A:
            def __init__(self, c): self.indicators = {'close': c}
        prices = {'NYSE:JPM': 100.0, 'AMEX:SPY': 500.0, 'BINANCE:BTCUSDT': 50000.0}

        class Store:
            interval = '1d'
            def analysis(self, t, interval=None): return A(prices[t]) if t in prices else None
        opp = core.pd.DataFrame([
            {'Market': 'US Stocks', 'Symbol': 'JPM', 'Ticker': 'NYSE:JPM', 'Score': 80.0, 'Status': 'QUALIFIED'},
            {'Market': 'Crypto', 'Symbol': 'BTCUSDT', 'Ticker': 'BINANCE:BTCUSDT', 'Score': 75.0, 'Status': 'QUALIFIED'},
            {'Market': 'US Stocks', 'Symbol': 'MA', 'Ticker': 'NYSE:MA', 'Score': 72.0, 'Status': 'REJECTED'}])
        assert core.log_signals(Store(), opp) == 2
        assert core.log_signals(Store(), opp) == 0, 'not logged again within a week'
        Store.interval = '4h'
        assert core.log_signals(Store(), opp) == 0, 'only the daily chart is logged'
        log = core.load_signals()
        btc = next(s for s in log if s['ticker'] == 'BINANCE:BTCUSDT')
        assert btc['bench'] is None, 'BTC is its own benchmark - judged on its own return'
        for s in log:                                          # pretend they were logged 10 days ago
            s['date'] = (core.dt.datetime.now() - core.dt.timedelta(days=10)).isoformat(timespec='minutes')
        with open(path, 'w') as f:
            json.dump(log, f)
        prices.update({'NYSE:JPM': 110.0, 'AMEX:SPY': 505.0, 'BINANCE:BTCUSDT': 45000.0})
        df, summ = core.track_record(Store())
        jpm = df.set_index('Symbol').loc['JPM']
        assert abs(jpm['Return %'] - 10) < 1e-9 and abs(jpm['Benchmark %'] - 1) < 1e-9 and bool(jpm['Beat it'])
        btc = df.set_index('Symbol').loc['BTCUSDT']
        assert btc['Compared with'] == core.CASH and btc['Benchmark %'] == 0 and not btc['Beat it'], \
            'no benchmark: compared with holding cash'
        assert summ['n'] == 2 and abs(summ['avg'] - 0) < 1e-9 and summ['beat_pct'] == 50 and summ['win_pct'] == 50
        os.remove(path)

    @test('Track record: no pick drops out, lowest price, protective level and fixed-age returns are kept')
    def _():
        path = core.signals_path()
        if os.path.exists(path):
            os.remove(path)

        class A:
            def __init__(self, c, low=None, atr=None):
                self.indicators = {'close': c, **({'low': low} if low else {}),
                                   **({'ATR': atr, 'SMA200': 50.0, 'SMA200[1]': 50.0} if atr else {})}
        prices = {'NYSE:JPM': A(100.0, atr=5.0), 'AMEX:SPY': A(500.0), 'FX_IDC:EURUSD': A(1.10)}

        class Store:
            interval = '1d'
            def analysis(self, t, interval=None): return prices.get(t)
        opp = core.pd.DataFrame([
            {'Market': 'US Stocks', 'Symbol': 'JPM', 'Ticker': 'NYSE:JPM', 'Score': 80.0, 'Status': 'QUALIFIED'},
            {'Market': 'Forex', 'Symbol': 'EURUSD', 'Ticker': 'FX_IDC:EURUSD', 'Score': 75.0, 'Status': 'QUALIFIED'}])
        assert core.log_signals(Store(), opp) == 2
        log = core.load_signals()
        jpm = next(s for s in log if s['symbol'] == 'JPM')
        assert jpm['stop'] == 90.0, 'protective level = price - 2 x ATR'
        assert next(s for s in log if s['symbol'] == 'EURUSD')['stop'] is None, 'no ATR: no level'
        for s in log:                                          # pretend they were logged 30 days ago
            s['date'] = (core.dt.datetime.now() - core.dt.timedelta(days=30)).isoformat(timespec='minutes')
        with open(path, 'w') as f:
            json.dump(log, f)
        prices.update({'NYSE:JPM': A(95.0, low=88.0), 'AMEX:SPY': A(510.0), 'FX_IDC:EURUSD': A(1.21)})
        assert core.update_signal_history(Store())
        assert not core.update_signal_history(Store()), 'nothing new: the file is not rewritten'
        log = core.load_signals()
        jpm = next(s for s in log if s['symbol'] == 'JPM')
        assert jpm['low'] == 88.0 and jpm['last'] == 95.0 and jpm['bench_last'] == 510.0
        assert set(jpm['at']) == {'1 week', '4 weeks'}, 'reached 1 and 4 weeks, not 12'
        prices.update({'NYSE:JPM': A(120.0)})                  # recovered later: the low and the ages stay
        core.update_signal_history(Store())
        df, summ = core.track_record(Store())
        row = df.set_index('Symbol').loc['JPM']
        assert abs(row['Return %'] - 20) < 1e-9 and abs(row['Lowest %'] + 12) < 1e-9 and row['Price from'] == 'live'
        assert bool(row['Hit it']) and abs(row['With exit %'] + 10) < 1e-9, 'sold at the level: -10%, not +20%'
        assert abs(row['After 4 weeks %'] + 5) < 1e-9 and core.pd.isna(row['After 12 weeks %'])
        assert summ['n_hit'] == 1 and summ['horizons']['4 weeks']['n'] == 2
        assert summ['horizons']['4 weeks']['beat_pct'] == 50, 'JPM -5% vs S&P +2%; EURUSD +10% vs cash'
        prices.clear()                                         # market not loaded: the last saved price is used
        df, summ = core.track_record(Store())
        row = df.set_index('Symbol').loc['JPM']
        assert len(df) == 2 and summ['n_missing'] == 0 and row['Now'] == 120.0
        assert row['Price from'].startswith('saved') and abs(row['Benchmark %'] - 2) < 1e-9
        with open(path, 'w') as f:                             # a pick never seen since logging
            json.dump([{**jpm, 'last': None, 'bench_last': None}], f)
        df, summ = core.track_record(Store())
        assert len(df) == 1 and df.iloc[0]['Price from'] == 'no price yet' and summ['n_missing'] == 1
        assert summ['avg'] is None
        os.remove(path)

    @test('Track record: picks are logged from the daily chart even while another timeframe is on screen')
    def _():
        path = core.signals_path()
        if os.path.exists(path):
            os.remove(path)
        s2 = core.MarketStore(pf)
        s2.set_interval(core.DASH_TIMEFRAMES['4 Hours'])
        assert all(s2._track_due(mk) for mk in S.RUN_MARKETS), 'no daily data yet: due'
        for mk in S.RUN_MARKETS:
            assert s2.refresh(mk, core.RISK_INTERVAL)
        assert not any(s2._track_due(mk) for mk in S.RUN_MARKETS), 'just loaded: not due again for hours'
        daily, _, _ = core.opportunities(s2, core.RISK_INTERVAL)
        assert s2.state == {} and not daily.empty, 'scored from the daily data, not the (empty) 4-hour data'
        expected = int((daily['Status'] == 'QUALIFIED').sum())
        logged = [s for s in core.load_signals() if s.get('kind', 'qualified') == 'qualified']
        assert len(logged) == expected, (len(logged), expected)
        os.remove(path)

    @test('Practice portfolio: separate from the real one, updated from the same data')
    def _():
        pr = core.Portfolio(os.path.join(tmp, 'practice_test.json'))
        s2 = core.MarketStore(pf, practice=pr)
        ok, msg = pr.add_known('Crypto', 'BINANCE:ETHUSDT', 2500.0, 0.4)
        assert ok and 'Practice' in msg and not pr.add_known('Crypto', 'BINANCE:ETHUSDT', 2500.0, 0)[0]
        assert 'BINANCE:ETHUSDT' in s2.held_tickers('Crypto') and 'BINANCE:ETHUSDT' not in pf.tickers('Crypto')
        assert s2.refresh('Crypto')
        assert pr.holdings[0].get('atr_stop'), 'its risk level is kept up to date too'
        assert core.portfolio_table(pr, s2).iloc[0]['Now'] == 2500.0

    @test('Market hours: when the US and NZ markets are open or closed (weekends, time zones)')
    def _():
        import datetime as dt
        utc = dt.timezone.utc
        at = lambda *a: dt.datetime(*a, tzinfo=utc)
        # Thursday 12 Nov 2026, 13:56 in NZ (00:56 UTC) - NZX open; Wednesday 19:56 in New York - US closed at 16:00
        assert core.market_session('NZ Stocks', at(2026, 11, 12, 0, 56)) == ('open', None)
        assert core.market_session('US Stocks', at(2026, 11, 12, 0, 56)) == ('closed', at(2026, 11, 11, 21, 0))
        # Thursday 8pm in NZ: closed since 4:45pm (03:45 UTC)
        assert core.market_session('NZ Stocks', at(2026, 11, 12, 7, 0)) == ('closed', at(2026, 11, 12, 3, 45))
        # Saturday, and Monday 8am before the open: the last session was Friday's
        assert core.market_session('NZ Stocks', at(2026, 11, 14, 1, 0)) == ('closed', at(2026, 11, 13, 3, 45))
        assert core.market_session('NZ Stocks', at(2026, 11, 15, 19, 0)) == ('closed', at(2026, 11, 13, 3, 45))
        assert core.market_session('Crypto') is None and core.market_session('Forex') is None
        # Fetched 10 minutes after the close: not final yet. 40 minutes after: final, no need to fetch again.
        now = at(2026, 11, 12, 7, 0)
        assert not core.is_settled('NZ Stocks', at(2026, 11, 12, 3, 55), now)
        assert core.is_settled('NZ Stocks', at(2026, 11, 12, 4, 25), now)
        assert not core.is_settled('Crypto', at(2026, 11, 12, 4, 25), now)

    @test('Market hours: a closed market already fetched after its close is not fetched again')
    def _():
        import datetime as dt
        s2 = core.MarketStore(pf)
        assert s2.refresh_all()
        real = core.market_session
        closed_at = core._utc_now() - dt.timedelta(hours=3)
        core.market_session = lambda mk, now=None: ('closed', closed_at) if mk == 'NZ Stocks' else real(mk, now)
        try:
            for mk in ('Crypto', 'Forex'):
                assert not s2.is_settled(mk), 'crypto and forex trade around the clock'
            assert s2.is_settled('NZ Stocks') and s2.is_fresh('NZ Stocks')
            FAKE['screeners'] = []
            before = FAKE['calls']
            assert s2.refresh_all()
            skipped = 1 + sum(s2.is_settled(m) for m in S.RUN_MARKETS if m != 'NZ Stocks')   # (US may be closed too)
            assert FAKE['calls'] - before == len(S.RUN_MARKETS) - skipped, FAKE['calls'] - before
            assert s2.refresh('NZ Stocks'), 'the market\'s own Refresh button still fetches'
        finally:
            core.market_session = real

    @test('Market hours: settings are checked (time zone and open/close times)')
    def _():
        saved = dict(S.MARKETS['NZ Stocks'])
        try:
            S.MARKETS['NZ Stocks']['hours'] = {'tz': 'Mars/Olympus', 'open': '10:00', 'close': '16:45'}
            c = dict((n, (s, d)) for s, n, d in core.health_check(pf))['Settings']
            assert c[0] == 'fail' and "'hours'" in c[1], c
        finally:
            S.MARKETS['NZ Stocks'] = saved

    @test('Timeframe check: loaded timeframes reused, the missing ones in ONE request, same rating as normal')
    def _():
        s2 = core.MarketStore(pf)
        assert s2.refresh('Crypto')                          # the Dashboard has the 1 Day chart
        t = 'BINANCE:BTCUSDT'
        ratings, when = core.timeframe_check(s2, 'Crypto', t)
        assert ratings['1 Day'] is not None and ratings['1 Hour'] is None and when is None, 'no request yet'
        before = FAKE['calls']
        ratings, when = core.timeframe_check(s2, 'Crypto', t, fetch=True)
        assert FAKE['calls'] - before == 1 and all(a is not None for a in ratings.values())
        q = FAKE['scans'][-1][1]
        assert {c.split('|')[1] for c in q['columns'] if '|' in c} == {'60', '240', '1W'}, 'only the missing ones'
        before = FAKE['calls']
        core.timeframe_check(s2, 'Crypto', t, fetch=True)     # all known now: nothing to fetch
        assert FAKE['calls'] == before
        core.timeframe_check(s2, 'Crypto', t, force=True)     # Refresh: all four again, still one request
        assert FAKE['calls'] - before == 1
        per_tf = core.fetch_timeframes('Crypto', ['1d'])['1d'][t]
        assert per_tf.summary['RECOMMENDATION'] == FakeAnalysis(t).summary['RECOMMENDATION']
        assert 'timeframes' in core.agreement(ratings)

    @test('Reuse: exit targets and company figures come from loaded data (no request); Refresh clears extras')
    def _():
        s2 = core.MarketStore(pf)
        assert s2.refresh('US Stocks')                       # daily data for the watchlist
        core._target_cache.clear()
        core._fund_cache.clear()
        before = FAKE['calls']
        assert core.target_data_if_known('NYSE:JPM', s2) is not None
        values, _ = core.fetch_target_data('US Stocks', 'NYSE:JPM', s2)
        assert FAKE['calls'] == before and values['close'] == 320.0, 'from the Dashboard\'s data'
        core.fetch_target_data('US Stocks', 'NYSE:JPM', s2, force=True)   # the Refresh button
        assert FAKE['calls'] - before == 1
        core.fetch_target_data('US Stocks', 'NASDAQ:ZZZ1', s2)            # not loaded anywhere: one request...
        core.fetch_target_data('US Stocks', 'NASDAQ:ZZZ1', s2)            # ...then kept (no 15-minute expiry)
        assert FAKE['calls'] - before == 2
        s2.refresh('US Stocks', manual=True)                              # a manual refresh clears the extras
        assert 'NASDAQ:ZZZ1' not in core._target_cache
        # a market scan's figures are reused too
        res = core.full_scan(S.INTERVAL, markets=['US Stocks'], reference={'US Stocks': s2.state['US Stocks']['raw']})
        before = FAKE['calls']
        assert core.target_data_if_known('NASDAQ:SCAN3', s2) is not None and FAKE['calls'] == before

    @test('Reuse: switching back to a timeframe shows its data as it was - only missing data is fetched')
    def _():
        s2 = core.MarketStore(pf)
        s2.refresh_all()
        for d in s2.state.values():                           # pretend it was loaded an hour ago
            d['time'] -= core.dt.timedelta(hours=1)
        s2.set_interval('4h')
        assert set(s2.refresh_stale(background=False)) == set(S.RUN_MARKETS), '4 Hours never loaded: fetched'
        before = FAKE['calls']
        s2.set_interval(S.INTERVAL)
        assert s2.refresh_stale(background=False) == [] and FAKE['calls'] == before, 'old data kept, not re-fetched'

    def wait_news(ticker, scored=True, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            e = news.get(ticker)
            if e is not None and not news.is_pending(ticker) and (e['summary'] or not scored):
                return e
            time.sleep(0.02)
        raise AssertionError(f'no news for {ticker}: {news.get(ticker)}')

    @test('News: company and coin names, and what is searched for')
    def _():
        assert news.clean_name('Fisher & Paykel Healthcare Corporation Limited') == 'Fisher & Paykel Healthcare'
        assert news.clean_name('Apple Inc.') == 'Apple' and news.clean_name('Bitcoin / TetherUS') == 'Bitcoin'
        assert news.clean_name('Berkshire Hathaway Inc. New') == 'Berkshire Hathaway'
        assert news.search_query('Forex', 'FX_IDC:NZDUSD') == '"NZD/USD" forex'
        assert news.search_query('Crypto', 'BINANCE:SOLUSDT') == '"SOL" crypto'
        assert news.search_query('Crypto', 'BINANCE:SOLUSDT', 'Solana') == '"Solana" crypto'
        assert news.search_query('NZ Stocks', 'NZX:FPH', 'Fisher & Paykel Healthcare') == \
            '"Fisher & Paykel Healthcare" (NZX OR shares OR "New Zealand")'
        assert news.search_query('US Stocks', 'NASDAQ:AAPL', 'Apple') == '"Apple" (stock OR shares OR Nasdaq OR NYSE)'
        assert news.search_query('US Stocks', 'NASDAQ:AAPL').startswith('"AAPL" '), 'no name known: the symbol'
        terms = news.relevance_terms('US Stocks', 'NASDAQ:AAPL', 'Apple')
        assert news.is_relevant('Apple shares rise after results', terms)
        assert not news.is_relevant('Fire causes apple orchard to close', terms), 'case-sensitive: not the fruit'
        assert not news.is_relevant('Pineapple prices jump', terms) and news.is_relevant('AAPL hits a high', terms)
        assert not news.is_relevant('Apple Inc. (AAPL) stock price, news, quote and history', terms), 'quote page'
        assert not news.is_relevant('Can Apple Hospitality REIT (NYSE:APLE) Keep Going?', terms, 'AAPL'), 'look-alike'
        assert news.is_relevant('Apple (AAPL) heads to trial', terms, 'AAPL')
        fbu = news.relevance_terms('NZ Stocks', 'NZX:FBU', 'Fletcher Building')
        assert news.is_relevant('Fletcher Building (ASX:FBU) shares in focus', fbu, 'FBU'), 'same company, other listing'
        fph = news.relevance_terms('NZ Stocks', 'NZX:FPH', 'Fisher & Paykel Healthcare')
        assert news.is_relevant('Fisher & Paykel lifts guidance', fph)
        assert news.relevance_terms('Forex', 'FX_IDC:USDJPY') is None
        assert news.is_relevant('BTC falls below support', news.relevance_terms('Crypto', 'BINANCE:BTCUSDT', 'Bitcoin'))

    @test('News: headlines newest first, no repeats or old stories; Finnhub for US shares when a key is set')
    def _():
        src, items = news.headlines('NZ Stocks', 'NZX:FPH', 'Fisher & Paykel Healthcare')
        assert src == 'Google News', src
        assert [i['title'] for i in items] == ['Fisher & Paykel Healthcare beats forecasts',
                                               'Fisher & Paykel Healthcare falls after guidance cut',
                                               'Fisher & Paykel Healthcare shares surge on demand'], items
        assert items[0]['source'] == 'Reuters', 'the source is taken off the end of the title'
        url, params = NEWS_CALLS[-1]
        assert 'news.google.com' in url and params['gl'] == 'NZ' and params['q'].endswith(f'when:{S.NEWS_MAX_AGE_DAYS}d')
        saved = S.FINNHUB_API_KEY
        S.FINNHUB_API_KEY = 'test-key'
        try:
            src, items = news.headlines('US Stocks', 'NYSE:JPM')
            assert src == 'Finnhub' and items[0]['title'] == 'JPM beats forecasts'
            assert NEWS_CALLS[-1][1]['token'] == 'test-key' and NEWS_CALLS[-1][1]['symbol'] == 'JPM'
            assert news.headlines('NZ Stocks', 'NZX:FPH')[0] == 'Google News', 'Finnhub is for US shares only'
        finally:
            S.FINNHUB_API_KEY = saved

    @test('News: fetched in the background, rated by FinBERT, summarised; not fetched again within the hour')
    def _():
        news.clear()
        news.MODEL.update(state='not loaded', classify=None, error='')
        with news._names_lock:
            news._names['NASDAQ:AAPL'] = 'Apple'
        assert news.request('US Stocks', ['NASDAQ:AAPL']) == 1
        e = wait_news('NASDAQ:AAPL')
        assert [i['label'] for i in e['items']] == ['Positive', 'Negative', 'Positive'], e['items']
        assert e['summary'] == {'label': 'Positive', 'score': 0.28, 'n': 3, 'pos': 2, 'neg': 1, 'neu': 0}, e['summary']
        assert news.request('US Stocks', ['NASDAQ:AAPL']) == 0, 'fresh news is reused'
        assert news.MODEL['state'] == 'ready' and news.status() == ''
        assert [news.summarise([{'score': s, 'label': 'Neutral'}])['label'] for s in (0.2, 0.1, -0.2)] == \
            ['Positive', 'Neutral', 'Negative']

    @test('News: without FinBERT the headlines still show, unrated, with a note saying why')
    def _():
        saved = news.make_pipeline
        def broken():
            raise RuntimeError('no internet for the download')
        news.make_pipeline = broken
        news.MODEL.update(state='not loaded', classify=None, error='')
        news.clear()
        try:
            news.request('NZ Stocks', ['NZX:FPH'])
            e = wait_news('NZX:FPH', scored=False)
            assert len(e['items']) == 3 and e['summary'] is None and all('label' not in i for i in e['items'])
            assert 'could not load' in news.status() and 'no internet' in news.status()
        finally:
            news.make_pipeline = saved
            news.MODEL.update(state='not loaded', classify=None, error='')
            news.clear()

    @test('News: the mood of a pick\'s news is saved with it in the track record')
    def _():
        path = core.signals_path()
        if os.path.exists(path):
            os.remove(path)

        class A:
            def __init__(self, c): self.indicators = {'close': c}

        class Store:
            interval = '1d'
            def analysis(self, t, interval=None): return A(100.0)
        with news._lock:
            news._cache['NYSE:JPM'] = {'time': time.time(), 'market': 'US Stocks', 'source': 'Google News',
                                      'items': [], 'error': '', 'summary': {'label': 'Positive', 'score': 0.4, 'n': 5,
                                                                           'pos': 3, 'neg': 0, 'neu': 2}}
        row = {'Market': 'US Stocks', 'Symbol': 'JPM', 'Ticker': 'NYSE:JPM', 'Score': 80.0, 'Status': 'QUALIFIED'}
        assert core.log_signals(Store(), core.pd.DataFrame([row])) == 1
        s = core.load_signals()[-1]
        assert s['news'] == 0.4 and s['news_n'] == 5, s
        news.clear()
        os.remove(path)

    # ============================== Part 2: the web pages ==============================
    from streamlit.testing.v1 import AppTest
    import tvbot_ui

    tvbot_ui.get_app.clear()
    S.BEGINNER_MODE = False          # the page tests below use every control; Beginner mode has its own test

    def page(label):
        script = (f'import sys\nsys.path.insert(0, {ROOT!r})\nimport tvbot_ui\n'
                  f'tvbot_ui.render_page({label!r})')
        at = AppTest.from_string(script, default_timeout=60)
        at.run()
        return at

    def texts(at):
        return ' '.join(str(m.value) for m in list(at.markdown) + list(at.caption) + list(at.info))

    def no_errors(at):
        assert not at.exception, [e.value for e in at.exception]

    @test('Website: the app starts on the Home page, with the menu of pages')
    def _():
        at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=60)
        at.run()
        no_errors(at)
        assert list(tvbot_ui.PAGES) == ['Home', 'Learn', 'Top Picks', 'My Portfolio', 'Dashboard', 'Market Scan',
                                        'Symbol Details']
        assert tvbot_ui.ADVANCED_PAGES == ['Dashboard', 'Market Scan', 'Symbol Details']
        assert 'Start here' in texts(at) and 'Your portfolio' in texts(at)
        assert tvbot_ui.get_app()['store'].wait_ready(20)

    @test('Page: Home - portfolio in NZ$, what needs attention, today\'s idea - with no requests')
    def _():
        app = tvbot_ui.get_app()
        assert app['store'].wait_ready(20)
        at = page('Home')                                   # first draw (may compute company figures once)
        before = FAKE['calls']
        at = page('Home')
        no_errors(at)
        assert FAKE['calls'] == before, 'Home only uses data the app already has'
        t = texts(at)
        assert 'Needs your attention' in t and "Today's strongest idea" in t and 'step by step' in t
        assert at.number_input(key='home_total').value == app['store'].total_invested
        assert 'No share passes' in t or 'strongest chart signal among the shares' in t
        opp, _, _ = core.opportunities(app['store'])
        shares_ok = opp[(opp['Status'] == 'QUALIFIED') & opp['Market'].isin(['US Stocks', 'NZ Stocks'])]
        if not shares_ok.empty:                             # the idea shown is the best SHARE, never crypto/forex
            assert f"### {shares_ok.iloc[0]['Symbol']} " in t, t[:600]
        # a holding that needs attention shows up there, worst first
        pf = app['portfolio']
        ok, _ = pf.add('US Stocks', 'xom', 2000, 1, app['store'])     # bought far above the price -> breached
        at = page('Home')
        no_errors(at)
        assert 'XOM' in texts(at), texts(at)[:400]
        pf.delete(pf.holdings[-1]['id'])

    @test('Page: Home - "Try it in Practice" buys today\'s idea with pretend money')
    def _():
        app = tvbot_ui.get_app()
        at = page('Home')
        if not [b for b in at.button if b.key == 'home_practice']:
            return                                          # no idea qualifies in this data - nothing to try
        n = len(app['practice'].holdings)
        at.button(key='home_practice').click().run()
        no_errors(at)
        assert len(app['practice'].holdings) == n + 1 and not any(
            h['id'] == app['practice'].holdings[-1]['id'] for h in app['portfolio'].holdings)
        app['practice'].delete(app['practice'].holdings[-1]['id'])

    @test('Website: health check is not shown to users when it passes')
    def _():
        at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=60)
        at.run()
        t = texts(at).lower()
        assert 'health' not in t and 'could not start' not in t

    @test('Page: Dashboard shows every market with its table')
    def _():
        at = page('Dashboard')
        no_errors(at)
        assert [s.value for s in at.subheader] == S.RUN_MARKETS and len(at.dataframe) == len(S.RUN_MARKETS)
        assert 'NZ Stocks' in S.RUN_MARKETS
        cols = list(at.dataframe[0].value.columns)
        assert 'Name' in cols and 'Chart signal' in cols and 'Indicator balance' in cols, cols
        assert any('What do these columns mean' in e.label for e in at.expander)
        assert any('How risky' in e.label for e in at.expander), 'each market explains what it is'

    @test('Page: every page shows market status chips; a new alert pops up once in an open page')
    def _():
        app_store = tvbot_ui.get_app()['store']
        at = page('Top Picks')
        no_errors(at)
        chips = ' '.join(str(m.value) for m in at.markdown if 'tvb-status' in str(m.value))
        assert all(mk in chips for mk in S.RUN_MARKETS), chips[:300]
        assert not at.toast, 'old alerts are not replayed when a page opens'
        app_store._alert('warn', 'TEST: Hold → Exit Warning')
        at.run()
        assert any('TEST: Hold' in t.value for t in at.toast), [t.value for t in at.toast]
        at.run()
        assert not any('TEST: Hold' in t.value for t in at.toast), 'shown once, not on every refresh'
        app_store.alerts.clear()

    @test('Page: Dashboard - each market has its own auto-refresh switch (off) and interval')
    def _():
        app_store = tvbot_ui.get_app()['store']
        at = page('Dashboard')
        no_errors(at)
        for mk in S.RUN_MARKETS:
            assert at.toggle(key=f'auto_{mk}').value is False, f'{mk} should start with auto-refresh off'
            assert list(at.selectbox(key=f'auto_every_{mk}').options) == list(core.AUTO_CHOICES)
        assert 'auto-refresh off' in texts(at)
        try:
            at.toggle(key='auto_US Stocks').set_value(True).run()
            at.selectbox(key='auto_every_US Stocks').set_value('15 min').run()
            no_errors(at)
            assert app_store.auto['US Stocks'] == {'on': True, 'minutes': 15}, app_store.auto['US Stocks']
            assert all(not app_store.auto[mk]['on'] for mk in S.RUN_MARKETS if mk != 'US Stocks'), 'only that one'
            again = page('Dashboard')                            # a fresh page shows the saved choice
            assert again.toggle(key='auto_US Stocks').value is True
            assert again.selectbox(key='auto_every_US Stocks').value == '15 min'
        finally:
            app_store.set_auto('US Stocks', on=False, minutes=5)

    @test('Page: Dashboard timeframe dropdown (1 Hour ... 4 Weeks) reloads the tables')
    def _():
        app_store = tvbot_ui.get_app()['store']
        at = page('Dashboard')
        dd = at.selectbox(key='dash_timeframe')
        assert dd.value == '1 Day' and list(dd.options) == list(core.DASH_TIMEFRAMES), (dd.value, dd.options)
        try:
            FAKE['intervals'] = []
            t0 = time.time()
            dd.set_value('4 Weeks').run()
            assert time.time() - t0 < 5, 'changing the timeframe should not hold up the page'
            no_errors(at)
            assert app_store.interval == core.DASH_TIMEFRAMES['4 Weeks']
            assert app_store.wait_ready(20) and '1M' in FAKE['intervals']
            at.run()
            assert len(at.dataframe) == len(S.RUN_MARKETS) and '4 Weeks' in texts(at)
            tp = page('Top Picks')
            assert '4 Weeks' in texts(tp)
        finally:
            at.selectbox(key='dash_timeframe').set_value('1 Day').run()
        assert app_store.interval == S.INTERVAL and app_store.wait_ready(20)

    @test('Page: a "TradingView is busy" notice shows while it is rate-limiting')
    def _():
        core.RATE_LIMIT['until'] = time.time() + 30
        try:
            at = page('Dashboard')
            no_errors(at)
            assert any('TradingView is busy' in w.value for w in at.warning), [w.value for w in at.warning]
        finally:
            core.RATE_LIMIT['until'] = 0.0
        at = page('Dashboard')
        assert not any('TradingView is busy' in w.value for w in at.warning)

    @test('Page: My Portfolio - add a holding with the form')
    def _():
        at = page('My Portfolio')
        no_errors(at)
        at.selectbox(key='add_market').set_value('Crypto')
        at.text_input(key='add_symbol').input('eth')
        at.number_input(key='add_price').set_value(2000.0)
        at.number_input(key='add_qty').set_value(2.0)
        at.button(key='add_submit').click().run()
        no_errors(at)
        app_pf = tvbot_ui.get_app()['portfolio']
        assert any(h['ticker'] == 'BINANCE:ETHUSDT' and h['qty'] == 2 for h in app_pf.holdings)
        assert any('Added BINANCE:ETHUSDT' in s.value for s in at.toast), [s.value for s in at.toast]
        assert not at.success, 'confirmation is a pop-up, not a box in the page'
        eth = next(h for h in app_pf.holdings if h['ticker'] == 'BINANCE:ETHUSDT')
        assert eth.get('atr_stop') and eth.get('added'), 'a new holding gets its ATR risk level straight away'
        at.run()
        no_errors(at)
        t = texts(at)
        assert 'Safety levels' in t and 'never buys or sells' in t and 'ETHUSDT' in t
        heads = [m.value for m in at.markdown if 'tvb-rec-head' in str(m.value)]
        rec = core.portfolio_table(app_pf, tvbot_ui.get_app()['store']).set_index('id').loc[eth['id'], 'Recommendation']
        assert heads and any(f'<span>{core.PLAIN_REC[rec]}</span>' in h for h in heads), (rec, heads)
        cols = list(at.dataframe[0].value.columns)
        assert 'Value (NZ$)' in cols and 'Safety check' in cols and 'Name' in cols, cols
        assert len(at.dataframe) >= 3     # holdings, risk levels, profit/loss

    @test('Page: My Portfolio - a mistake shows a red message that stays on the page')
    def _():
        at = page('My Portfolio')
        at.text_input(key='add_symbol').input('')
        at.button(key='add_submit').click().run()
        no_errors(at)
        assert any('Enter a symbol' in e.value for e in at.error), [e.value for e in at.error]
        assert not at.toast

    @test('Page: My Portfolio - a holding added while TradingView is busy is kept and shown')
    def _():
        app_pf = tvbot_ui.get_app()['portfolio']
        core.RATE_LIMIT['until'] = time.time() + 60
        try:
            at = page('My Portfolio')
            at.selectbox(key='add_market').set_value('US Stocks')
            at.text_input(key='add_symbol').input('ko')
            at.number_input(key='add_price').set_value(60.0)
            at.number_input(key='add_qty').set_value(10.0)
            at.button(key='add_submit').click().run()
            no_errors(at)
            assert any('Saved KO' in s.value for s in at.toast), [s.value for s in at.toast]
            h = next(h for h in app_pf.holdings if h.get('pending') and h['candidates'][0] == 'NASDAQ:KO')
            at = page('My Portfolio')                          # refresh the page: still there
            no_errors(at)
            assert 'Saved while TradingView was busy' in texts(at)
        finally:
            core.RATE_LIMIT['until'], core.RATE_LIMIT['strikes'] = 0.0, 0
        app_pf.delete(h['id'])

    @test('Page: My Portfolio - sell part, then everything, with the form')
    def _():
        app_pf = tvbot_ui.get_app()['portfolio']
        hid = next(h['id'] for h in app_pf.holdings if h['ticker'] == 'BINANCE:ETHUSDT')
        at = page('My Portfolio')
        at.selectbox(key='sell_holding').set_value(hid)
        at.number_input(key='sell_qty').set_value(0.5)
        at.number_input(key='sell_price').set_value(2400.0)
        at.button(key='sell_submit').click().run()
        no_errors(at)
        assert any('realised +200.00 USDT' in s.value for s in at.toast), [s.value for s in at.toast]
        at.selectbox(key='sell_holding').set_value(hid)
        at.checkbox(key='sell_all').check()
        at.button(key='sell_submit').click().run()
        no_errors(at)
        assert not any(h['id'] == hid for h in app_pf.holdings)
        assert len(at.dataframe) >= 2      # profit/loss summary + recent sales

    @test('Page: My Portfolio - Reset P/L button')
    def _():
        at = page('My Portfolio')
        at.button(key='reset_confirm').click().run()
        no_errors(at)
        assert not tvbot_ui.get_app()['portfolio'].realised

    @test('Page: Top Picks leads with plain idea cards; the full ranking, early ideas and record are in tabs')
    def _():
        at = page('Top Picks')
        no_errors(at)
        assert len(at.dataframe) >= 3                              # ranking + bull/bear (+ track record once logged)
        assert [t.label for t in at.tabs][:2] == ["Today's ideas", 'Everything scored']
        assert any(e.label.startswith('Track record') for e in at.expander)
        t = texts(at)
        assert 'Overall market mood' in t and 'Only things TradingView rates' in t
        opp, _, _ = core.opportunities(tvbot_ui.get_app()['store'])
        if (opp['Status'] == 'QUALIFIED').any():                   # an idea card, in plain words
            assert 'not the chance' in t and 'Does this work?' in t and 'How much?' in t and 'Next steps' in t, t[:900]
            assert not any('Suggested position size' in s.value for s in at.success), 'one sizing rule only'
        else:
            assert 'No buy idea today' in t
        assert any('TradingView rating only' in e.label for e in at.expander), 'bull/bear tables are folded away'
        assert not [b for b in at.button if (b.key or '').startswith('scan_')], 'scan buttons moved to Market Scan'
        at.toggle(key='tbl_opp_parts').set_value(True).run()       # the score breakdown is one switch away
        no_errors(at)
        at.button(key='exit_top_go').click().run()                 # exit targets for the selected symbol
        no_errors(at)
        t = texts(at)
        assert 'Short-term' in t and 'Medium-term' in t and 'Stretch' in t and 'Safety level' in t, t[-800:]

    @test('Beginner mode: 1 Day chart, refreshes by itself, fewer controls, larger companies in Market Scan')
    def _():
        app_store = tvbot_ui.get_app()['store']
        saved_total = app_store.total_invested
        try:
            app_store.set_interval(core.DASH_TIMEFRAMES['1 Week'])
            app_store.set_beginner(True)
            assert app_store.interval == core.RISK_INTERVAL, 'Beginner mode goes back to the 1 Day chart'
            assert app_store.auto_cfg('Crypto') == {'on': True, 'minutes': S.BEGINNER_AUTO_MINUTES}
            assert app_store.auto['Crypto']['on'] is False, 'your own auto-refresh choices are kept for later'
            assert app_store.scan_min_cap() >= S.BEGINNER_MIN_MARKET_CAP
            q = core.scan_query('US Stocks', core.RISK_INTERVAL, app_store.scan_min_cap())
            assert {'left': 'market_cap_basic', 'operation': 'egreater', 'right': app_store.scan_min_cap()} in q['filter']
            at = page('Dashboard')
            no_errors(at)
            assert not [s for s in at.selectbox if s.key == 'dash_timeframe'], 'no timeframe choice'
            assert not [t for t in at.toggle if (t.key or '').startswith('auto_')], 'no refresh switches'
            assert 'Beginner mode is on' in texts(at)
            home = page('Home')
            no_errors(home)
            assert home.toggle(key='beginner_mode').value is True
            app_store.total_invested = 25000.0                  # remembered with Beginner mode, even without "remember"
            core.save_prefs(app_store)
            s2 = core.MarketStore(pf)
            core.apply_prefs(s2, core.load_prefs())
            assert s2.beginner and s2.total_invested == 25000.0 and s2.interval == core.RISK_INTERVAL
        finally:
            app_store.set_beginner(False)
            app_store.total_invested = saved_total
            if os.path.exists(core.prefs_path()):
                os.remove(core.prefs_path())
            app_store.set_interval(S.INTERVAL)
        assert app_store.wait_ready(20)

    @test('Page: Learn - NZ/Sharesies guide and a working position-size calculator')
    def _():
        at = page('Learn')
        no_errors(at)
        t = texts(at)
        assert 'Sharesies' in t and 'NZ$50,000' in t and 'ird.govt.nz' in t and 'afford to lose' in t
        assert 'What it does' in t and 'Worked example' in t and 'step by step' in t
        no_errors(at)
        assert any('Invest about $1,000' in s.value for s in at.success), [s.value for s in at.success]   # defaults
        at.number_input(key='calc_stop').set_value(30.0).run()     # far-away protective level -> risk rule
        no_errors(at)
        assert any('Invest about $263' in s.value for s in at.success), [s.value for s in at.success]  # 100/18.4*48.4
        at.number_input(key='calc_stop').set_value(60.0).run()     # above the price -> explained, no crash
        assert any('below' in w.value for w in at.warning)

    @test('Page: My Portfolio - Practice switch shows the separate practice portfolio; practice-buy from Top Picks')
    def _():
        app = tvbot_ui.get_app()
        at = page('Top Picks')
        at.button(key='exit_top_go').click().run()
        at.button(key='exit_top_practice').click().run()
        no_errors(at)
        assert any('Practice portfolio' in t.value for t in at.toast), [t.value for t in at.toast]
        added = app['practice'].holdings[-1]
        assert added['ticker'] not in [h['ticker'] for h in app['portfolio'].holdings if h['id'] == added['id']]
        pg = page('My Portfolio')
        pg.segmented_control(key='pf_mode').set_value('Practice').run()
        no_errors(pg)
        assert 'Practice portfolio' in texts(pg) and core.short(added['ticker']) in texts(pg)
        app['practice'].delete(added['id'])

    @test('Page: Market Scan - one button per market; scans only the market clicked')
    def _():
        at = page('Market Scan')
        no_errors(at)
        assert 'not scanned yet' in texts(at)
        assert all(at.button(key=f'scan_{mk}') for mk in S.RUN_MARKETS), 'one scan button per market'
        assert len(at.tabs) >= len(S.RUN_MARKETS)
        store_ = tvbot_ui.get_app()['store']
        at.button(key='scan_US Stocks').click().run()
        no_errors(at)
        end = time.time() + 20
        while (store_.scan['running'] or 'US Stocks' not in store_.scan['results']) and time.time() < end:
            time.sleep(0.1)
        at.run()
        no_errors(at)
        assert set(store_.scan['results']) == {'US Stocks'}, 'only the market clicked is scanned'
        assert at.session_state['scan_tab'] == 'US Stocks', 'the scanned market\'s tab is shown'
        res = store_.scan['results']['US Stocks']
        qual = res['df'][res['df']['Status'] == 'QUALIFIED']
        # Strong Buys + early signals, and the News tab's table when anything QUALIFIED
        assert len(at.dataframe) == 2 + (not qual.empty) and 'Scanned at' in texts(at), texts(at)[-500:]
        assert 'Early signals' in texts(at)
        assert 'Crypto not scanned yet' in texts(at)
        failed = (res['df']['Status'] != 'QUALIFIED').any() or (res['early']['Status'] != 'EARLY').any()
        assert ('Why the other' in texts(at)) == bool(failed), 'failed rules are counted up under the table'
        shown = at.dataframe[0].value
        assert all(w.startswith('✓') for w in shown.loc[shown['Status'] == 'QUALIFIED', 'Why']), 'passing rows say so'
        assert any(t.label == 'News (QUALIFIED)' for t in at.tabs)
        if not qual.empty:                                   # the News tab fills in as headlines arrive
            for t in qual['Ticker']:
                wait_news(t)
            at.run()
            no_errors(at)
            assert 'overall (average' in texts(at) and 'Most positive' in texts(at), texts(at)[-800:]

    @test('Page: Symbol Details shows the 26 metrics in two tables, no raw values')
    def _():
        at = page('Symbol Details')
        no_errors(at)
        assert at.selectbox(key='detail_symbol').value == 'BINANCE:BTCUSDT'
        assert len(at.dataframe) == 2 and 'raw' not in texts(at).lower()
        at.selectbox(key='detail_symbol').set_value('FX_IDC:NZDUSD').run()
        no_errors(at)
        assert 'FX_IDC:NZDUSD' in texts(at)

    @test('Page: Symbol Details and Top Picks show news, rated by FinBERT (fetched in the background)')
    def _():
        news.clear()
        at = page('Symbol Details')
        no_errors(at)
        assert 'News' in texts(at)
        wait_news('BINANCE:BTCUSDT')
        at.run()
        no_errors(at)
        assert 'beats forecasts' in texts(at) and 'Positive' in texts(at), texts(at)[-800:]
        assert len(at.dataframe) == 2, 'news is a list, not another table'
        at = page('Top Picks')
        no_errors(at)
        assert "News on today's picks" in texts(at)

    @test('Page: Symbol Details - timeframe check reuses loaded timeframes; the rest in one request, then kept')
    def _():
        app_store = tvbot_ui.get_app()['store']
        app_store.tf_checks.clear()
        at = page('Symbol Details')
        no_errors(at)
        assert '1 Day' in texts(at) and 'not loaded' in texts(at), 'the Dashboard\'s 1 Day rating is shown straight away'
        before = FAKE['calls']
        at.button(key='tf_check').click().run()
        no_errors(at)
        assert FAKE['calls'] - before == 1, 'the missing timeframes in one request'
        assert 'not loaded' not in texts(at) and 'timeframes are' in texts(at)
        before = FAKE['calls']
        again = page('Symbol Details')                       # page refresh / coming back: nothing re-requested
        assert FAKE['calls'] == before and 'not loaded' not in texts(again)
        assert again.button(key='tf_check').label == 'Refresh'

    @test('Website recovers if its program files are updated while it is running')
    def _():
        import importlib
        old = tvbot_ui.get_app()
        importlib.reload(core)                 # what Streamlit does when a program file changes
        core.tv_get, core.tv_scan, core._sleep = fake_tv, fake_scan, real_sleep
        S.PAUSE_BETWEEN_REQUESTS = 0
        at = page('Dashboard')
        no_errors(at)
        new = tvbot_ui.get_app()
        assert new is not old and isinstance(new['store'], core.MarketStore)
        assert old['store']._stop.is_set(), 'the old background refresher should have been stopped'
        # A late save from the old copy must not wipe a holding added through the new one
        new_pf, old_pf = new['portfolio'], old['portfolio']
        ok, _ = new_pf.add('Crypto', 'eth', 2000, 0.25, new['store'])
        hid = new_pf.holdings[-1]['id']
        assert ok and old_pf.retired
        old_pf.save()
        assert any(h['id'] == hid for h in core.Portfolio().holdings), 'old copy overwrote the new holding'
        new_pf.delete(hid)
        assert new['store'].wait_ready(20)

    @test('Website reloads its logic file if that file is newer than the running copy')
    def _():
        old = tvbot_ui.get_app()
        core.LOADED_FROM_MTIME = 0             # pretend tvbot_core.py was edited after the app started
        at = page('Dashboard')
        no_errors(at)
        new = tvbot_ui.get_app()
        assert core.LOADED_FROM_MTIME == os.path.getmtime(core.__file__), 'logic file was not reloaded'
        core.tv_scan = fake_scan                # the reload brought back the real screener - keep tests offline
        assert new is not old and old['store']._stop.is_set() and hasattr(new['store'], 'interval')
        assert new['store'].wait_ready(20)
        S.PAUSE_BETWEEN_REQUESTS = 0

    @test('Website: a broken setting shows a clear "could not start" page')
    def _():
        saved = list(S.RUN_MARKETS)
        tvbot_ui.get_app()['store'].stop()
        tvbot_ui.get_app.clear()
        S.RUN_MARKETS = ['Crypto', 'Shares']
        try:
            at = AppTest.from_file(os.path.join(ROOT, 'app.py'), default_timeout=60)
            at.run()
            t = texts(at)
            assert 'could not start' in t and "RUN_MARKETS includes 'Shares'" in t, t[:300]
        finally:
            S.RUN_MARKETS = saved
            tvbot_ui.get_app.clear()

    store.stop()


if __name__ == '__main__':
    sys.exit(main())
