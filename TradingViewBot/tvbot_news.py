"""
TradingView Analysis Bot - news headlines and their sentiment (Top Picks and Symbol Details).

Headlines come from free sources only, and only headlines are read (no article pages, nothing behind a paywall):
  * US shares: Finnhub's company-news API when FINNHUB_API_KEY is set in settings.py (a free key from finnhub.io),
    otherwise Google News.
  * Everything else: Google News RSS, searched by company or coin name (or the currency pair).
Sentiment is FinBERT (ProsusAI/finbert), a model trained on financial news, run on THIS computer. The first time it's
used it downloads once (about 440 MB) and loads in the background; until then headlines show without sentiment.

Everything runs in one background thread, one request at a time, so news never holds up a page or the
TradingView requests. Results are kept for NEWS_CACHE_MINUTES.
"""
import datetime as dt
import email.utils
import re
import threading
import time
import xml.etree.ElementTree as ET

import settings as S
import tvbot_core as core

FINBERT = 'ProsusAI/finbert'
POSITIVE_AT, NEGATIVE_AT = 0.15, -0.15          # average sentiment (-1..+1) at or beyond which news counts as such
PAUSE_SECONDS = 1.0                             # between news requests (be polite to Google News)
LABEL_COLOURS = {'Positive': core.TONE['good'], 'Negative': core.TONE['bad'], 'Neutral': core.TONE['neutral']}


def _setting(name, default):
    return getattr(S, name, default)


def enabled():
    return bool(_setting('NEWS_ENABLED', True))


# ---------------------------------------------------------------- fetching (swappable, so the tests stay offline)
def _http_get(url, params=None):
    import requests                              # installed with tradingview-ta
    r = requests.get(url, params=params, timeout=20, headers={'User-Agent': 'Mozilla/5.0 (news reader)'})
    r.raise_for_status()
    return r


http_get = _http_get


# ---------------------------------------------------------------- what to search for
_SUFFIXES = {'inc', 'inc.', 'corp', 'corp.', 'corporation', 'limited', 'ltd', 'ltd.', 'plc', 'co', 'co.',
             'company', 'class', 'a', 'b', 'c', 'new', 'ordinary', 'shares', 'common', 'stock', 'holdings', 'the',
             'nv', 'n.v.', 'sa', 's.a.', 'ag', 'se', '&', 'and', '-'}
_names = {}                                      # ticker -> company / coin name from TradingView (never changes)
_names_lock = threading.Lock()


def clean_name(description):
    """'Fisher & Paykel Healthcare Corporation Limited' -> 'Fisher & Paykel Healthcare'; 'Bitcoin / TetherUS' ->
    'Bitcoin'. Legal endings are dropped so the search finds everyday mentions of the company."""
    name = (description or '').split(' / ')[0].replace(',', ' ').strip()
    words = name.split()
    while len(words) > 1 and words[-1].lower() in _SUFFIXES:
        words.pop()
    return ' '.join(words)


def names(market, tickers):
    """{ticker: name} - one TradingView request for the names not looked up yet in this market, then remembered."""
    with _names_lock:
        for t in tickers:                        # a market scan already brought the name back with its data
            hit = core._scanned.get(t)
            if t not in _names and hit and isinstance(hit[2].get('description'), str):
                _names[t] = clean_name(hit[2]['description'])
        need = [t for t in tickers if t not in _names]
    if need and market in S.MARKETS:
        try:
            reply = core.scan(S.MARKETS[market]['screener'],
                              {'symbols': {'tickers': need, 'query': {'types': []}}, 'columns': ['description']})
            got = {r.get('s'): (r.get('d') or [None])[0] for r in reply.get('data') or []}
        except Exception:                        # TradingView busy: search by symbol this time, try names again later
            return {t: _names.get(t) for t in tickers}
        with _names_lock:
            for t in need:
                _names[t] = clean_name(got.get(t)) if isinstance(got.get(t), str) else None
    return {t: _names.get(t) for t in tickers}


