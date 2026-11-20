import ccxt
import time
import pandas as pd
from datetime import datetime, timedelta
import logging

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

def fetch_exchange_tickers(symbols):
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

def compute_rsi(exchange_id, symbol, timeframe='1h', period=14):
    """
    Рассчитывает RSI для конкретной монеты на конкретной бирже.
    Запрашивается ТОЛЬКО для кандидатов (чтобы не спамить API).
    """
    try:
        exchange = get_exchange_instance(exchange_id)
        
        # Проверяем, торгуется ли монета на этой бирже
        if not exchange.has['fetchOHLCV']:
            return None
            
        # Запрашиваем свечи
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=period + 20)
        if not ohlcv or len(ohlcv) < period:
            return None
            
        # Конвертируем в DataFrame для удобного расчета
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        
        # Логика расчета RSI
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
