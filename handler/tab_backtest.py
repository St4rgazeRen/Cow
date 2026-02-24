"""
handler/tab_backtest.py
Tab 4: 時光機回測
- 波段策略 PnL
- 雙幣滾倉回測
- 牛市雷達準確度驗證

[Task 4b - UX] 新增 CSV 下載功能:
  - 波段交易回測紀錄（trades_df）可下載為 .csv
  - 雙幣滾倉回測日誌（trade_log）可下載為 .csv
  使用 st.download_button，點擊即可在瀏覽器直接下載，無需後端儲存。
"""
import io
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import timedelta

from strategy.swing import run_swing_strategy_backtest
from strategy.dual_invest import run_dual_investment_backtest
from config import DEFAULT_INITIAL_CAPITAL


def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """
    將 DataFrame 轉換為 UTF-8 BOM 編碼的 CSV bytes，供 st.download_button 使用。

    使用 UTF-8-BOM（utf-8-sig）確保在 Windows Excel 開啟時中文不亂碼。
    返回 bytes 物件，可直接傳入 st.download_button 的 data 參數。
    """
    buffer = io.StringIO()
    df.to_csv(buffer, index=True, encoding='utf-8-sig')
    # encode 為 bytes（download_button 需要 bytes 或 str）
    return buffer.getvalue().encode('utf-8-sig')