def search_query(market, ticker, name=None):
    """The Google News search for a symbol."""
    sym = core.short(ticker)
    if market == 'Forex' and len(sym) == 6:
        return f'"{sym[:3]}/{sym[3:]}" forex'
    if market == 'Crypto':
        coin = name or next((sym[:-len(q)] for q in core.CRYPTO_QUOTES if sym.endswith(q) and len(sym) > len(q)), sym)
        return f'"{coin}" crypto'
    who = f'"{name}"' if name else f'"{sym}"'
    if market == 'NZ Stocks':                    # (stops e.g. a Nigerian "Genesis Energy" crowding out the NZX one)
        return f'{who} (NZX OR shares OR "New Zealand")'
    return f'{who} (stock OR shares OR Nasdaq OR NYSE)'


def relevance_terms(market, ticker, name=None):
    """Words a Google News headline must contain (case-sensitive) to be about this symbol, or None to keep all
    (forex: the search is already specific). E.g. Apple -> keeps 'Apple shares rise', drops 'apple orchard fire'."""
    if market == 'Forex':
        return None
    sym = core.short(ticker)
    terms = {sym}
    if market == 'Crypto':
        terms.add(next((sym[:-len(q)] for q in core.CRYPTO_QUOTES if sym.endswith(q) and len(sym) > len(q)), sym))
    if name:
        terms.add(name)
        words = name.split()
        if len(words) >= 3:
            terms.add(' '.join(words[:2]))       # 'Fisher & Paykel Healthcare' -> also 'Fisher & Paykel'
    return terms


_JUNK = re.compile(r'stock price, news, quote|quote and history|returns chart|stock price (today|& chart)|'
                   r'share price (today|& chart)', re.I)


_TAGGED = re.compile(r'\(([A-Z]{2,8}):([A-Z0-9.]{1,10})\)')    # e.g. '(NYSE:GEL)', '(ASX:FBU)'


def is_relevant(title, terms, symbol=None):
    if _JUNK.search(title):                      # quote / chart pages, not news
        return False
    tags = {s for _, s in _TAGGED.findall(title)}
    if symbol and tags and symbol not in tags:   # tagged with another company's ticker: a look-alike name
        return False                             # (e.g. 'Apple Hospitality REIT (NYSE:APLE)' for Apple)
    return terms is None or any(re.search(rf'(?<![\w]){re.escape(t)}(?![\w])', title) for t in terms)


# ---------------------------------------------------------------- sources
def _clean_title(title, source):
    """Google News titles end in ' - Source'; drop it (the source has its own column)."""
    title = (title or '').strip()
    if source and title.endswith(f' - {source}'):
        title = title[:-len(source) - 3].rstrip()
    return title


def google_news(query, market):
    """Headlines from Google News RSS for a search, newest first."""
    nz = market == 'NZ Stocks'
    days = int(_setting('NEWS_MAX_AGE_DAYS', 7))
    params = {'q': f'{query} when:{days}d', 'hl': 'en-NZ' if nz else 'en-US', 'gl': 'NZ' if nz else 'US',
              'ceid': 'NZ:en' if nz else 'US:en'}
    root = ET.fromstring(http_get('https://news.google.com/rss/search', params).content)
    items = []
    for it in root.iter('item'):
        src_el = it.find('source')
        source = (src_el.text or '').strip() if src_el is not None else ''
        try:
            published = email.utils.parsedate_to_datetime(it.findtext('pubDate') or '')
        except (TypeError, ValueError):
            published = None
        title = _clean_title(it.findtext('title'), source)
        if title:
            items.append({'title': title, 'source': source, 'url': (it.findtext('link') or '').strip(),
                          'published': published})
    return items


