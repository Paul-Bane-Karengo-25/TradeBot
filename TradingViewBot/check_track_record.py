"""
TradingView Analysis Bot - check the Track record without opening the app.

Fetches today's daily prices for every pick in signals.json (one request per market) and prints how the
QUALIFIED and EARLY picks have done against their benchmark. Read-only: it never changes any file, so it is safe to
run while the app is open.

Run it with  check_track_record.bat  (Windows)  or  bash check_track_record.sh  (Mac).
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)                       # settings.PORTFOLIO_FILE (and so signals.json) is relative to the app folder

import pandas as pd                  # noqa: E402

import settings as S                 # noqa: E402
import tvbot_core as core            # noqa: E402

COLUMNS = ['Date', 'Market', 'Symbol', 'Score', 'Then', 'Now', 'Return %', 'Compared with', 'Benchmark %', 'Beat it',
           *[f'After {label} %' for label in core.SIGNAL_HORIZONS], 'Lowest %', 'Hit it', 'With exit %',
           'Price from']


class Prices:
    """Just enough of the app's data store for core.track_record: the prices fetched here."""
    interval = core.RISK_INTERVAL

    def __init__(self, raw):
        self.raw = raw

    def analysis(self, ticker, interval=None):
        return self.raw.get(ticker)


def pct(v):
    return '-' if v is None or pd.isna(v) else f'{v:+.1f}%'


def share(v):
    return '-' if v is None or pd.isna(v) else f'{v:.0f}%'


def fetch_prices(log):
    """{ticker: analysis} for every logged pick and its benchmark: one request per market."""
    wanted = {}
    for s in log:
        wanted.setdefault(s.get('market'), set()).update({s['ticker']} | ({s['bench']} if s.get('bench') else set()))
    raw = {}
    for mk, tickers in wanted.items():
        if mk not in S.MARKETS:
            print(f'  {mk}: not in settings.py - using the last prices the app saw.')
            continue
        print(f'  Getting {mk} prices from TradingView...')
        try:
            _, got, _ = core.analyse(mk, core.RISK_INTERVAL, extra=sorted(tickers))
            raw.update(got)
        except Exception as e:
            print(f'  {mk}: could not get prices ({e}) - using the last prices the app saw.')
    return raw


def show(kind, df, summ):
    word = core.SIGNAL_KINDS[kind]
    print('\n' + '=' * 100)
    print(f' {word} picks')
    print('=' * 100)
    if summ is None:
        print(' Nothing logged yet. Picks are logged automatically while the app is running.')
        return
    print(f" Logged: {summ['n']} since {summ['since']}   (at least a day old: {summ['n_aged']})")
    print(f" Average return: {pct(summ['avg'])}   Benchmark, same dates: {pct(summ['bench_avg'])}   "
          f"Beat it: {share(summ['beat_pct'])}   Went up: {share(summ['win_pct'])}")
    print(f" With the exit rule: {pct(summ['exit_avg'])}   Fell to protective level: {summ['n_hit']}")
    print(' At fixed ages: ' + '   '.join(
        f"{label}: {pct(v['avg'])}, beat {share(v['beat_pct'])} ({v['n']})" if v['n'] else f'{label}: none yet'
        for label, v in summ['horizons'].items()))
    if summ['n_missing']:
        print(f" {summ['n_missing']} pick(s) have no price yet and are left out of the averages.")
    out = df.reindex(columns=COLUMNS).copy()
    for c in out.columns:
        if c.endswith('%'):
            out[c] = out[c].map(pct)
    for c in ('Beat it', 'Hit it'):
        out[c] = out[c].map({True: 'Yes', False: 'No'}).fillna('-')
    out['Score'] = out['Score'].map(lambda v: f'{v:.0f}')
    with pd.option_context('display.width', 250, 'display.max_columns', None, 'display.max_rows', None):
        print()
        print(out.to_string(index=False, na_rep='-'))


def main():
    print('TradingView Bot - Track record check (read-only)')
    log = core.load_signals()
    if not log:
        print(f'\nNothing logged yet ({core.signals_path()} is missing or empty).')
        return 0
    store = Prices(fetch_prices(log))
    for kind in core.SIGNAL_KINDS:
        df, summ = core.track_record(store, kind)
        show(kind, df, summ)
    print('\nThis is a short record, so read it with care: a few weeks of picks is mostly noise. Not financial advice.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
