"""Мониторинг CoinMarketCap. Собирает топ-100 монет по капитализации."""

import asyncio
import json
import os
from datetime import datetime

import pandas as pd
import requests

CMC_API_KEY = os.environ['CMC_API_KEY']
STATE_FILE = 'data/cmc_history.json'


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Ошибка чтения {STATE_FILE}: {e}")
    return {}


def save_state(data):
    os.makedirs('data', exist_ok=True)
    tmp_path = f"{STATE_FILE}.tmp"
    with open(tmp_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, STATE_FILE)
    print("💾 cmc_history.json обновлён")


async def main():
    print(f"CMC Monitor: {datetime.now().isoformat()}")
    
    url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
    headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
    params = {
        'start': '1',
        'limit': '100',
        'convert': 'USD'
    }
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        cmc_data = []
        for item in data.get('data', []):
            cmc_data.append({
                'symbol': item['symbol'],
                'name': item['name'],
                'price_usd': item['quote']['USD']['price'],
                'market_cap_usd': item['quote']['USD']['market_cap'],
                'volume_24h_usd': item['quote']['USD']['volume_24h'],
                'percent_change_24h': item['quote']['USD']['percent_change_24h'],
                'circulating_supply': item['circulating_supply'],
                'last_updated': item['quote']['USD']['last_updated']
            })
        
        result = {
            'cmc_data': cmc_data,
            'updated_at': pd.Timestamp.now(tz='UTC').isoformat()
        }
        
        save_state(result)
        print(f"✅ Обработано {len(cmc_data)} монет с CoinMarketCap")
        
    except Exception as e:
        print(f"❌ Ошибка запроса к CoinMarketCap: {e}")


if __name__ == '__main__':
    asyncio.run(main())
