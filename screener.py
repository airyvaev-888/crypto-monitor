"""Ежедневный скринер: отбирает ликвидные монеты с CMC, проверяет стакан,
сохраняет в history.json, отправляет отчёт в ntfy.
Асинхронная версия с кэшем рынков."""
import asyncio
import json
import os
from datetime import datetime, timezone

import apprise
import ccxt.async_support as ccxt
import requests

CMC_API_KEY = os.environ['CMC_API_KEY']
APPRISE_URL = os.environ['APPRISE_URL']
HISTORY_FILE = 'history.json'
MARKETS_CACHE = 'markets_cache.json'

EXCHANGE_IDS = ['binance', 'kucoin', 'bybit', 'mexc', 'gateio']

MIN_MARKET_CAP = 100_000_000
MIN_VOLUME_24H = 1_000_000
MAX_COINS = 500

STABLECOINS = {
    'USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'USDD',
    'FDUSD', 'USDE', 'PYUSD', 'USD1', 'USDP',
}

MIN_DEPTH_USD = 10_000
DEPTH_BAND_PCT = 0.02
MAX_SPREAD_PCT = 0.01
MARKETS_TTL_SECONDS = 3600


def fetch_cmc_listings():
    # ... (без изменений) ...
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    params = {'start': 1, 'limit': MAX_COINS, 'convert': 'USD',
              'sort': 'market_cap', 'sort_dir': 'desc'}
    r = requests.get(url, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    out = []
    for coin in r.json().get('data', []):
        if coin['symbol'].upper() in STABLECOINS:
            continue
        q = coin['quote']['USD']
        if q['market_cap'] < MIN_MARKET_CAP or q['volume_24h'] < MIN_VOLUME_24H:
            continue
        out.append({
            'symbol': coin['symbol'],
            'name': coin['name'],
            'cmc_id': coin['id'],
            'market_cap': q['market_cap'],
            'volume_24h': q['volume_24h'],
        })
    return out


def load_cache(path):
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
                if (datetime.now(timezone.utc) - datetime.fromisoformat(data['fetched_at'])).total_seconds() < MARKETS_TTL_SECONDS:
                    return data['markets']
        except Exception:
            pass
    return None


def save_cache(path, data):
    try:
        with open(path, 'w') as f:
            json.dump({'fetched_at': datetime.now(timezone.utc).isoformat(), 'markets': data}, f, indent=2)
    except Exception:
        pass


async def check_liquidity_async(exchange, symbol, semaphore):
    async with semaphore:
        try:
            ob = await exchange.fetch_order_book(symbol, limit=50)
            bids, asks = ob.get('bids', []), ob.get('asks', [])
            if not bids or not asks:
                return None
            best_bid, best_ask = bids[0][0], asks[0][0]
            mid = (best_bid + best_ask) / 2
            spread_pct = (best_ask - best_bid) / mid
            if spread_pct > MAX_SPREAD_PCT:
                return None
            bid_band = mid * (1 - DEPTH_BAND_PCT)
            ask_band = mid * (1 + DEPTH_BAND_PCT)
            bid_depth = sum(p * a for p, a in bids if p >= bid_band)
            ask_depth = sum(p * a for p, a in asks if p <= ask_band)
            depth = min(bid_depth, ask_depth)
            if depth < MIN_DEPTH_USD:
                return None
            return {'spread_pct': round(spread_pct * 100, 3),
                    'depth_usd': round(depth, 0)}
        except Exception as e:
            print(f"Стакан {exchange.id} {symbol}: {e}")
            return None


async def main():
    coins = fetch_cmc_listings()
    print(f"CMC: {len(coins)} монет прошли по капе/объёму")

    # Кэш рынков
    markets_cache = load_cache(MARKETS_CACHE)
    exchanges, markets = {}, {}
    semaphore_map = {}

    for ex_id in EXCHANGE_IDS:
        try:
            ex = getattr(ccxt, ex_id)({'enableRateLimit': True})
            if markets_cache and ex_id in markets_cache:
                ex.markets = markets_cache[ex_id]
            else:
                await ex.load_markets()
                if ex_id not in markets_cache:
                    markets_cache = markets_cache or {}
                    markets_cache[ex_id] = ex.markets
            exchanges[ex_id] = ex
            markets[ex_id] = set(ex.markets.keys())
            semaphore_map[ex_id] = asyncio.Semaphore(10)
            print(f"{ex_id}: {len(markets[ex_id])} рынков")
        except Exception as e:
            print(f"Биржа {ex_id} недоступна: {e}")

    save_cache(MARKETS_CACHE, markets_cache)

    liquid = []
    tasks = []
    for coin in coins:
        pair = f"{coin['symbol']}/USDT"
        for ex_id in EXCHANGE_IDS:
            if ex_id not in markets or pair not in markets[ex_id]:
                continue
            tasks.append(check_liquidity_async(exchanges[ex_id], pair, semaphore_map[ex_id]))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    task_idx = 0
    for coin in coins:
        pair = f"{coin['symbol']}/USDT"
        for ex_id in EXCHANGE_IDS:
            if ex_id not in markets or pair not in markets[ex_id]:
                continue
            res = results[task_idx]
            task_idx += 1
            if isinstance(res, dict):
                liquid.append({
                    'exchange': ex_id,
                    'symbol': pair,
                    'cmc_id': coin['cmc_id'],
                    'name': coin['name'],
                    'market_cap': coin['market_cap'],
                    'volume_24h': coin['volume_24h'],
                    'spread_pct': res['spread_pct'],
                    'depth_usd': res['depth_usd'],
                })

    print(f"Ликвидных пар: {len(liquid)}")

    with open(HISTORY_FILE, 'w') as f:
        json.dump({
            'liquid_symbols': liquid,
            'last_updated': datetime.now(timezone.utc).isoformat(),
            'total': len(liquid),
        }, f, indent=2, ensure_ascii=False)

    apobj = apprise.Apprise()
    apobj.add(APPRISE_URL)
    body = (f"📊 Скринер завершён\n"
            f"Монет (CMC): {len(coins)}\n"
            f"Ликвидных пар: {len(liquid)}")
    top = sorted(liquid, key=lambda x: -x['depth_usd'])[:5]
    if top:
        body += "\n\nТоп по глубине стакана:\n" + "\n".join(
            f"• {t['symbol']} на {t['exchange']}: ${t['depth_usd']:,.0f}"
            for t in top)
    try:
        apobj.notify(title="Crypto Screener", body=body)
    except Exception as e:
        print(f"Ошибка уведомления: {e}")

    await asyncio.gather(*[ex.close() for ex in exchanges.values()])


if __name__ == '__main__':
    asyncio.run(main())
