import os
import time
import ccxt
import requests
from datetime import datetime, timezone

TARGET_EXCHANGES = ['binance', 'kucoin', 'gateio', 'bybit', 'mexc']
LIQUIDITY_THRESHOLD = 100000       # quoteVolume 24h в USDT
MIN_MARKET_CAP = 50000000          # 50 млн $
COINGECKO_API = os.getenv('COINGECKO_API')


def fetch_coingecko_watchlist():
    """Возвращает монеты с капитализацией > 50 млн $ (все страницы)."""
    if not COINGECKO_API:
        raise ValueError("COINGECKO_API не задан")

    headers = {'Accepts': 'application/json', 'X-Cg-Pro-API-Key': COINGECKO_API}
    url = 'https://pro-api.coingecko.com/api/v3/coins/markets'

    coins = []
    page = 1
    per_page = 250
    retries_429 = 0

    while True:
        params = {
            'vs_currency': 'usd',
            'order': 'market_cap_desc',
            'per_page': per_page,
            'page': page,
            'sparkline': 'false',
            'price_change_percentage': '24h',
        }
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
        except Exception as e:
            print(f"[ERROR] CoinGecko request failed: {e}")
            break

        time.sleep(1.1)  # лимит 1 rps

        if response.status_code == 429:
            retries_429 += 1
            if retries_429 > 3:
                print("[ERROR] Слишком много 429 от CoinGecko, прекращаем")
                break
            print(f"[WARN] 429 от CoinGecko (попытка {retries_429}). Ждём 60 сек...")
            time.sleep(60)
            continue

        if response.status_code != 200:
            print(f"[WARN] CoinGecko HTTP {response.status_code}: {response.text[:200]}")
            break

        try:
            data = response.json()
        except Exception as e:
            print(f"[ERROR] CoinGecko JSON parse failed: {e}")
            break

        if not isinstance(data, list) or not data:
            break

        for coin in data:
            mc = coin.get('market_cap')
            if mc and mc > MIN_MARKET_CAP:
                coins.append({
                    'id': coin['id'],
                    'symbol': coin['symbol'].upper(),
                    'name': coin['name'],
                    'market_cap': mc,
                    'price_change_24h': coin.get('price_change_percentage_24h_in_currency') or 0,
                })

        if len(data) < per_page:
            break
        page += 1

    return coins


def check_liquidity_on_exchanges(symbols):
    """Проверяет ликвидность пар SYMBOL/USDT одним bulk-запросом на биржу."""
    results = []
    wanted = {f"{s}/USDT" for s in symbols}

    exchanges = {
        name: getattr(ccxt, name)({'defaultType': 'spot', 'enableRateLimit': True})
        for name in TARGET_EXCHANGES
    }

    per_exchange_volumes = {}
    for name, ex in exchanges.items():
        try:
            ex.load_markets()
            tickers = ex.fetch_tickers()
            vol_map = {}
            for sym, t in tickers.items():
                if sym not in wanted:
                    continue
                quote_vol = t.get('quoteVolume') or 0  # только USDT-объём
                if quote_vol >= LIQUIDITY_THRESHOLD:
                    vol_map[sym] = quote_vol
            per_exchange_volumes[name] = vol_map
            print(f"[INFO] {name}: ликвидных пар — {len(vol_map)}")
        except Exception as e:
            print(f"[WARN] {name} bulk fetch failed: {e}")
            per_exchange_volumes[name] = {}

    by_symbol = {}
    for name, vol_map in per_exchange_volumes.items():
        for sym, v in vol_map.items():
            by_symbol.setdefault(sym, {})[name] = v

    for sym, ex_vols in by_symbol.items():
        results.append({
            'symbol': sym.split('/')[0],
            'liquid_exchanges': ex_vols,
            'total_volume': sum(ex_vols.values()),
        })

    return results


def build_snapshot():
    print("[INFO] Шаг 1: получение монет с CoinGecko...")
    watchlist = fetch_coingecko_watchlist()
    symbols = [c['symbol'] for c in watchlist]

    print(f"[INFO] Найдено {len(symbols)} монет с кап. > ${MIN_MARKET_CAP / 1e6:.0f}M. Проверка ликвидности...")
    liquid_coins = check_liquidity_on_exchanges(symbols)
    print(f"[INFO] Ликвидных монет: {len(liquid_coins)}")

    # Первое вхождение символа выигрывает (защита от дублей)
    coin_map = {}
    for c in watchlist:
        coin_map.setdefault(c['symbol'], c)

    snapshot = []
    for coin in liquid_coins:
        meta = coin_map.get(coin['symbol'])
        if not meta:
            continue
        snapshot.append({
            'symbol': coin['symbol'],
            'name': meta['name'],
            'market_cap': meta['market_cap'],
            'price_change_24h': meta['price_change_24h'],
            'liquid_exchanges': coin['liquid_exchanges'],
            'total_volume': coin['total_volume'],
            'timestamp': datetime.now(timezone.utc).isoformat(),
        })

    return snapshot
