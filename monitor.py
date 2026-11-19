"""Часовой монитор ликвидных монет из history.json с историей сигналов и ntfy-уведомлениями."""
import asyncio
import json
import os
from datetime import datetime

import apprise
import ccxt.async_support as ccxt
import pandas as pd
import pytz

# === НОВОЕ: Импортируем все индикаторы, функцию сигналов и детектор дивергенций ===
from indicators import (
    compute_rsi, compute_bollinger, compute_avg_volume,
    compute_macd, compute_stoch, compute_adx,
    generate_signal,  # <-- Главная новая функция
    detect_divergence # <-- Новая функция для поиска дивергенций
)

HISTORY_FILE = 'history.json'
STATE_FILE = 'monitor_state.json'
TIMEFRAME = '1h'

EXCHANGE_IDS = ['kucoin', 'mexc', 'gateio']
FALLBACK_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

ORENBURG_TZ = pytz.timezone('Asia/Yekaterinburg')
WINDOW_START = 8
WINDOW_END = 20

RSI_LOW = 30
RSI_HIGH = 70
VOLUME_SPIKE_RATIO = 2.5
VOLUME_SPIKE_CHANGE_PCT = 2.5

RPS_LIMITS = {
    'kucoin': 10,
    'mexc': 5,
    'gateio': 5
}


def now_orenburg():
    return datetime.now(ORENBURG_TZ)


def in_window() -> bool:
    h = now_orenburg().hour
    return WINDOW_START <= h < WINDOW_END


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения {path}: {e}")
    return default


def atomic_save(path, data):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def load_symbols():
    hist = load_json(HISTORY_FILE, {})
    items = hist.get('liquid_symbols', [])
    pairs = []
    seen = set()
    for it in items:
        ex, sym = it.get('exchange'), it.get('symbol')
        if ex and sym and (ex, sym) not in seen:
            seen.add((ex, sym))
            pairs.append((ex, sym))
    if not pairs:
        print("⚠️ history.json пуст — использую fallback")
        for ex in EXCHANGE_IDS:
            for sym in FALLBACK_SYMBOLS:
                pairs.append((ex, sym))
    return pairs


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

            # 1. Базовые индикаторы
            rsi = compute_rsi(close, 14)
            _, upper, lower = compute_bollinger(close, 20, 2)
            avg_vol = compute_avg_volume(volume, 20)
            price = float(close.iloc[-1])
            cur_vol = float(volume.iloc[-1])
            prev_close = float(close.iloc[-2]) if len(close) > 1 else price
            change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
            vol_ratio = cur_vol / avg_vol.iloc[-1] if avg_vol.iloc[-1] > 0 else 0

            # 2. Новые индикаторы для сигналов
            macd_line, signal_line, _ = compute_macd(close)
            stoch_k, _ = compute_stoch(high, low, close)
            adx, _, _ = compute_adx(high, low, close)
            ema_50 = compute_ema(close, 50)

            # 3. Поиск дивергенций (НОВОЕ)
            rsi_divergence = detect_divergence(close, rsi, lookback=10)
            macd_divergence = detect_divergence(close, macd_line, lookback=10)

            print(f"[{exchange.id}] {symbol}: Цена={price:.4g}, Сигнал=?, RSI={rsi.iloc[-1]:.1f}")

            # 4. Генерация торгового сигнала
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
                bollinger_lower=pd.Series([lower.iloc[-1]])
            )

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
    state = load_json(STATE_FILE, {'signals': {}, 'counters': {}, 'error_breakers': {}})
    counters = state.get('counters', {})
    breakers = state.get('error_breakers', {})
    prev_snapshot = json.dumps(counters, sort_keys=True)

    active_exchanges = [ex for ex in EXCHANGE_IDS if breakers.get(ex, 0) < 3]
    if not active_exchanges:
        print("❌ Все биржи в блоке (Circuit Breaker). Выход.")
        return

    print(f"Активные биржи (не в блоке): {active_exchanges}")
    pairs = load_symbols()
    print(f"Проверяю {len(pairs)} пар")

    # === НОВОЕ: Инициализация Apprise для ntfy ===
    apobj = apprise.Apprise()
    ntfy_url = os.environ.get('NTFY_URL')
    if not ntfy_url:
        print("❌ ОШИБКА: Переменная NTFY_URL не найдена в окружении!")
        return
    apobj.add(ntfy_url)

    exchanges = {}
    semaphore_map = {}
    for ex_id in active_exchanges:
        cls = getattr(ccxt, ex_id, None)
        if cls is None:
            continue
        try:
            exchanges[ex_id] = cls({'enableRateLimit': True})
            semaphore_map[ex_id] = asyncio.Semaphore(RPS_LIMITS.get(ex_id, 5))
        except Exception as e:
            print(f"Ошибка инициализации {ex_id}: {e}")
            breakers[ex_id] = breakers.get(ex_id, 0) + 1

    tasks = []
    for ex_id, sym in pairs:
        if ex_id not in exchanges:
            continue
        tasks.append((ex_id, sym, analyze_symbol(exchanges[ex_id], sym, semaphore_map[ex_id])))

    results = await asyncio.gather(*[t[2] for t in tasks], return_exceptions=True)

    current_keys = set()
    messages_to_send = []
    
    for res in results:
        if isinstance(res, Exception):
            print(f"Task error: {res}")
            continue
        if not res:
            continue
        
        key = f"{res['exchange']}:{res['symbol']}"
        current_keys.add(key)
        
        # Обновляем счетчики аномалий (старая логика)
        # ... (здесь можно оставить логику для volume_anomaly, если нужно)
        
        # === НОВОЕ: Логика истории сигналов и уведомлений ===
        old_signal = state.get('signals', {}).get(key, {}).get('signal')
        new_signal = res['signal']
        
        # Сохраняем текущее состояние
        state['signals'][key] = {
            'signal': new_signal,
            'price': res['price'],
            'rsi': res['rsi'],
            'vol_ratio': res['vol_ratio'],
            'rsi_divergence': res['rsi_divergence'],
            'macd_divergence': res['macd_divergence'],
            'timestamp': pd.Timestamp.now().isoformat()
        }
        
        # Если сигнал изменился (и это не первый запуск), готовим уведомление
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

    # Очистка старых счетчиков
    for key in list(counters.keys()):
        if key not in current_keys:
            del counters[key]

    # === НОВОЕ: Отправка батча в ntfy ===
    if messages_to_send:
        print(f"📤 Отправляем батч из {len(messages_to_send)} уведомлений в ntfy...")
        try:
            for msg in messages_to_send:
                success = apobj.notify(title=msg['title'], body=msg['body'])
                if not success:
                    print(f"❌ Ошибка отправки в ntfy для {msg['title']}")
        except Exception as e:
            print(f"❌ Ошибка работы Apprise: {e}")
    else:
        print("🤷‍♂️ Смен сигналов не обнаружено. Уведомления не отправлены.")

    state['counters'] = counters
    state['error_breakers'] = breakers
    if json.dumps(counters, sort_keys=True) != prev_snapshot:
        atomic_save(STATE_FILE, state)
        print("💾 monitor_state.json обновлён")
    else:
        print("ℹ️ Счётчики не изменились, state не сохранен")

    await asyncio.gather(*[ex.close() for ex in exchanges.values()])

if __name__ == '__main__':
    asyncio.run(main())
