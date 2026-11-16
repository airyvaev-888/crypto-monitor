import ccxt
import pandas as pd
from datetime import datetime
import apprise
import os
import pytz

# --- НАСТРОЙКИ ---
APPRISE_URL = os.getenv('APPRISE_URL', 'ntfys://ntfy.sh/air-crypto-alerts-888')
apobj = apprise.Apprise()
apobj.add(APPRISE_URL)

# Ограничение по времени (Оренбург, UTC+5)
ORENBURG_TZ = pytz.timezone('Asia/Yekaterinburg')
now_orenburg = datetime.now(ORENBURG_TZ)
current_hour = now_orenburg.hour
if current_hour < 8 or current_hour >= 20:
    print(f"Время {now_orenburg.strftime('%H:%M')} вне окна 08:00-20:00. Завершаем работу.")
    exit()

SYMBOLS = ['ICP/USDT', 'FIL/USDT', 'LUNC/USDT', 'XOR/USDT', 'XEM/USDT', 'JASMY/USDT', 'VR/USDT', 'XVG/USDT', 'BTC/USDT']
TIMEFRAME = '1h'  # 1 час, так как запуск раз в час
exchange_ids = ['binance', 'kucoin', 'bybit', 'mexc']

# Пороги для аномалий
PRICE_CHANGE_THRESHOLD = 2.5  # Изменение цены за 1 час в %
VOLUME_SPIKE_MULTIPLIER = 2.5 # Во сколько раз объем выше среднего

exchanges = {ex: getattr(ccxt, ex)({'enableRateLimit': True}) for ex in exchange_ids}

def send_alert(title, message):
    print(f"🚨 Отправка: {title}")
    apobj.notify(body=message, title=title)

def get_indicators(exchange, symbol):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + gain / loss))
    
    # Средний объем
    df['Volume_MA20'] = df['volume'].rolling(window=20).mean()
    
    # EMA50
    df['EMA50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # Полосы Боллинджера
    df['SMA20'] = df['close'].rolling(window=20).mean()
    df['STD20'] = df['close'].rolling(window=20).std()
    df['Upper_BB'] = df['SMA20'] + (df['STD20'] * 2)
    df['Lower_BB'] = df['SMA20'] - (df['STD20'] * 2)

    price_change_pct = ((df['close'].iloc[-1] - df['open'].iloc[-1]) / df['open'].iloc[-1]) * 100
    
    return {
        'price': df['close'].iloc[-1],
        'rsi': df['RSI'].iloc[-1],
        'change_pct': price_change_pct,
        'vol': df['volume'].iloc[-1],
        'avg_vol': df['Volume_MA20'].iloc[-1],
        'lower_bb': df['Lower_BB'].iloc[-1],
        'upper_bb': df['Upper_BB'].iloc[-1]
    }

print(f"Запуск проверки в {now_orenburg.strftime('%H:%M')} (Оренбург)")

for ex_id, exchange in exchanges.items():
    for symbol in SYMBOLS:
        try:
            data = get_indicators(exchange, symbol)
            if pd.isna(data['rsi']):
                continue
            
            # Логика 1: RSI + Боллинджер
            if data['rsi'] < 30 and data['price'] <= data['lower_bb']:
                send_alert(f"💎 Отскок от низа ({ex_id.upper()})", f"{symbol} у нижней BB! RSI: {data['rsi']:.1f}. Цена: {data['price']:.8f}.")
            elif data['rsi'] > 70 and data['price'] >= data['upper_bb']:
                send_alert(f"🔥 Отскок от верха ({ex_id.upper()})", f"{symbol} у верхней BB! RSI: {data['rsi']:.1f}. Цена: {data['price']:.8f}.")
                
            # Логика 2: Аномальный объем и резкое движение
            if data['avg_vol'] > 0:
                vol_ratio = data['vol'] / data['avg_vol']
                if abs(data['change_pct']) >= PRICE_CHANGE_THRESHOLD and vol_ratio >= VOLUME_SPIKE_MULTIPLIER:
                    direction = "📈 РОСТ" if data['change_pct'] > 0 else "📉 ПАДЕНИЕ"
                    send_alert(
                        f"🔥 Аномалия: {direction} ({ex_id.upper()})",
                        f"{symbol} изменился на {data['change_pct']:.2f}% за 1 час.\nОбъем: в {vol_ratio:.1f} раз выше среднего.\nЦена: {data['price']:.8f}"
                    )
        except Exception:
            pass

print("Проверка завершена.")
