"""
service/realtime.py
即時數據服務 — 價格、資金費率、恐懼貪婪指數
TTL=60s，每分鐘刷新

[Task #1] SSL 繞過：企業網路常以中間人憑證攔截 HTTPS 流量，
導致 requests 驗證失敗。透過以下兩步解決：
  1. urllib3.disable_warnings()  — 靜默 InsecureRequestWarning 警告
  2. requests.get(..., verify=False) — 跳過 SSL 憑證驗證
注意：此設定僅適用於受信任的內部/企業網路環境。
"""
import random
import requests
import urllib3   # [Task #1] 引入 urllib3 以關閉 SSL 警告
import ccxt
import streamlit as st

# [Task #1] 關閉 InsecureRequestWarning，避免每次 API 呼叫都印出警告訊息
# 若未來網路環境恢復正常，只需移除此行與各 verify=False 即可
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@st.cache_data(ttl=60)
def fetch_realtime_data():
    """
    即時抓取:
    1. Binance 現貨/期貨價格 & 資金費率 (CCXT)
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
    }

    # 1. Binance via CCXT
    try:
        exchange = ccxt.binance()
        ticker = exchange.fetch_ticker('BTC/USDT')
        data['price'] = ticker['last']
        try:
            fut = ccxt.binance({'options': {'defaultType': 'future'}})
            fr = fut.fetch_funding_rate('BTC/USDT')
            data['funding_rate'] = fr['fundingRate'] * 100
        except Exception:
            pass
    except Exception as e:
        print(f"Binance error: {e}")

    # 2. DeFiLlama
    # [Task #1] verify=False 繞過企業 SSL 憑證阻擋
    try:
        r = requests.get("https://api.llama.fi/v2/chains", timeout=5, verify=False)
        if r.status_code == 200:
            for c in r.json():
                if c['name'] == 'Bitcoin':
                    data['tvl'] = c['tvl'] / 1e9
                    break

        r2 = requests.get(
            "https://stablecoins.llama.fi/stablecoins?includePrices=true",
            timeout=5,
            verify=False  # [Task #1] 同上，SSL 繞過
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
    # [Task #1] verify=False 繞過企業 SSL 憑證阻擋
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=5, verify=False)
        if r.status_code == 200:
            item = r.json()['data'][0]
            data['fng_value'] = int(item['value'])
            data['fng_class'] = item['value_classification']
    except Exception as e:
        print(f"F&G error: {e}")

    return data
