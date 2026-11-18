"""Общие технические индикаторы для монитора, скринера и предиктора."""
import pandas as pd


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = -delta.where(delta < 0, 0.0).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


def compute_bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + std_mult * std
    lower = ma - std_mult * std
    return ma, upper, lower


def compute_ema(close: pd.Series, period: int = 50) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def compute_avg_volume(volume: pd.Series, period: int = 20) -> pd.Series:
    return volume.rolling(period).mean()
