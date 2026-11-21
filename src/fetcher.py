import ccxt
import time
import pandas as pd
from datetime import datetime, timedelta
import logging
import requests
import os

# Список целевых бирж (Binance и Bybit убраны, добавлены OKX и Bitget)
TARGET_EXCHANGES = ['kucoin', 'gateio', 'mexc', 'okx', 'bitget']

def get_exchange_instance(exchange_id):
    """Создает и настраивает инстанс биржи CCXT"""
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
        }
    })
    return exchange

def fetch_exchange_tickers(symbols=None):
    """
    Загружает тикеры со всех целевых бирж за 1 запрос (bulk) и 
    возвращает словарь с объемами и данными по каждой монете.
    """
    exchange_data = {}
    
    for ex_id in TARGET_EXCHANGES:
        try:
            exchange = get_exchange_instance(ex_id)
            # Загружаем все тикеры разом (защита от таймаутов и бан-лимитов)
            tickers = exchange.fetch_tickers()
            logging.info(f"[{ex_id}] Успешно загружено {len(tickers)} тикеров.")
            
            for symbol, ticker in tickers.items():
                # Нам нужны только пары к USDT
                if not symbol.endswith('/USDT'):
                    continue
                
                base_coin = symbol.split('/')[0]
                # Используем строго quoteVolume (объем в USDT)
                quote_volume = ticker.get('quoteVolume', 0)
                
                if quote_volume is None:
                    quote_volume = 0
                    
                if base_coin not in exchange_data:
                    exchange_data[base_coin] = {}
                
                exchange_data[base_coin][ex_id] = {
                    'quoteVolume': quote_volume,
                    'price': ticker.get('last', 0)
                }
                
        except Exception as e:
            logging.error(f"[{ex_id}] Ошибка при получении тикеров: {e}")
            
    return exchange_data

def fetch_market_data():
    """
    Главная функция сбора данных: 
    1. Берет Топ-2000 монет с CoinGecko (8 страниц).
    2. Фильтрует по капитализации > 50 млн $.
    3. Подтягивает объемы с целевых бирж через CCXT.
    """
    logging.info("Начинаем сбор данных с CoinGecko (Топ-2000)...")
    coingecko_coins = []
    
    cg_api_key = os.environ.get("COINGECKO_API")
    headers = {}
    if cg_api_key:
        headers["x-cg-demo-api-key"] = cg_api_key

    url = "https://api.coingecko.com/api/v3/coins/markets"
    
    # Пагинация: 8 страниц по 250 = Топ-2000
    for page in range(1, 9):
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": page,
            "sparkline": "false"
        }
        
        try:
            logging.info(f"Запрос к CoinGecko: страница {page}...")
            response = requests.get(url, params=params, headers=headers, timeout=20)
            
            # Защита от лимитов (429)
            if response.status_code == 429:
                logging.warning("CoinGecko: 429 Too Many Requests. Ждем 30 секунд...")
                time.sleep(30)
                response = requests.get(url, params=params, headers=headers, timeout=20)
                
            response.raise_for_status()
            data = response.json()
            
            if not data:
                logging.info(f"CoinGecko: страница {page} пуста. Завершаем сбор.")
                break
                
            coingecko_coins.extend(data)
            logging.info(f"CoinGecko: загружена страница {page} ({len(data)} монет).")
            
        except Exception as e:
            logging.error(f"Ошибка при загрузке страницы {page} с CoinGecko: {e}")
        
        # Безопасная пауза между страницами (15 секунд), чтобы не получить бан
        time.sleep(15) 

    # Фильтрация по капитализации (> 50 млн $)
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

    # Получаем данные с бирж (CCXT)
    logging.info("Начинаем сбор тикеров с бирж (OKX, Bitget, KuCoin, Gate, MEXC)...")
    exchange_data = fetch_exchange_tickers()

    # Объединяем данные CoinGecko и бирж
    final_coins = []
    for coin in candidates:
        sym = coin["symbol"]
        if sym in exchange_data:
            coin["exchange_tickers"] = exchange_data[sym]
            final_coins.append(coin)

    logging.info(f"Итоговое количество монет после объединения: {len(final_coins)}")
    return final_coins

def compute_rsi(exchange_id, symbol, timeframe='1h', period=14):
    """
    Рассчитывает RSI для конкретной монеты на конкретной бирже.
    Запрашивается ТОЛЬКО для кандидатов (чтобы не спамить API).
    """
    try:
        exchange = get_exchange_instance(exchange_id)
        
        if not exchange.has['fetchOHLCV']:
            return None
            
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=period + 20)
        if not ohlcv or len(ohlcv) < period:
            return None
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        current_rsi = rsi.iloc[-1]
        
        if pd.isna(current_rsi):
            return None
            
        return round(current_rsi, 2)
        
    except Exception as e:
        logging.warning(f"Не удалось рассчитать RSI для {symbol} на {exchange_id}: {e}")
        return None
