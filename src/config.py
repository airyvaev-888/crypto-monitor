# src/config.py

MIN_MARKET_CAP = 50_000_000      
MIN_TOTAL_VOLUME = 500_000       
MIN_EXCHANGE_VOLUME = 50_000     
MIN_EXCHANGES = 2                
COOLDOWN_HOURS = 4               

TIMEFRAME = '1h'                 
RSI_PERIOD = 14
# Расширяем границы до 50 (середина), чтобы ловить больше откатов
RSI_LONG_THRESHOLD = 50          
RSI_SHORT_THRESHOLD = 50         

USE_EMA_FILTER = True            

ATR_PERIOD = 14                  
SL_ATR_MULTIPLIER = 2.0          
TP_ATR_MULTIPLIER = 4.0          
