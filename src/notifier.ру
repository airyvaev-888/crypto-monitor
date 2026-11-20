import os
import requests


def send_ntfy(title: str, message: str):
    url = os.getenv('NTFY_URL')
    if not url:
        print("[ERROR] NTFY_URL не задан в секретах GitHub")
        return

    try:
        response = requests.post(
            url,
            data=message.encode('utf-8'),
            headers={
                'Title': title,
                'Priority': 'high',
                'Tags': 'chart_with_upwards_trend',
            },
            timeout=30,
        )
        response.raise_for_status()
        print(f"[INFO] Уведомление отправлено: {title}")
    except Exception as e:
        print(f"[ERROR] Ошибка отправки в ntfy: {e}")
