# src/analyzer.py
import time

CHANGE_THRESHOLD = 15.0
VOLUME_CONFIRM = 500_000
MIN_EXCHANGES = 2
RSI_LONG_MAX = 75
RSI_SHORT_MIN = 25
COOLDOWN_HOURS = 4


def _is_on_cooldown(symbol, history):
    last = history.get(symbol)
    if not last:
        return False
    return (time.time() - last) < COOLDOWN_HOURS * 3600


def analyze(coins, history=None):
    history = history or {}
    signals = []
    for c in coins:
        change = c["change_24h"]
        if abs(change) < CHANGE_THRESHOLD:
            continue
        if c["volume"] < VOLUME_CONFIRM:
            continue
        if c["exchange_count"] < MIN_EXCHANGES:
            continue

        side = "LONG" if change > 0 else "SHORT"
        rsi = c.get("rsi")

        # RSI-фильтры: не LONGим на пике, не SHORTим на дне.
        # Если RSI не удалось посчитать — сигнал не блокируем (но отмечаем в сообщении).
        if rsi is not None:
            if side == "LONG" and rsi > RSI_LONG_MAX:
                continue
            if side == "SHORT" and rsi < RSI_SHORT_MIN:
                continue

        if _is_on_cooldown(c["symbol"], history):
            continue

        signals.append({
            "symbol": c["symbol"],
            "name": c["name"],
            "side": side,
            "price": c["price"],
            "change_24h": change,
            "volume": c["volume"],
            "exchanges": sorted(c["exchanges"]),
            "rsi": rsi,
            "timestamp": int(time.time()),
        })
    return signals
