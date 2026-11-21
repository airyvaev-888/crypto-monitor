import json
import os
import time

from fetcher import fetch_market_data
from analyzer import analyze
from notifier import send

HISTORY_PATH = "data/signals_history.json"
SNAPSHOT_PATH = "data/market_snapshot.json"
HISTORY_TTL_DAYS = 7


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clean_history(history):
    cutoff = time.time() - HISTORY_TTL_DAYS * 86400
    return {sym: ts for sym, ts in history.items() if ts >= cutoff}


def save_snapshot(coins):
    snapshot = load_json(SNAPSHOT_PATH, [])
    for c in coins:
        c = dict(c)
        
        # ИСПРАВЛЕНИЕ: берем ключи из exchange_tickers, а не ищем exchanges
        if "exchange_tickers" in c:
            c["exchanges"] = sorted(c["exchange_tickers"].keys())
            del c["exchange_tickers"] # Удаляем тяжелый словарь, чтобы не раздувать JSON
        else:
            c["exchanges"] = []
            
        c["timestamp"] = int(time.time())
        snapshot.append(c)
    save_json(SNAPSHOT_PATH, snapshot)


def main():
    coins = fetch_market_data()
    print(f"Coins fetched: {len(coins)}")

    history = clean_history(load_json(HISTORY_PATH, {}))
    signals = analyze(coins, history)
    print(f"Signals: {len(signals)}")

    for s in signals:
        send(s)
        history[s["symbol"]] = s["timestamp"]

    save_json(HISTORY_PATH, history)
    save_snapshot(coins)


if __name__ == "__main__":
    main()
