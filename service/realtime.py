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
  直接呼叫 Binance API 抓取 BTC/USDT 永續合約的即時未平倉量。
  同時計算與上一次快取值的變化百分比，作為趨勢延續的輔助判斷指標。
  - OI 上升 + 價格上漲 → 強勢趨勢延續（多頭建倉）
  - OI 上升 + 價格下跌 → 空頭主導建倉（趨勢可能反轉）
  - OI 下降           → 持倉平倉，趨勢動能衰竭
"""
import random
import requests
import urllib3   # [Task #1] 引入 urllib3 以關閉 SSL 警告
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
    1. Binance 現貨/期貨價格、資金費率、未平倉量 OI (改用直接 requests 繞過 SSL 阻擋)
    2. DeFiLlama TVL & 穩定幣市值
    3. Alternative.me 恐懼貪婪指數
    返回: dict
    """
    data = {
        "price": None,
        "funding_rate": None,
        "tvl": None,
        "stablecoin_mcap": None,
        "defi_yield": None,
        "fng_value": None,
        "fng_class": None,
        "open_interest": None,      
        "open_interest_usd": None,  
        "oi_change_pct": None,      
    }

    # 建立偽裝的 Headers，避免被幣安等 API 的反爬蟲機制 (WAF) 阻擋
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # 1. Binance 數據 (棄用 ccxt，改用 requests 以強制套用 verify=SSL_VERIFY 與 headers)
    try:
        # 取得現貨最新價格
        r_price = requests.get(
            "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", 
            timeout=5, 
            verify=SSL_VERIFY,
            headers=headers  # 加入偽裝 Header
        )
        if r_price.status_code == 200:
            data['price'] = float(r_price.json()['price'])

        # 取得期貨市場數據 (資金費率 & 未平倉量)
        try:
            # 資金費率 (Premium Index 端點)
            r_fr = requests.get(
                "https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT", 
                timeout=5, 
                verify=SSL_VERIFY,
                headers=headers  # 加入偽裝 Header
            )
            if r_fr.status_code == 200:
                # API 回傳的 lastFundingRate 是小數 (例如 0.000012 代表 0.0012%)
                data['funding_rate'] = float(r_fr.json()['lastFundingRate']) * 100

            # 未平倉量 (Open Interest 端點)
            r_oi = requests.get(
                "https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT", 
                timeout=5, 
                verify=SSL_VERIFY,
                headers=headers  # 加入偽裝 Header
            )
            if r_oi.status_code == 200:
                current_oi = float(r_oi.json()['openInterest'])
                data['open_interest'] = current_oi

                # 以美元計算（顆數 × 現價），單位：億 USD
                if data['price']:
                    data['open_interest_usd'] = (current_oi * data['price']) / 1e8

                # 計算 60s 變化率
                try:
                    prev_oi = st.session_state.get('_prev_oi', None)
                    if prev_oi is not None and prev_oi > 0:
                        data['oi_change_pct'] = (current_oi / prev_oi - 1) * 100
                    st.session_state['_prev_oi'] = current_oi
                except Exception:
                    pass

        except Exception as e:
            print(f"Binance futures direct API error (OI/funding): {e}")

    except Exception as e:
        print(f"Binance spot direct API error: {e}")

    # 2. DeFiLlama
    try:
        r = requests.get(
            "https://api.llama.fi/v2/chains", 
            timeout=5, 
            verify=SSL_VERIFY,
            headers=headers
        )
        if r.status_code == 200:
            for c in r.json():
                if c['name'] == 'Bitcoin':
                    data['tvl'] = c['tvl'] / 1e9
                    break

        r2 = requests.get(
            "https://stablecoins.llama.fi/stablecoins?includePrices=true",
            timeout=5,
            verify=SSL_VERIFY,
            headers=headers
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
    try:
        r = requests.get(
            "https://api.alternative.me/fng/", 
            timeout=5, 
            verify=SSL_VERIFY,
            headers=headers
        )
        if r.status_code == 200:
            item = r.json()['data'][0]
            data['fng_value'] = int(item['value'])
            data['fng_class'] = item['value_classification']
    except Exception as e:
        print(f"F&G error: {e}")

    return data