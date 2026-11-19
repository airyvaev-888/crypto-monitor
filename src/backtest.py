"""Бэктестинг торговой стратегии на исторических данных.
Читает историю с бирж и CoinMarketCap, симулирует торговлю по сигналам."""

import asyncio
import json
import os
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from indicators import (
    compute_rsi, compute_bollinger, compute_avg_volume,
    compute_macd, compute_stoch, compute_adx,
    generate_signal, detect_divergence
)

# Настройки
HISTORY_FILE = 'data/history.json'
CMC_HISTORY_FILE = 'data/cmc_history.json'
REPORT_FILE = 'data/backtest_report.json'

# Параметры стратегии (должны совпадать с теми, что в monitor.py)
RSI_LOW = 30
RSI_HIGH = 70
ADX_THRESHOLD = 25
VOLUME_SPIKE = 1.5
VOLATILITY_THRESHOLD = 0.02


def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ Ошибка чтения {path}: {e}")
    return {}


def save_report(data):
    os.makedirs('data', exist_ok=True)
    tmp_path = f"{REPORT_FILE}.tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, REPORT_FILE)
    print(f"💾 Отчёт сохранён в {REPORT_FILE}")


async def analyze_symbol_ohlcv(ohlcv):
    """Анализирует OHLCV данные и возвращает сигнал."""
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

    return {
        'price': price,
        'signal': signal,
        'rsi': float(rsi.iloc[-1]),
        'vol_ratio': float(vol_ratio),
        'change_pct': change_pct,
        'rsi_divergence': rsi_divergence,
        'macd_divergence': macd_divergence
    }


async def run_backtest():
    print(f"🚀 Запуск бэктестинга: {datetime.now().isoformat()}")
    
    # Загрузка истории
    history = load_json(HISTORY_FILE)
    cmc_history = load_json(CMC_HISTORY_FILE)
    
    if not history or not history.get('liquid_symbols'):
        print("❌ Нет данных в history.json")
        return
        
    pairs = history.get('liquid_symbols', [])
    print(f"📊 Проверяю {len(pairs)} пар")
    
    # Симуляция торговли
    results = []
    for item in pairs:
        ex_id = item.get('exchange')
        sym = item.get('symbol')
        
        # Загрузка исторических данных для этой пары
        # Здесь нужно реализовать чтение свечей из API или локального файла
        # Для примера возьмём последние 100 свечей
        try:
            # TODO: Реализовать загрузку исторических данных
            # Например, через ccxt.async_support
            ohlcv = []  # Заглушка
            analysis = await analyze_symbol_ohlcv(ohlcv)
            
            if analysis:
                results.append({
                    'symbol': sym,
                    'exchange': ex_id,
                    'signal': analysis['signal'],
                    'price': analysis['price'],
                    'rsi': analysis['rsi'],
                    'vol_ratio': analysis['vol_ratio'],
                    'change_pct': analysis['change_pct'],
                    'rsi_divergence': analysis['rsi_divergence'],
                    'macd_divergence': analysis['macd_divergence']
                })
        except Exception as e:
            print(f"❌ Ошибка анализа {ex_id} {sym}: {e}")
            continue
    
    # Статистика
    total_trades = len(results)
    buy_signals = len([r for r in results if r['signal'] == 'BUY'])
    sell_signals = len([r for r in results if r['signal'] == 'SELL'])
    
    # Средний PnL (заглушка, нужно реализовать расчёт)
    avg_pnl = 0.0
    
    report = {
        'generated_at': pd.Timestamp.now().isoformat(),
        'total_trades': total_trades,
        'buy_signals': buy_signals,
        'sell_signals': sell_signals,
        'avg_pnl': avg_pnl,
        'results': results,
        'cmc_data': cmc_history.get('cmc_data', [])
    }
    
    save_report(report)
    print(f"✅ Бэктестинг завершён. Всего сделок: {total_trades}")


if __name__ == '__main__':
    asyncio.run(run_backtest())
