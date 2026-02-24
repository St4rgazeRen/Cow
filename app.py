"""
app.py — 比特幣投資戰情室 (Bitcoin Command Center)
薄層入口點：負責組合各層模組，不含業務邏輯

架構分層:
  core/       — 純計算 (指標、評分)，無 Streamlit 依賴
  service/    — 數據獲取 (市場數據、鏈上、即時)
  strategy/   — 策略引擎 (波段、雙幣)
  handler/    — Streamlit UI (每個 Tab 為獨立函數)
"""
import streamlit as st
from datetime import datetime

# Handler 層
from handler.layout import setup_page, render_sidebar
import handler.tab_bull_radar as tab1_handler
import handler.tab_swing as tab2_handler
import handler.tab_dual_invest as tab3_handler
import handler.tab_backtest as tab4_handler
import handler.tab_bear_bottom as tab5_handler

# Service 層
from service.market_data import fetch_market_data
from service.onchain import fetch_aux_history
from service.realtime import fetch_realtime_data
from service.mock import (
    get_mock_funding_rate,
    get_mock_tvl,
    calculate_fear_greed_proxy,
    get_realtime_proxies,
)

# Core 層
from core.indicators import calculate_technical_indicators, calculate_ahr999
from core.bear_bottom import calculate_bear_bottom_indicators

# ==============================================================================
# 1. 頁面初始化
# ==============================================================================
setup_page()
sidebar_params = render_sidebar()

capital = sidebar_params["capital"]
risk_per_trade = sidebar_params["risk_per_trade"]
call_risk = sidebar_params["call_risk"]
put_risk = sidebar_params["put_risk"]
ahr_threshold = sidebar_params["ahr_threshold"]
c_start = sidebar_params["c_start"]
c_end = sidebar_params["c_end"]

# ==============================================================================
# 2. 數據載入（含錯誤邊界與降級方案）
# ==============================================================================
_data_warnings = []  # 收集非致命警告，統一顯示

with st.spinner("正在連線至戰情室數據庫..."):
    # --- BTC 歷史數據（唯一致命依賴）---
    try:
        btc, dxy = fetch_market_data()
    except Exception as e:
        btc, dxy = __import__('pandas').DataFrame(), __import__('pandas').DataFrame()
        _data_warnings.append(f"市場數據載入異常: {e}")

    if btc.empty:
        st.error("❌ 無法取得 BTC 歷史數據（三層備援 Yahoo / Binance / Kraken 均失敗）。")
        st.info("💡 可能原因：網路不通、所有 API 暫時限速。請等待 5 分鐘後重新整理頁面（快取 TTL 為 300 秒）。")
        st.stop()

    # 指標計算
    try:
        btc = calculate_technical_indicators(btc)
        btc = calculate_ahr999(btc)
        btc = calculate_bear_bottom_indicators(btc)
    except Exception as e:
        _data_warnings.append(f"指標計算部分失敗: {e}")

    # 鏈上輔助數據（非致命，失敗時顯示空圖表）
    try:
        tvl_hist, stable_hist, fund_hist = fetch_aux_history()
    except Exception as e:
        import pandas as _pd
        tvl_hist = stable_hist = fund_hist = _pd.DataFrame()
        _data_warnings.append(f"鏈上數據載入失敗 (TVL/穩定幣/資金費率)，顯示空白: {e}")

    # 即時數據（非致命，失敗時全 Proxy 備援）
    try:
        realtime_data = fetch_realtime_data()
    except Exception as e:
        realtime_data = {k: None for k in ['price', 'funding_rate', 'tvl', 'stablecoin_mcap', 'defi_yield', 'fng_value', 'fng_class']}
        _data_warnings.append(f"即時數據載入失敗，使用模擬數據: {e}")

    curr = btc.iloc[-1]
    current_price = realtime_data.get('price') or curr['close']

    # Fallback 數值
    funding_rate = (
        realtime_data['funding_rate']
        if realtime_data['funding_rate'] is not None
        else get_mock_funding_rate()
    )
    tvl_val = (
        realtime_data['tvl']
        if realtime_data['tvl'] is not None
        else get_mock_tvl(current_price)
    )

    # 恐懼貪婪指數
    if realtime_data['fng_value']:
        fng_val = realtime_data['fng_value']
        fng_state = realtime_data['fng_class']
        if "Greed" in fng_state:
            fng_state += " 🤑"
        elif "Fear" in fng_state:
            fng_state += " 😨"
        fng_source = "Alternative.me"
    else:
        fng_val = calculate_fear_greed_proxy(curr['RSI_14'], current_price, curr['SMA_50'])
        fng_state = "Proxy Mode"
        fng_source = "Antigravity Proxy"

    proxies = get_realtime_proxies(current_price, curr['close'])

    # 圖表切片
    try:
        mask = (btc.index.date >= c_start) & (btc.index.date <= c_end)
        chart_df = btc.loc[mask]
        if chart_df.empty:
            chart_df = btc.tail(365)
    except Exception:
        chart_df = btc.tail(365)

# ==============================================================================
# 3. 頁面標題
# ==============================================================================
st.title("🦅 比特幣投資戰情室")
st.caption(
    f"數據更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 核心版本: Antigravity v4"
)

# 顯示非致命警告（可收起）
if _data_warnings:
    with st.expander(f"⚠️ {len(_data_warnings)} 個數據警告（不影響核心功能）", expanded=False):
        for w in _data_warnings:
            st.warning(w)

# ==============================================================================
# 4. Tabs
# ==============================================================================
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🐂 牛市雷達 (Bull Detector)",
    "🌊 波段狙擊 (Swing Trading)",
    "💰 雙幣理財 (Dual Investment)",
    "⏳ 時光機回測 (Backtest)",
    "🐻 熊市底部獵人 (Bear Bottom Hunter)",
])

with tab1:
    tab1_handler.render(
        btc, chart_df, tvl_hist, stable_hist, fund_hist,
        curr, dxy, funding_rate, tvl_val,
        fng_val, fng_state, fng_source, proxies, realtime_data,
    )

with tab2:
    tab2_handler.render(btc, curr, funding_rate, proxies, capital, risk_per_trade)

with tab3:
    tab3_handler.render(btc, realtime_data)

with tab4:
    tab4_handler.render(btc, call_risk, put_risk, ahr_threshold)

with tab5:
    tab5_handler.render(btc)