def render(btc, call_risk, put_risk, ahr_threshold):
    st.markdown("### ⏳ 時光機回測 (Backtest Engine)")

    bt_tab1, bt_tab2, bt_tab3 = st.tabs([
        "📉 波段策略 PnL",
        "💰 雙幣滾倉回測",
        "🐂 牛市雷達準確度",
    ])

    # --- Sub-Tab 1: 波段策略 ---
    with bt_tab1:
        st.markdown("#### 📉 波段策略驗證 (自訂區間 PnL)")
        b_col1, b_col2 = st.columns([1, 3])

        with b_col1:
            st.subheader("⚙️ 回測設定")
            min_date = btc.index[0].date()
            max_date = btc.index[-1].date()
            start_d = st.date_input(
                "開始日期", value=min_date + timedelta(days=365),
                min_value=min_date, max_value=max_date,
            )
            end_d = st.date_input("結束日期", value=max_date,
                                  min_value=min_date, max_value=max_date)
            init_cap = st.number_input(
                "初始本金 (USDT)",
                value=int(DEFAULT_INITIAL_CAPITAL),
                step=1_000,
            )
            run_backtest = st.button("🚀 執行波段回測")

        with b_col2:
            if run_backtest:
                if start_d >= end_d:
                    st.error("結束日期必須晚於開始日期")
                else:
                    with st.spinner("正在模擬交易..."):
                        trades, final_val, roi, num_trades, mdd, stats = run_swing_strategy_backtest(
                            btc, start_d, end_d, init_cap
                        )
                        # 第一行: 核心指標
                        m1, m2, m3, m4, m5 = st.columns(5)
                        m1.metric("最終資產", f"${final_val:,.0f}")
                        m2.metric("總報酬率 (ROI)", f"{roi:+.2f}%", delta_color="normal")

                        start_price = btc.loc[pd.Timestamp(start_d):]['close'].iloc[0]
                        end_price = btc.loc[:pd.Timestamp(end_d)]['close'].iloc[-1]
                        bh_roi = (end_price / start_price - 1) * 100
                        m3.metric("Buy & Hold 報酬", f"{bh_roi:+.2f}%")
                        m4.metric("最大回撤 (MDD)", f"{mdd:.2f}%", delta_color="inverse")
                        m5.metric("總交易", f"{num_trades} 次")

                        # 第二行: 進階統計
                        st.markdown("---")
                        s1, s2, s3, s4 = st.columns(4)
                        s1.metric("勝率 (Win Rate)", f"{stats['win_rate']:.1f}%")
                        s2.metric("Sharpe Ratio", f"{stats['sharpe']:.2f}")
                        s3.metric("平均獲利", f"{stats['avg_profit']:+.2f}%",
                                  delta_color="normal")
                        s4.metric("平均虧損", f"{stats['avg_loss']:+.2f}%",
                                  delta_color="inverse")

                        mask = (btc.index >= pd.Timestamp(start_d)) & \
                               (btc.index <= pd.Timestamp(end_d))
                        sub_df = btc.loc[mask]
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=sub_df.index, y=sub_df['close'],
                            mode='lines', name='Price', line=dict(color='gray', width=1),
                        ))
                        fig.add_trace(go.Scatter(
                            x=sub_df.index, y=sub_df['EMA_20'],
                            mode='lines', name='EMA 20', line=dict(color='yellow', width=1),
                        ))
                        if not trades.empty:
                            buys = trades[trades['Type'] == 'Buy']
                            sells = trades[trades['Type'] == 'Sell']
                            fig.add_trace(go.Scatter(
                                x=buys['Date'], y=buys['Price'], mode='markers', name='Buy',
                                marker=dict(color='#00ff88', symbol='triangle-up', size=10),
                            ))
                            fig.add_trace(go.Scatter(
                                x=sells['Date'], y=sells['Price'], mode='markers', name='Sell',
                                marker=dict(color='#ff4b4b', symbol='triangle-down', size=10),
                            ))
                        fig.update_layout(title="波段交易買賣點回放", height=500, template="plotly_dark")
                        st.plotly_chart(fig, width='stretch')
                        if not trades.empty:
                            with st.expander("交易明細"):
                                st.dataframe(trades)

                            # [Task 4b] CSV 下載功能
                            # _df_to_csv_bytes 轉換為 UTF-8-BOM，確保 Excel 開啟不亂碼
                            csv_bytes = _df_to_csv_bytes(trades)
                            st.download_button(
                                label="⬇️ 下載波段交易紀錄 (.csv)",
                                data=csv_bytes,
                                # 檔名包含日期區間，方便管理多份回測結果
                                file_name=f"swing_trades_{start_d}_{end_d}.csv",
                                mime="text/csv",
                                help="下載本次回測的完整交易明細，包含進出場日期、價格、PnL、手續費等欄位",
                            )

    # --- Sub-Tab 2: 雙幣滾倉 ---
    with bt_tab2:
        st.markdown("#### 💰 雙幣理財長期滾倉回測")
        if st.button("🚀 執行滾倉回測"):
            with st.spinner("正在模擬每日滾倉..."):
                logs = run_dual_investment_backtest(btc, call_risk=call_risk, put_risk=put_risk)
                if not logs.empty:
                    m1, m2 = st.columns(2)
                    final_eq = logs.iloc[-1]['Equity_BTC']
                    ret = (final_eq - 1) * 100
                    m1.metric("最終權益 (BTC)", f"{final_eq:.4f}", f"{ret:.2f}%")
                    m2.metric("總交易次數", f"{len(logs[logs['Action'] == 'Open'])} 次")
                    fig2 = go.Figure()
                    fig2.add_trace(go.Scatter(
                        x=logs['Time'], y=logs['Equity_BTC'],
                        mode='lines', name='Equity (BTC)', line=dict(color='#00ff88'),
                    ))
                    fig2.update_layout(
                        title="資產淨值走勢 (BTC本位)", height=400, template="plotly_dark"
                    )
                    st.plotly_chart(fig2, width='stretch')
                    with st.expander("詳細交易日誌"):
                        st.dataframe(logs)

                    # [Task 4b] CSV 下載功能
                    csv_bytes_logs = _df_to_csv_bytes(logs)
                    st.download_button(
                        label="⬇️ 下載雙幣滾倉日誌 (.csv)",
                        data=csv_bytes_logs,
                        file_name="dual_invest_trade_log.csv",
                        mime="text/csv",
                        help="下載完整的雙幣理財滾倉交易日誌，包含每筆開單/結算的資產、餘額、行權價、備注等欄位",
                    )
                else:
                    st.warning("無交易紀錄")

    # --- Sub-Tab 3: 牛市雷達準確度 ---
    with bt_tab3:
        st.markdown("#### 🐂 牛市雷達準確度驗證")
        st.caption(
            "驗證：黃金交叉 (Close > MA200 & MA50 > MA200) + 年線上揚 (MA200 Slope > 0)\n"
            "⚠️ 2017 年若數據只有 2015+ 年起，SMA200 需 200 日累積，2017 前半年可能無信號屬正常。"
        )

        # 已知牛市區間（擴充至 2024-2025，提升捕捉率）
        bull_ranges = [
            ("2017-01", "2017-12"),   # 2017 牛市
            ("2020-10", "2021-04"),   # 2020-2021 牛市
            ("2023-10", "2024-03"),   # 2023-2024 年初牛市
            ("2024-10", "2025-01"),   # 2024 Q4 後特朗普行情
        ]

        val_df = btc.copy()
        # NaN 守衛：SMA 計算需要足夠歷史（200日），用 fillna(False) 避免 NaN 比較返回 False
        sma200_valid = val_df['SMA_200'].notna()
        sma50_valid  = val_df['SMA_50'].notna()
        slope_valid  = val_df['SMA_200_Slope'].notna()

        val_df['Trend_Bull'] = (
            sma200_valid & sma50_valid & slope_valid &
            (val_df['close'] > val_df['SMA_200'].fillna(0)) &
            (val_df['SMA_50'] > val_df['SMA_200'].fillna(0)) &
            (val_df['SMA_200_Slope'].fillna(0) > 0)
        )
        val_df['Signal_Bull'] = val_df['Trend_Bull']
        val_df['Actual_Bull'] = False

        for start, end in bull_ranges:
            try:
                s_dt = pd.to_datetime(start)
                e_dt = pd.to_datetime(end) + pd.offsets.MonthEnd(0)
                val_df.loc[s_dt:e_dt, 'Actual_Bull'] = True
            except Exception:
                pass

        conditions = [
            (val_df['Signal_Bull']) & (val_df['Actual_Bull']),
            (val_df['Signal_Bull']) & (~val_df['Actual_Bull']),
            (~val_df['Signal_Bull']) & (val_df['Actual_Bull']),
            (~val_df['Signal_Bull']) & (~val_df['Actual_Bull']),
        ]
        choices = ['Correct Bull', 'False Alarm (Trap)', 'Missed Opportunity', 'Correct Bear']
        val_df['Result'] = np.select(conditions, choices, default='Unknown')

        total_days = len(val_df)
        counts = val_df['Result'].value_counts()
        c_bull = counts.get('Correct Bull', 0)
        c_trap = counts.get('False Alarm (Trap)', 0)
        c_miss = counts.get('Missed Opportunity', 0)
        bull_days = len(val_df[val_df['Actual_Bull']])
        sensitivity = c_bull / bull_days * 100 if bull_days > 0 else 0
        acc_total = (c_bull + counts.get('Correct Bear', 0)) / total_days * 100

        v1, v2, v3, v4 = st.columns(4)
        v1.metric("牛市捕捉率", f"{sensitivity:.1f}%", f"{c_bull} 天命中")
        v2.metric("誤報天數", f"{c_trap} 天", delta_color="inverse")
        v3.metric("踏空天數", f"{c_miss} 天", delta_color="inverse")
        v4.metric("整體準確度", f"{acc_total:.1f}%")

        val_df['AHR_Signal'] = val_df['AHR999'] < ahr_threshold

        fig_m = go.Figure()
        fig_m.add_trace(go.Scatter(
            x=val_df.index, y=val_df['close'],
            mode='lines', name='Price', line=dict(color='gray', width=1),
        ))
        fig_m.add_trace(go.Scatter(
            x=val_df.index, y=val_df['SMA_200'],
            mode='lines', name='SMA 200', line=dict(color='orange', width=1),
        ))
        traps = val_df[val_df['Result'] == 'False Alarm (Trap)']
        if not traps.empty:
            fig_m.add_trace(go.Scatter(
                x=traps.index, y=traps['close'], mode='markers',
                name='❌ 誤判', marker=dict(color='#ff4b4b', size=8, symbol='x'),
            ))
        corrects = val_df[val_df['Result'] == 'Correct Bull']
        if not corrects.empty:
            fig_m.add_trace(go.Scatter(
                x=corrects.index, y=corrects['close'], mode='markers',
                name='✅ 命中', marker=dict(color='#00ff88', size=4, opacity=0.4),
            ))
        ahr_buys = val_df[val_df['AHR_Signal']]
        if not ahr_buys.empty:
            fig_m.add_trace(go.Scatter(
                x=ahr_buys.index, y=ahr_buys['close'] * 0.9, mode='markers',
                name=f'AHR < {ahr_threshold} (Buy Zone)',
                marker=dict(color='cyan', size=2, opacity=0.3),
            ))
        fig_m.update_layout(
            title="策略有效性驗證", height=400,
            template="plotly_dark", yaxis_type="log",
        )
        st.plotly_chart(fig_m, width='stretch')
