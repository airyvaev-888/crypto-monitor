"""
Технические индикаторы для Crypto Monitor.
Использует pandas-ta. Включает расчет дивергенций и историю сигналов.
"""

import pandas as pd
import pandas_ta as ta


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Вычисляет RSI (Индекс относительной силы) через pandas-ta."""
    rsi = ta.rsi(close, length=period)
    return rsi


def compute_bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """Вычисляет Bollinger Bands (Ленты Боллинджера) через pandas-ta."""
    bbands = ta.bbands(close, length=period, std=std_mult)
    ma = bbands[f"BBM_{period}_{std_mult}"]
    upper = bbands[f"BBU_{period}_{std_mult}"]
    lower = bbands[f"BBL_{period}_{std_mult}"]
    return ma, upper, lower


def compute_ema(close: pd.Series, period: int = 50) -> pd.Series:
    """Вычисляет EMA (Экспоненциальная скользящая средняя) через pandas-ta."""
    ema = ta.ema(close, length=period)
    return ema


def compute_macd(close: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
    """Вычисляет MACD, сигнальную линию и гистограмму через pandas-ta."""
    macd_df = ta.macd(close, fast=fast_period, slow=slow_period, signal=signal_period)
    macd_line = macd_df[f"MACD_{fast_period}_{slow_period}_{signal_period}"]
    signal_line = macd_df[f"MACDs_{fast_period}_{slow_period}_{signal_period}"]
    histogram = macd_df[f"MACDh_{fast_period}_{slow_period}_{signal_period}"]
    return macd_line, signal_line, histogram


def compute_stoch(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3):
    """Вычисляет Stochastic Oscillator (%K и %D) через pandas-ta."""
    stoch_df = ta.stoch(high=high, low=low, close=close, k=k_period, d=d_period)
    stoch_k = stoch_df[f"STOCHk_{k_period}_{d_period}_{d_period}"]
    stoch_d = stoch_df[f"STOCHd_{k_period}_{d_period}_{d_period}"]
    return stoch_k, stoch_d


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    """Вычисляет ADX (сила тренда), +DI и -DI через pandas-ta."""
    adx_df = ta.adx(high=high, low=low, close=close, length=period)
    adx = adx_df[f"ADX_{period}"]
    plus_di = adx_df[f"DMP_{period}_{period}"]
    minus_di = adx_df[f"DMN_{period}_{period}"]
    return adx, plus_di, minus_di


def compute_avg_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Вычисляет средний объем за период (простое скользящее среднее)."""
    return volume.rolling(period).mean()


def detect_divergence(close: pd.Series, indicator: pd.Series, lookback: int = 10) -> str:
    """
    Ищет дивергенцию между ценой и индикатором.
    :param close: Цены закрытия.
    :param indicator: Значения индикатора (RSI, MACD и т.д.).
    :param lookback: Сколько свечей смотреть назад.
    :return: 'bullish', 'bearish' или 'none'.
    """
    if len(close) < lookback * 2:
        return 'none'

    # Ищем локальные минимумы и максимумы цены
    price_min_idx = close.iloc[-lookback:].idxmin()
    price_max_idx = close.iloc[-lookback:].idxmax()
    
    price_min_val = close.loc[price_min_idx]
    price_max_val = close.loc[price_max_idx]

    # Ищем соответствующие точки на индикаторе
    ind_min_val = indicator.loc[price_min_idx]
    ind_max_val = indicator.loc[price_max_idx]

    # Бычья дивергенция: цена делает Lower Low, а индикатор Higher Low
    if price_min_val < close.iloc[-2] and ind_min_val > indicator.iloc[-2]:
        return 'bullish'
    
    # Медвежья дивергенция: цена делает Higher High, а индикатор Lower High
    if price_max_val > close.iloc[-2] and ind_max_val < indicator.iloc[-2]:
        return 'bearish'
        
    return 'none'


def generate_signal(
    close: pd.Series,
    volume: pd.Series = None,
    rsi: pd.Series = None,
    macd: pd.Series = None,
    signal_line: pd.Series = None,
    ema: pd.Series = None,
    stoch_k: pd.Series = None,
    adx: pd.Series = None,
    bollinger_upper: pd.Series = None,
    bollinger_lower: pd.Series = None,
    rsi_oversold: int = 30,
    rsi_overbought: int = 70,
    adx_trend_threshold: int = 25,
    volume_spike_multiplier: float = 1.5,
    volatility_threshold: float = 0.02
) -> str:
    """
    Генерирует торговый сигнал (BUY, SELL или HOLD) на основе набора индикаторов.
    Учитывает объем и волатильность для фильтрации ложных сигналов.
    """
    if len(close) < 2 or close.isna().any():
        return 'HOLD'
        
    close_curr = close.iloc[-1]
    close_prev = close.iloc[-2]
    
    trend_is_bullish = close_curr > ema.iloc[-1] if ema is not None else True
    trend_is_bearish = close_curr < ema.iloc[-1] if ema is not None else False
    
    volume_confirm = True
    if volume is not None:
        avg_volume = volume.rolling(20).mean().iloc[-1]
        curr_volume = volume.iloc[-1]
        volume_confirm = curr_volume > (avg_volume * volume_spike_multiplier)
        
    volatility_confirm = True
    if bollinger_upper is not None and bollinger_lower is not None:
        upper = bollinger_upper.iloc[-1]
        lower = bollinger_lower.iloc[-1]
        band_width = (upper - lower) / close_curr
        volatility_confirm = band_width > volatility_threshold
        
    macd_buy = False
    macd_sell = False
    if macd is not None and signal_line is not None:
        macd_curr, signal_curr = macd.iloc[-1], signal_line.iloc[-1]
        macd_prev, signal_prev = macd.iloc[-2], signal_line.iloc[-2]
        if macd_prev < signal_prev and macd_curr > signal_curr:
            macd_buy = True
        elif macd_prev > signal_prev and macd_curr < signal_curr:
            macd_sell = True
            
    rsi_buy = False
    rsi_sell = False
    if rsi is not None:
        rsi_curr = rsi.iloc[-1]
        if rsi_curr > rsi_oversold and rsi_curr < 50:
            rsi_buy = True
        elif rsi_curr > rsi_overbought:
            rsi_sell = True
            
    stoch_buy = False
    stoch_sell = False
    if stoch_k is not None:
        stoch_curr = stoch_k.iloc[-1]
        if stoch_curr < 20:
            stoch_buy = True
        elif stoch_curr > 80:
            stoch_sell = True
            
    trend_is_strong = True
    if adx is not None:
        trend_is_strong = adx.iloc[-1] > adx_trend_threshold
        
    is_buy_signal = (
        trend_is_bullish and 
        (macd_buy or rsi_buy or stoch_buy) and 
        trend_is_strong and 
        volume_confirm and 
        volatility_confirm
    )
    
    is_sell_signal = (
        trend_is_bearish and 
        (macd_sell or rsi_sell or stoch_sell) and 
        trend_is_strong and 
        volume_confirm and 
        volatility_confirm
    )
    
    if is_buy_signal:
        return 'BUY'
    elif is_sell_signal:
        return 'SELL'
    else:
        return 'HOLD'
