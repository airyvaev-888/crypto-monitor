import json
from datetime import datetime, timezone

GROWTH_THRESHOLD = 15
DROP_THRESHOLD = -15
VOLUME_CONFIRM = 500000
SNAPSHOT_PATH = 'data/market_snapshot.json'


def load_snapshot():
    try:
        with open(SNAPSHOT_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"[WARN] {SNAPSHOT_PATH} не найден — сигналов нет")
        return []
    except Exception as e:
        print(f"[ERROR] Ошибка чтения snapshot: {e}")
        return []


def analyze_signals():
    data = load_snapshot()
    signals = []

    for coin in data:
        change = coin.get('price_change_24h') or 0
        volume = coin.get('total_volume') or 0

        if change >= GROWTH_THRESHOLD and volume >= VOLUME_CONFIRM:
            signals.append({
                'symbol': coin['symbol'],
                'type': 'LONG',
                'reason': f"Импульс {change:.2f}% | Объём {volume / 1e6:.1f}M$",
                'exchanges': list(coin['liquid_exchanges'].keys()),
            })

        if change <= DROP_THRESHOLD and volume >= VOLUME_CONFIRM:
            signals.append({
                'symbol': coin['symbol'],
                'type': 'SHORT',
                'reason': f"Дамп {change:.2f}% | Объём {volume / 1e6:.1f}M$",
                'exchanges': list(coin['liquid_exchanges'].keys()),
            })

    return signals


def main():
    signals = analyze_signals()

    if not signals:
        print("[INFO] Сигналов не найдено.")
        return

    from notifier import send_ntfy
    time_label = datetime.now(timezone.utc).strftime('%H:%M UTC')
    title = f"Торговые сигналы ({time_label})"

    msg_lines = []
    for s in signals:
        msg_lines.append(
            f"• {s['type']} {s['symbol']}: {s['reason']} "
            f"(Биржи: {', '.join(s['exchanges'])})"
        )

    send_ntfy(title, "\n".join(msg_lines))


if __name__ == '__main__':
    main()
