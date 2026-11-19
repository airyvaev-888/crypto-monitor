"""Технические индикаторы для Crypto Monitor.
Реализация без pandas-ta (только pandas + numpy)."""

import pandas as pd
import numpy as np


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Вычисляет RSI (Индекс относительной силы)."""
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_ema(close: pd.Series, period: int = 50) -> pd.Series:
    """Вычисляет EMA (Экспоненциальная скользящая средняя)."""
    return close.ewm(span=period, adjust=False).mean()


def compute_macd(close: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9):
    """Вычисляет MACD, сигнальную линию и гистограмму."""
    ema_fast = close.ewm(span=fast_period, adjust=False).mean()
    ema_slow = close.ewm(span=slow_period, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """Вычисляет Bollinger Bands (Ленты Боллинджера)."""
    ma = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = ma + std_mult * std
    lower = ma - std_mult * std
    return ma, upper, lower


def compute_stoch(high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3):
    """Вычисляет Stochastic Oscillator (%K и %D)."""
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    stoch_k = 100 * ((close - lowest_low) / (highest_high - lowest_low))
    stoch_d = stoch_k.rolling(window=d_period).mean()
    return stoch_k, stoch_d


def compute_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    """Вычисляет ADX (сила тренда), +DI и -DI."""
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    up_move = high.diff()
    down_move = low.diff().abs()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))
    adx = dx.rolling(window=period).mean()
    return adx, plus_di, minus_di


def compute_avg_volume(volume:
