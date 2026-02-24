"""
service/onchain.py
鏈上數據服務 — TVL、穩定幣市值、資金費率歷史
透過 data_manager 本地緩存 + Binance API 補救

[Task #1] SSL 繞過：所有外部 requests.get() 加入 verify=False
[Task #2] 非同步抓取：_fetch_funding_rate_history 改用 httpx.AsyncClient 並行發送請求
"""
import time
import asyncio          # [Task #2] 用於執行非同步事件迴圈
import requests
import urllib3          # [Task #1] 引入 urllib3 以靜默 SSL 警告
import httpx            # [Task #2] 非同步 HTTP 客戶端，需 pip install httpx
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
    """
    同步補救：直接抓取全量穩定幣歷史市值。
    [Task #1] verify=False 繞過企業 SSL 憑證阻擋。
    """
    try:
        # [Task #1] 加入 verify=False，避免公司 SSL 攔截導致連線失敗
        r = requests.get(
            "https://stablecoins.llama.fi/stablecoincharts/all",
            timeout=10,
            verify=SSL_VERIFY,  # 動態 SSL：本地 False / 雲端 True
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
# [Task #2] 非同步資金費率抓取
# 原始做法：20 次同步迴圈 + time.sleep(0.1)，總計至少 2 秒阻塞
# 新做法：httpx.AsyncClient 並行發出全部請求，牆鐘時間降低 ~10x
# ──────────────────────────────────────────────────────────────────────────────

async def _fetch_funding_page_async(client: httpx.AsyncClient, start_ts: int) -> list:
    """
    非同步抓取單一分頁的資金費率資料。
    client: httpx.AsyncClient 物件（由呼叫端統一管理連線池）
    start_ts: 以毫秒為單位的起始時間戳
    返回: 原始 JSON 列表（可能為空）
    """
    try:
        resp = await client.get(
            "https://fapi.binance.com/fapi/v1/fundingRate",
            params={'symbol': 'BTCUSDT', 'limit': 1000, 'startTime': start_ts},
            timeout=10.0  # 單頁請求逾時 10 秒
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        print(f"Async funding page error (start={start_ts}): {e}")
    return []


async def _fetch_funding_rate_async() -> pd.DataFrame:
    """
    非同步主函式：計算出所有需要抓取的分頁時間戳後，
    使用 httpx.AsyncClient 並行發送全部請求，最後合併結果。

    [Task #2] 核心邏輯：
    - Binance 資金費率每 8 小時一筆，從 2021-01-01 至今約 4,000+ 筆
    - 每頁 limit=1000，約需 5 頁 → 並行 vs 序列節省 ~80% 時間
    - verify=False 透過 httpx 的 SSL 設定傳入（verify=False in AsyncClient）
    """
    start_ts = int(datetime(2021, 1, 1).timestamp() * 1000)   # 起始時間戳 (ms)
    end_ts   = int(datetime.now().timestamp() * 1000)          # 當前時間戳 (ms)
    interval_ms = 1000 * 8 * 3600 * 1000  # 每頁最多 1000 筆 × 8h = 8,000,000,000 ms

    # 預先計算每一頁的起始時間戳，不需要等前一頁回來才知道下一頁從哪開始
    page_starts = []
    ts = start_ts
    while ts < end_ts:
        page_starts.append(ts)
        ts += interval_ms  # 每頁跨度 = 1000 × 8h

    all_rates = []

    # [Task #2] 建立非同步 HTTP 客戶端，verify=False 繞過企業 SSL
    async with httpx.AsyncClient(verify=SSL_VERIFY) as client:
        # 並行發送所有分頁請求，等待全部完成
        tasks = [_fetch_funding_page_async(client, s) for s in page_starts]
        pages = await asyncio.gather(*tasks, return_exceptions=True)

        for page in pages:
            if isinstance(page, list):  # 過濾掉 Exception 物件
                all_rates.extend(page)

    if not all_rates:
        return pd.DataFrame()

    # 將原始資料轉換為 DataFrame
    recs = []
    for item in all_rates:
        try:
            dt   = pd.to_datetime(int(item['fundingTime']), unit='ms', utc=True)
            rate = float(item['fundingRate']) * 100  # 轉為百分比
            recs.append({'date': dt, 'fundingRate': rate})
        except Exception:
            continue

    if not recs:
        return pd.DataFrame()

    df = pd.DataFrame(recs).set_index('date')
    df = df[~df.index.duplicated(keep='first')]  # 去除重複時間戳
    df.sort_index(inplace=True)
    print(f"[Async] Funding history fetched: {len(df)} rows from {len(page_starts)} pages")
    return df


def _fetch_funding_rate_history() -> pd.DataFrame:
    """
    公開同步介面：包裝非同步函式，讓現有的同步呼叫端不需改動。

    [Task #2] asyncio.run() 在已有事件迴圈的環境（如 Jupyter/Streamlit）
    可能衝突，使用 try/except 提供後備方案：
    - 若無現有迴圈 → asyncio.run()
    - 若已有迴圈（如 Streamlit Cloud）→ 建立新執行緒執行
    """
    try:
        # 嘗試標準方式執行非同步函式
        return asyncio.run(_fetch_funding_rate_async())
    except RuntimeError:
        # Streamlit Cloud 等環境已有事件迴圈，改用執行緒避免衝突
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _fetch_funding_rate_async())
            try:
                return future.result(timeout=60)  # 最多等 60 秒
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
