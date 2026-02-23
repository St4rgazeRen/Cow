"""
service/market_data.py
市場數據服務 — BTC 歷史 OHLCV + DXY
增量更新：本地 CSV 緩存，只下載缺失日期
加入 SSL 繞過機制與 Binance 備援 API
"""
import os
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta
import requests
import urllib3
import ccxt

# 關閉 urllib3 的 SSL 憑證驗證警告 (為配合公司內網防火牆設定)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BTC_CSV = "BTC_HISTORY.csv"

def get_yf_session():
    """
    建立自訂的 requests Session 供 yfinance 使用。
    1. verify=False: 關閉 SSL 驗證，繞過公司網路阻擋。
    2. 加入 User-Agent: 降低在 Streamlit Cloud 上被 Yahoo 視為機器人阻擋的機率。
    """
    session = requests.Session()
    session.verify = False
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def fetch_binance_daily(start_date_str):
    """
    備援方案：當 Yahoo Finance 失敗時，改從 Binance 抓取 BTC/USDT 日線數據。
    使用專案既有的 ccxt 套件來獲取。
    """
    exchange = ccxt.binance()
    # 將字串日期轉換為毫秒時間戳
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp() * 1000)
    
    # ccxt 回傳格式: [timestamp, open, high, low, close, volume]
    ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1d', since=start_ts, limit=1000)
    
    if not ohlcv:
        return pd.DataFrame()
        
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('date', inplace=True)
    df.drop(columns=['timestamp'], inplace=True)
    
    # 確保 index 格式與 yfinance 一致 (移除時區資訊)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
        
    return df

@st.cache_data(ttl=300)
def fetch_market_data():
    """
    獲取 BTC-USD 日線數據（本地 CSV 增量更新）
    返回: (btc_df, dxy_df)
    """
    today = datetime.now().date()
    # 實例化帶有 SSL 繞過與偽裝的 Session
    session = get_yf_session()

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
    start_fetch_date = None
    
    if last_date and last_date < today:
        start_fetch_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
    elif not last_date:
        start_fetch_date = "2017-01-01"

    # 若有需要更新的日期，開始抓取
    if start_fetch_date:
        try:
            # 主方案：使用 yfinance 並傳入自訂 session
            btc_new = yf.download("BTC-USD", start=start_fetch_date, interval="1d", progress=False, session=session)
            if not btc_new.empty:
                # 處理 yfinance 可能回傳 MultiIndex columns 的問題
                btc_new.columns = [
                    c[0].lower() if isinstance(c, tuple) else c.lower()
                    for c in btc_new.columns
                ]
        except Exception as e:
            st.warning(f"⚠️ Yahoo Finance 連線異常，準備切換備援 API...")

        # 備援方案：若 yfinance 抓不到資料 (如在 Streamlit Cloud 上)，改用 Binance
        if btc_new.empty:
            try:
                btc_new = fetch_binance_daily(start_fetch_date)
            except Exception as e:
                st.error(f"❌ 備援 API (Binance) 也獲取失敗: {e}")

    # 3. 合併並存檔
    if not btc_new.empty:
        full_df = pd.concat([local_df, btc_new]) if not local_df.empty else btc_new
        full_df = full_df[~full_df.index.duplicated(keep='last')]
        full_df.sort_index(inplace=True)
        # 本地端存檔，避免下次啟動重複下載
        full_df.to_csv(BTC_CSV)
        btc_final = full_df
    else:
        btc_final = local_df

    if btc_final.empty:
        return pd.DataFrame(), pd.DataFrame()

    # 4. DXY (美元指數)
    try:
        # DXY 同樣套用自訂 session 避開 SSL 問題
        dxy = yf.download("DX-Y.NYB", start="2017-01-01", interval="1d", progress=False, session=session)
        dxy.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in dxy.columns]
        if not dxy.empty and dxy.index.tz is not None:
            dxy.index = dxy.index.tz_localize(None)
    except Exception:
        dxy = pd.DataFrame()

    return btc_final, dxy
