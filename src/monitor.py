"""Мониторинг ликвидных монет на биржах (Binance, KuCoin, Bybit, Gate.io, MEXC).
Работает в GitHub Actions. Отправляет уведомления в ntfy при смене сигнала."""

import asyncio
import json
import os
from datetime import datetime

import apprise
import ccxt.async_support as ccxt
import pandas as pd
import pytz

from indicators import (
    compute_rsi, compute_bollinger, compute_avg_volume,
    compute_macd, compute_stoch, compute_adx,
    generate_signal, detect_divergence
)

# Настройки
EXCHANGE_IDS = ['binance', 'kucoin', 'bybit', 'gateio', 'mexc']
TIMEFRAME = '1h'

ORENBURG_TZ = pytz.timezone('Asia/Yekaterinburg')
WINDOW_START = 8   # 08:00
WINDOW_END = 20    # 20:00

STATE_FILE = 'data/signals.json'

# Пороги для сигналов
RSI_LOW = 30
RSI_HIGH = 70
ADX_THRESHOLD = 25
VOLUME_SPIKE = 1.5
VOLATILITY_THRESHOLD = 0.02


def now_orenburg():
    return datetime.now(ORENBURG_TZ)


def in_window() -> bool:
    h = now_orenburg().hour
    return WINDOW_START <= h < WINDOW_END


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Ошибка чтения {STATE_FILE}: {e}")
    return {'signals': {}, 'counters': {}, 'error_breakers': {}}


def save_state(state):
    os.makedirs('data', exist_ok=True)
    tmp_path = f"{STATE_FILE}.tmp"
    with open(tmp_path, 'w') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, STATE_FILE)
    print("💾 signals.json обновлён")


async def analyze_symbol(exchange, symbol, semaphore):
    async with semaphore:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
            if not ohlcv or len(ohlcv) < 30:
                return None
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            close = df['close']
            volume = df['volume']
            high = df['high']
            low = df['low']

            # Индикаторы
            rsi = compute_rsi(close, 14)
            _, upper, lower = compute_bollinger(close, 20, 2)
            avg_vol = compute_avg_volume(volume, 20)
            price = float(close.iloc[-1])
            cur_vol = float(volume.iloc[-1])
            prev_close = float(close.iloc[-2]) if len(close) > 1 else price
            change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
            vol_ratio = cur_vol / avg_vol.iloc[-1] if avg_vol.iloc[-1] > 0 else 0

            macd_line, signal_line, _ = compute_macd(close)
            stoch_k, _ = compute_stoch(high, low, close)
            adx, _, _ = compute_adx(high, low, close)
            ema_50 = compute_ema(close, 50)

            # Дивергенции
            rsi_divergence = detect_divergence(close, rsi, lookback=10)
            macd_divergence = detect_divergence(close, macd_line, lookback=10)

            # Сигнал
            signal = generate_signal(
                close=close,
                volume=volume,
                rsi=rsi,
                macd=macd_line,
                signal_line=signal_line,
                ema=ema_50,
                stoch_k=stoch_k,
                adx=adx,
                bollinger_upper=pd.Series([upper.iloc[-1]]),
                bollinger_lower=pd.Series([lower.iloc[-1]]),
                rsi_oversold=RSI_LOW,
                rsi_overbought=RSI_HIGH,
                adx_trend_threshold=ADX_THRESHOLD,
                volume_spike_multiplier=VOLUME_SPIKE,
                volatility_threshold=VOLATILITY_THRESHOLD
            )

            print(f"[{exchange.id}] {symbol}: Цена={price:.4g}, Сигнал={signal}, RSI={rsi.iloc[-1]:.1f}")

            return {
                'symbol': symbol,
                'exchange': exchange.id,
                'price': price,
                'signal': signal,
                'rsi': float(rsi.iloc[-1]),
                'vol_ratio': float(vol_ratio),
                'change_pct': change_pct,
                'rsi_divergence': rsi_divergence,
                'macd_divergence': macd_divergence
            }
        except Exception as e:
            print(f"❌ Ошибка запроса {exchange.id} {symbol}: {e}")
            return None


