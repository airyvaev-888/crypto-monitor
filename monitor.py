"""Часовой монитор ликвидных монет из history.json с генерацией торговых сигналов."""
import asyncio
import json
import os
from datetime import datetime

import apprise
import ccxt.async_support as ccxt
import pandas as pd
import pytz

# === НОВОЕ: Импортируем все индикаторы и функцию сигналов ===
from indicators import (
    compute_rsi, compute_bollinger, compute_avg_volume,
    compute_macd, compute_stoch, compute_adx,
    generate_signal  # <-- Главная новая функция
)

HISTORY_FILE = 'history.json'
STATE_FILE = 'monitor_state.json'
TIMEFRAME = '1h'

# Оставили только те биржи, которые не блокируют GitHub
EXCHANGE_IDS = ['kucoin', 'mexc', 'gateio']
FALLBACK_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

ORENBURG_TZ = pytz.timezone('Asia/Yekaterinburg')
WINDOW_START = 8
WINDOW_END = 20

# Пороги для базовых фильтров (оставляем для логики аномалий)
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


# === НОВОЕ: Обновленная функция анализа с расчетом всех индикаторов ===
async def analyze_symbol(exchange, symbol, semaphore):
    async with semaphore:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=100)
            if not ohlcv or len(ohlcv) < 30:
                return []
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            close = df['close']
            volume = df['volume']
            high = df['high']
            low = df['low']

            # 1. Базовые индикаторы (были раньше)
            rsi = float(compute_rsi(close, 14).iloc[-1])
            _, upper, lower = compute_bollinger(close, 20, 2)
            avg_vol = float(compute_avg_volume(volume, 20).iloc[-1])
            price = float(close.iloc[-1])
            cur_vol = float(volume.iloc[-1])
            prev_close = float(close.iloc[-2]) if len(close) > 1 else price
            change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0

            # 2. Новые индикаторы для сигналов
            macd_line, signal_line, _ = compute_macd(close)
            stoch_k, _ = compute_stoch(high, low, close)
            adx, _, _ = compute_adx(high, low, close)

            print(f"[{exchange.id}] {symbol}: Цена={price:.4g}, RSI={rsi:.1f}, MACD={macd_line.iloc[-1]:.4g}/{signal_line.iloc[-1]:.4g}")

            # 3. Генерация торгового сигнала (BUY/SELL/HOLD)
            signal = generate_signal(
                close=close,
                volume=volume,
                rsi=pd.Series([rsi]),  # Передаем как Series для совместимости
                macd=macd_line,
                signal_line=signal_line,
                ema=close.ewm(span=50, adjust=False),  # Используем EMA 50 как тренд
                stoch_k=stoch_k,
                adx=adx,
                bollinger_upper=pd.Series([upper.iloc[-1]]),
                bollinger_lower=pd.Series([lower.iloc[-1]])
            )

            # 4. Логика аномалий (оставляем как доп. инфу)
            signals = []
            if rsi < RSI_LOW and price <= float(lower.iloc[-1]):
                signals.append(('bounce_low', f"RSI={rsi:.1f}, цена у нижней BB"))
            if rsi > RSI_HIGH and price >= float(upper.iloc[-1]):
                signals.append(('bounce_high', f"RSI={rsi:.1f}, цена у верхней BB"))
            if avg_vol > 0 and vol_ratio >= VOLUME_SPIKE_RATIO \
                    and abs(change_pct) >= VOLUME_SPIKE_CHANGE_PCT:
                arrow = "↑" if change_pct > 0 else "↓"
                signals.append(('volume_anomaly',
                                f"Объём x{vol_ratio:.1f} при изменении {change_pct:+.2f}% {arrow}"))
            
            # 5. Формируем итоговый результат
            result = {
                'symbol': symbol,
                'exchange': exchange.id,
                'price': price,
                'signal': signal,  # <-- ГЛАВНЫЙ РЕЗУЛЬТАТ
                'rsi': rsi,
                'vol_ratio': vol_ratio,
                'change_pct': change_pct,
                'anomalies': [s[0] for s in signals]  # Сохраняем коды аномалий
            }
            
            if signal != 'HOLD':
                print(f"🔥 ТОРГОВЫЙ СИГНАЛ: {exchange.id} {symbol} -> {signal}")
            
            return result
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

    apobj = apprise.Apprise()
    apobj.add(os.environ['APPRISE_URL'])

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
    grouped = {}
    for res in results:
        if isinstance(res, Exception):
            print(f"Task error: {res}")
            continue
        if not res:
            continue
        
        key = f"{res['exchange']}:{res['symbol']}"
        current_keys.add(key)
        
        # Обновляем счетчики аномалий (старая логика)
        for anomaly in res.get('anomalies', []):
            anomaly_key = f"{key}:{anomaly}"
            counters[anomaly_key] = counters.get(anomaly_key, 0) + 1
        
        # Сохраняем торговый сигнал
        state['signals'][key] = {
            'signal': res['signal'],
            'price': res['price'],
            'rsi': res['rsi'],
            'vol_ratio': res['vol_ratio'],
            'timestamp': pd.Timestamp.now().isoformat()
        }
        
        # Группируем для уведомлений
        if res['signal'] != 'HOLD':
            grouped.setdefault(res['signal'], []).append(res)

    # Очистка старых счетчиков
    for key in list(counters.keys()):
        if key not in current_keys:
            del counters[key]

    messages_to_send = []
    for sig_type, occ in grouped.items():
        n_total = len(occ)
        all_symbols = ", ".join([f"{o['symbol']} ({o['exchange']})" for o in occ])
        first_price = occ[0]['price']
        
        if n_total == 1:
            msg = f"🔔 {occ[0]['symbol']} на {occ[0]['exchange']}: {sig_type}\nЦена: {first_price:.6g}"
        else:
            msg = (f"🔔 МАССОВЫЙ СИГНАЛ: {sig_type}\n"
                   f"Найдено на {n_total} парах\n"
                   f"Пары: {all_symbols}")
        messages_to_send.append(msg)

    if messages_to_send:
        print(f"📤 Отправляем батч из {len(messages_to_send)} уведомлений...")
        try:
            success = apobj.notify(title="Crypto Monitor", body="\n\n".join(messages_to_send))
            print(f"Результат отправки Apprise: {success}")
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")
    else:
        print("🤷‍♂️ Сигналов для отправки нет.")

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
