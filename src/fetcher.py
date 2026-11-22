# src/fetcher.py
import ccxt
import time
import random
import pandas as pd
import logging
import requests
import os
import config

TARGET_EXCHANGES = ['kucoin', 'gateio', 'mexc', 'okx', 'bitget']

def get_exchange_instance(exchange_id):
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
    return exchange

def _cg_get_json(url, params, headers, max_retries=6, base_delay=15.0, timeout=30):
    delay = base_delay
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            if r.status_code == 200: return r.json()
            if r.status_code == 429:
                ra = r.headers.get("Retry-After")
                wait = max(int(ra), delay) if ra and ra.isdigit() else delay
                wait += random.uniform(0, 3)
                logging.warning(f"CoinGecko 429, ждём {wait:.1f}с")
                time.sleep(wait)
                delay = min(delay * 1.8, 120)
                continue
            if 500 <= r.status_code < 600:
                time.sleep(delay)
                delay = min(delay * 1.8, 120)
                continue
            r.raise_for_status()
        except requests.RequestException as e:
            time.sleep(delay)
            delay = min(delay * 1.8, 120)
    raise RuntimeError(f"CoinGecko недоступен после {max_retries} попыток")

def fetch_exchange_tickers(symbols=None):
    exchange_data = {}
    for ex_id in TARGET_EXCHANGES:
        try:
            exchange = get_exchange_instance(ex_id)
            exchange.load_markets()
            tickers = exchange.fetch_tickers()
            for symbol, ticker in tickers.items():
                if not symbol.endswith('/USDT'): continue
                base_coin = symbol.split('/')[0]
                quote_volume = ticker.get('quoteVolume', 0) or 0
                if base_coin not in exchange_data: exchange_data[base_coin] = {}
                exchange_data[base_coin][ex_id] = {'quoteVolume': quote_volume, 'price': ticker.get('last', 0)}
        except Exception as e:
            logging.error(f"[{ex_id}] Ошибка: {e}")
    return exchange_data

def fetch_market_data():
    coingecko_coins = []
    cg_api_key = os.environ.get("COINGECKO_API")
    headers = {"x-cg-demo-api-key": cg_api_key} if cg_api_key else {}
    url = "https://api.coingecko.com/api/v3/coins/markets"
    
    for page in range(1, 9):
        params = {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": page, "sparkline": "false"}
        data = _cg_get_json(url, params, headers)
        if not data: break
        coingecko_coins.extend(data)
        if page < 8: time.sleep(15)

    candidates = []
    for coin in coingecko_coins:
        mcap = coin.get("market_cap") or 0
        if mcap > config.MIN_MARKET_CAP:
            candidates.append({
                "symbol": coin["symbol"].upper(), "name": coin["name"],
                "price": coin.get("current_price", 0), "market_cap": mcap, "exchange_tickers": {}
            })

    exchange_data = fetch_exchange_tickers()
    final_coins = []
    for coin in candidates:
        if coin["symbol"] in exchange_data:
            coin["exchange_tickers"] = exchange_data[coin["symbol"]]
            final_coins.append(coin)
    return final_coins

def fetch_indicators(exchange_id, symbol):
    """
    Загружает свечи и рассчитывает RSI, MACD, ATR, EMA200
    """
    try:
        exchange = get_exchange_instance(exchange_id)
        if not exchange.has.get('fetchOHLCV'): return None

        # 1. Загружаем 4h свечи для EMA 200 и MACD
        ohlcv_4h = exchange.fetch_ohlcv(symbol, timeframe='4h', limit=250)
        if not ohlcv_4h or len(ohlcv_4h) < 200: return None
        
        # 2. Загружаем 1h свечи для RSI и ATR
        ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe=config.TIMEFRAME, limit=100)
        if not ohlcv_1h or len(ohlcv_1h) < 50: return None

        df_4h = pd.DataFrame(ohlcv_4h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        
        # --- EMA 200 (4h) ---
        ema200 = df_4h['c'].ewm(span=200, adjust=False).mean().iloc[-1]
        last_close_4h = df_4h['c'].iloc[-1]

        # --- MACD (4h) ---
        exp1 = df_4h['c'].ewm(span=12, adjust=False).mean()
        exp2 = df_4h['c'].ewm(span=26, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line
        
        # Проверяем, был ли MACD отрицательным в прошлой свече и стал положительным
        macd_bullish_cross = macd_hist.iloc[-2] < 0 and macd_hist.iloc[-1] > 0
        macd_bearish_cross = macd_hist.iloc[-2] > 0 and macd_hist.iloc[-1] < 0

        # --- RSI (1h) ---
        delta = df_1h['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=config.RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=config.RSI_PERIOD).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        current_rsi = rsi_series.iloc[-1]
        prev_rsi = rsi_series.iloc[-2]

        # --- ATR (1h) ---
        high_low = df_1h['h'] - df_1h['l']
        high_close = (df_1h['h'] - df_1h['c'].shift()).abs()
        low_close = (df_1h['l'] - df_1h['c'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(config.ATR_PERIOD).mean().iloc[-1]

        return {
            "price_4h": last_close_4h,
            "ema200": ema200,
            "macd_bullish": macd_bullish_cross,
            "macd_bearish": macd_bearish_cross,
            "rsi": current_rsi,
            "prev_rsi": prev_rsi,
            "atr": atr
        }
    except Exception as e:
        logging.warning(f"Ошибка индикаторов {symbol}@{exchange_id}: {e}")
        return None
