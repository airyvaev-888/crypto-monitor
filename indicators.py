"""
Технические индикаторы для Crypto Monitor.
Использует библиотеку pandas-ta для расчета всех индикаторов.
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
    # pandas-ta возвращает DataFrame с колонками BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
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
    plus_di = adx_df[f"DMP_{period}_{period}"]  # Positive Directional Indicator
    minus_di = adx_df[f"DMN_{period}_{period}"]  # Negative Directional Indicator
    return adx, plus_di, minus_di


def compute_avg_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Вычисляет средний объем за период (простое скользящее среднее)."""
    return volume.rolling(period).mean()
