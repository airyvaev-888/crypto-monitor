"""Мониторинг CoinMarketCap. Собирает топ-100 монет по капитализации."""

import asyncio
import json
import os
from datetime import datetime

import pandas as pd
import requests

CMC_API_KEY = os.environ['CMC_API_KEY']
STATE_FILE = 'data/cmc_history.json'

# Порог капитализации: 50 млн долларов
MIN_MARKET_CAP = 50_000_000


def load
