"""
handler/tab_swing.py
Tab 2: 波段狙擊 — Antigravity v4 核心策略引擎
"""
import streamlit as st


def render(btc, curr, funding_rate, proxies, capital, risk_per_trade):
    st.markdown("### 🌊 Antigravity v4 核心策略引擎")

    # A. 趨勢濾網
    st.subheader("A. 趨勢濾網 (Trend Filter)")
    f_col1, f_col2, f_col3 = st.columns(3)

    bull_ma = curr['close'] > curr['SMA_200']
    bull_rsi = curr.get('RSI_Weekly', 50) > 50
    not_overheated = funding_rate < 0.05

    f_col1.markdown(f"**價格 > MA200**: {'✅ 通過' if bull_ma else '❌ 未通過'}")
    f_col2.markdown(f"**週線 RSI > 50**: {'✅ 通過' if bull_rsi else '❌ 未通過'}")
    f_col3.markdown(f"**資金費率 < 0.05%**: {'✅ 通過' if not_overheated else '⚠️ 過熱'}")

    can_long = bull_ma and bull_rsi and not_overheated
    if can_long:
        st.success("🎯 策略狀態: **允許做多 (LONG ALLOWED)**")
    else:
        st.warning("🛡️ 策略狀態: **風險管控中 (RISK OFF)** - 建議觀望")

    st.markdown("---")

    # B & C: 智能進出場 + 動態止損
    logic_col1, logic_col2 = st.columns(2)
    ema_20 = curr['EMA_20']
    dist_pct = (curr['close'] / ema_20 - 1) * 100
    atr_val = curr['ATR']
    stop_price = ema_20 - (2.0 * atr_val)
    risk_dist_pct = (curr['close'] - stop_price) / curr['close']

    with logic_col1:
        st.subheader("B. 智能進出場 (Entries & Exits)")
        cex_flow = proxies['cex_flow']
        st.metric(
            "CEX 資金流向 (24h Proxy)", f"{cex_flow:+.0f} BTC",
            "交易所淨流出 (吸籌)" if cex_flow < 0 else "交易所淨流入 (拋壓)",
            delta_color="normal" if cex_flow < 0 else "inverse",
        )
        st.metric("EMA 20", f"${ema_20:,.0f}", f"乖離率 {dist_pct:.2f}%")

        if curr['close'] < ema_20:
            st.error("🔴 **賣出訊號 (SELL)**\n\n跌破均線，短期趨勢轉弱。")
            st.metric("建議回補價", f"${curr['BB_Lower']:,.0f}", "布林下軌支撐")
        elif can_long and (0 <= dist_pct <= 1.5):
            st.success("🟢 **買進訊號 (BUY)**\n\n甜蜜點！趨勢向上且回踩均線。")
            st.metric("建議止盈價", f"${curr['BB_Upper']:,.0f}", "布林上軌壓力")
        elif dist_pct > 3.0:
            st.warning(f"🟡 **乖離過大 (WAIT)**\n\n已偏離 {dist_pct:.2f}%，勿追高。")
            st.metric("建議接回價", f"${ema_20:,.0f}", "EMA 20")
        else:
            st.info("🔵 **持倉續抱 (HOLD)**\n\n趨勢延續中。")
            st.metric("下行防守價", f"${ema_20:,.0f}", "趨勢生命線")

    with logic_col2:
        st.subheader("C. 動態止損 & 清算地圖")
        st.caption("🔥 鏈上清算熱區 (Liquidation Clusters)")
        for heat in proxies['liq_map']:
            st.markdown(f"- **${heat['price']:,.0f}** ({heat['side']} {heat['vol']})")

        st.metric(
            "建議止損價 (EMA20 - 2ATR)", f"${stop_price:,.0f}",
            f"預計虧損幅度 -{risk_dist_pct * 100:.2f}%",
        )
        if risk_dist_pct < 0:
            st.error("⚠️ 當前價格已低於建議止損價！")

    st.markdown("---")

    # D. 倉位計算機
    st.subheader("D. 倉位計算機 (Risk Calculator)")
    entry_price = st.number_input("預計進場價格 (預設現價)", value=float(curr['close']))
    manual_stop = st.number_input("止損價格 (預設系統建議)", value=float(stop_price))

    if st.button("計算建議倉位"):
        if entry_price <= manual_stop:
            st.error("❌ 進場價必須高於止損價")
        else:
            risk_amt = capital * (risk_per_trade / 100)
            stop_dist_usd = entry_price - manual_stop
            pos_size_btc = risk_amt / stop_dist_usd
            pos_size_usdt = pos_size_btc * entry_price
            leverage = pos_size_usdt / capital

            st.markdown(f"""
            #### 🧮 計算結果
            - **風險金額**: `${risk_amt:.2f}` ({risk_per_trade}%)
            - **止損距離**: `${stop_dist_usd:.2f}` ({(stop_dist_usd / entry_price) * 100:.2f}%)
            """)

            res_col1, res_col2 = st.columns(2)
            if leverage > 1.5:
                res_col1.warning(f"⚠️ 原始計算槓桿: {leverage:.2f}x (超過 1.5x 上限)")
                capped_usdt = capital * 1.5
                capped_btc = capped_usdt / entry_price
                new_risk = ((capped_btc * stop_dist_usd) / capital) * 100
                res_col1.metric("建議開倉 (經風控)", f"{capped_btc:.4f} BTC", f"總值 ${capped_usdt:,.0f}")
                res_col2.metric("實際風險", f"{new_risk:.2f}%", f"原本 {risk_per_trade}%")
            else:
                res_col1.metric("建議開倉", f"{pos_size_btc:.4f} BTC", f"總值 ${pos_size_usdt:,.0f}")
                res_col2.metric("槓桿倍數", f"{leverage:.2f}x", "安全範圍")
