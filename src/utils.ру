"""Вспомогательные функции для Crypto Monitor.
Логирование, работа с API, форматирование данных, обработка ошибок."""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from loguru import logger


# Настройка логирования
def setup_logging(log_level: str = 'INFO'):
    """Настраивает логирование через loguru."""
    logger.remove()  # Удаляем стандартный обработчик
    logger.add(
        'logs/crypto_monitor.log',
        rotation='10 MB',
        retention='7 days',
        level=log_level,
        format='{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}'
    )
    logger.info(f"Логирование настроено. Уровень: {log_level}")


# Работа с JSON
def load_json(path: str) -> Dict[str, Any]:
    """Загружает JSON файл."""
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Ошибка чтения {path}: {e}")
    return {}


def save_json(path: str, data: Dict[str, Any]):
    """Сохраняет данные в JSON файл."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
        logger.info(f"Файл сохранён: {path}")
    except Exception as e:
        logger.error(f"Ошибка сохранения {path}: {e}")


# Работа с API
async def fetch_with_retry(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
    timeout: int = 30
) -> Optional[Dict[str, Any]]:
    """Выполняет HTTP-запрос с повторными попытками."""
    for attempt in range(max_retries):
        try:
            async with asyncio.timeout(timeout):
                async with requests.Session() as session:
                    response = await session.get(url, headers=headers, params=params)
                    response.raise_for_status()
                    return response.json()
        except Exception as e:
            logger.warning(f"Попытка {attempt + 1} не удалась: {e}")
            if attempt == max_retries - 1:
                logger.error(f"Все попытки провалились для {url}")
                return None
            await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
    return None


# Форматирование данных
def format_price(price: float) -> str:
    """Форматирует цену для вывода."""
    if price >= 1000:
        return f"{price:,.0f}"
    elif price >= 1:
        return f"{price:,.2f}"
    else:
        return f"{price:.6f}"


def format_volume(volume: float) -> str:
    """Форматирует объём для вывода."""
    if volume >= 1e9:
        return f"{volume/1e9:.1f}B"
    elif volume >= 1e6:
        return f"{volume/1e6:.1f}M"
    elif volume >= 1e3:
        return f"{volume/1e3:.1f}K"
    else:
        return f"{volume:.0f}"


def format_percentage(value: float) -> str:
    """Форматирует процент для вывода."""
    if value >= 0:
        return f"+{value:.2f}%"
    else:
        return f"{value:.2f}%"


# Обработка ошибок
def handle_error(error: Exception, context: str = "Неизвестная ошибка"):
    """Обрабатывает ошибки и логирует их."""
    logger.error(f"{context}: {error}")
    return {
        'error': str(error),
        'context': context,
        'timestamp': datetime.now().isoformat()
    }


# Проверка окружения
def check_env_variables(required_vars: List[str]) -> bool:
    """Проверяет наличие обязательных переменных окружения."""
    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        logger.error(f"Отсутствуют переменные окружения: {', '.join(missing)}")
        return False
    return True


# Утилиты для работы с временем
def get_current_time(tz: str = 'UTC') -> datetime:
    """Возвращает текущее время в указанном часовом поясе."""
    from pytz import timezone
    return datetime.now(timezone(tz))


def timestamp_to_str(timestamp: float, fmt: str = '%Y-%m-%d %H:%M:%S') -> str:
    """Преобразует timestamp в строку."""
    return datetime.fromtimestamp(timestamp).strftime(fmt)


# Пример использования
if __name__ == '__main__':
    setup_logging()
    logger.info("Utils module loaded successfully")
