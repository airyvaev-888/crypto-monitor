import asyncio
import json
import os
from datetime import datetime

import apprise
import requests
import pandas as pd
import pytz

from indicators import (
    compute_rsi, compute_bollinger, compute_avg_volume,
    compute_macd, compute_stoch, compute_adx,
    generate_signal, detect_divergence
)

CMC_API_KEY = os.environ['CMC_API_KEY']
STATE_FILE = 'data/signals.json'

# ... (остальной код без бирж)
