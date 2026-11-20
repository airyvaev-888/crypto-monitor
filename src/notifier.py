import requests
import logging
import json

NTFY_TOPIC = "air-crypto-alerts-888" # Убедитесь, что тут ваш топик
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}"

def send_signal(signal):
    """Форматирует и отправляет сигнал в ntfy"""
    symbol = signal['symbol']
    signal_type = signal['type']
    price = signal['price']
    change = signal['change_24h']
    rsi = signal['rsi']
    exchanges = ", ".join(signal['exchanges'])
    
    # Эмодзи для тегов (чтобы не было проблем с кодировкой в заголовке)
    emoji = "🚀" if signal_type == "LONG" else "🔻"
    
    # Формируем заголовок (ТОЛЬКО ASCII символы)
    title = f"{signal_type} {symbol} | Crypto Alert"
    
    # Универсальная ссылка на TradingView (или можно использовать OKX)
    # Ссылка на поиск на TradingView по тикеру
    tv_link = f"https://www.tradingview.com/chart/?symbol=OKX:{symbol}USDT"
    
    # Текст сообщения
    message = (
        f"Монета: {symbol}\n"
        f"Тип: {signal_type}\n"
        f"Цена: ${price}\n"
        f"Изм. 24ч: {change:.2f}%\n"
        f"RSI (1h): {rsi if rsi else 'N/A'}\n"
        f"Биржи: {exchanges}\n\n"
        f"📈 График: {tv_link}"
    )
    
    # Заголовки для ntfy
    headers = {
        "Title": title,
        "Tags": f"{emoji},chart_with_upwards_trend",
        "Click": tv_link, # При клике на пуш откроется график
        "Priority": "high"
    }
    
    try:
        # Отправляем POST запрос
        response = requests.post(
            NTFY_URL, 
            data=message.encode('utf-8'), 
            headers=headers, 
            timeout=10
        )
        response.raise_for_status() # Вызовет исключение при ошибке 4xx/5xx
        logging.info(f"Уведомление по {symbol} успешно отправлено (Status: {response.status_code})")
        
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при отправке уведомления в ntfy: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logging.error(f"Ответ сервера: {e.response.text}")
