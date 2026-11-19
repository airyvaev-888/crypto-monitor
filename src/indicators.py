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


def compute_avg_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    """Вычисляет средний объем за период."""
    return volume.rolling(window=period).mean()


def detect_divergence(close: pd.Series, indicator: pd.Series, lookback: int = 10) -> str:
    """Ищет дивергенцию между ценой и индикатором."""
    if len(close) < lookback * 2:
        return 'none'
    price_min_idx = close.iloc[-lookback:].idxmin()
    price_max_idx = close.iloc[-lookback:].idxmax()
    price_min_val = close.loc[price_min_idx]
    price_max_val = close.loc[price_max_idx]
    ind_min_val = indicator.loc[price_min_idx]
    ind_max_val = indicator.loc[price_max_idx]
    if price_min_val < close.iloc[-2] and ind_min_val > indicator.iloc[-2]:
        return 'bullish'
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
    """Генерирует торговый сигнал (BUY, SELL или HOLD)."""
    if len(close) < 2 or close.isna().any():
        return 'HOLD'
    close_curr = close.iloc[-1]
    close_prev = close.iloc[-2]
    trend_is_bullish = close_curr > ema.iloc[-1] if ema is not None else True
    trend_is_bearish = close_curr < ema.iloc[-1] if ema is not None else False
    volume_confirm = True
    if volume is not None:
        avg_volume = volume.rolling(window=20).mean().iloc[-1]
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
