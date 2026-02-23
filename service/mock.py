"""
service/mock.py
模擬數據 & Proxy 計算 — API 失敗時的備援
"""
import math
import random
import numpy as np
from datetime import datetime


def get_mock_funding_rate():
    base = 0.0001
    noise = random.uniform(-0.00005, 0.0005)
    return (base + noise) * 100


def get_mock_onchain_data():
    return {
        "SOPR": 1.0 + random.uniform(-0.05, 0.1),
        "MVRV": 1.5 + random.uniform(-0.5, 1.5),
    }


def get_mock_m2_liquidity():
    base_growth = 5.0
    cycle = math.sin(datetime.now().timestamp() / 1_000_000) * 3
    return base_growth + cycle


def get_mock_tvl(price):
    locked = 500_000 * random.uniform(0.9, 1.2)
    return (locked * price) / 1e9


def get_mock_global_m2_series(df):
    m2 = df['close'].rolling(window=100).mean()
    m2_norm = (m2 / m2.iloc[0]) * 100
    time_idx = np.arange(len(df))
    macro_cycle = 5 * np.sin(time_idx / 365)
    return m2_norm + macro_cycle


def get_realtime_proxies(current_price, previous_close):
    """CEX 流量、ETF 流量、清算熱度 Proxy"""
    pct_change = (current_price - previous_close) / previous_close
    cex_flow = -1 * (pct_change * 100_000) * random.uniform(0.8, 1.2)
    etf_flow = (pct_change * 5_000) * 10
    if abs(etf_flow) < 10:
        etf_flow = random.uniform(-50, 50)
    liq_clusters = [
        {"price": current_price * 1.02, "vol": "High", "side": "Short"},
        {"price": current_price * 0.98, "vol": "Medium", "side": "Long"},
        {"price": current_price * 1.05, "vol": "Extreme", "side": "Short"},
    ]
    return {"cex_flow": cex_flow, "etf_flow": etf_flow, "liq_map": liq_clusters}


def calculate_fear_greed_proxy(rsi, close, ma50):
    score = rsi
    score += 10 if close > ma50 else -10
    return max(5, min(95, score))
