import logging
from datetime import datetime, timedelta
import json
import os

def check_cooldown(symbol, history_file='data/signals_history.json', cooldown_hours=4):
    """Проверяет, не было ли сигнала по этой монете за последние N часов"""
    if not os.path.exists(history_file):
        return False
        
    try:
        with open(history_file, 'r', encoding='utf-8') as f:
            history = json.load(f)
            
        if symbol in history:
            last_signal_time = datetime.fromisoformat(history[symbol])
            if datetime.now() - last_signal_time < timedelta(hours=cooldown_hours):
                return True # Кулдаун активен, сигнал отправлять нельзя
                
    except Exception as e:
        logging.error(f"Ошибка чтения истории сигналов: {e}")
        
    return False

def update_cooldown(symbol, history_file='data/signals_history.json'):
    """Обновляет время последнего сигнала по монете и чистит старые записи"""
    history = {}
    if os.path.exists(history_file):
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        except Exception:
            pass
            
    # Записываем текущее время
    history[symbol] = datetime.now().isoformat()
    
    # Чистим записи старше 7 дней
    cutoff = datetime.now() - timedelta(days=7)
    cleaned_history = {}
    for sym, time_str in history.items():
        try:
            if datetime.fromisoformat(time_str) > cutoff:
                cleaned_history[sym] = time_str
        except ValueError:
            continue
            
    # Сохраняем обратно
    os.makedirs(os.path.dirname(history_file), exist_ok=True)
    with open(history_file, 'w', encoding='utf-8') as f:
        json.dump(cleaned_history, f, indent=4, ensure_ascii=False)

def analyze_market(coins_data, exchange_tickers, min_volume_usd=50000):
    """
    Основная логика анализа. 
    coins_data - данные с CoinGecko
    exchange_tickers - данные с бирж (из fetcher.py)
    """
    signals = []
    
    for coin in coins_data:
        symbol = coin.get('symbol', '').upper()
        name = coin.get('name', '')
        market_cap = coin.get('market_cap', 0)
        price_change_24h = coin.get('price_change_percentage_24h', 0)
        current_price = coin.get('current_price', 0)
        
        # 1. Фильтр по капитализации (> 50 млн $)
        if not market_cap or market_cap < 50000000:
            continue
            
        # 2. Фильтр по изменению цены (> +15% или < -15%)
        signal_type = None
        if price_change_24h > 15:
            signal_type = "LONG"
        elif price_change_24h < -15:
            signal_type = "SHORT"
            
        if not signal_type:
            continue
            
        # 3. Проверка ликвидности на целевых биржах
        coin_exchanges = exchange_tickers.get(symbol, {})
        valid_exchanges = []
        total_volume = 0
        
        for ex_id, data in coin_exchanges.items():
            vol = data.get('quoteVolume', 0)
            if vol > min_volume_usd:
                valid_exchanges.append(ex_id)
                total_volume += vol
                
        # Монета должна торговаться минимум на 2 целевых биржах с достаточным объемом
        if len(valid_exchanges) < 2:
            continue
            
        # 4. Проверка кулдауна (антидубль)
        if check_cooldown(symbol):
            logging.info(f"Сигнал по {symbol} пропущен из-за кулдауна.")
            continue
            
        # 5. Расчет RSI (запрашиваем только для прошедших фильтры)
        # Берем первую биржу из списка валидных для запроса свечей
        primary_exchange = valid_exchanges[0]
        rsi_value = None
        
        # Импортируем здесь, чтобы избежать циклической зависимости, если она есть
        from fetcher import compute_rsi
        rsi_value = compute_rsi(primary_exchange, f"{symbol}/USDT")
        
        # Фильтрация по RSI
        if signal_type == "LONG" and rsi_value is not None and rsi_value > 75:
            logging.info(f"Сигнал LONG по {symbol} отменен: RSI {rsi_value} > 75 (перекупленность).")
            continue
        if signal_type == "SHORT" and rsi_value is not None and rsi_value < 25:
            logging.info(f"Сигнал SHORT по {symbol} отменен: RSI {rsi_value} < 25 (перепроданность).")
            continue
            
        # Если все проверки пройдены - формируем сигнал
        signal = {
            'symbol': symbol,
            'name': name,
            'type': signal_type,
            'price': current_price,
            'change_24h': price_change_24h,
            'market_cap': market_cap,
            'volume': total_volume,
            'exchanges': valid_exchanges,
            'rsi': rsi_value
        }
        signals.append(signal)
        
    return signals
