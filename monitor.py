"""Часовой монитор ликвидных монет из history.json с историей сигналов и ntfy-уведомлениями."""
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
                return None
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

            # 3. Генерация торгового сигнала (BUY/SELL/HOLD)
            signal = generate_signal(
                close=close,
                volume=volume,
                rsi=pd.Series([rsi]),
                macd=macd_line,
                signal_line=signal_line,
                ema=close.ewm(span=50, adjust=False),
                stoch_k=stoch_k,
                adx=adx,
                bollinger_upper=pd.Series([upper.iloc[-1]]),
                bollinger_lower=pd.Series([lower.iloc[-1]])
            )

            print(f"[{exchange.id}] {symbol}: Цена={price:.4g}, Сигнал={signal}, RSI={rsi:.1f}")

            return {
                'symbol': symbol,
                'exchange': exchange.id,
                'price': price,
                'signal': signal,
                'rsi': rsi,
                'vol_ratio': vol_ratio,
                'change_pct': change_pct
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
    # Убедись, что в .env или Secrets GitHub есть NTFY_URL
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