async def main():
    if not in_window():
        print(f"⏳ Вне окна ({now_orenburg().strftime('%H:%M')} Оренбург). Выход.")
        return

    print("✅ Мы внутри временного окна. Начинаем работу...")
    state = load_state()
    prev_snapshot = json.dumps(state.get('counters', {}), sort_keys=True)

    # Инициализация бирж
    exchanges = {}
    semaphore_map = {}
    for ex_id in EXCHANGE_IDS:
        cls = getattr(ccxt, ex_id, None)
        if cls is None:
            continue
        try:
            exchanges[ex_id] = cls({
                'enableRateLimit': True,
                'apiKey': os.environ.get(f'{ex_id.upper()}_API_KEY'),
                'secret': os.environ.get(f'{ex_id.upper()}_API_SECRET')
            })
            semaphore_map[ex_id] = asyncio.Semaphore(5)
        except Exception as e:
            print(f"❌ Ошибка инициализации {ex_id}: {e}")

    # Список пар (для примера возьмем топ-20 по объему с каждой биржи)
    # В реальности лучше загружать из history.json или через API
    pairs = []
    for ex_id in exchanges:
        try:
            tickers = await exchanges[ex_id].fetch_tickers()
            usdt_pairs = [(s, d) for s, d in tickers.items() if s.endswith('/USDT') and d.get('quoteVolume')]
            usdt_pairs.sort(key=lambda x: x[1]['quoteVolume'], reverse=True)
            for symbol, data in usdt_pairs[:20]:
                pairs.append((ex_id, symbol))
        except Exception as e:
            print(f"❌ Ошибка загрузки тикеров {ex_id}: {e}")

    print(f"Проверяю {len(pairs)} пар")

    # Анализ
    tasks = [(ex_id, sym, analyze_symbol(exchanges[ex_id], sym, semaphore_map[ex_id])) for ex_id, sym in pairs]
    results = await asyncio.gather(*[t[2] for t in tasks], return_exceptions=True)

    # Обработка результатов
    current_keys = set()
    messages_to_send = []
    
    for res in results:
        if isinstance(res, Exception) or not res:
            continue
        
        key = f"{res['exchange']}:{res['symbol']}"
        current_keys.add(key)
        
        old_signal = state.get('signals', {}).get(key, {}).get('signal')
        new_signal = res['signal']
        
        state['signals'][key] = {
            'signal': new_signal,
            'price': res['price'],
            'rsi': res['rsi'],
            'vol_ratio': res['vol_ratio'],
            'rsi_divergence': res['rsi_divergence'],
            'macd_divergence': res['macd_divergence'],
            'timestamp': pd.Timestamp.now().isoformat()
        }
        
        if old_signal and old_signal != new_signal:
            title = f"📈 {res['symbol']} ({res['exchange']})"
            body = (f"🔄 Смена сигнала: {old_signal} → {new_signal}\n"
                    f"💰 Цена: {res['price']:.6g}\n"
                    f"📉 RSI: {res['rsi']:.1f}\n"
                    f"📈 Дивергенция RSI: {res['rsi_divergence']}\n"
                    f"📈 Дивергенция MACD: {res['macd_divergence']}")
            
            messages_to_send.append({
                'title': title,
                'body': body
            })
            print(f"🔔 УВЕДОМЛЕНИЕ: {title} | {old_signal} -> {new_signal}")

    # Очистка старых данных
    for key in list(state.get('counters', {}).keys()):
        if key not in current_keys:
            del state['counters'][key]

    # Отправка уведомлений
    if messages_to_send:
        print(f"📤 Отправляем батч из {len(messages_to_send)} уведомлений в ntfy...")
        try:
            apobj = apprise.Apprise()
            apobj.add(os.environ['NTFY_URL'])
            for msg in messages_to_send:
                success = apobj.notify(title=msg['title'], body=msg['body'])
                if not success:
                    print(f"❌ Ошибка отправки в ntfy для {msg['title']}")
        except Exception as e:
            print(f"❌ Ошибка работы Apprise: {e}")
    else:
        print("🤷‍♂️ Смен сигналов не обнаружено. Уведомления не отправлены.")

    # Сохранение состояния
    if json.dumps(state.get('counters', {}), sort_keys=True) != prev_snapshot:
        save_state(state)
    else:
        print("ℹ️ Счётчики не изменились, state не сохранен")

    # Закрытие соединений
    await asyncio.gather(*[ex.close() for ex in exchanges.values()])


if __name__ == '__main__':
    asyncio.run(main())
