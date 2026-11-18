"""Прогнозный бот: макро-контекст + технический скор по ликвидным монетам.
Асинхронная версия с группировкой уведомлений."""
import asyncio
import json
import os
from datetime import datetime

import apprise
import ccxt.async_support as ccxt
import pandas as pd
import pytz
import requests

from indicators import (
    compute_rsi, compute_bollinger, compute_ema, compute_avg_volume,
)

CMC_API_KEY = os.environ['CMC_API_KEY']
APPRISE_URL = os.environ['APPRISE_URL']
HISTORY_FILE = 'history.json'
STATE_FILE = 'predictor_state.json'

ORENBURG_TZ = pytz.timezone('Asia/Yekaterinburg')

SCORE_INCLUDE = 70
SCORE_ALERT_INDIVIDUAL = 80
MAX_INDIVIDUAL_ALERTS = 5


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default


def atomic_save(path, data):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def get_macro():
    # ... (без изменений) ...
    data, fg = None, None
    try:
        r = requests.get(
            "https://pro-api.coinmarketcap.com/v1/global-metrics/quotes/latest",
            headers={'X-CMC_PRO_API_KEY': CMC_API_KEY}, timeout=30)
        data = r.json()['data']
    except Exception as e:
        print(f"CMC global: {e}")
    try:
        fg = requests.get("https://api.alternative.me/fng/?limit=1", timeout=15).json()['data'][0]
    except Exception as e:
        print(f"F&G: {e}")
    return {
        'btc_dominance': data['btc_dominance'] if data else None,
        'eth_dominance': data['eth_dominance'] if data else None,
        'fear_greed': int(fg['value']) if fg else None,
        'fear_greed_class': fg['value_classification'] if fg else None,
    }


async def compute_coin_score(exchange, symbol, semaphore):
    async with semaphore:
        try:
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe='1d', limit=100)
            if not ohlcv or len(ohlcv) < 60:
                return None
            df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
            close, volume = df['close'], df['volume']

            rsi = float(compute_rsi(close, 14).iloc[-1])
            _, upper, lower = compute_bollinger(close, 20, 2)
            ema50 = float(compute_ema(close, 50).iloc[-1])
            avg_vol = float(compute_avg_volume(volume, 20).iloc[-1])
            cur_vol = float(volume.iloc[-1])
            price = float(close.iloc[-1])

            score, reasons = 0, []
            width_pct = (float(upper.iloc[-1]) - float(lower.iloc[-1])) / price * 100 if price else 0
            if width_pct < 5:
                score += 25; reasons.append(f"сжатие BB ({width_pct:.1f}%)")
            if avg_vol > 0 and (cur_vol / avg_vol) >= 2.0:
                score += 25; reasons.append(f"объём x{cur_vol/avg_vol:.1f}")
            dist_ema = (price - ema50) / ema50 * 100 if ema50 else 0
            if abs(dist_ema) > 10:
                score += 20; reasons.append(f"отклонение от EMA50 {dist_ema:+.1f}%")
            if rsi < 25 or rsi > 75:
                score += 20; reasons.append(f"RSI={rsi:.0f}")
            if len(close) >= 2:
                dc = (float(close.iloc[-1]) - float(close.iloc[-2])) / float(close.iloc[-2]) * 100
                if abs(dc) >= 7:
                    score += 15; reasons.append(f"дн. движение {dc:+.1f}%")

            return {'score': min(score, 100), 'reasons': reasons}
        except Exception as e:
            print(f"Ошибка анализа {exchange.id} {symbol}: {e}")
            return None


def interpret_macro(m):
    # ... (без изменений) ...
    fg = m.get('fear_greed')
    if fg is None:
        return None
    if fg >= 80:
        return f"🌐 F&G={fg} ({m['fear_greed_class']}) — эйфория, риск коррекции"
    if fg <= 20:
        return f"🌐 F&G={fg} ({m['fear_greed_class']}) — паника, возможен отскок"
    return None


async def main():
    print(f"Predictor: {datetime.now(ORENBURG_TZ).isoformat()}")
    hist = load_json(HISTORY_FILE, {})
    items = hist.get('liquid_symbols', [])
    if not items:
        print("history.json пуст — выход")
        return

    state = load_json(STATE_FILE, {'counters': {}, 'error_breakers': {}})
    counters = state.get('counters', {})
    breakers = state.get('error_breakers', {})
    prev_snapshot = json.dumps(counters, sort_keys=True)

    macro = get_macro()
    print(f"Macro: {macro}")

    signals = []
    macro_msg = interpret_macro(macro)
    if macro_msg:
        signals.append(("market:macro_risk", macro_msg))

    seen = set()
    exchanges = {}
    semaphore_map = {}
    high = []

    for it in items:
        ex_id, sym = it.get('exchange'), it.get('symbol')
        if not ex_id or not sym or (ex_id, sym) in seen:
            continue
        seen.add((ex_id, sym))
        if ex_id not in exchanges:
            cls = getattr(ccxt, ex_id, None)
            if cls is None or breakers.get(ex_id, 0) >= 3:
                continue
            try:
                exchanges[ex_id] = cls({'enableRateLimit': True})
                semaphore_map[ex_id] = asyncio.Semaphore(5)
            except Exception as e:
                print(f"ccxt {ex_id}: {e}")
                continue
        res = await compute_coin_score(exchanges[ex_id], sym, semaphore_map[ex_id])
        if res and res['score'] >= SCORE_INCLUDE:
            high.append((res['score'], sym, ex_id, res['reasons']))

    high_sorted = sorted(high, key=lambda x: -x[0])
    individual = [h for h in high_sorted if h[0] >= SCORE_ALERT_INDIVIDUAL][:MAX_INDIVIDUAL_ALERTS]
    for score, sym, ex_id, reasons in individual:
        reasons_str = ", ".join(reasons) if reasons else "—"
        signals.append((f"{ex_id}:{sym}:high_vol", f"⚠️ {sym.replace('/USDT','')} на {ex_id}: скор {score}/100 ({reasons_str})"))

    if len(high) >= 3:
        syms = sorted({h[1].replace('/USDT', '') for h in high_sorted})[:15]
        signals.append(("market:volatility_summary", f"📊 {len(high)} монет с высоким скором: {', '.join(syms)}"))

    current_keys = set()
    to_send = []
    for key, msg in signals:
        current_keys.add(key)
        counters[key] = counters.get(key, 0) + 1
        if counters[key] % 2 == 1:
            to_send.append(msg)

    for key in list(counters.keys()):
        if key not in current_keys:
            del counters[key]

    if to_send:
        apobj = apprise.Apprise()
        apobj.add(APPRISE_URL)
        header = ""
        if macro.get('fear_greed') is not None:
            header = (f"😱 F&G: {macro['fear_greed']} ({macro['fear_greed_class']})\n"
                      f"₿ Доминация BTC: {macro['btc_dominance']:.1f}%\n\n")
        body = header + "\n\n".join(to_send)
        try:
            apobj.notify(title="Crypto Predictor", body=body)
            print(f"Отправлено сообщений: {len(to_send)}")
        except Exception as e:
            print(f"Ошибка уведомления: {e}")
    else:
        print("Нет сигналов для отправки")

    state['counters'] = counters
    state['error_breakers'] = breakers
    if json.dumps(counters, sort_keys=True) != prev_snapshot:
        atomic_save(STATE_FILE, state)
        print("predictor_state.json обновлён")

    await asyncio.gather(*[ex.close() for ex in exchanges.values()])


if __name__ == '__main__':
    asyncio.run(main())
