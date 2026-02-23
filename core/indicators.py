"""
core/indicators.py
技術指標計算層 — 純 Python，無 Streamlit 依賴
"""
import pandas as pd
import numpy as np
import pandas_ta as ta
from datetime import datetime


def calculate_technical_indicators(df):
    df = df.copy()
    if df.empty:
        return df

    # Moving Averages
    df['SMA_200'] = ta.sma(df['close'], length=200)
    df['EMA_20'] = ta.ema(df['close'], length=20)
    df['SMA_50'] = ta.sma(df['close'], length=50)

    # SMA 200 Slope (20-day lookback)
    if 'SMA_200' in df.columns:
        df['SMA_200_Slope'] = df['SMA_200'].diff(20)
    else:
        df['SMA_200_Slope'] = 0

    # RSI (Daily)
    df['RSI_14'] = ta.rsi(df['close'], length=14)

    # RSI (Weekly)
    weekly_close = df['close'].resample('W-MON').last()
    weekly_rsi = ta.rsi(weekly_close, length=14)
    df['RSI_Weekly'] = weekly_rsi.reindex(df.index).ffill()

    # ATR
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)

    # Bollinger Bands
    bb = ta.bbands(df['close'], length=20, std=2.0)
    if bb is not None:
        df = pd.concat([df, bb], axis=1)
        bbl = [c for c in df.columns if c.startswith('BBL')][0]
        bbu = [c for c in df.columns if c.startswith('BBU')][0]
        df['BB_Lower'] = df[bbl]
        df['BB_Upper'] = df[bbu]

    # Pivot Points (Classic)
    df['P'] = (df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 3
    df['R1'] = 2 * df['P'] - df['low'].shift(1)
    df['S1'] = 2 * df['P'] - df['high'].shift(1)
    df['R2'] = df['P'] + (df['high'].shift(1) - df['low'].shift(1))
    df['S2'] = df['P'] - (df['high'].shift(1) - df['low'].shift(1))

    # KDJ (9, 3, 3)
    kdj = ta.kdj(df['high'], df['low'], df['close'], length=9, signal=3)
    if kdj is not None:
        df = pd.concat([df, kdj], axis=1)
        df['K'] = df['K_9_3']
        df['J'] = df['J_9_3']

    # ADX
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None:
        df = pd.concat([df, adx], axis=1)
        adx_col = [c for c in df.columns if c.startswith('ADX')][0]
        df['ADX'] = df[adx_col]

    # MACD (12, 26, 9)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        macd_col = [c for c in df.columns if c.startswith('MACD_')][0]
        hist_col = [c for c in df.columns if c.startswith('MACDh_')][0]
        sig_col = [c for c in df.columns if c.startswith('MACDs_')][0]
        df['MACD'] = df[macd_col]
        df['MACD_Hist'] = df[hist_col]
        df['MACD_Signal'] = df[sig_col]

    return df


def calculate_ahr999(df):
    """
    AHR999 囤幣指標
    公式: (Price / 200日均線) × (Price / 指數增長估值)
    估值 = 10^(2.68 + 0.00057 × 創世以來天數)
    """
    genesis_date = datetime(2009, 1, 3)

    def get_val(row):
        if pd.isna(row['SMA_200']):
            return None
        days = (row.name - genesis_date).days
        valuation = 10 ** (2.68 + 0.00057 * days)
        return (row['close'] / row['SMA_200']) * (row['close'] / valuation)

    df['AHR999'] = df.apply(get_val, axis=1)

    # MVRV Z-Score Proxy
    if not df.empty and 'SMA_200' in df.columns:
        rolling_std = df['close'].rolling(window=200).std()
        df['MVRV_Z_Proxy'] = (df['close'] - df['SMA_200']) / rolling_std

    return df
