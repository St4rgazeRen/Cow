"""
handler/tab_dual_invest.py
Tab 3: 雙幣理財顧問
"""
import streamlit as st
import pandas as pd

from strategy.dual_invest import get_current_suggestion


def render(btc, realtime_data):
    st.markdown("### 💰 雙幣理財顧問 (Dual Investment)")

    defi_yield = realtime_data.get('defi_yield') or 5.0

    # 期限選擇（影響 APY 計算）
    t_days = st.select_slider(
        "產品期限（天）— 影響 APY 估算",
        options=[1, 3, 7, 14, 30],
        value=3,
    )

    st.info(
        f"💡 **DeFi 機會成本參考**: Aave USDT 活存約 **{defi_yield:.2f}%** 年化。"
        f"  若 APY(年化) 低於此值，建議改為單純放貸。"
    )

    suggestion = get_current_suggestion(btc, t_days=t_days)

    if suggestion:
        s_col1, s_col2 = st.columns([1, 2])

        with s_col1:
            curr_row = btc.iloc[-1]
            signal = (
                "Sell High"
                if curr_row['EMA_20'] >= curr_row['SMA_50']
                else "觀望 / Sell High Only"
            )
            st.metric("核心信號", signal)
            st.caption("基於 EMA20 vs SMA50 趨勢")
            st.markdown("#### 技術解讀")
            for line in suggestion['explanation']:
                st.markdown(f"- {line}")

        with s_col2:
            st.markdown("#### 🎯 智能掛單推薦 (Ladder Strategy)")
            t1, t2 = st.tabs(["🟢 Sell High (持有BTC)", "🔴 Buy Low (持有USDT)"])

            with t1:
                if suggestion['sell_ladder']:
                    df_sell = pd.DataFrame(suggestion['sell_ladder'])
                    df_sell['Strike'] = df_sell['Strike'].apply(lambda x: f"${x:,.0f}")
                    df_sell['Distance'] = df_sell['Distance'].apply(lambda x: f"+{x:.2f}%")
                    st.table(df_sell[['Type', 'Strike', 'Weight', 'Distance', 'APY(年化)']])
                else:
                    st.info("暫無建議 (可能是週末或數據不足)")

            with t2:
                if suggestion['buy_ladder']:
                    df_buy = pd.DataFrame(suggestion['buy_ladder'])
                    df_buy['Strike'] = df_buy['Strike'].apply(lambda x: f"${x:,.0f}")
                    df_buy['Distance'] = df_buy['Distance'].apply(lambda x: f"{x:.2f}%")
                    st.table(df_buy[['Type', 'Strike', 'Weight', 'Distance', 'APY(年化)']])
                else:
                    st.warning("⚠️ 趨勢偏空或濾網觸發，不建議 Buy Low (接刀)")
