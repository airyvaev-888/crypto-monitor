import ccxt
import time
import random
import pandas as pd
from datetime import datetime, timedelta
import logging
import requests
import os

TARGET_EXCHANGES = ['kucoin', 'gateio', 'mexc', 'okx', 'bitget']

def get_exchange_instance(exchange_id):
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'}
    })
    return exchange

def _cg_get_json(url, params, headers, max_retries=6, base_delay=15.0, timeout=30):
    delay = base_delay
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                wait = max(int(ra), delay) if ra and ra.isdigit() else delay
                wait += random.uniform(0, 3)
                logging.warning(f"CoinGecko 429 (попытка {attempt}/{max_retries}), ждём {wait:.1f}с")
                time.sleep(wait)
                delay = min(delay * 1.8, 120)
                continue
            if 500 <= r.status_code < 600:
                logging.warning(f"CoinGecko {r.status_code} (попытка {attempt}/{max_retries}), ждём {delay:.1f}с")
                time.sleep(delay)
                delay = min(delay * 1.8, 120)
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            logging.warning(f"Сетевая ошибка (попытка {attempt}/{max_retries}): {e}")
            time.sleep(delay)
            delay = min(delay * 1.8, 120)
    raise RuntimeError(f"CoinGecko: {url} недоступен после {max_retries} попыток")

def fetch_exchange_tickers(symbols=None):
    exchange_data = {}
    
    for ex_id in TARGET_EXCHANGES:
        try:
            exchange = get_exchange_instance(ex_id)
            logging.info(f"[{ex_id}] Загрузка списка рынков...")
            exchange.load_markets()
            tickers = exchange.fetch_tickers()
            
            # Считаем именно пары к USDT
            usdt_pairs_count = sum(1 for sym in tickers.keys() if sym.endswith('/USDT'))
            logging.info(f"[{ex_id}] Успешно загружено {len(tickers)} тикеров (из них USDT: {usdt_pairs_count}).")

            for symbol, ticker in tickers.items():
                if not symbol.endswith('/USDT'):
                    continue
                base_coin = symbol.split('/')[0]
                quote_volume = ticker.get('quoteVolume', 0) or 0

                if base_coin not in exchange_data:
                    exchange_data[base_coin] = {}
                
                exchange_data[base_coin][ex_id] = {
                    'quoteVolume': quote_volume,
                    'price': ticker.get('last', 0)
                }
        except Exception as e:
            logging.error(f"[{ex_id}] КРИТИЧЕСКАЯ ОШИБКА при получении тикеров: {e}")
            
    logging.info(f"Всего уникальных базовых монет собрано с бирж: {len(exchange_data)}")
    return exchange_data

def fetch_market_data():
    logging.info("Начинаем сбор данных с CoinGecko (Топ-2000)...")
    coingecko_coins = []
    cg_api_key = os.environ.get("COINGECKO_API")
    headers = {}
    if cg_api_key:
        headers["x-cg-demo-api-key"] = cg_api_key
    
    url = "https://api.coingecko.com/api/v3/coins/markets"
    for page in range(1, 9):
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": page, "sparkline": "false"}
        data = _cg_get_json(url, params=params, headers=headers, max_retries=6, base_delay=15.0)
        if not data: break
        coingecko_coins.extend(data)
        if page < 8: time.sleep(15)

    candidates = []
    for coin in coingecko_coins:
        mcap = coin.get("market_cap") or 0
        if mcap > 50_000_000:
            candidates.append({
                "symbol": coin["symbol"].upper(),
                "name": coin["name"],
                "price": coin.get("current_price", 0),
                "price_change_24h": coin.get("price_change_percentage_24h") or 0,
                "market_cap": mcap,
                "exchange_tickers": {}
            })

    logging.info(f"После фильтра по капитализации (>50M) осталось {len(candidates)} монет.")
    exchange_data = fetch_exchange_tickers()

    final_coins = []
    missing_symbols = []
    
    for coin in candidates:
        sym = coin["symbol"]
        if sym in exchange_data:
            coin["exchange_tickers"] = exchange_data[sym]
            final_coins.append(coin)
        else:
            missing_symbols.append(sym)

    # Покажем первые 20 монет, которые не нашли на биржах (для диагностики)
    if missing_symbols:
        logging.info(f"Примеры монет (из {len(missing_symbols)}), не найденных на биржах: {', '.join(missing_symbols[:20])}...")

    logging.info(f"Итоговое количество монет после объединения: {len(final_coins)}")
    return final_coins

# Функции compute_rsi и compute_ema200_4h оставляем без изменений (как в прошлом сообщении)
def compute_rsi(exchange_id, symbol, timeframe='1h', period=14):
    try:
        exchange = get_exchange_instance(exchange_id)
        if not exchange.has['fetchOHLCV']: return None
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=period + 20)
        if not ohlcv or len(ohlcv) < period: return None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]
        if pd.isna(current_rsi): return None
        return round(current_rsi, 2)
    except Exception as e:
        logging.warning(f"Ошибка RSI {symbol}@{exchange_id}: {e}")
        return None

def compute_ema200_4h(exchange_id, symbol, limit=250):
    try:
        exchange = get_exchange_instance(exchange_id)
        if not exchange.has.get('fetchOHLCV'): return None, None
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=limit)
        if not ohlcv or len(ohlcv) < 200: return None, None
        closes = [c[4] for c in ohlcv]
        k = 2.0 / (200 + 1)
        ema = closes[0]
        for price in closes[1:]: ema = price * k + ema * (1 - k)
        return float(ema), float(closes[-1])
    except Exception as e:
        logging.warning(f"Ошибка EMA200 {symbol}@{exchange_id}: {e}")
        return None, None
