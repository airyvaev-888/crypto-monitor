import os
import requests
import logging

def send(signal):
    """
    Отправляет уведомление в ntfy с торговыми рекомендациями.
    """
    ntfy_url = os.environ.get("NTFY_URL")
    
    if not ntfy_url:
        logging.warning("NTFY_URL не задан. Уведомление не отправлено.")
        return

    symbol = signal["symbol"]
    name = signal.get("name", symbol)
    signal_type = signal["type"]
    price = signal["price"]
    tp = signal.get("tp", 0)
    sl = signal.get("sl", 0)
    rsi = signal.get("rsi", "N/A")
    reason = signal.get("reason", "")
    exchange = signal.get("exchange", "okx").upper()

    # Расчет процентов для TP и SL
    if price > 0 and tp > 0 and sl > 0:
        if signal_type == "LONG":
            tp_pct = ((tp - price) / price) * 100
            sl_pct = ((price - sl) / price) * 100
        else: # SHORT
            tp_pct = ((price - tp) / price) * 100
            sl_pct = ((sl - price) / price) * 100
        
        tp_str = f"{tp:.6g} (+{tp_pct:.2f}%)"
        sl_str = f"{sl:.6g} (-{sl_pct:.2f}%)"
    else:
        tp_str = f"{tp:.6g}"
        sl_str = f"{sl:.6g}"

    # Формируем ссылку на TradingView
    tv_link = f"https://www.tradingview.com/chart/?symbol={exchange}:{symbol}USDT"

    # Формируем рекомендации в зависимости от направления
    if signal_type == "LONG":
        rec_action = (
            "1. Покупаем по текущей цене (или ставьте лимитный ордер чуть ниже).\n"
            "2. СРАЗУ выставляем Take Profit и Stop Loss.\n"
            "3. При достижении цены на половине пути к TP, переведите SL в безубыток (Breakeven)."
        )
        emoji = "🟢"
        tags = "chart_with_upwards_trend,moneybag"
        title = f"LONG: {symbol}"
        priority = "high"
    else:
        rec_action = (
            "1. Открываем Шорт по текущей цене (или лимиткой чуть выше).\n"
            "2. СРАЗУ выставляем Take Profit и Stop Loss.\n"
            "3. При падении цены на половину пути к TP, переведите SL в безубыток."
        )
        emoji = "🔴"
        tags = "chart_with_downwards_trend,drop_of_blood"
        title = f"SHORT: {symbol}"
        priority = "high"

    # Текст сообщения
    message = (
        f"{emoji} Монета: {name} ({symbol})\n"
        f"Биржа для входа: {exchange}\n"
        f"────────────────────\n"
        f"💰 Цена входа: {price:.6g}$\n"
        f"🎯 Take Profit: {tp_str}\n"
        f"🛑 Stop Loss: {sl_str}\n"
        f"────────────────────\n"
        f"📊 RSI (1h): {rsi}\n"
        f"⚙️ Сигнал: {reason}\n"
        f"────────────────────\n"
        f"💡 РЕКОМЕНДАЦИИ:\n"
        f"{rec_action}\n"
        f"⚠️ Риск-менеджмент: не используйте более 2-5% депозита на одну сделку."
    )

    headers = {
        "Title": title,
        "Tags": tags,
        "Click": tv_link,
        "Priority": priority
    }

    try:
        response = requests.post(
            ntfy_url,
            data=message.encode('utf-8'),
            headers=headers,
            timeout=10
        )
        response.raise_for_status()
        logging.info(f"Уведомление для {symbol} ({signal_type}) успешно отправлено.")
        
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления в ntfy для {symbol}: {e}")
