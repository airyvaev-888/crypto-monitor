# src/config.py

# === НАСТРОЙКИ БАЗЫ ===
MIN_MARKET_CAP = 50_000_000      
MIN_TOTAL_VOLUME = 500_000       
MIN_EXCHANGE_VOLUME = 50_000     
MIN_EXCHANGES = 2                
COOLDOWN_HOURS = 4               

# === НАСТРОЙКИ СТРАТЕГИИ (Разворот тренда) ===
TIMEFRAME = '1h'                 
RSI_PERIOD = 14
# Слегка поднимаем порог RSI, чтобы не ждать экстремальных падений
RSI_LONG_THRESHOLD = 45          # Если RSI был ниже 45 и пошел вверх
RSI_SHORT_THRESHOLD = 55         # Если RSI был выше 55 и пошел вниз

USE_EMA_FILTER = True            

# === НАСТРОЙКИ УПРАВЛЕНИЯ РИСКАМИ ===
ATR_PERIOD = 14                  
SL_ATR_MULTIPLIER = 2.0          
TP_ATR_MULTIPLIER = 4.0          
