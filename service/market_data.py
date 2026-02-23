"""
service/market_data.py
市場數據服務 — BTC 歷史 OHLCV + DXY
增量更新：本地 CSV 緩存，只下載缺失日期
"""
import os
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta

BTC_CSV = "BTC_HISTORY.csv"


@st.cache_data(ttl=300)
def fetch_market_data():
    """
    獲取 BTC-USD 日線數據（本地 CSV 增量更新）
    返回: (btc_df, dxy_df)
    """
    today = datetime.now().date()

    # 1. 讀取本地緩存
    if os.path.exists(BTC_CSV):
        try:
            local_df = pd.read_csv(BTC_CSV, index_col=0, parse_dates=True)
            if local_df.index.tz is not None:
                local_df.index = local_df.index.tz_localize(None)
            last_date = local_df.index[-1].date()
        except Exception:
            local_df = pd.DataFrame()
            last_date = None
    else:
        local_df = pd.DataFrame()
        last_date = None

    # 2. 確定需要下載的範圍
    btc_new = pd.DataFrame()
    if last_date and last_date < today:
        start_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
        try:
            btc_new = yf.download("BTC-USD", start=start_date, interval="1d", progress=False)
            if not btc_new.empty:
                btc_new.columns = [
                    c[0].lower() if isinstance(c, tuple) else c.lower()
                    for c in btc_new.columns
                ]
        except Exception as e:
            st.warning(f"增量更新失敗: {e}")
    elif not last_date:
        try:
            btc_new = yf.download("BTC-USD", start="2017-01-01", interval="1d", progress=False)
            btc_new.columns = [
                c[0].lower() if isinstance(c, tuple) else c.lower()
                for c in btc_new.columns
            ]
        except Exception as e:
            st.error(f"初始下載失敗: {e}")

    # 3. 合併並存檔
    if not btc_new.empty:
        full_df = pd.concat([local_df, btc_new]) if not local_df.empty else btc_new
        full_df = full_df[~full_df.index.duplicated(keep='last')]
        full_df.sort_index(inplace=True)
        full_df.to_csv(BTC_CSV)
        btc_final = full_df
    else:
        btc_final = local_df

    if btc_final.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 4. DXY
    try:
        dxy = yf.download("DX-Y.NYB", start="2017-01-01", interval="1d", progress=False)
        dxy.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in dxy.columns]
        if not dxy.empty and dxy.index.tz is not None:
            dxy.index = dxy.index.tz_localize(None)
    except Exception:
        dxy = pd.DataFrame()

    return btc_final, dxy
