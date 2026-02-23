"""
service/onchain.py
鏈上數據服務 — TVL、穩定幣市值、資金費率歷史
透過 data_manager 本地緩存 + Binance API 補救
"""
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime

import data_manager


@st.cache_data(ttl=3600)
def fetch_aux_history():
    """
    獲取輔助歷史數據:
    - BTC 鏈上 TVL (DeFiLlama)
    - 全球穩定幣市值 (DeFiLlama)
    - BTC 資金費率歷史 (Binance，迴圈分頁 2021-Now)
    返回: (tvl_df, stable_df, funding_df)
    """
    tvl = pd.DataFrame()
    stable = pd.DataFrame()
    funding = pd.DataFrame()

    # 優先透過 data_manager 本地緩存
    try:
        tvl, stable, funding = data_manager.load_all_historical_data()
    except Exception:
        pass

    # 補救：穩定幣市值
    if stable is None or stable.empty:
        stable = _fetch_stablecoin_history()

    # 補救：資金費率（迴圈分頁）
    if funding is None or funding.empty:
        funding = _fetch_funding_rate_history()

    return _clean(tvl, "tvl"), _clean(stable, "stable"), _clean(funding, "funding")


def _fetch_stablecoin_history():
    try:
        r = requests.get("https://stablecoins.llama.fi/stablecoincharts/all", timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        recs = []
        for item in r.json():
            try:
                dt = pd.to_datetime(int(item['date']), unit='s', utc=True)
                mc = float(item['totalCirculating']['peggedUSD'])
                recs.append({'date': dt, 'mcap': mc})
            except Exception:
                continue
        if recs:
            return pd.DataFrame(recs).set_index('date')
    except Exception as e:
        print(f"Stablecoin fetch error: {e}")
    return pd.DataFrame()


def _fetch_funding_rate_history():
    try:
        all_rates = []
        start_ts = int(datetime(2021, 1, 1).timestamp() * 1000)
        end_ts = int(datetime.now().timestamp() * 1000)

        for _ in range(20):
            r = requests.get(
                "https://fapi.binance.com/fapi/v1/fundingRate",
                params={'symbol': 'BTCUSDT', 'limit': 1000, 'startTime': start_ts},
                timeout=5
            )
            if r.status_code != 200:
                break
            data = r.json()
            if not data:
                break
            all_rates.extend(data)
            last_time = data[-1]['fundingTime']
            start_ts = last_time + 1
            if last_time >= end_ts - 3_600_000:
                break
            time.sleep(0.1)

        if not all_rates:
            return pd.DataFrame()

        recs = []
        for item in all_rates:
            try:
                dt = pd.to_datetime(int(item['fundingTime']), unit='ms', utc=True)
                rate = float(item['fundingRate']) * 100
                recs.append({'date': dt, 'fundingRate': rate})
            except Exception:
                continue

        if recs:
            df = pd.DataFrame(recs).set_index('date')
            df = df[~df.index.duplicated(keep='first')]
            print(f"Funding history fetched: {len(df)} rows")
            return df
    except Exception as e:
        print(f"Funding rate fetch error: {e}")
    return pd.DataFrame()


def _clean(df, name="data"):
    if df is None or df.empty:
        return pd.DataFrame()
    try:
        if df.index.dtype == 'object' or str(df.index.dtype) == 'string':
            df.index = pd.to_datetime(df.index, format='mixed', utc=True)
        else:
            df.index = pd.to_datetime(df.index, utc=True)
        df = df[df.index.notna()]
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df.sort_index(inplace=True)
        return df
    except Exception as e:
        print(f"Error cleaning {name}: {e}")
        return pd.DataFrame()