def finnhub_news(ticker):
    """US company news from Finnhub (needs FINNHUB_API_KEY)."""
    days = int(_setting('NEWS_MAX_AGE_DAYS', 7))
    today = dt.date.today()
    rows = http_get('https://finnhub.io/api/v1/company-news',
                    {'symbol': core.short(ticker), 'from': (today - dt.timedelta(days=days)).isoformat(),
                     'to': today.isoformat(), 'token': _setting('FINNHUB_API_KEY', '')}).json()
    items = []
    for r in rows if isinstance(rows, list) else []:
        when = r.get('datetime')
        items.append({'title': (r.get('headline') or '').strip(), 'source': r.get('source') or '',
                      'url': r.get('url') or '',
                      'published': dt.datetime.fromtimestamp(when, dt.timezone.utc) if core.is_num(when) else None})
    return [i for i in items if i['title']]


def headlines(market, ticker, name=None):
    """(source name, newest-first headlines from the last NEWS_MAX_AGE_DAYS, at most NEWS_PER_SYMBOL, no repeats)."""
    if market == 'US Stocks' and _setting('FINNHUB_API_KEY', ''):
        source, items = 'Finnhub', finnhub_news(ticker)
    else:
        terms = relevance_terms(market, ticker, name)
        source = 'Google News'
        sym = None if market == 'Forex' else core.short(ticker)
        items = [i for i in google_news(search_query(market, ticker, name), market)
                 if is_relevant(i['title'], terms, sym)]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=int(_setting('NEWS_MAX_AGE_DAYS', 7)))
    seen, out = set(), []
    for i in sorted(items, key=lambda i: i['published'] or cutoff, reverse=True):
        key = re.sub(r'\W+', ' ', i['title'].lower()).strip()
        if key in seen or (i['published'] is not None and i['published'] < cutoff):
            continue
        seen.add(key)
        out.append(i)
    return source, out[:int(_setting('NEWS_PER_SYMBOL', 10))]


# ---------------------------------------------------------------- FinBERT
def _make_pipeline():
    """Load FinBERT (downloads it the first time). Returns a function: list of texts -> list of {label: prob}."""
    from transformers import pipeline           # imported here: the app works without it (no sentiment)
    pipe = pipeline('text-classification', model=FINBERT, top_k=None, truncation=True)

    def classify(texts):
        return [{d['label'].lower(): d['score'] for d in res} for res in pipe(list(texts), batch_size=16)]
    return classify


make_pipeline = _make_pipeline
MODEL = {'state': 'not loaded', 'classify': None, 'error': ''}   # not loaded / loading / ready / missing / error
_model_lock = threading.Lock()


def model_installed():
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in ('transformers', 'torch'))


def ensure_model():
    """Load FinBERT once (called from the news thread). Returns the classify function, or None."""
    with _model_lock:
        if MODEL['state'] == 'ready':
            return MODEL['classify']
        if MODEL['state'] in ('missing', 'error'):
            return None
        if make_pipeline is _make_pipeline and not model_installed():
            MODEL['state'] = 'missing'
            return None
        MODEL['state'] = 'loading'
    try:
        classify = make_pipeline()
    except Exception as e:                       # e.g. no internet for the first download
        with _model_lock:
            MODEL.update(state='error', error=str(e) or type(e).__name__)
        return None
    with _model_lock:
        MODEL.update(state='ready', classify=classify)
    return classify


def label_of(probs):
    return max(('positive', 'negative', 'neutral'), key=lambda k: probs.get(k, 0)).title()


def summarise(items):
    """Overall sentiment of a symbol's scored headlines: {'label', 'score' -1..+1, 'n', 'pos', 'neg', 'neu'}."""
    scored = [i for i in items if i.get('score') is not None]
    if not scored:
        return None
    avg = sum(i['score'] for i in scored) / len(scored)
    label = 'Positive' if avg >= POSITIVE_AT else 'Negative' if avg <= NEGATIVE_AT else 'Neutral'
    return {'label': label, 'score': round(avg, 2), 'n': len(scored),
            'pos': sum(i['label'] == 'Positive' for i in scored), 'neg': sum(i['label'] == 'Negative' for i in scored),
            'neu': sum(i['label'] == 'Neutral' for i in scored)}


