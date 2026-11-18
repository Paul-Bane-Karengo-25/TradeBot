"""
TradingView Analysis Bot - SETTINGS
===================================
Change what the app watches here. Open this file in any text editor (Notepad on Windows, TextEdit on a Mac),
make your change, save, then close the app's black window and start the app again.
Keep the quote marks and commas exactly as they are.
"""
from tradingview_ta import Interval

# Each market: TradingView "screener", the default exchange, and the symbols to watch.
# Put 'EXCHANGE:SYMBOL' in a watchlist to use a different exchange, e.g. 'NYSE:KO'.
MARKETS = {
    # 'benchmark': what relative strength is measured against. 'regime': symbols that decide whether the
    # market as a whole is bullish or bearish (both are fetched in the same request as the watchlist).
    'Crypto': {
        'screener': 'crypto', 'exchange': 'BINANCE',
        'benchmark': 'BTCUSDT', 'regime': ['BTCUSDT'],
        'watchlist': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT',
                      'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'LINKUSDT', 'DOTUSDT'],
    },
    'US Stocks': {
        # Top 20 US stocks by market cap (Nov 2026). NYSE-listed ones need the NYSE: prefix.
        'screener': 'america', 'exchange': 'NASDAQ', 'currency': 'USD',
        'benchmark': 'AMEX:SPY', 'regime': ['AMEX:SPY', 'NASDAQ:QQQ'],      # S&P 500 and Nasdaq-100 ETFs
        # Trading hours (local time, Mon-Fri). While closed, the data can't change, so it isn't re-fetched.
        'hours': {'tz': 'America/New_York', 'open': '09:30', 'close': '16:00'},
        'watchlist': ['AAPL', 'NVDA', 'MSFT', 'GOOGL', 'AMZN', 'META', 'AVGO', 'TSLA',
                      'NYSE:LLY', 'NYSE:BRK.B', 'WMT', 'NYSE:JPM', 'AMD', 'NYSE:V',
                      'NYSE:JNJ', 'NYSE:XOM', 'NYSE:MA', 'NYSE:ABBV', 'COST', 'PLTR'],
    },
    'Forex': {
        'screener': 'forex', 'exchange': 'FX_IDC',
        'watchlist': ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD',
                      'NZDUSD', 'EURGBP', 'EURJPY', 'GBPJPY', 'AUDNZD', 'NZDJPY'],
    },
    'NZ Stocks': {
        # 20 of the largest NZX companies (Australian banks dual-listed on the NZX are left out).
        'screener': 'newzealand', 'exchange': 'NZX', 'currency': 'NZD',
        'benchmark': 'NZX:NZ50G', 'regime': ['NZX:NZ50G'],                 # S&P/NZX 50 index
        'hours': {'tz': 'Pacific/Auckland', 'open': '10:00', 'close': '16:45'},
        # NZX trades far less than the US: liquidity limit in NZD per day. 200K (Nov 2026): 49 of 113 NZX companies
        # pass, covering 98% of all NZX trading; a NZ$2,000 order is about 1% of a day's trading at this level.
        'min_daily_value': 200_000,
        'watchlist': ['FPH', 'AIA', 'IFT', 'MEL', 'MCY', 'CEN', 'FCG', 'MFT', 'EBO', 'SPK',
                      'CNU', 'ATM', 'POT', 'FBU', 'AIR', 'SUM', 'RYM', 'GNE', 'VCT', 'FRW'],
    },
}

# Which markets to show (remove any you don't want)
RUN_MARKETS = ['Crypto', 'US Stocks', 'NZ Stocks', 'Forex']

# Chart timeframe for the ratings. Options: INTERVAL_1_HOUR, INTERVAL_4_HOURS, INTERVAL_1_DAY,
# INTERVAL_1_WEEK, INTERVAL_1_MONTH (also 1/5/15/30 minutes and 2 hours)
INTERVAL = Interval.INTERVAL_1_DAY

# Results younger than this (minutes) are reused when you switch timeframe, instead of asking TradingView again.
# (How often each market refreshes BY ITSELF is set on the Dashboard: each market has its own switch and interval.)
POLL_MINUTES = 5

# Seconds to wait between requests to TradingView (lower than 2 risks being blocked for a while)
PAUSE_BETWEEN_REQUESTS = 3

# ---- Composite Opportunity Score (Top Picks page) ----
# These are starting points, not proven best values - ideally they'd be tuned by backtesting.
ENTRY_MIN_SCORE = 70            # minimum score (0-100) for a new position
BEAR_MIN_SCORE = 85             # minimum score when that market's regime is Bearish
WIN_MARGIN = 5                  # the best pick must lead the next qualifier by this many points, or it's capped at 50%
MAX_EXTENSION_PCT = 12          # reject if the price is more than this % above its 20-bar average
MAX_EXTENSION_PCT_FX = 3        # the same for forex (currencies move about a tenth as much as shares)
MIN_DAILY_DOLLAR_VOLUME = 2_000_000    # reject if less than this is traded per day (crypto: on Binance only)
                                       # (a market's own 'min_daily_value' above overrides it, e.g. NZ Stocks)

# ---- Early Entry Score (Top Picks, "Early" table) ----
# A second, separate score that looks for trends that are TURNING UP, before TradingView's rating reaches Strong Buy.
# Earlier entries mean more false starts: compare its track record with the main score before trusting it.
EARLY_MIN_SCORE = 60            # minimum early score (0-100) to be marked EARLY
EARLY_BEAR_MIN_SCORE = 80       # minimum early score when that market's regime is Bearish

# ---- News and sentiment (Top Picks and Symbol Details) ----
# Recent headlines for each pick, rated Positive / Neutral / Negative by FinBERT (a financial-news model that runs on
# this computer). Shown alongside the scores; it does NOT change them.
NEWS_ENABLED = True
FINNHUB_API_KEY = ''            # optional free key from finnhub.io for better US company news ('' = Google News)
NEWS_MAX_AGE_DAYS = 7           # only headlines from the last this-many days
NEWS_PER_SYMBOL = 10            # at most this many headlines per symbol
NEWS_CACHE_MINUTES = 60         # news is fetched again after this long

# ---- Full market scan (Top Picks, "Run full scan" button) ----
# Finds Strong Buys that are NOT in your watchlists and scores them the same way (one request per market).
SCAN_MIN_SCORE = 65                    # list scanned symbols scoring at least this
SCAN_EARLY_MIN_SCORE = 60              # list scanned symbols whose EARLY score is at least this
SCAN_MIN_MARKET_CAP = 0                # US shares smaller than this (in USD) are skipped; 0 = scan every size
SCAN_MAX_PER_MARKET = 5000             # at most this many Strong Buys are scored per market (largest first)

# ---- Beginner mode (switch it on or off on the Home page; the app remembers your choice) ----
# Simpler screens: ratings always use the 1 Day chart, every market refreshes by itself while it trades, and
# Market Scan leaves out small US companies (which can swing wildly and are easy to manipulate).
BEGINNER_MODE = True                   # what the app starts with the very first time
BEGINNER_AUTO_MINUTES = 15             # in Beginner mode, each market refreshes by itself this often while it trades
BEGINNER_MIN_MARKET_CAP = 2_000_000_000   # in Beginner mode, Market Scan skips US companies worth less (USD)

# Where your holdings, sales and profit/loss are saved
PORTFOLIO_FILE = 'portfolio.json'
