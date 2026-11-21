import os
import requests
import logging

def send(signal):
    """
    Отправляет уведомление в ntfy на основе данных сигнала.
    """
    # Берем URL топика из переменной окружения (передается из GitHub Secrets)
    ntfy_url = os.environ.get("NTFY_URL")
    
    if not ntfy_url:
        logging.warning("NTFY_URL не задан. Уведомление не отправлено.")
        return

    symbol = signal["symbol"]
    signal_type = signal["type"]
    price = signal["price"]
    change = signal["change"]
    rsi = signal.get("rsi", "N/A")
    exchanges = ", ".join([ex.upper() for ex in signal["exchanges"]])

    # Формируем ссылку на TradingView (используем OKX, как договаривались)
    # Формат: OKX:BTCUSDT
    tv_link = f"https://www.tradingview.com/chart/?symbol=OKX:{symbol}USDT"

    # Текст сообщения
    message = (
        f"Монета: {symbol}\n"
        f"Цена: {price}$\n"
        f"Изменение (24ч): {change}%\n"
        f"RSI (1h): {rsi}\n"
        f"Биржи: {exchanges}"
    )

    # Эмодзи для тегов
    if signal_type == "LONG":
        tags = "chart_with_upwards_trend,moneybag"
        title = f"LONG: {symbol}"
    else:
        tags = "chart_with_downwards_trend,drop_of_blood"
        title = f"SHORT: {symbol}"

    headers = {
        "Title": title,           # Заголовок (без эмодзи, чтобы не ломалось кодирование)
        "Tags": tags,             # Эмодзи через теги
        "Click": tv_link,         # Ссылка при клике на уведомление
        "Priority": "high" if abs(change) > 20 else "default" # Если изменение > 20%, делаем приоритетным
    }

    try:
        # Отправляем запрос в ntfy
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
