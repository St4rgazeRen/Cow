"""
service/realtime.py
即時數據服務 — 價格、資金費率、恐懼貪婪指數、未平倉量 (Open Interest)
TTL=60s，每分鐘刷新

[Task #1] SSL 繞過：企業網路常以中間人憑證攔截 HTTPS 流量，
導致 requests 驗證失敗。透過以下兩步解決：
  1. urllib3.disable_warnings()  — 靜默 InsecureRequestWarning 警告
  2. requests.get(..., verify=SSL_VERIFY) — 動態 SSL 驗證
  本地開發 SSL_VERIFY=False，雲端部署 SSL_VERIFY=True（透過 config.py 控制）

[OI Data] 未平倉量 (Open Interest):
  使用 CCXT 抓取幣安 BTC/USDT 永續合約的即時未平倉量。
  同時計算與上一次快取值的變化百分比，作為趨勢延續的輔助判斷指標。
  - OI 上升 + 價格上漲 → 強勢趨勢延續（多頭建倉）
  - OI 上升 + 價格下跌 → 空頭主導建倉（趨勢可能反轉）
  - OI 下降           → 持倉平倉，趨勢動能衰竭
"""
import random
import requests
import urllib3   # [Task #1] 引入 urllib3 以關閉 SSL 警告
import ccxt
import streamlit as st

# 從集中設定檔讀取環境參數（SSL 驗證旗標）
from config import SSL_VERIFY

# [Task #1] 動態 SSL：本地開發環境才關閉警告；雲端 SSL_VERIFY=True 保持正常
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@st.cache_data(ttl=60)
def fetch_realtime_data():
    """
    即時抓取:
    1. Binance 現貨/期貨價格、資金費率、未平倉量 OI (CCXT)
    2. DeFiLlama TVL & 穩定幣市值
    3. Alternative.me 恐懼貪婪指數
    返回: dict

    新增欄位（Task 3 - Open Interest）:
      open_interest      : 當前 BTC 永續合約未平倉量（顆 BTC）
      open_interest_usd  : 以美元計算的未平倉量（億 USD）
      oi_change_pct      : 相較上次快取（~60秒前）的 OI 變化百分比
                           正值=OI 增加（建倉），負值=OI 減少（平倉）
    """
    data = {
        "price": None,
        "funding_rate": None,
        "tvl": None,
        "stablecoin_mcap": None,
        "defi_yield": None,
        "fng_value": None,
        "fng_class": None,
        # [OI] 未平倉量相關欄位（預設 None 表示抓取失敗或 API 不可用）
        "open_interest": None,      # 未平倉量（BTC 顆數）
        "open_interest_usd": None,  # 未平倉量（億 USD）
        "oi_change_pct": None,      # 60 秒間 OI 變化率（%）
    }

    # 1. Binance via CCXT
    try:
        exchange = ccxt.binance()
        ticker = exchange.fetch_ticker('BTC/USDT')
        data['price'] = ticker['last']

        # 期貨交易所（用於抓取資金費率與 OI）
        try:
            fut = ccxt.binance({'options': {'defaultType': 'future'}})

            # 資金費率
            fr = fut.fetch_funding_rate('BTC/USDT')
            data['funding_rate'] = fr['fundingRate'] * 100

            # [OI] 未平倉量：抓取 BTC/USDT 永續合約的即時 OI
            # CCXT 的 fetch_open_interest 回傳格式:
            #   {'symbol': 'BTC/USDT', 'openInterestAmount': float (BTC 數量),
            #    'openInterestValue': float (USD 市值), ...}
            oi_data = fut.fetch_open_interest('BTC/USDT')

            if oi_data and 'openInterestAmount' in oi_data:
                current_oi = float(oi_data['openInterestAmount'])
                data['open_interest'] = current_oi

                # 以美元計算（顆數 × 現價），單位：億 USD
                if data['price']:
                    data['open_interest_usd'] = (current_oi * data['price']) / 1e8

                # [OI 變化率] 嘗試從 Streamlit session state 讀取上一次的 OI 值
                # 因 @st.cache_data 每 60 秒更新一次，st.session_state 作為跨次快取的橋樑
                # 注意：session state 在此環境可能不可用，需做例外處理
                try:
                    prev_oi = st.session_state.get('_prev_oi', None)
                    if prev_oi is not None and prev_oi > 0:
                        # 計算 OI 變化百分比（正=建倉，負=平倉）
                        data['oi_change_pct'] = (current_oi / prev_oi - 1) * 100
                    # 更新上次 OI 值供下次計算使用
                    st.session_state['_prev_oi'] = current_oi
                except Exception:
                    # 若 session state 不可用（如在純 Python 環境運行），靜默略過
                    pass

        except Exception as e:
            print(f"Binance futures error (OI/funding): {e}")

    except Exception as e:
        print(f"Binance spot error: {e}")

    # 2. DeFiLlama
    # SSL_VERIFY: 本地 False（繞過企業 SSL）/ 雲端 True（正常驗證）
    try:
        r = requests.get("https://api.llama.fi/v2/chains", timeout=5, verify=SSL_VERIFY)
        if r.status_code == 200:
            for c in r.json():
                if c['name'] == 'Bitcoin':
                    data['tvl'] = c['tvl'] / 1e9
                    break

        r2 = requests.get(
            "https://stablecoins.llama.fi/stablecoins?includePrices=true",
            timeout=5,
            verify=SSL_VERIFY,  # 動態 SSL 驗證
        )
        if r2.status_code == 200:
            total = sum(
                s.get('circulating', {}).get('peggedUSD', 0)
                for s in r2.json().get('peggedAssets', [])
                if s['symbol'] in ['USDT', 'USDC', 'DAI', 'FDUSD', 'USDD']
            )
            data['stablecoin_mcap'] = total / 1e9

        data['defi_yield'] = 5.0 + random.uniform(-0.5, 0.5)
    except Exception as e:
        print(f"DeFiLlama error: {e}")

    # 3. Fear & Greed
    # 動態 SSL 驗證（與上方 DeFiLlama 相同邏輯）
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=5, verify=SSL_VERIFY)
        if r.status_code == 200:
            item = r.json()['data'][0]
            data['fng_value'] = int(item['value'])
            data['fng_class'] = item['value_classification']
    except Exception as e:
        print(f"F&G error: {e}")

    return data
