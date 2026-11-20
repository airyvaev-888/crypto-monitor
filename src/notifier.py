import logging
import json
import os
import time
import requests
from datetime import datetime

# Импортируем наши модули
from fetcher import fetch_exchange_tickers
from analyzer import analyze_market, update_cooldown
from notifier import send_signal

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Константы
COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
DATA_DIR = "data"
SNAPSHOT_FILE = os.path.join(DATA_DIR, "market_snapshot.json")

def fetch_coingecko_data(pages=2):
    """
    Загружает данные о монетах с CoinGecko.
    По умолчанию берет 2 страницы по 250 монет (топ-500 по капитализации).
    """
    all_coins = []
    headers = {
        "Accept": "application/json",
        "User-Agent": "CryptoMonitorBot/1.0"
    }
    
    for page in range(1, pages + 1):
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": page,
            "sparkline": "false",
            "price_change_percentage": "24h"
        }
        
        try:
            logging.info(f"Запрос к CoinGecko (страница {page})...")
            response = requests.get(COINGECKO_URL, params=params, headers=headers, timeout=15)
            
            # Обработка лимитов CoinGecko (429)
            if response.status_code == 429:
                logging.warning("Превышен лимит CoinGecko (429). Ждем 30 секунд...")
                time.sleep(30)
                response = requests.get(COINGECKO_URL, params=params, headers=headers, timeout=15)
                
            response.raise_for_status()
            data = response.json()
            
            if not data:
                break
                
            all_coins.extend(data)
            time.sleep(2) # Пауза между страницами, чтобы не получить бан
            
        except Exception as e:
            logging.error(f"Ошибка при получении данных с CoinGecko (страница {page}): {e}")
            break
            
    logging.info(f"Всего получено монет с CoinGecko: {len(all_coins)}")
    return all_coins

def save_snapshot(coins_data):
    """Сохраняет снимок рынка в JSON для истории (нужно для коммита в GitHub Actions)"""
    os.makedirs(DATA_DIR, exist_ok=True)
    
    snapshot = {
        "timestamp": datetime.now().isoformat(),
        "total_coins": len(coins_data),
        # Сохраняем только самое важное, чтобы файл не разрастался до гигабайт
        "coins": [
            {
                "symbol": c.get("symbol", "").upper(),
                "name": c.get("name", ""),
                "price": c.get("current_price", 0),
                "market_cap": c.get("market_cap", 0),
                "change_24h": c.get("price_change_percentage_24h", 0)
            } 
            for c in coins_data if c.get("market_cap", 0) > 50000000
        ]
    }
    
    try:
        with open(SNAPSHOT_FILE, 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, indent=4, ensure_ascii=False)
        logging.info(f"Снимок рынка сохранен в {SNAPSHOT_FILE}")
    except Exception as e:
        logging.error(f"Не удалось сохранить снимок рынка: {e}")

def main():
    logging.info("=== Запуск Crypto Monitor Bot ===")
    
    # 1. Получаем данные с CoinGecko
    coins_data = fetch_coingecko_data(pages=2)
    if not coins_data:
        logging.error("Нет данных с CoinGecko. Завершаем работу.")
        return
        
    # 2. Сохраняем снимок для GitHub Actions
    save_snapshot(coins_data)
    
    # 3. Загружаем данные с бирж (CCXT)
    # Передаем список тикеров для оптимизации (хотя в fetcher.py мы загружаем всё разом, 
    # это хорошая практика на будущее)
    symbols = [c.get('symbol', '').upper() for c in coins_data]
    logging.info("Загрузка тикеров с целевых бирж (OKX, Bitget, MEXC, Gate, KuCoin)...")
    exchange_tickers = fetch_exchange_tickers(symbols)
    
    # 4. Анализируем рынок
    logging.info("Анализ данных и поиск сигналов...")
    signals = analyze_market(coins_data, exchange_tickers)
    
    # 5. Отправляем сигналы и обновляем историю
    if signals:
        logging.info(f"🔥 Найдено {len(signals)} сигналов!")
        for signal in signals:
            symbol = signal['symbol']
            logging.info(f"Отправка сигнала: {signal['type']} по {symbol}")
            
            # Отправляем в ntfy
            send_signal(signal)
            
            # Записываем в историю (кулдаун), чтобы завтра не отправить то же самое
            update_cooldown(symbol)
    else:
        logging.info("Сигналов не найдено. Рынок спокоен или фильтры слишком строгие.")
        
    logging.info("=== Работа бота завершена ===")

if __name__ == "__main__":
    main()
