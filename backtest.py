"""
Бэктестинг стратегии Crypto Monitor на исторических данных.
Читает данные из history.json и рассчитывает PnL (прибыль/убыток).
"""

import json
import pandas as pd
from datetime import datetime
from indicators import (
    compute_rsi, compute_bollinger, compute_avg_volume,
    compute_macd, compute_stoch, compute_adx,
    generate_signal
)

HISTORY_FILE = 'history.json'
TIMEFRAME = '1h'

# Параметры стратегии (должны совпадать с теми, что в monitor.py)
RSI_LOW = 30
RSI_HIGH = 70
ADX_THRESHOLD = 25
VOLUME_SPIKE = 1.5
VOLATILITY_THRESHOLD = 0.02


def load_history_data():
    """Загружает исторические данные из history.json."""
    try:
        with open(HISTORY_FILE, 'r') as f:
            data = json.load(f)
        
        # Ищем ликвидные пары
        liquid_symbols = data.get('liquid_symbols', [])
        if not liquid_symbols:
            print("❌ В history.json нет данных о ликвидных парах.")
            return {}
            
        # Группируем данные по парам
        history = {}
        for item in liquid_symbols:
            ex = item['exchange']
            sym = item['symbol']
            key = f"{ex}:{sym}"
            
            # Ищем данные для этой пары в массиве history
            for h in data.get('history', []):
                if h.get('exchange') == ex and h.get('symbol') == sym:
                    history[key] = pd.DataFrame(h['ohlcv'])
                    break
                    
        return history
    except FileNotFoundError:
        print(f"❌ Файл {HISTORY_FILE} не найден. Запусти монитор сначала.")
        return {}
    except Exception as e:
        print(f"❌ Ошибка чтения истории: {e}")
        return {}


def run_backtest_for_pair(df: pd.DataFrame, pair_name: str):
    """Запускает бэктест для одной пары."""
    if len(df) < 50:
        print(f"⚠️ Недостаточно данных для {pair_name} (нужно >50 свечей)")
        return None

    # Подготовка данных
    close = df['close']
    volume = df['volume']
    high = df['high']
    low = df['low']
    
    # Расчет индикаторов (используем те же функции, что и в мониторе)
    rsi = compute_rsi(close, 14)
    _, upper_bb, lower_bb = compute_bollinger(close, 20, 2)
    macd, signal_line, _ = compute_macd(close)
    stoch_k, _ = compute_stoch(high, low, close)
    adx, _, _ = compute_adx(high, low, close)
    ema_50 = close.ewm(span=50, adjust=False)
    
    # Состояние портфеля
    position = 0  # 0 = вне рынка, 1 = в лонге
    entry_price = 0
    trades = []
    
    print(f"📊 Тестирование {pair_name} ({len(df)} свечей)...")
    
    for i in range(50, len(df)):  # Начинаем с 50-й свечи, чтобы индикаторы "прогрелись"
        # Берем данные до текущей свечи (не включая текущую, чтобы избежать заглядывания в будущее)
        close_hist = close.iloc[:i]
        volume_hist = volume.iloc[:i]
        high_hist = high.iloc[:i]
        low_hist = low.iloc[:i]
        
        # Генерируем сигнал на основе прошлых данных
        signal = generate_signal(
            close=close_hist,
            volume=volume_hist,
            rsi=rsi.iloc[:i],
            macd=macd.iloc[:i],
            signal_line=signal_line.iloc[:i],
            ema=ema_50.iloc[:i],
            stoch_k=stoch_k.iloc[:i],
            adx=adx.iloc[:i],
            bollinger_upper=pd.Series([upper_bb.iloc[i-1]]),
            bollinger_lower=pd.Series([lower_bb.iloc[i-1]]),
            rsi_oversold=RSI_LOW,
            rsi_overbought=RSI_HIGH,
            adx_trend_threshold=ADX_THRESHOLD,
            volume_spike_multiplier=VOLUME_SPIKE,
            volatility_threshold=VOLATILITY_THRESHOLD
        )
        
        current_price = close.iloc[i]
        
        # Логика входа и выхода
        if position == 0 and signal == 'BUY':
            # Открываем лонг
            position = 1
            entry_price = current_price
            trades.append({
                'type': 'BUY',
                'price': entry_price,
                'time': df['ts'].iloc[i]
            })
            print(f"   🟢 BUY @ {entry_price:.6g}")
            
        elif position == 1 and signal == 'SELL':
            # Закрываем лонг
            pnl = (current_price - entry_price) / entry_price * 100
            trades.append({
                'type': 'SELL',
                'price': current_price,
                'pnl': pnl,
                'time': df['ts'].iloc[i]
            })
            print(f"   🔴 SELL @ {current_price:.6g} | PnL: {pnl:+.2f}%")
            position = 0
            entry_price = 0
            
        # Если сигнал HOLD - ничего не делаем
        
    # Итоговая статистика
    if not trades:
        print(f"❌ Для {pair_name} не было совершено ни одной сделки.")
        return None
        
    total_trades = len([t for t in trades if t['type'] == 'BUY'])
    winning_trades = len([t for t in trades if t.get('pnl', 0) > 0])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    
    total_pnl = sum(t.get('pnl', 0) for t in trades if 'pnl' in t)
    avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
    
    return {
        'pair': pair_name,
        'total_trades': total_trades,
        'win_rate': win_rate,
        'total_pnl': total_pnl,
        'avg_pnl': avg_pnl,
        'trades': trades
    }


def main():
    print("🚀 Запуск бэктестинга стратегии Crypto Monitor...")
    print("=" * 60)
    
    history = load_history_data()
    if not history:
        return
        
    all_results = []
    
    for pair_name, df in history.items():
        result = run_backtest_for_pair(df, pair_name)
        if result:
            all_results.append(result)
            
    # Итоговый отчет
    print("\n" + "=" * 60)
    print("📈 ИТОГОВЫЙ ОТЧЕТ ПО СТРАТЕГИИ")
    print("=" * 60)
    
    if not all_results:
        print("❌ Нет данных для анализа.")
        return
        
    grand_total_trades = 0
    grand_total_pnl = 0
    
    for res in all_results:
        print(f"\n📊 {res['pair']}:")
        print(f"   Сделок: {res['total_trades']}")
        print(f"   Win Rate: {res['win_rate']:.1f}%")
        print(f"   Суммарный PnL: {res['total_pnl']:+.2f}%")
        print(f"   Средний PnL на сделку: {res['avg_pnl']:+.2f}%")
        
        grand_total_trades += res['total_trades']
        grand_total_pnl += res['total_pnl']
        
    print("\n" + "=" * 60)
    print(f"💰 ОБЩИЙ ИТОГ: {grand_total_trades} сделок, Суммарный PnL: {grand_total_pnl:+.2f}%")
    print("=" * 60)
    
    # Сохранение отчета в JSON
    report = {
        'generated_at': datetime.now().isoformat(),
        'results': all_results,
        'summary': {
            'total_trades': grand_total_trades,
            'total_pnl': grand_total_pnl
        }
    }
    
    with open('backtest_report.json', 'w') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
        
    print(f"💾 Отчет сохранен в backtest_report.json")


if __name__ == '__main__':
    main()
