"""
service/market_data.py
市場數據服務 — BTC 歷史 OHLCV + DXY
增量更新：本地 CSV 緩存，只下載缺失日期
加入 SSL 繞過機制與多層備援 API:
  1st: Yahoo Finance (yfinance)
  2nd: Binance (ccxt) — 部分 Streamlit Cloud IP 被 451 封鎖
  3rd: Kraken 公開 API — 無地理限制，適合 Streamlit Cloud
  4th: CryptoCompare 公開 API — 有 2010 年起完整 BTC 日線歷史，分頁抓取
"""
import os
import time
import pandas as pd
import yfinance as yf
import streamlit as st
from datetime import datetime, timedelta
import requests
import urllib3
import ccxt

# 從集中設定檔讀取 SSL 動態驗證旗標
from config import SSL_VERIFY

# 動態 SSL：本地開發環境才關閉警告；雲端 SSL_VERIFY=True 維持正常驗證
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BTC_CSV = "BTC_HISTORY.csv"

def get_yf_session():
    """
    建立自訂的 requests Session 供 yfinance 使用。
    1. verify=SSL_VERIFY: 動態 SSL 驗證（本地 False，雲端 True）。
    2. 加入 User-Agent: 降低在 Streamlit Cloud 上被 Yahoo 視為機器人阻擋的機率。
    """
    session = requests.Session()
    session.verify = SSL_VERIFY  # 動態 SSL：本地 False / 雲端 True
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def fetch_binance_daily(start_date_str):
    """
    第二備援：當 Yahoo Finance 失敗時，改從 Binance 抓取 BTC/USDT 日線數據。
    注意：Binance 對部分 Streamlit Cloud IP 返回 451（地理封鎖）。

    [Fix Issue 6] 加入分頁迴圈（Pagination Loop）:
    原始版本只抓 1000 筆（約 2.7 年），無法覆蓋完整歷史。
    修正後無限迴圈直到資料用盡，每批 1000 根日線 K 棒，自動分頁。
    Binance 限速：每分鐘 1200 次請求，每批加入 0.1s 延遲。
    """
    exchange = ccxt.binance()
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp() * 1000)

    all_ohlcv = []
    since     = start_ts
    now_ts    = int(datetime.now().timestamp() * 1000)

    while since < now_ts:
        try:
            # ccxt 回傳格式: [timestamp_ms, open, high, low, close, volume]
            batch = exchange.fetch_ohlcv(
                "BTC/USDT", timeframe="1d", since=since, limit=1000
            )
        except Exception as e:
            print(f"[Binance] fetch_ohlcv 失敗 (since={since}): {e}")
            break

        if not batch:
            break  # 無更多資料，結束

        all_ohlcv.extend(batch)

        # 不足 1000 筆：代表已到最新資料，不需要再請求
        if len(batch) < 1000:
            break

        # 下一頁從最後一根 K 棒的下一天開始（+1 天 = +86,400,000 ms）
        since = batch[-1][0] + 86_400_000
        time.sleep(0.1)  # 遵守 Binance API 速率限制

    if not all_ohlcv:
        return pd.DataFrame()

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    # 去除可能的重複時間戳（分頁邊界）
    df = df.drop_duplicates(subset="timestamp", keep="last")
    df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("date", inplace=True)
    df.drop(columns=["timestamp"], inplace=True)

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    return df


