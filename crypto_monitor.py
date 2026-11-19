"""Часовой монитор ликвидных монет из history.json."""
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
)

HISTORY_FILE = 'history.json'
STATE_FILE = 'monitor_state.json'
TIMEFRAME = '1h'

EXCHANGE_IDS = ['binance', 'kucoin', 'bybit', 'mexc', 'gateio']
FALLBACK_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']

ORENBURG_TZ = pytz.timezone('Asia/Yekaterinburg')
WINDOW_START = 8
WINDOW_END = 20

RSI_LOW = 99
RSI_HIGH = 70
VOLUME_SPIKE_RATIO = 2.5
VOLUME_SPIKE_CHANGE_PCT = 2.5

RPS_LIMITS = {
    'binance': 10,
    'kucoin': 10,
    'bybit': 10,
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
                return []
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            close = df['close']
            volume = df['volume']

            rsi = float(compute_rsi(close, 14).iloc[-1])
            _, upper, lower = compute_bollinger(close, 20, 2)
            avg_vol = float(compute_avg_volume(volume, 20).iloc[-1])
            price = float(close.iloc[-1])
            cur_vol = float(volume.iloc[-1])
            prev_close = float(close.iloc[-2]) if len(close) > 1 else price
            change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0

            # 🔍 ДИАГНОСТИКА: Выводим метрики в лог, чтобы видеть, что происходит
            vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0
            print(f"[{exchange.id}] {symbol}: Цена={price:.4g}, RSI={rsi:.1f}, Объем={vol_ratio:.1f}x, Изм={change_pct:+.2f}%")

            signals = []
            if rsi < RSI_LOW and price <= float(lower.iloc[-1]):
                signals.append(('bounce_low', f"RSI={rsi:.1f}, цена у нижней BB ({price:.6g}) — отскок от низа"))
            if rsi > RSI_HIGH and price >= float(upper.iloc[-1]):
                signals.append(('bounce_high', f"RSI={rsi:.1f}, цена у верхней BB ({price:.6g}) — отскок от верха"))
            if avg_vol > 0 and vol_ratio >= VOLUME_SPIKE_RATIO \
                    and abs(change_pct) >= VOLUME_SPIKE_CHANGE_PCT:
                arrow = "↑" if change_pct > 0 else "↓"
                signals.append(('volume_anomaly',
                                f"Объём x{vol_ratio:.1f} при изменении {change_pct:+.2f}% {arrow}"))
            
            if signals:
                print(f"🔥 НАЙДЕН СИГНАЛ: {exchange.id} {symbol} -> {signals}")
            return signals
        except Exception as e:
            print(f"❌ Ошибка запроса {exchange.id} {symbol}: {e}")
            return None


async def main():
    if not in_window():
        print(f"⏳ Вне окна ({now_orenburg().strftime('%H:%M')} Оренбург). Выход.")
        return

    print("✅ Мы внутри временного окна. Начинаем работу...")
    state = load_json(STATE_FILE, {'counters': {}, 'error_breakers': {}})
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
    for (ex_id, sym), res in zip([(t[0], t[1]) for t in tasks], results):
        if isinstance(res, Exception):
            print(f"Task error {ex_id} {sym}: {res}")
            breakers[ex_id] = breakers.get(ex_id, 0) + 1
            continue
        if not res:
            continue
        for sig_type, desc in res:
            key = f"{ex_id}:{sym}:{sig_type}"
            current_keys.add(key)
            counters[key] = counters.get(key, 0) + 1
            grouped.setdefault((sym.replace('/USDT', ''), sig_type), []).append(
                (ex_id, desc, counters[key]))

    for key in list(counters.keys()):
        if key not in current_keys:
            print(f"♻️ Сброс счетчика (сигнал пропал): {key}")
            del counters[key]

    messages_to_send = []
    for (short_sym, sig_type), occ in grouped.items():
        to_notify = [(ex, desc) for ex, desc, cnt in occ if cnt % 2 == 1]
        if not to_notify:
            print(f"⏭️ Пропуск отправки для {short_sym} ({sig_type}) - логика 'через раз' (счетчик четный)")
            continue
        n_total = len(occ)
        all_exchanges = ", ".join(ex for ex, _, _ in occ)
        first_desc = occ[0][1]
        if n_total == 1:
            msg = f"🔔 {short_sym} на {all_exchanges}: {sig_type}\n{first_desc}"
        else:
            msg = (f"🔔 {short_sym}: {sig_type} — сигнал на {n_total} из {len(EXCHANGE_IDS)} бирж\n"
                   f"Биржи: {all_exchanges}\n{first_desc}")
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
