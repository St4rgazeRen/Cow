"""
handler/tab_backtest.py  ·  v2.0
Tab 4: 時光機回測

v2.0 重構:
  - 所有策略參數（call_risk / put_risk / ahr_threshold）移至 Tab 內部設定
  - bt_tab1 新增「參數面板」，可手動調整進場條件
  - bt_tab1 新增「🔍 尋找最佳參數」一鍵最佳化按鈕
  - bt_tab3 修正：同時繪製 MA200 + MA50，與驗證邏輯完全吻合

[Task 4b - UX] CSV 下載功能:
  - 波段交易回測紀錄（trades_df）可下載為 .csv
  - 雙幣滾倉回測日誌（trade_log）可下載為 .csv
"""
import io
import itertools
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import timedelta

from strategy.swing import run_swing_strategy_backtest
from strategy.dual_invest import run_dual_investment_backtest
from config import DEFAULT_INITIAL_CAPITAL


def _df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """將 DataFrame 轉換為 UTF-8 BOM 編碼的 CSV bytes"""
    buffer = io.StringIO()
    df.to_csv(buffer, index=True, encoding='utf-8-sig')
    return buffer.getvalue().encode('utf-8-sig')


def render(btc, call_risk=None, put_risk=None, ahr_threshold=None):
    """
    回測 Tab 渲染入口

    v2.0: call_risk / put_risk / ahr_threshold 不再由 sidebar 傳入，
          改為在各子 Tab 內部設定（兼容舊呼叫方式，有傳值則用為預設值）。
    """
    st.markdown("### ⏳ 時光機回測 (Backtest Engine)")

    bt_tab1, bt_tab2, bt_tab3 = st.tabs([
        "📉 波段策略 PnL",
        "💰 雙幣滾倉回測",
        "🐂 牛市雷達準確度",
    ])

    # ══════════════════════════════════════════════════════════════
    # Sub-Tab 1: 波段策略 PnL（已移除最大乖離限制）
    # ══════════════════════════════════════════════════════════════
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
            end_d = st.date_input(
                "結束日期", value=max_date,
                min_value=min_date, max_value=max_date,
            )
            init_cap = st.number_input(
                "初始本金 (USDT)",
                value=int(DEFAULT_INITIAL_CAPITAL),
                step=1_000,
            )

            st.markdown("---")
            st.markdown("**進場條件調整**")
            dist_min = st.slider(
                "EMA20 最小乖離 (%)",
                min_value=0.0, max_value=2.0, value=0.0, step=0.1,
                help="收盤價高於 EMA20 的最小百分比偏差（0 = 只要站上 EMA20 即符合）",
            )
            # 已移除「最大乖離」滑桿
            rsi_thresh = st.slider(
                "RSI 動能閾值",
                min_value=40, max_value=65, value=50, step=1,
                help="RSI 需高於此值才視為多頭動能",
            )
            adx_thresh = st.slider(
                "ADX 趨勢強度閾值",
                min_value=10, max_value=35, value=20, step=1,
                help="ADX 需高於此值才視為有效趨勢（過濾橫盤假訊號）",
            )

            run_backtest = st.button("🚀 執行波段回測", type="primary")

            st.markdown("---")
            st.markdown("**🔍 參數最佳化**")
            st.caption("迴圈搜尋「勝率最高」或「報酬最佳」的參數組合")
            opt_metric = st.radio(
                "最佳化目標",
                options=["最高勝率 (Win Rate)", "最高總報酬 (ROI)"],
                index=0, horizontal=True,
            )
            run_optimize = st.button("🔬 尋找最佳參數", help="需要數秒鐘，請耐心等候")

        with b_col2:
            if run_backtest:
                if start_d >= end_d:
                    st.error("結束日期必須晚於開始日期")
                else:
                    with st.spinner("正在模擬交易..."):
                        # 呼叫回測引擎 (已移除 entry_dist_max_pct)
                        trades, final_val, roi, num_trades, mdd, stats = run_swing_strategy_backtest(
                            btc, start_d, end_d, init_cap,
                            entry_dist_min_pct=dist_min,
                            rsi_min=rsi_thresh,
                            adx_min=adx_thresh,
                        )
                        m1, m2, m3, m4, m5 = st.columns(5)
                        m1.metric("最終資產", f"${final_val:,.0f}")
                        m2.metric("總報酬率 (ROI)", f"{roi:+.2f}%", delta_color="normal")
                        start_price = btc.loc[pd.Timestamp(start_d):]['close'].iloc[0]
                        end_price   = btc.loc[:pd.Timestamp(end_d)]['close'].iloc[-1]
                        bh_roi = (end_price / start_price - 1) * 100
                        m3.metric("Buy & Hold 報酬", f"{bh_roi:+.2f}%")
                        m4.metric("最大回撤 (MDD)", f"{mdd:.2f}%", delta_color="inverse")
                        m5.metric("總交易", f"{num_trades} 次")

                        st.markdown("---")
                        s1, s2, s3, s4 = st.columns(4)
                        s1.metric("勝率 (Win Rate)", f"{stats['win_rate']:.1f}%")
                        s2.metric("Sharpe Ratio", f"{stats['sharpe']:.2f}")
                        s3.metric("平均獲利", f"{stats['avg_profit']:+.2f}%", delta_color="normal")
                        s4.metric("平均虧損", f"{stats['avg_loss']:+.2f}%", delta_color="inverse")

                        mask   = (btc.index >= pd.Timestamp(start_d)) & (btc.index <= pd.Timestamp(end_d))
                        sub_df = btc.loc[mask]
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=sub_df.index, y=sub_df['close'],
                            mode='lines', name='Price', line=dict(color='gray', width=1),
                        ))
                        # 改畫 SMA50，因為現在出場看這條
                        if 'SMA_50' in sub_df.columns:
                            fig.add_trace(go.Scatter(
                                x=sub_df.index, y=sub_df['SMA_50'],
                                mode='lines', name='SMA 50 (防守線)', line=dict(color='yellow', width=1, dash='dash'),
                            ))
                        if not trades.empty:
                            buys  = trades[trades['Type'] == 'Buy']
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
                        st.plotly_chart(fig, use_container_width=True)

                        if not trades.empty:
                            with st.expander("交易明細"):
                                st.dataframe(trades)
                            st.download_button(
                                label="⬇️ 下載波段交易紀錄 (.csv)",
                                data=_df_to_csv_bytes(trades),
                                file_name=f"swing_trades_{start_d}_{end_d}.csv",
                                mime="text/csv",
                            )

            # ──────────────────────────────────────────────────────
            # 最佳化功能 (移除最大乖離維度，大幅加速)
            # ──────────────────────────────────────────────────────
            if run_optimize:
                if start_d >= end_d:
                    st.error("結束日期必須晚於開始日期")
                else:
                    st.info("🔬 開始網格搜尋，掃描參數組合中...")

                    # 搜尋網格 (減少維度)
                    dist_min_range  = [0.0, 0.2, 0.5]
                    rsi_range       = [45, 50, 55]
                    adx_range       = [15, 20, 25]

                    grid = list(itertools.product(dist_min_range, rsi_range, adx_range))

                    best_params = None
                    best_metric_val = -float('inf')
                    results = []

                    progress_bar = st.progress(0)
                    total = len(grid)

                    for i, (dmin, rsi, adx) in enumerate(grid):
                        _, fval, roi_v, ntrades, _, sts = run_swing_strategy_backtest(
                            btc, start_d, end_d, init_cap,
                            entry_dist_min_pct=dmin,
                            rsi_min=rsi,
                            adx_min=adx,
                        )
                        target_val = sts.get('win_rate', 0) if "勝率" in opt_metric else roi_v
                        results.append({
                            "EMA乖離Min(%)": dmin,
                            "RSI閾值": rsi,
                            "ADX閾值": adx,
                            "勝率(%)": round(sts.get('win_rate', 0), 1),
                            "總報酬ROI(%)": round(roi_v, 2),
                            "Sharpe": round(sts.get('sharpe', 0), 2),
                            "交易次數": ntrades,
                        })
                        if target_val > best_metric_val and ntrades >= 3:
                            best_metric_val = target_val
                            best_params = {
                                "EMA乖離Min(%)": dmin,
                                "RSI閾值": rsi,
                                "ADX閾值": adx,
                                "勝率(%)": round(sts.get('win_rate', 0), 1),
                                "總報酬ROI(%)": round(roi_v, 2),
                                "Sharpe": round(sts.get('sharpe', 0), 2),
                                "交易次數": ntrades,
                            }
                        progress_bar.progress(min((i+1)/total, 1.0))

                    progress_bar.empty()

                    if best_params:
                        st.success(f"✅ 找到最佳參數！（最佳化目標：{opt_metric}）")
                        bp_cols = st.columns(4)
                        bp_cols[0].metric("EMA乖離Min", f"{best_params['EMA乖離Min(%)']}%")
                        bp_cols[1].metric("RSI 閾值",    f"{best_params['RSI閾值']}")
                        bp_cols[2].metric("ADX 閾值",    f"{best_params['ADX閾值']}")
                        bp_cols[3].metric("勝率 / ROI",  f"{best_params['勝率(%)']}% / {best_params['總報酬ROI(%)']:+.1f}%")
                    else:
                        st.warning("⚠️ 在所有參數組合中，交易次數均不足 3 次，無法評估。請調整日期範圍。")

                    results_df = pd.DataFrame(results)
                    sort_col   = "勝率(%)" if "勝率" in opt_metric else "總報酬ROI(%)"
                    results_df = results_df.sort_values(sort_col, ascending=False).head(10)
                    with st.expander("📊 Top 10 參數組合結果", expanded=True):
                        st.dataframe(results_df, use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════
    # Sub-Tab 2: 雙幣滾倉回測（參數移至 Tab 內部）
    # ══════════════════════════════════════════════════════════════
    with bt_tab2:
        st.markdown("#### 💰 雙幣理財長期滾倉回測")

        di_col1, di_col2 = st.columns(2)
        with di_col1:
            _call_risk = st.number_input(
                "Sell High 風險係數",
                value=float(call_risk) if call_risk is not None else 0.5,
                step=0.1, min_value=0.1, max_value=2.0,
                help="越大掛越遠（越保守），決定行權價距離現價的倍數",
            )
        with di_col2:
            _put_risk = st.number_input(
                "Buy Low 風險係數",
                value=float(put_risk) if put_risk is not None else 0.5,
                step=0.1, min_value=0.1, max_value=2.0,
                help="越大掛越遠（越保守），決定行權價距離現價的倍數",
            )

        if st.button("🚀 執行滾倉回測"):
            with st.spinner("正在模擬每日滾倉..."):
                logs = run_dual_investment_backtest(btc, call_risk=_call_risk, put_risk=_put_risk)
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
                    st.plotly_chart(fig2, use_container_width=True)
                    with st.expander("詳細交易日誌"):
                        st.dataframe(logs)
                    st.download_button(
                        label="⬇️ 下載雙幣滾倉日誌 (.csv)",
                        data=_df_to_csv_bytes(logs),
                        file_name="dual_invest_trade_log.csv",
                        mime="text/csv",
                    )
                else:
                    st.warning("無交易紀錄")

    # ══════════════════════════════════════════════════════════════
    # Sub-Tab 3: 牛市雷達準確度（修正：加入 MA50 圖層）
    # ══════════════════════════════════════════════════════════════
    with bt_tab3:
        st.markdown("#### 🐂 牛市雷達準確度驗證")
        st.caption(
            "驗證：黃金交叉 (Close > MA200 & **MA50 > MA200**) + 年線上揚 (MA200 Slope > 0)\n"
            "圖表同時繪製 **MA200（橙色）** 與 **MA50（青色）**，讓金叉/死叉視覺與文字條件完全對應。"
        )

        # AHR999 閾值（參數移至 Tab 內）
        _ahr_threshold = st.slider(
            "AHR999 抄底閾值",
            min_value=0.3, max_value=1.5,
            value=float(ahr_threshold) if ahr_threshold is not None else 0.45,
            step=0.05,
            help="AHR999 低於此值時標記為抄底買入信號（圖表中青色散點）",
        )

        bull_ranges = [
            ("2017-01", "2017-12"),
            ("2020-10", "2021-04"),
            ("2023-10", "2024-03"),
            ("2024-10", "2025-01"),
        ]

        val_df = btc.copy()
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

        total_days  = len(val_df)
        counts      = val_df['Result'].value_counts()
        c_bull      = counts.get('Correct Bull', 0)
        c_trap      = counts.get('False Alarm (Trap)', 0)
        c_miss      = counts.get('Missed Opportunity', 0)
        bull_days   = len(val_df[val_df['Actual_Bull']])
        sensitivity = c_bull / bull_days * 100 if bull_days > 0 else 0
        acc_total   = (c_bull + counts.get('Correct Bear', 0)) / total_days * 100

        v1, v2, v3, v4 = st.columns(4)
        v1.metric("牛市捕捉率", f"{sensitivity:.1f}%", f"{c_bull} 天命中")
        v2.metric("誤報天數", f"{c_trap} 天", delta_color="inverse")
        v3.metric("踏空天數", f"{c_miss} 天", delta_color="inverse")
        v4.metric("整體準確度", f"{acc_total:.1f}%")

        val_df['AHR_Signal'] = val_df['AHR999'] < _ahr_threshold

        # 修正：圖表同時繪製 MA200 + MA50，與文字驗證條件（金叉/死叉）完全吻合
        fig_m = go.Figure()
        fig_m.add_trace(go.Scatter(
            x=val_df.index, y=val_df['close'],
            mode='lines', name='Price', line=dict(color='gray', width=1),
        ))
        # MA200（橙色，主要趨勢濾網）
        fig_m.add_trace(go.Scatter(
            x=val_df.index, y=val_df['SMA_200'],
            mode='lines', name='SMA 200',
            line=dict(color='orange', width=1.5),
        ))
        # MA50（青色，與 MA200 形成金叉/死叉 — 這正是驗證條件 MA50 > MA200）
        fig_m.add_trace(go.Scatter(
            x=val_df.index, y=val_df['SMA_50'],
            mode='lines', name='SMA 50',
            line=dict(color='cyan', width=1.2, dash='dash'),
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
                name=f'AHR < {_ahr_threshold} (Buy Zone)',
                marker=dict(color='cyan', size=2, opacity=0.3),
            ))

        fig_m.update_layout(
            title="策略有效性驗證（橙色=MA200，青色=MA50，金叉區間=訊號觸發）",
            height=400, template="plotly_dark", yaxis_type="log",
        )
        st.plotly_chart(fig_m, use_container_width=True)

        with st.expander("📖 驗證條件說明"):
            st.markdown("""
            **買入訊號觸發條件（三合一）**:
            1. `Close > SMA_200` — 價格站上 200 日均線（多頭市場確認）
            2. `SMA_50 > SMA_200` — 金叉：50 日均線穿越 200 日均線上方（圖表橙線 vs 青線）
            3. `SMA_200 Slope > 0` — 200 日均線斜率為正（年線趨勢向上）

            圖表中橙色為 SMA200、青色為 SMA50，
            當青色（SMA50）在橙色（SMA200）上方時即為金叉狀態，與文字條件完全對應。
            """)