def fetch_kraken_daily(start_date_str):
    """
    第三備援：從 Kraken 公開 API 抓取 BTC/USD 日線數據。
    Kraken 無地理封鎖限制，適合從 Streamlit Cloud 呼叫。
    - 每頁最多 720 筆，從 start_date 分頁取到最新
    - 免費、無需 API Key
    - 回傳真實 OHLCV，與 yfinance/Binance 格式一致
    """
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp())
    url = "https://api.kraken.com/0/public/OHLC"
    all_candles = []
    since = start_ts

    for _ in range(15):  # 每頁最多 720 筆，15 頁可涵蓋約 30 年
        try:
            resp = requests.get(
                url,
                params={'pair': 'XBTUSD', 'interval': 1440, 'since': since},
                timeout=15,
                verify=SSL_VERIFY,
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get('error'):
                print(f"[Kraken] API 錯誤: {data['error']}")
                break

            candles = data.get('result', {}).get('XXBTZUSD', [])
            if not candles:
                break

            all_candles.extend(candles)

            # 'last' 是下一頁的 since 值（已存在的最後一筆 Unix 時間戳）
            last_ts = data.get('result', {}).get('last', 0)
            if last_ts <= since:
                break  # 無更多數據
            since = last_ts
            time.sleep(0.5)  # 遵守 Kraken 速率限制（每秒 1 請求）

        except Exception as e:
            print(f"[Kraken] 分頁請求失敗: {e}")
            break

    if not all_candles:
        return pd.DataFrame()

    # Kraken OHLC 格式: [time, open, high, low, close, vwap, volume, count]
    df = pd.DataFrame(
        all_candles,
        columns=['timestamp', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count']
    )
    df['date'] = pd.to_datetime(df['timestamp'].astype(int), unit='s')
    df.set_index('date', inplace=True)
    df = df[['open', 'high', 'low', 'close', 'volume']].astype(float)

    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    return df

def fetch_cryptocompare_daily(start_date_str):
    """
    第四備援：從 CryptoCompare 公開 API 抓取 BTC/USD 日線歷史。
    - 無需 API Key，免費端點
    - 有自 2010 年起的完整比特幣日線數據，可覆蓋 2015 年以前的歷史
    - 每次最多 2000 筆，分頁倒序抓取（toTs 往前推）

    分頁策略:
      CryptoCompare histoday 以「結束時間戳」為錨點向前抓取 limit 筆
      → 先抓到現在，再往前推直到 start_date_str 前的時間
    """
    url = "https://min-api.cryptocompare.com/data/v2/histoday"
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp())
    now_ts = int(datetime.now().timestamp())

    all_rows = []
    to_ts = now_ts  # 從當前時間往前翻頁

    for _ in range(20):  # 最多 20 頁 × 2000 = 40,000 天，足以覆蓋 BTC 全歷史
        try:
            resp = requests.get(
                url,
                params={
                    "fsym": "BTC",
                    "tsym": "USD",
                    "limit": 2000,
                    "toTs": to_ts,
                },
                timeout=20,
                verify=SSL_VERIFY,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("Response") != "Success":
                print(f"[CryptoCompare] API 返回錯誤: {data.get('Message', '未知')}")
                break

            rows = data.get("Data", {}).get("Data", [])
            if not rows:
                break

            # 過濾掉 time=0 或 close=0 的無效行
            valid = [r for r in rows if r.get("time", 0) > 0 and r.get("close", 0) > 0]
            all_rows.extend(valid)

            # 最早一筆時間戳
            earliest_ts = min(r["time"] for r in valid)
            if earliest_ts <= start_ts:
                break  # 已覆蓋目標起始日期，不再繼續

            # 往更早翻頁（減 1 天避免重複）
            to_ts = earliest_ts - 86_400
            time.sleep(0.3)

        except Exception as e:
            print(f"[CryptoCompare] 分頁請求失敗: {e}")
            break

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["date"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("date", inplace=True)
    # 只保留 OHLCV 欄位，並轉為 float
    df = df[["open", "high", "low", "close", "volumeto"]].copy()
    df.rename(columns={"volumeto": "volume"}, inplace=True)
    df = df.astype(float)

    # 過濾到 start_date_str 之後的數據
    df = df[df.index >= pd.Timestamp(start_date_str)]
    df = df[~df.index.duplicated(keep="last")]
    df.sort_index(inplace=True)

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
        # 目標：抓取 2015-01-01 起的完整歷史
        # Yahoo Finance BTC 最早 ~2014-09，Binance 從 2017-08，Kraken 有限
        # CryptoCompare 第四備援可覆蓋 2015 前資料
        start_fetch_date = "2015-01-01"

    # 若有需要更新的日期，開始抓取（三層備援）
    if start_fetch_date:
        # --- 第一層：Yahoo Finance ---
        try:
            btc_new = yf.download("BTC-USD", start=start_fetch_date, interval="1d", progress=False, session=session)
            if not btc_new.empty:
                # 處理 yfinance 可能回傳 MultiIndex columns 的問題
                btc_new.columns = [
                    c[0].lower() if isinstance(c, tuple) else c.lower()
                    for c in btc_new.columns
                ]
        except Exception as e:
            st.warning(f"⚠️ Yahoo Finance 連線異常 ({type(e).__name__})，切換備援 API...")

        # --- 第二層：Binance（注意：Streamlit Cloud 部分 IP 被 451 地理封鎖）---
        if btc_new.empty:
            try:
                btc_new = fetch_binance_daily(start_fetch_date)
            except Exception as e:
                err_msg = str(e)
                if "451" in err_msg:
                    st.warning("⚠️ Binance 返回 451（地理封鎖），切換第三備援 Kraken...")
                else:
                    st.warning(f"⚠️ Binance 備援失敗 ({type(e).__name__})，切換第三備援 Kraken...")

        # --- 第三層：Kraken（無地理封鎖，Streamlit Cloud 可用）---
        if btc_new.empty:
            try:
                btc_new = fetch_kraken_daily(start_fetch_date)
                if not btc_new.empty:
                    st.info(f"ℹ️ Kraken 備援成功，取得 {len(btc_new)} 筆數據")
            except Exception as e:
                st.warning(f"⚠️ Kraken 備援失敗 ({type(e).__name__})，切換第四備援 CryptoCompare...")

        # --- 第四層：CryptoCompare（有 2010 年起完整 BTC 歷史，最強歷史覆蓋）---
        if btc_new.empty:
            try:
                btc_new = fetch_cryptocompare_daily(start_fetch_date)
                if not btc_new.empty:
                    st.success(f"✅ CryptoCompare 備援成功，取得 {len(btc_new)} 筆 (自 {btc_new.index[0].date()})")
            except Exception as e:
                st.error(f"❌ 所有備援 API 均失敗。CryptoCompare 錯誤: {type(e).__name__}: {e}")

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
        st.error("❌ 四層備援均失敗（Yahoo / Binance / Kraken / CryptoCompare）。請稍後重試。")
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
