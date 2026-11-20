# src/notifier.py
import requests

NTFY_TOPIC = "your_topic_here"  # как у тебя сейчас
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"


def _tradingview_url(signal):
    return f"https://www.tradingview.com/chart/?symbol=BINANCE:{signal['symbol']}USDT"


def format_message(s):
    rsi_str = f"{s['rsi']}" if s["rsi"] is not None else "N/A"
    ex_str = ", ".join(s["exchanges"])
    return (
        f"{s['symbol']}/USDT | {ex_str}\n"
        f"Change 24h: {s['change_24h']:+.2f}%\n"
        f"Price: ${s['price']:,.6g}\n"
        f"Volume: ${s['volume']:,.0f}\n"
        f"RSI(1h): {rsi_str}\n"
        f"{_tradingview_url(s)}"
    )


def send(signal):
    title = f"{signal['side']} {signal['symbol']}/USDT {signal['change_24h']:+.1f}%"
    headers = {
        "Title": title,
        "Priority": "high",
        "Tags": "chart_with_upwards_trend" if signal["side"] == "LONG"
                else "chart_with_downwards_trend",
        "Click": _tradingview_url(signal),
    }
    try:
        r = requests.post(
            NTFY_URL,
            data=format_message(signal).encode("utf-8"),
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[ntfy] {r.status_code} {r.text}")
    except Exception as e:
        print(f"[ntfy] error: {e}")
