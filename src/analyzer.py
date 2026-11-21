import time
import logging
from fetcher import compute_rsi

# Настройки фильтрации (из документации проекта)
COOLDOWN_HOURS = 4
VOLATILITY_THRESHOLD = 15.0      # 15% изменения за 24ч
MIN_TOTAL_VOLUME = 500_000       # Общий объем > 500k $
MIN_EXCHANGE_VOLUME = 50_000     # Мин. объем на одной бирже > 50k $
MIN_EXCHANGES = 2                # Минимум 2 биржи

def analyze(coins, history):
    """
    Анализирует список монет и возвращает список торговых сигналов.
    """
    signals = []
    current_time = int(time.time())
    cooldown_seconds = COOLDOWN_HOURS * 3600

    for coin in coins:
        sym = coin["symbol"]
        
        # 1. Проверка кулдауна (антидубль)
        if sym in history:
            last_signal_time = history[sym]
            if current_time - last_signal_time < cooldown_seconds:
                continue

        # 2. Проверка на волатильность (изменение за 24ч)
        change = coin["price_change_24h"]
        
        signal_type = None
        if change >= VOLATILITY_THRESHOLD:
            signal_type = "LONG"
        elif change <= -VOLATILITY_THRESHOLD:
            signal_type = "SHORT"
            
        if not signal_type:
            continue

        # 3. Проверка объемов и количества бирж
        exchange_tickers = coin.get("exchange_tickers", {})
        
        # Отбираем только биржи, где объем > 50k $
        valid_exchanges = {
            ex: data for ex, data in exchange_tickers.items() 
            if data.get("quoteVolume", 0) > MIN_EXCHANGE_VOLUME
        }
        
        # Монета должна торговаться минимум на 2 биржах
        if len(valid_exchanges) < MIN_EXCHANGES:
            continue
            
        # Общий объем должен быть > 500k $
        total_volume = sum(data.get("quoteVolume", 0) for data in valid_exchanges.values())
        if total_volume < MIN_TOTAL_VOLUME:
            continue

        # 4. Расчет RSI
        # Берем биржу с самым большим объемом для запроса свечей
        best_exchange = max(valid_exchanges.items(), key=lambda x: x[1].get("quoteVolume", 0))[0]
        symbol_ccxt = f"{sym}/USDT"
        
        rsi = compute_rsi(best_exchange, symbol_ccxt)
        
        # 5. RSI-фильтр
        if rsi is not None:
            if signal_type == "LONG" and rsi > 75:
                logging.info(f"Пропуск LONG {sym}: RSI слишком высокий ({rsi})")
                continue
            if signal_type == "SHORT" and rsi < 25:
                logging.info(f"Пропуск SHORT {sym}: RSI слишком низкий ({rsi})")
                continue

        # 6. Формирование сигнала
        signal = {
            "symbol": sym,
            "name": coin["name"],
            "type": signal_type,
            "price": coin["price"],
            "change": round(change, 2),
            "rsi": rsi,
            "exchanges": list(valid_exchanges.keys()),
            "timestamp": current_time
        }
        signals.append(signal)

    return signals
