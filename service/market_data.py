"""
service/market_data.py
市場數據服務 — BTC 歷史 OHLCV + DXY
增量更新：本地緩存，只下載缺失日期

[Task #1] SSL 繞過：
- 企業 Proxy 攔截 HTTPS 導致 yfinance SSL 驗證失敗
- ssl._create_unverified_context 全域覆寫預設 SSL 設定
- verify=False 的 requests.Session 注入 yfinance 使用
[Task #4] SQLite 取代 CSV：
- 改用 data_manager 的 SQLite 工具函式，解決多執行緒寫入衝突
"""
import os
import ssl
import requests
import urllib3
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta

# [Task #1] 全域關閉 SSL 憑證驗證（企業網路 Proxy 攔截 HTTPS 時必要）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except AttributeError:
    pass  # 部分 Python 環境不支援，忽略

# [Task #1] 建立 verify=False 的 requests Session，用於 yfinance 下載
# yfinance 0.2.x 的 download()/Ticker.history() 均支援 session 參數
_yf_session = requests.Session()
_yf_session.verify = False

# [Task #4] 匯入 data_manager 提供的 SQLite 讀寫工具
import data_manager


def _normalize_yf_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    統一 yfinance 欄位名稱到小寫（相容 yfinance 0.2.x MultiIndex 欄位格式）。
    yfinance 某些版本回傳 ('Close', 'BTC-USD') 格式的 MultiIndex，
    此函式將其扁平化為小寫字串，如 'close'。
    """
    df.columns = [
        c[0].lower() if isinstance(c, tuple) else c.lower()
        for c in df.columns
    ]
    return df


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
        try:
            # [Task #1] session=_yf_session 繞過 SSL 驗證
            btc_new = yf.download(
                "BTC-USD", start=start_date, interval="1d",
                progress=False, session=_yf_session
            )
            if not btc_new.empty:
                btc_new = _normalize_yf_columns(btc_new)
        except Exception as e:
            st.warning(f"[BTC] 增量更新失敗: {e}")

    elif not last_date:
        # 首次下載：從 2017-01-01 開始
        try:
            # [Task #1] session=_yf_session 繞過 SSL 驗證
            btc_new = yf.download(
                "BTC-USD", start="2017-01-01", interval="1d",
                progress=False, session=_yf_session
            )
            if not btc_new.empty:
                btc_new = _normalize_yf_columns(btc_new)
        except Exception as e:
            st.error(f"[BTC] 初始下載失敗: {e}")

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
    try:
        # [Task #1] session=_yf_session 繞過 SSL 驗證
        dxy = yf.download(
            "DX-Y.NYB", start="2017-01-01", interval="1d",
            progress=False, session=_yf_session
        )
        if not dxy.empty:
            dxy = _normalize_yf_columns(dxy)
            if dxy.index.tz is not None:
                dxy.index = dxy.index.tz_localize(None)
    except Exception:
        dxy = pd.DataFrame()

    return btc_final, dxy
