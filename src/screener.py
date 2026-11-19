import requests
import json
import pandas as pd

CMC_API_KEY = os.environ['CMC_API_KEY']

url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
headers = {'X-CMC_PRO_API_KEY': CMC_API_KEY}
params = {'start': '1', 'limit': '100', 'convert': 'USD'}

response = requests.get(url, headers=headers, params=params)
data = response.json()

pairs = []
for item in data.get('data', []):
    pairs.append({
        "symbol": item['symbol'],
        "name": item['name'],
        "market_cap_usd": item['quote']['USD']['market_cap'],
        "volume_24h_usd": item['quote']['USD']['volume_24h']
    })

with open('data/history.json', 'w') as f:
    json.dump({"liquid_symbols": pairs, "updated_at": pd.Timestamp.now().isoformat()}, f, indent=2)
