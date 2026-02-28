"""
service/onchain.py
鏈上數據服務 — TVL、穩定幣市值、資金費率歷史
透過 data_manager 本地緩存 + Binance API 補救 (新增 Bybit 備援機制)

[Task #1] SSL 繞過：所有外部 requests.get() 加入 verify=False
[Task #2] 非同步抓取：_fetch_funding_rate_history 改用 httpx.AsyncClient 並行發送請求
[Task #3] Geo-block 備援：新增 Bybit API 作為 Binance 遭遇 451 時的備用方案
"""
import time
import asyncio          
import requests
import urllib3          
import httpx            
import pandas as pd
import streamlit as st
from datetime import datetime

import data_manager

# 從集中設定檔讀取 SSL 動態驗證旗標
from config import SSL_VERIFY

# [Task #1] 動態 SSL：本地開發環境才關閉警告
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

@st.cache_data(ttl=3600)
def fetch_aux_history():
    """
    獲取輔助歷史數據:
    - BTC 鏈上 TVL (DeFiLlama)
    - 全球穩定幣市值 (DeFiLlama)
    - BTC 資金費率歷史 (Binance / Bybit，迴圈分頁 2021-Now)
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

    # 補救：資金費率（非同步抓取）
    if funding is None or funding.empty:
        funding = _fetch_funding_rate_history()

    return _clean(tvl, "tvl"), _clean(stable, "stable"), _clean(funding, "funding")

def _fetch_stablecoin_history():
    """
    同步補救：直接抓取全量穩定幣歷史市值。
    [Task #1] verify=False 繞過企業 SSL 憑證阻擋。
    """
    try:
        r = requests.get(
            "https://stablecoins.llama.fi/stablecoincharts/all",
            timeout=10,
            verify=SSL_VERIFY,  
        )
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

# ──────────────────────────────────────────────────────────────────────────────
# [Task #2] 非同步資金費率抓取 (加入 Bybit 備援)
# ──────────────────────────────────────────────────────────────────────────────

async def _fetch_binance_funding_page_async(client: httpx.AsyncClient, start_ts: int) -> list:
    """抓取 Binance 單頁資金費率"""
    try:
        resp = await client.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={'symbol': 'BTCUSDT', 'limit': 1000, 'startTime': start_ts},
            timeout=10.0
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"[Binance] Async funding page error (start={start_ts}): {e}")
    return []

async def _fetch_bybit_funding_page_async(client: httpx.AsyncClient, start_ts: int, end_ts: int) -> list:
    """抓取 Bybit 單頁資金費率 (備援用)"""
    try:
        resp = await client.get(
            "https://api.bybit.com/v5/market/funding/history",
            params={'category': 'linear', 'symbol': 'BTCUSDT', 'limit': 200, 'startTime': start_ts, 'endTime': end_ts},
            timeout=10.0
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("retCode") == 0:
                return data.get("result", {}).get("list", [])
    except Exception as e:
        print(f"[Bybit] Async funding page error (start={start_ts}): {e}")
    return []

async def _fetch_binance_funding_rate_async() -> pd.DataFrame:
    """非同步抓取 Binance 全部資金費率"""
    start_ts = int(datetime(2021, 1, 1).timestamp() * 1000)
    end_ts   = int(datetime.now().timestamp() * 1000)
    interval_ms = 1000 * 8 * 3600 * 1000  

    page_starts = []
    ts = start_ts
    while ts < end_ts:
        page_starts.append(ts)
        ts += interval_ms  

    all_rates = []
    async with httpx.AsyncClient(verify=SSL_VERIFY) as client:
        tasks = [_fetch_binance_funding_page_async(client, s) for s in page_starts]
        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for page in pages:
            if isinstance(page, list):
                all_rates.extend(page)

    if not all_rates:
        return pd.DataFrame()

    recs = []
    for item in all_rates:
        try:
            dt   = pd.to_datetime(int(item['fundingTime']), unit='ms', utc=True)
            rate = float(item['fundingRate']) * 100  
            recs.append({'date': dt, 'fundingRate': rate})
        except Exception:
            continue

    if not recs:
        return pd.DataFrame()

    df = pd.DataFrame(recs).set_index('date')
    df = df[~df.index.duplicated(keep='first')]
    df.sort_index(inplace=True)
    print(f"[Market] 成功使用 Binance 抓取資金費率歷史: {len(df)} 筆")
    return df

async def _fetch_bybit_funding_rate_async() -> pd.DataFrame:
    """非同步抓取 Bybit 全部資金費率 (Binance 遭遇 451 時的替代方案)"""
    start_ts = int(datetime(2021, 1, 1).timestamp() * 1000)
    end_ts   = int(datetime.now().timestamp() * 1000)
    interval_ms = 200 * 8 * 3600 * 1000  # Bybit 每頁最大 200 筆限制

    page_starts = []
    ts = start_ts
    while ts < end_ts:
        page_starts.append(ts)
        ts += interval_ms

    all_rates = []
    async with httpx.AsyncClient(verify=SSL_VERIFY) as client:
        tasks = []
        for s in page_starts:
            e = s + interval_ms - 1
            tasks.append(_fetch_bybit_funding_page_async(client, s, e))
        
        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for page in pages:
            if isinstance(page, list):
                all_rates.extend(page)

    if not all_rates:
        return pd.DataFrame()

    recs = []
    for item in all_rates:
        try:
            dt   = pd.to_datetime(int(item['fundingRateTimestamp']), unit='ms', utc=True)
            rate = float(item['fundingRate']) * 100  
            recs.append({'date': dt, 'fundingRate': rate})
        except Exception:
            continue

    if not recs:
        return pd.DataFrame()

    df = pd.DataFrame(recs).set_index('date')
    df = df[~df.index.duplicated(keep='first')]
    df.sort_index(inplace=True)
    print(f"[Market] 成功使用 Bybit 抓取資金費率歷史: {len(df)} 筆")
    return df

async def _fetch_funding_rate_async() -> pd.DataFrame:
    """資金費率主邏輯：優先 Binance，失敗則 fallback 到 Bybit"""
    df = await _fetch_binance_funding_rate_async()
    if not df.empty:
        return df
    
    print("[Market] Binance 資金費率抓取失敗 (可能遇到 451 地理封鎖)，啟動 Bybit 備援機制...")
    return await _fetch_bybit_funding_rate_async()

def _fetch_funding_rate_history() -> pd.DataFrame:
    """
    公開同步介面：包裝非同步函式，讓現有的同步呼叫端不需改動。
    """
    try:
        return asyncio.run(_fetch_funding_rate_async())
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _fetch_funding_rate_async())
            try:
                return future.result(timeout=60)
            except Exception as e:
                print(f"Async funding rate fallback error: {e}")
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
