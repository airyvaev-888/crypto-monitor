# src/fetcher.py
import time
import ccxt
import requests

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
EXCHANGES = ["binance", "kucoin", "gateio", "bybit", "mexc"]
MIN_MARKET_CAP = 50_000_000
MIN_EXCHANGE_VOLUME = 50_000        # порог, чтобы считать, что биржа «торгует» монету
VOLUME_CONFIRM = 500_000            # суммарный объём-подтверждение
CHANGE_THRESHOLD = 15.0             # % за 24ч для кандидата


def fetch_coingecko():
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": 250,
        "page": 1,
        "price_change_percentage": "24h",
    }
    for attempt in range(3):
        r = requests.get(COINGECKO_URL, params=params, timeout=30)
        if r.status_code == 200:
            return [c for c in r.json() if (c.get("market_cap") or 0) >= MIN_MARKET_CAP]
        if r.status_code == 429:
            time.sleep(60)
            continue
        time.sleep(5)
    return []


def fetch_exchange_tickers():
    """Возвращает {symbol_base: {"exchanges": set(...), "total_volume": float}}."""
    result = {}
    for name in EXCHANGES:
        try:
            ex = getattr(ccxt, name)({"enableRateLimit": True})
            tickers = ex.fetch_tickers()
        except Exception as e:
            print(f"[{name}] tickers error: {e}")
            continue
        for symbol, t in tickers.items():
            if not symbol.endswith("/USDT"):
                continue
            base = symbol.split("/")[0]
            qv = t.get("quoteVolume") or 0
            if qv < MIN_EXCHANGE_VOLUME:
                continue
            entry = result.setdefault(base, {"exchanges": set(), "total_volume": 0.0})
            entry["exchanges"].add(name)
            entry["total_volume"] += qv
    return result


def _make_exchange(name):
    return getattr(ccxt, name)({"enableRateLimit": True})


def compute_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 2)


def enrich_with_rsi(coins):
    """Для каждого кандидата тянем OHLCV с той биржи, где он впервые встретился."""
    for c in coins:
        ex_name = next(iter(c["exchanges"]))
        try:
            ex = _make_exchange(ex_name)
            ohlcv = ex.fetch_ohlcv(f"{c['symbol']}/USDT", timeframe="1h", limit=100)
            c["rsi"] = compute_rsi([row[4] for row in ohlcv])
        except Exception as e:
            print(f"[RSI {c['symbol']}] {e}")
            c["rsi"] = None
    return coins


def fetch_market_data():
    cg = fetch_coingecko()
    tickers = fetch_exchange_tickers()
    coins = []
    for c in cg:
        base = c["symbol"].upper()
        ex_info = tickers.get(base)
        if not ex_info:
            continue
        change = c.get("price_change_percentage_24h") or 0
        coins.append({
            "symbol": base,
            "name": c["name"],
            "price": c["current_price"],
            "change_24h": round(change, 2),
            "market_cap": c["market_cap"],
            "volume": ex_info["total_volume"],
            "exchanges": ex_info["exchanges"],
            "exchange_count": len(ex_info["exchanges"]),
            "rsi": None,
        })

    # OHLCV дёргаем только для тех, кто и так уже прошёл базовые фильтры —
    # экономим запросы к биржам и не ловим rate-limit.
    candidates = [
        c for c in coins
        if abs(c["change_24h"]) >= CHANGE_THRESHOLD
        and c["volume"] >= VOLUME_CONFIRM
        and c["exchange_count"] >= 2
    ]
    enrich_with_rsi(candidates)
    return coins
