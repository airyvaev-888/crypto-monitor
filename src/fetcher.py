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
_EXCHANGES = {}

def get_exchange_instance(exchange_id):
    if exchange_id in _EXCHANGES: return _EXCHANGES[exchange_id]
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
    _EXCHANGES[exchange_id] = exchange
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
                time.sleep(wait)
                delay = min(delay * 1.8, 120)
                continue
            if 500 <= r.status_code < 600:
                time.sleep(delay)
                delay = min(delay * 1.8, 120)
                continue
            r.raise_for_status()
        except requests.RequestException:
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
            logging.error(f"[{ex_id}] Ошибка тикеров: {e}")
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
    try:
        exchange = get_exchange_instance(exchange_id)
        if not exchange.has.get('fetchOHLCV'): return None

        ohlcv_1h = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=1000)
        if not ohlcv_1h or len(ohlcv_1h) < 800: return None

        df_1h = pd.DataFrame(ohlcv_1h, columns=['ts', 'o', 'h', 'l', 'c', 'v'])
        df_1h['dt'] = pd.to_datetime(df_1h['ts'], unit='ms')
        df_1h.set_index('dt', inplace=True)
        
        df_4h = df_1h.resample('4h').agg({'o': 'first', 'h': 'max', 'l': 'min', 'c': 'last', 'v': 'sum'}).dropna()
        if len(df_4h) < 200: return None

        ema200 = df_4h['c'].ewm(span=200, adjust=False).mean().iloc[-1]
        last_close_4h = df_4h['c'].iloc[-1]

        exp1 = df_4h['c'].ewm(span=12, adjust=False).mean()
        exp2 = df_4h['c'].ewm(span=26, adjust=False).mean()
        macd_line = exp1 - exp2
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - signal_line
        
        # УПРОЩЕННЫЙ MACD: гистограмма просто растет/падает по сравнению с прошлым закрытым баром
        macd_bullish = macd_hist.iloc[-2] > macd_hist.iloc[-3]
        macd_bearish = macd_hist.iloc[-2] < macd_hist.iloc[-3]

        delta = df_1h['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=config.RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=config.RSI_PERIOD).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        current_rsi = rsi_series.iloc[-1]
        prev_rsi = rsi_series.iloc[-2]

        high_low = df_1h['h'] - df_1h['l']
        high_close = (df_1h['h'] - df_1h['c'].shift()).abs()
        low_close = (df_1h['l'] - df_1h['c'].shift()).abs()
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr = true_range.rolling(config.ATR_PERIOD).mean().iloc[-1]

        return {
            "price_4h": last_close_4h,
            "ema200": ema200,
            "macd_bullish": macd_bullish,
            "macd_bearish": macd_bearish,
            "rsi": current_rsi,
            "prev_rsi": prev_rsi,
            "atr": atr
        }
    except Exception as e:
        # ВОЗВРАЩАЕМ ЛОГ ОШИБКИ, чтобы видеть, если биржа не отдает свечи
        logging.warning(f"Ошибка индикаторов {symbol}@{exchange_id}: {e}")
        return None
