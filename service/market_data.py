"""
service/market_data.py
市場數據服務 — BTC 歷史 OHLCV + DXY
增量更新：SQLite 本地緩存，只下載缺失日期

[Task #4] SQLite 取代 CSV：
- 改用 data_manager 的 SQLite 工具函式，解決多執行緒寫入衝突
"""
import os
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta

# [Task #4] 匯入 data_manager 提供的 SQLite 讀寫工具
import data_manager


def _normalize_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    統一 yfinance 欄位名稱為小寫，相容多版本。

    yfinance 各版本欄位格式差異：
    - <= 0.1.x: 平坦字串 ('Open', 'High', 'Low', 'Close', 'Volume')
    - >= 0.2.18 單 ticker: MultiIndex [('Open','BTC-USD'), ('Close','BTC-USD'), ...]
    - >= 0.2.45: MultiIndex 中第一層可能是 'Price' 等新格式

    策略：若為 MultiIndex 則取第一層並轉小寫；否則直接轉小寫。
    """
    if isinstance(df.columns, pd.MultiIndex):
        # 取第一層（屬性名稱），捨棄第二層（ticker 符號）
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    return df


def _download_yf(ticker: str, start: str) -> pd.DataFrame:
    """
    健壯的 yfinance 下載封裝，對應不同版本的 API 差異。

    yfinance 0.2.x 版本差異大，分兩步降級：
    1. yf.download() — 主要方法，不傳 session 確保相容性
    2. yf.Ticker().history() — 備援方法
    兩者均失敗時返回空 DataFrame，由上層處理。
    """
    # 方法 1: yf.download()（不傳 session，避免新舊版本相容問題）
    try:
        df = yf.download(
            ticker,
            start=start,
            interval="1d",
            progress=False,
            auto_adjust=True,   # 自動還原拆股/除息，避免欄位帶 'Adj'
        )
        if not df.empty:
            return _normalize_yf_columns(df)
    except Exception as e:
        print(f"[yfinance] download() 失敗，嘗試備援: {e}")

    # 方法 2: yf.Ticker().history()（不同版本均支援）
    try:
        ticker_obj = yf.Ticker(ticker)
        df = ticker_obj.history(
            start=start,
            interval="1d",
            auto_adjust=True,
        )
        if not df.empty:
            df.columns = [str(c).lower() for c in df.columns]
            # Ticker.history() 回傳 tz-aware index，統一去除時區
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            return df
    except Exception as e:
        print(f"[yfinance] Ticker.history() 備援也失敗: {e}")

    return pd.DataFrame()


@st.cache_data(ttl=300)
def fetch_market_data():
    """
    獲取 BTC-USD 日線數據（SQLite 增量緩存）。
    返回: (btc_df, dxy_df)

    [Task #4] 數據流說明:
    1. 從 SQLite 讀取現有 BTC 歷史（取代 pd.read_csv）
    2. 計算缺失日期範圍，只下載新數據（省頻寬）
    3. 合併後透過 data_manager._df_to_sqlite() 寫入（有寫入鎖）
    4. DXY 每次從 yfinance 重新下載（小數據，不做緩存）
    """
    today = datetime.now().date()

    # --- 1. 從 SQLite 讀取 BTC 歷史緩存 ---
    # [Task #4] 取代原本的 pd.read_csv(BTC_CSV)
    local_df  = data_manager._df_from_sqlite('btc_history')
    last_date = None

    if not local_df.empty:
        # 確保 index 為無時區 datetime
        if local_df.index.tz is not None:
            local_df.index = local_df.index.tz_localize(None)
        last_date = local_df.index[-1].date()

    # --- 2. 計算需要下載的日期範圍 ---
    btc_new = pd.DataFrame()

    if last_date and last_date < today:
        # 增量：只下載最後一筆之後的日期
        start_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
        btc_new = _download_yf("BTC-USD", start=start_date)
        if btc_new.empty:
            st.warning("[BTC] 增量更新失敗，使用現有緩存繼續運行")

    elif not last_date:
        # 首次下載：從 2017-01-01 開始
        btc_new = _download_yf("BTC-USD", start="2017-01-01")
        if btc_new.empty:
            st.error("[BTC] 首次下載失敗。請確認 yfinance 服務是否正常，或稍後重試。")

    # --- 3. 合併並寫入 SQLite ---
    if not btc_new.empty:
        full_df = pd.concat([local_df, btc_new]) if not local_df.empty else btc_new
        full_df = full_df[~full_df.index.duplicated(keep='last')]
        full_df.sort_index(inplace=True)

        # [Task #4] 使用 data_manager 的 SQLite 寫入（帶 _db_lock 安全鎖）
        data_manager._df_to_sqlite(full_df, 'btc_history')
        btc_final = full_df
    else:
        btc_final = local_df

    if btc_final.empty:
        return pd.DataFrame(), pd.DataFrame()

    # --- 4. DXY（每次重新下載，資料量小不需緩存） ---
    dxy = _download_yf("DX-Y.NYB", start="2017-01-01")

    return btc_final, dxy
