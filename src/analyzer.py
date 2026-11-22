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
        
        if sym in history and (current_time - history[sym] < cooldown_seconds):
            continue

        exchange_tickers = coin.get("exchange_tickers", {})
        valid_exchanges = {
            ex: data for ex, data in exchange_tickers.items() 
            if data.get("quoteVolume", 0) > config.MIN_EXCHANGE_VOLUME
        }
        
        if len(valid_exchanges) < config.MIN_EXCHANGES: continue
        total_volume = sum(data.get("quoteVolume", 0) for data in valid_exchanges.values())
        if total_volume < config.MIN_TOTAL_VOLUME: continue

        best_exchange = max(valid_exchanges.items(), key=lambda x: x[1].get("quoteVolume", 0))[0]
        symbol_ccxt = f"{sym}/USDT"
        
        ind = fetch_indicators(best_exchange, symbol_ccxt)
        if not ind: continue

        signal_type = None
        reason = ""

        # === ЛОГИКА LONG ===
        if ind["macd_bullish"] and ind["rsi"] > ind["prev_rsi"] and ind["prev_rsi"] < config.RSI_LONG_THRESHOLD:
            if not config.USE_EMA_FILTER or ind["price_4h"] > ind["ema200"]:
                signal_type = "LONG"
                reason = f"MACD Momentum UP + RSI Bounce {ind['prev_rsi']:.1f}->{ind['rsi']:.1f}"
        
        # === ЛОГИКА SHORT ===
        elif ind["macd_bearish"] and ind["rsi"] < ind["prev_rsi"] and ind["prev_rsi"] > config.RSI_SHORT_THRESHOLD:
            if not config.USE_EMA_FILTER or ind["price_4h"] < ind["ema200"]:
                signal_type = "SHORT"
                reason = f"MACD Momentum DOWN + RSI Drop {ind['prev_rsi']:.1f}->{ind['rsi']:.1f}"

        if not signal_type: continue

        entry_price = coin["price"]
        atr = ind["atr"]
        
        if signal_type == "LONG":
            sl = entry_price - (atr * config.SL_ATR_MULTIPLIER)
            tp = entry_price + (atr * config.TP_ATR_MULTIPLIER)
        else:
            sl = entry_price + (atr * config.SL_ATR_MULTIPLIER)
            tp = entry_price - (atr * config.TP_ATR_MULTIPLIER)

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
        
        logging.info(f"!!! СИГНАЛ {signal_type}: {sym} @ {entry_price} (Причина: {reason})")

    return signals
