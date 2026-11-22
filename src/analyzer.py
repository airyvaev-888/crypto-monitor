# src/analyzer.py
import time
import logging
import config
from fetcher import fetch_indicators

def analyze(coins, history):
    signals = []
    current_time = int(time.time())
    cooldown_seconds = config.COOLDOWN_HOURS * 3600

    for coin in coins:
        sym = coin["symbol"]
        
        # 1. Кулдаун
        if sym in history and (current_time - history[sym] < cooldown_seconds):
            continue

        # 2. Фильтр объемов и бирж
        exchange_tickers = coin.get("exchange_tickers", {})
        valid_exchanges = {
            ex: data for ex, data in exchange_tickers.items() 
            if data.get("quoteVolume", 0) > config.MIN_EXCHANGE_VOLUME
        }
        
        if len(valid_exchanges) < config.MIN_EXCHANGES: continue
        total_volume = sum(data.get("quoteVolume", 0) for data in valid_exchanges.values())
        if total_volume < config.MIN_TOTAL_VOLUME: continue

        # Берем лучшую биржу
        best_exchange = max(valid_exchanges.items(), key=lambda x: x[1].get("quoteVolume", 0))[0]
        symbol_ccxt = f"{sym}/USDT"
        
        # 3. Загружаем индикаторы
        ind = fetch_indicators(best_exchange, symbol_ccxt)
        if not ind: continue

        signal_type = None
        reason = ""

        # === ЛОГИКА LONG (Покупка на откате) ===
        # Условия: Глобальный тренд вверх (цена > EMA200), MACD развернулся вверх, RSI выходил из перепроданности
        if ind["macd_bullish"] and ind["rsi"] > ind["prev_rsi"] and ind["prev_rsi"] < config.RSI_LONG_THRESHOLD:
            if not config.USE_EMA_FILTER or ind["price_4h"] > ind["ema200"]:
                signal_type = "LONG"
                reason = f"MACD Cross UP + RSI {ind['prev_rsi']:.1f}->{ind['rsi']:.1f}"
        
        # === ЛОГИКА SHORT (Продажа на отскоке) ===
        # Условия: Глобальный тренд вниз (цена < EMA200), MACD развернулся вниз, RSI выходил из перекупленности
        elif ind["macd_bearish"] and ind["rsi"] < ind["prev_rsi"] and ind["prev_rsi"] > config.RSI_SHORT_THRESHOLD:
            if not config.USE_EMA_FILTER or ind["price_4h"] < ind["ema200"]:
                signal_type = "SHORT"
                reason = f"MACD Cross DOWN + RSI {ind['prev_rsi']:.1f}->{ind['rsi']:.1f}"

        if not signal_type: continue

        # 4. Расчет Take Profit и Stop Loss на основе волатильности (ATR)
        entry_price = coin["price"]
        atr = ind["atr"]
        
        if signal_type == "LONG":
            sl = entry_price - (atr * config.SL_ATR_MULTIPLIER)
            tp = entry_price + (atr * config.TP_ATR_MULTIPLIER)
        else: # SHORT
            sl = entry_price + (atr * config.SL_ATR_MULTIPLIER)
            tp = entry_price - (atr * config.TP_ATR_MULTIPLIER)

        # 5. Формируем сигнал
        signals.append({
            "symbol": sym,
            "name": coin["name"],
            "type": signal_type,
            "price": entry_price,
            "tp": tp,
            "sl": sl,
            "rsi": round(ind["rsi"], 2),
            "reason": reason,
            "exchange": best_exchange,
            "timestamp": current_time
        })

    return signals