# ---------------------------------------------------------------- the news store (one background thread)
_cache = {}            # ticker -> {'time', 'market', 'source', 'items': [...], 'summary', 'error'}
_pending = []          # tickers waiting for the thread (in order)
_markets = {}          # ticker -> market, for the thread
_lock = threading.Lock()
_thread = [None]


def get(ticker):
    """What the app has for a ticker right now (never fetches): the cache entry, or None."""
    with _lock:
        return _cache.get(ticker)


def is_pending(ticker):
    with _lock:
        return ticker in _pending


def fresh(ticker):
    e = get(ticker)
    return e is not None and time.time() - e['time'] < 60 * float(_setting('NEWS_CACHE_MINUTES', 60))


def request(market, tickers):
    """Ask for news on these tickers (fetched in the background unless already fresh). Returns how many queued."""
    if not enabled():
        return 0
    added = 0
    with _lock:
        for t in tickers:
            if t not in _pending and not (t in _cache and time.time() - _cache[t]['time']
                                          < 60 * float(_setting('NEWS_CACHE_MINUTES', 60))):
                _pending.append(t)
                _markets[t] = market
                added += 1
        if added and (_thread[0] is None or not _thread[0].is_alive()):
            _thread[0] = threading.Thread(target=_run, daemon=True, name='news')
            _thread[0].start()
    return added


def _score(entries):
    """Score every headline not scored yet (FinBERT loads the first time)."""
    todo = [i for e in entries for i in e['items'] if i.get('score') is None]
    if not todo:
        return
    classify = ensure_model()
    if classify is None:
        return
    probs = classify([i['title'] for i in todo])
    for i, p in zip(todo, probs):
        i.update(score=round(p.get('positive', 0) - p.get('negative', 0), 3), label=label_of(p))
    with _lock:
        for e in entries:
            e['summary'] = summarise(e['items'])


def _run():
    """The news thread: fetch each waiting ticker's headlines, then score them, until nothing is left."""
    while True:
        with _lock:
            if not _pending:
                _thread[0] = None
                return
            t = _pending[0]
            mk = _markets.get(t)
            same = [p for p in _pending if _markets.get(p) == mk]    # look up their names in one request
        try:
            name = names(mk, same).get(t) if mk in ('US Stocks', 'NZ Stocks', 'Crypto') else None
            source, items = headlines(mk, t, name)
            entry = {'time': time.time(), 'market': mk, 'source': source, 'items': items, 'summary': None,
                     'error': ''}
        except Exception as e:
            entry = {'time': time.time(), 'market': mk, 'source': '', 'items': [], 'summary': None,
                     'error': str(e) or type(e).__name__}
        with _lock:
            _cache[t] = entry
        try:
            _score([entry])
        except Exception as e:                   # a scoring problem must not lose the headlines
            entry['error'] = f'sentiment failed: {e}'
        with _lock:
            if t in _pending:
                _pending.remove(t)
        time.sleep(PAUSE_SECONDS)


def summary_for_log(ticker):
    """(average sentiment, number of headlines) if the app already has scored news for a ticker, else (None, 0).
    Used by the track record; never fetches."""
    e = get(ticker)
    s = e and e.get('summary')
    return (s['score'], s['n']) if s else (None, 0)


def status():
    """One line about the sentiment model, for the page."""
    st = MODEL['state']
    if st == 'ready':
        return ''
    if st == 'missing' or (st == 'not loaded' and make_pipeline is _make_pipeline and not model_installed()):
        return ('Sentiment is off: FinBERT is not installed. Run setup again (or `pip install torch transformers`), '
                'then restart the app.')
    if st == 'error':
        return f"Sentiment is off: FinBERT could not load ({MODEL['error']})."
    if st == 'loading':
        return ('Loading FinBERT, the sentiment model (the first time it downloads about 440 MB, so this can take a '
                'few minutes). Headlines show now; their sentiment appears when it is ready.')
    return ''


def clear():
    """Forget all news (used by the tests)."""
    with _lock:
        _cache.clear()
        _pending.clear()
