"""
service/market_data.py
市場數據服務 — BTC 歷史 OHLCV + DXY
增量更新：本地 CSV 緩存，只下載缺失日期
加入 SSL 繞過機制與多層備援 API:
  0th: 本地 SQLite DB（db/btcusdt_15m_*.db，由 collector 預先收集）— 最優先、最可靠
  1st: Yahoo Finance (yfinance)
  2nd: Binance REST API（直接 HTTP，不依賴 ccxt）— 部分 Streamlit Cloud IP 被 451 封鎖
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

# 從集中設定檔讀取 SSL 動態驗證旗標
from config import SSL_VERIFY

# 本地 SQLite DB 讀取（由 collector/btc_price_collector.py 生成）
from service.local_db_reader import has_local_data, read_btc_daily

# 動態 SSL：本地開發環境才關閉警告；雲端 SSL_VERIFY=True 維持正常驗證
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BTC_CSV = "BTC_HISTORY.csv"

# Binance REST API 端點（不需要 API Key，公開 klines）
_BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


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
    第二備援：直接呼叫 Binance REST API（不使用 ccxt），抓取 BTC/USDT 日線 K 棒。

    API: GET https://api.binance.com/api/v3/klines
    - 無需 API Key（公開端點）
    - limit 最大 1000，分頁以 startTime 推進
    - 注意：Binance 對部分 Streamlit Cloud IP 返回 451（地理封鎖），此時自動跳至第三備援

    回應格式（每筆）:
      [open_time_ms, open, high, low, close, volume, close_time_ms, ...]
    """
    start_ts = int(datetime.strptime(start_date_str, "%Y-%m-%d").timestamp() * 1000)
    now_ts   = int(datetime.now().timestamp() * 1000)

    all_klines = []
    since = start_ts

    while since < now_ts:
        try:
            resp = requests.get(
                _BINANCE_KLINES_URL,
                params={
                    "symbol":    "BTCUSDT",
                    "interval":  "1d",
                    "startTime": since,
                    "limit":     1000,
                },
                timeout=15,
                verify=SSL_VERIFY,
            )
            # 451 地理封鎖：直接拋出讓 caller 捕捉
            if resp.status_code == 451:
                raise requests.HTTPError(f"451 Binance geo-block")
            resp.raise_for_status()
            batch = resp.json()
        except Exception as e:
            print(f"[Binance REST] 請求失敗 (since={since}): {e}")
            raise  # 由外層 try/except 處理並切換備援

        if not batch:
            break

        all_klines.extend(batch)

        if len(batch) < 1000:
            break  # 已到最新資料

        # 下一頁起點：最後一根 K 棒的 open_time + 1 天（ms）
        since = int(batch[-1][0]) + 86_400_000
        time.sleep(0.05)  # 遵守 Binance 限速（1200 req/min）

    if not all_klines:
        return pd.DataFrame()

    # 取前 6 欄：open_time, open, high, low, close, volume
    df = pd.DataFrame(all_klines, columns=[
        "timestamp", "open", "high", "low", "close", "volume",
        "ct", "qa", "nt", "tb", "tq", "i",
    ])
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
    df.set_index("date", inplace=True)
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    df = df[~df.index.duplicated(keep="last")]
    df.sort_index(inplace=True)

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

    # 若有需要更新的日期，開始抓取（四層備援，所有備援訊息改用 print 避免汙染 UI）
    _fetch_log = []  # 收集備援過程記錄，最後由 app.py 統一決定是否顯示

    if start_fetch_date:
        # --- 第零層：本地 SQLite DB（collector 預先收集的 15m 資料重採樣為日線）---
        if has_local_data():
            try:
                btc_new = read_btc_daily(start_date=start_fetch_date)
                if not btc_new.empty:
                    print(f"[Market] 本地 DB 成功，取得 {len(btc_new)} 筆日線（從 15m 重採樣）")
            except Exception as e:
                print(f"[Market] 本地 DB 讀取失敗 ({type(e).__name__})，切換 Yahoo Finance")
                btc_new = pd.DataFrame()

        # --- 第一層：Yahoo Finance ---
        if btc_new.empty:
            try:
                btc_new = yf.download("BTC-USD", start=start_fetch_date, interval="1d", progress=False, session=session)
                if not btc_new.empty:
                    # 處理 yfinance 可能回傳 MultiIndex columns 的問題
                    btc_new.columns = [
                        c[0].lower() if isinstance(c, tuple) else c.lower()
                        for c in btc_new.columns
                    ]
                    print(f"[Market] Yahoo Finance 成功，取得 {len(btc_new)} 筆")
            except Exception as e:
                print(f"[Market] Yahoo Finance 失敗 ({type(e).__name__})，切換 Binance REST")

        # --- 第二層：Binance REST API（直接 HTTP，不使用 ccxt）---
        if btc_new.empty:
            try:
                btc_new = fetch_binance_daily(start_fetch_date)
                if not btc_new.empty:
                    print(f"[Market] Binance REST 成功，取得 {len(btc_new)} 筆")
            except Exception as e:
                err_msg = str(e)
                tag = "451地理封鎖" if "451" in err_msg else type(e).__name__
                print(f"[Market] Binance REST 失敗 ({tag})，切換 Kraken")

        # --- 第三層：Kraken（無地理封鎖，Streamlit Cloud 可用）---
        if btc_new.empty:
            try:
                btc_new = fetch_kraken_daily(start_fetch_date)
                if not btc_new.empty:
                    print(f"[Market] Kraken 成功，取得 {len(btc_new)} 筆")
            except Exception as e:
                print(f"[Market] Kraken 失敗 ({type(e).__name__})，切換 CryptoCompare")

        # --- 第四層：CryptoCompare（有 2010 年起完整 BTC 歷史，最強歷史覆蓋）---
        if btc_new.empty:
            try:
                btc_new = fetch_cryptocompare_daily(start_fetch_date)
                if not btc_new.empty:
                    print(f"[Market] CryptoCompare 成功，取得 {len(btc_new)} 筆 (自 {btc_new.index[0].date()})")
            except Exception as e:
                print(f"[Market] CryptoCompare 失敗 ({type(e).__name__}: {e})")

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

    # ── T 日數據縫合 (Data Stitching) ───────────────────────────────────────────
    # 確保本地 SQLite 歷史資料與今日即時 T 日數據無縫 Concat，避免 MA/均線計算斷層。
    # 若歷史最後一筆早於今日，則嘗試從 Yahoo / Binance 補充當日 K 棒。
    if not btc_final.empty and btc_final.index[-1].date() < today:
        today_str = today.strftime('%Y-%m-%d')
        _tday_df  = pd.DataFrame()
        # 優先 Yahoo Finance（延遲最小）
        try:
            _tday_df = yf.download(
                "BTC-USD", start=today_str, interval="1d",
                progress=False, session=session,
            )
            if not _tday_df.empty:
                _tday_df.columns = [
                    c[0].lower() if isinstance(c, tuple) else c.lower()
                    for c in _tday_df.columns
                ]
        except Exception:
            _tday_df = pd.DataFrame()
        # 備援：Binance REST
        if _tday_df.empty:
            try:
                _tday_df = fetch_binance_daily(today_str)
            except Exception:
                _tday_df = pd.DataFrame()
        # 縫合：把 T 日數據 Concat 到歷史末端
        if not _tday_df.empty:
            if _tday_df.index.tz is not None:
                _tday_df.index = _tday_df.index.tz_localize(None)
            btc_final = pd.concat([btc_final, _tday_df])
            btc_final = btc_final[~btc_final.index.duplicated(keep='last')]
            btc_final.sort_index(inplace=True)

    if btc_final.empty:
        print("[Market] ❌ 五層備援均失敗（本地DB / Yahoo / Binance / Kraken / CryptoCompare）")
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
