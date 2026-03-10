"""
handler/tab_backtest.py  ·  v2.0
Tab 4: 時光機回測

v2.0 重構:
  - 所有策略參數（call_risk / put_risk / ahr_threshold）移至 Tab 內部設定
  - bt_tab1 新增「參數面板」，可手動調整進場條件與防守線
  - bt_tab1 新增「🔍 尋找最佳參數」一鍵最佳化按鈕，將防守線納入多維度掃描
  - bt_tab3 修正：同時繪製 MA200 + MA50，與驗證邏輯完全吻合

[Task 4b - UX] CSV 下載功能:
  - 波段交易回測紀錄（trades_df）可下載為 .csv
  - 雙幣滾倉回測日誌（trade_log）可下載為 .csv
"""
# 關閉 SSL 驗證警告，避免本地端公司網路環境報錯
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import io
import itertools
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from strategy.swing import run_swing_strategy_backtest, run_multitf_backtest
from strategy.dual_invest import run_dual_investment_backtest
from strategy.walkforward_backtest import WalkForwardBacktester
from service.local_db_reader import read_btc_15m, has_local_data
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

    bt_tab1, bt_tab2, bt_tab3, bt_tab4, bt_tab5 = st.tabs([
        "📉 波段策略 PnL",
        "💰 雙幣滾倉回測",
        "🐂 牛市雷達準確度",
        "📈 多週期回測 (Multi-TF)",
        "🚀 Walk-Forward 無先視回測",
    ])

    # ══════════════════════════════════════════════════════════════
    # Sub-Tab 1: 波段策略 PnL（支援動態防守線與最佳化）
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
            st.markdown("**進場與防守條件調整**")
            dist_min = st.slider(
                "EMA20 最小乖離 (%)",
                min_value=0.0, max_value=2.0, value=0.0, step=0.1,
                help="收盤價高於 EMA20 的最小百分比偏差（0 = 只要站上 EMA20 即符合）",
            )
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
            
            # 新增：選擇出場防守線的 UI
            exit_ma_key = st.selectbox(
                "波段防守線 (出場條件)",
                options=["SMA_50", "EMA_20", "SMA_200"],
                index=0,
                help="選擇做為出場防守的均線。當價格跌破此均線即觸發賣出。"
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
                        # 呼叫回測引擎，傳入使用者選擇的 exit_ma
                        trades, final_val, roi, num_trades, mdd, stats = run_swing_strategy_backtest(
                            btc, start_d, end_d, init_cap,
                            entry_dist_min_pct=dist_min,
                            rsi_min=rsi_thresh,
                            adx_min=adx_thresh,
                            exit_ma=exit_ma_key,
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
                        # 根據 UI 選擇動態畫出防守線
                        if exit_ma_key in sub_df.columns:
                            fig.add_trace(go.Scatter(
                                x=sub_df.index, y=sub_df[exit_ma_key],
                                mode='lines', name=f'{exit_ma_key} (防守線)', line=dict(color='yellow', width=1, dash='dash'),
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
            # 最佳化功能 (將防守線也納入網格搜尋的維度)
            # ──────────────────────────────────────────────────────
            if run_optimize:
                if start_d >= end_d:
                    st.error("結束日期必須晚於開始日期")
                else:
                    st.info("🔬 開始網格搜尋，掃描參數組合中...")

                    # 搜尋網格 (新增防守線維度)
                    dist_min_range  = [0.0, 0.2, 0.5]
                    rsi_range       = [45, 50, 55]
                    adx_range       = [15, 20, 25]
                    exit_ma_range   = ["SMA_50", "EMA_20", "SMA_200"]

                    grid = list(itertools.product(dist_min_range, rsi_range, adx_range, exit_ma_range))

                    best_params = None
                    best_metric_val = -float('inf')
                    results = []

                    progress_bar = st.progress(0)
                    total = len(grid)
                    completed_count = [0]

                    def _run_one(params):
                        dmin, rsi, adx, ema_exit = params
                        _, fval, roi_v, ntrades, _, sts = run_swing_strategy_backtest(
                            btc, start_d, end_d, init_cap,
                            entry_dist_min_pct=dmin,
                            rsi_min=rsi,
                            adx_min=adx,
                            exit_ma=ema_exit,
                        )
                        return params, roi_v, ntrades, sts

                    with ThreadPoolExecutor(max_workers=4) as executor:
                        futures = {executor.submit(_run_one, p): p for p in grid}
                        for future in as_completed(futures):
                            (dmin, rsi, adx, ema_exit), roi_v, ntrades, sts = future.result()
                            target_val = sts.get('win_rate', 0) if "勝率" in opt_metric else roi_v
                            row = {
                                "EMA乖離Min(%)": dmin,
                                "RSI閾值": rsi,
                                "ADX閾值": adx,
                                "防守線": ema_exit,
                                "勝率(%)": round(sts.get('win_rate', 0), 1),
                                "總報酬ROI(%)": round(roi_v, 2),
                                "Sharpe": round(sts.get('sharpe', 0), 2),
                                "交易次數": ntrades,
                            }
                            results.append(row)
                            if target_val > best_metric_val and ntrades >= 3:
                                best_metric_val = target_val
                                best_params = row
                            completed_count[0] += 1
                            progress_bar.progress(min(completed_count[0] / total, 1.0))

                    progress_bar.empty()

                    if best_params:
                        st.success(f"✅ 找到最佳參數！（最佳化目標：{opt_metric}）")
                        bp_cols = st.columns(4)
                        bp_cols[0].metric("EMA乖離Min", f"{best_params['EMA乖離Min(%)']}%")
                        bp_cols[1].metric("RSI / ADX",    f"{best_params['RSI閾值']} / {best_params['ADX閾值']}")
                        bp_cols[2].metric("最佳防守線",    f"{best_params['防守線']}")
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

    # ══════════════════════════════════════════════════════════════
    # Sub-Tab 4: 多週期回測 (Multi-Timeframe Backtest)
    # ══════════════════════════════════════════════════════════════
    with bt_tab4:
        st.markdown("#### 📈 多週期回測 (Multi-Timeframe)")
        st.caption(
            "🛡️ **防先視偏誤**：日線條件在第 N 日收盤後確認，第 N+1 日起的 15m 才允許進場；"
            "15m 訊號在第 M 根收盤後確認，第 M+1 根開盤執行。"
        )

        if not has_local_data():
            st.error("❌ 找不到本地 15m SQLite 資料庫（db/ 目錄）。請先執行 collector/btc_price_collector.py 收集資料。")
        else:
            mt_col1, mt_col2 = st.columns([1, 3])

            with mt_col1:
                st.subheader("⚙️ 多週期設定")

                min_date = btc.index[0].date()
                max_date = btc.index[-1].date()
                mt_start = st.date_input(
                    "開始日期", value=max_date - timedelta(days=365),
                    min_value=min_date, max_value=max_date, key="mt_start",
                )
                mt_end = st.date_input(
                    "結束日期", value=max_date,
                    min_value=min_date, max_value=max_date, key="mt_end",
                )
                mt_cap = st.number_input(
                    "初始本金 (USDT)", value=int(DEFAULT_INITIAL_CAPITAL),
                    step=1_000, key="mt_cap",
                )

                st.markdown("**日線宏觀過濾**")
                use_sma200 = st.checkbox("收盤 > SMA200（年線多頭）", value=True)
                use_golden = st.checkbox("SMA50 > SMA200（金叉確認）", value=False)

                st.markdown("**15m 進場條件**")
                ema_period = st.selectbox("15m EMA 週期", [10, 20, 50], index=1)
                rsi_15m    = st.slider("15m RSI 動能閾值", 40, 65, 50, key="mt_rsi")
                stop_pct   = st.slider(
                    "停損 (%)", 1.0, 10.0, 3.0, step=0.5,
                    help="進場後收盤跌破此百分比即觸發停損出場",
                )

                run_mt = st.button("🚀 執行多週期回測", type="primary", key="mt_run")

            with mt_col2:
                if run_mt:
                    if mt_start >= mt_end:
                        st.error("結束日期必須晚於開始日期")
                    else:
                        days_span = (mt_end - mt_start).days
                        if days_span > 730:
                            st.warning(f"⚠️ 回測區間 {days_span} 天，15m 資料量較大，計算需數秒，請耐心等候。")

                        with st.spinner("載入 15m 資料並執行多週期回測..."):
                            df_15m = read_btc_15m(
                                start_date=mt_start.strftime("%Y-%m-%d"),
                                end_date=mt_end.strftime("%Y-%m-%d"),
                            )

                        if df_15m.empty:
                            st.error("❌ 無法取得此期間的 15m 資料，請確認本地 DB 已更新。")
                        else:
                            with st.spinner("模擬多週期交易..."):
                                mt_trades, mt_final, mt_roi, mt_n, mt_mdd, mt_stats = run_multitf_backtest(
                                    df_daily=btc,
                                    df_15m=df_15m,
                                    start_date=mt_start,
                                    end_date=mt_end,
                                    initial_capital=mt_cap,
                                    daily_use_sma200=use_sma200,
                                    daily_use_golden=use_golden,
                                    ema_period_15m=ema_period,
                                    rsi_min_15m=rsi_15m,
                                    stop_loss_pct=stop_pct,
                                )

                            # ── 核心指標 ──
                            m1, m2, m3, m4, m5 = st.columns(5)
                            m1.metric("最終資產", f"${mt_final:,.0f}")
                            m2.metric("總報酬率 (ROI)", f"{mt_roi:+.2f}%", delta_color="normal")
                            try:
                                start_price = btc.loc[pd.Timestamp(mt_start):]['close'].iloc[0]
                                end_price   = btc.loc[:pd.Timestamp(mt_end)]['close'].iloc[-1]
                                bh_roi = (end_price / start_price - 1) * 100
                                m3.metric("Buy & Hold 報酬", f"{bh_roi:+.2f}%")
                            except Exception:
                                m3.metric("Buy & Hold 報酬", "—")
                            m4.metric("最大回撤 (MDD)", f"{mt_mdd:.2f}%", delta_color="inverse")
                            m5.metric("交易次數 (15m)", f"{mt_n} 次")

                            st.markdown("---")
                            s1, s2, s3, s4 = st.columns(4)
                            s1.metric("勝率", f"{mt_stats.get('win_rate', 0):.1f}%")
                            s2.metric("Sharpe (年化)", f"{mt_stats.get('sharpe', 0):.2f}")
                            s3.metric("平均獲利", f"{mt_stats.get('avg_profit', 0):+.2f}%", delta_color="normal")
                            s4.metric("平均虧損", f"{mt_stats.get('avg_loss', 0):+.2f}%", delta_color="inverse")

                            # ── 圖表：買賣點疊加 BTC 日線 ──
                            if not mt_trades.empty:
                                mask   = (btc.index >= pd.Timestamp(mt_start)) & (btc.index <= pd.Timestamp(mt_end))
                                sub_df = btc.loc[mask]
                                fig_mt = go.Figure()
                                fig_mt.add_trace(go.Scatter(
                                    x=sub_df.index, y=sub_df['close'],
                                    mode='lines', name='BTC (日線)',
                                    line=dict(color='gray', width=1),
                                ))
                                if 'SMA_200' in sub_df.columns:
                                    fig_mt.add_trace(go.Scatter(
                                        x=sub_df.index, y=sub_df['SMA_200'],
                                        mode='lines', name='SMA200 (日)',
                                        line=dict(color='orange', width=1, dash='dot'),
                                    ))

                                buys  = mt_trades[mt_trades['Type'] == 'Buy']
                                sells = mt_trades[mt_trades['Type'] == 'Sell']
                                if not buys.empty:
                                    fig_mt.add_trace(go.Scatter(
                                        x=buys['Date'], y=buys['Price'], mode='markers',
                                        name='15m 買入',
                                        marker=dict(color='#00ff88', symbol='triangle-up', size=7),
                                    ))
                                if not sells.empty:
                                    stop_sells = sells[sells['Reason'] == 'Stop Loss']
                                    norm_sells = sells[sells['Reason'] != 'Stop Loss']
                                    if not norm_sells.empty:
                                        fig_mt.add_trace(go.Scatter(
                                            x=norm_sells['Date'], y=norm_sells['Price'], mode='markers',
                                            name='15m 賣出',
                                            marker=dict(color='#ff4b4b', symbol='triangle-down', size=7),
                                        ))
                                    if not stop_sells.empty:
                                        fig_mt.add_trace(go.Scatter(
                                            x=stop_sells['Date'], y=stop_sells['Price'], mode='markers',
                                            name='停損出場',
                                            marker=dict(color='#ff9900', symbol='x', size=8),
                                        ))

                                fig_mt.update_layout(
                                    title="多週期回測買賣點（日線圖疊加 15m 訊號）",
                                    height=500, template="plotly_dark",
                                )
                                st.plotly_chart(fig_mt, use_container_width=True)

                                with st.expander("交易明細"):
                                    st.dataframe(mt_trades, use_container_width=True)
                                st.download_button(
                                    label="⬇️ 下載多週期交易紀錄 (.csv)",
                                    data=_df_to_csv_bytes(mt_trades),
                                    file_name=f"multitf_trades_{mt_start}_{mt_end}.csv",
                                    mime="text/csv",
                                )
                            else:
                                st.warning("⚠️ 此期間無任何進場訊號。可嘗試：放寬日線過濾條件、降低 RSI 閾值，或延長回測區間。")

                        with st.expander("📖 多週期策略邏輯說明"):
                            st.markdown(f"""
                            **日線宏觀過濾（今日生效的是昨日確認的條件）**：
                            {'- ✅ 收盤 > SMA200（年線多頭）' if use_sma200 else '- ⬜ SMA200 過濾已停用'}
                            {'- ✅ SMA50 > SMA200（金叉確認）' if use_golden else '- ⬜ 金叉過濾已停用'}

                            **15m 進場條件**（訊號收盤確認，次根開盤執行）：
                            - 15m 收盤 > 15m EMA{ema_period}
                            - 15m RSI14 > {rsi_15m}

                            **15m 出場條件**：
                            - 15m 收盤 < 15m EMA{ema_period}（趨勢轉弱）
                            - 固定停損：進場後收盤跌破 {stop_pct}%

                            **防先視偏誤**：所有訊號均已 shift(1)，確保使用的是「已知」資訊。
                            """)

    # ══════════════════════════════════════════════════════════════
    # Sub-Tab 5: Walk-Forward 無先視回測（改編自 tw_stock_climber）
    # ══════════════════════════════════════════════════════════════
    with bt_tab5:
        st.markdown("#### 🚀 Walk-Forward 無先視回測（逐日推進）")
        st.caption(
            "🛡️ **無先視偏誤設計**：每日掃描的進場條件只基於該日及以前的資料，"
            "模擬實際交易的『只知已知資訊』真實情境。"
        )

        wf_col1, wf_col2 = st.columns([1, 3])

        with wf_col1:
            st.subheader("⚙️ 回測設定")
            wf_min_date = btc.index[0].date()
            wf_max_date = btc.index[-1].date()
            wf_start = st.date_input(
                "開始日期", value=wf_min_date + timedelta(days=365),
                min_value=wf_min_date, max_value=wf_max_date, key="wf_start",
            )
            wf_end = st.date_input(
                "結束日期", value=wf_max_date,
                min_value=wf_min_date, max_value=wf_max_date, key="wf_end",
            )
            wf_init_cap = st.number_input(
                "初始本金 (USDT)",
                value=int(DEFAULT_INITIAL_CAPITAL),
                step=1_000, key="wf_cap",
            )

            st.markdown("---")
            st.markdown("**進場條件（Antigravity v4.1 五合一）**")
            wf_dist = st.slider(
                "EMA20 最小乖離 (%)",
                min_value=0.0, max_value=2.0, value=0.0, step=0.1,
                help="0 = 只要站上 EMA20 即符合", key="wf_dist",
            )
            wf_rsi = st.slider(
                "RSI 動能閾值",
                min_value=40, max_value=65, value=50, step=1, key="wf_rsi",
            )
            wf_adx = st.slider(
                "ADX 趨勢強度閾值",
                min_value=10, max_value=35, value=20, step=1, key="wf_adx",
            )
            wf_exit_ma = st.selectbox(
                "波段防守線 (出場條件)",
                options=["SMA_50", "EMA_20", "SMA_200"],
                index=0, key="wf_exit_ma",
            )

            st.markdown("**出場參數**")
            wf_atr_sl = st.slider(
                "ATR 停損倍數",
                min_value=0.5, max_value=3.0, value=2.0, step=0.25, key="wf_atr_sl",
                help="停損線 = 進場價 - ATR×倍數",
            )
            wf_atr_tp = st.slider(
                "ATR 目標倍數",
                min_value=1.0, max_value=5.0, value=3.0, step=0.25, key="wf_atr_tp",
                help="目標線 = 進場價 + ATR×倍數",
            )
            wf_scan = st.slider(
                "進場掃描頻率 (日)",
                min_value=1, max_value=10, value=5, step=1, key="wf_scan",
                help="每 N 日掃描一次進場訊號（降低計算負擔）",
            )

            wf_run = st.button("🚀 執行 Walk-Forward 回測", type="primary", key="wf_run")

        with wf_col2:
            if wf_run:
                if wf_start >= wf_end:
                    st.error("結束日期必須晚於開始日期")
                else:
                    with st.spinner("執行 Walk-Forward 逐日回測..."):
                        bt = WalkForwardBacktester()
                        wf_result = bt.run_walkforward(
                            df=btc,
                            start_date=wf_start.strftime("%Y-%m-%d"),
                            end_date=wf_end.strftime("%Y-%m-%d"),
                            initial_capital=wf_init_cap,
                            scan_freq=wf_scan,
                            exit_ma=wf_exit_ma,
                            entry_dist_min_pct=wf_dist,
                            rsi_min=wf_rsi,
                            adx_min=wf_adx,
                            atr_sl_multiplier=wf_atr_sl,
                            atr_tp_multiplier=wf_atr_tp,
                        )

                        # ── 核心指標 ──
                        wf_m1, wf_m2, wf_m3, wf_m4, wf_m5 = st.columns(5)
                        wf_m1.metric("最終資產", f"${wf_result['final_balance']:,.0f}")
                        wf_m2.metric("策略報酬", f"{wf_result['stock_return']:+.2f}%", delta_color="normal")
                        wf_m3.metric("Buy&Hold", f"{wf_result['benchmark_return']:+.2f}%")
                        wf_m4.metric("Alpha", f"{wf_result['alpha']:+.2f}%")
                        wf_m5.metric("交易次數", f"{wf_result['trade_count']} 次")

                        st.markdown("---")
                        wf_s1, wf_s2, wf_s3, wf_s4 = st.columns(4)
                        wf_s1.metric("勝率", f"{wf_result['win_rate']:.1f}%")
                        wf_s2.metric("Sharpe Ratio", f"{wf_result['sharpe']:.2f}")
                        wf_s3.metric("最大回撤", f"{wf_result['max_drawdown']:.2f}%", delta_color="inverse")

                        # ── 買賣點圖表 ──
                        if not wf_result['trades'].empty:
                            wf_trades = wf_result['trades']
                            wf_mask = (btc.index >= pd.Timestamp(wf_start)) & (btc.index <= pd.Timestamp(wf_end))
                            wf_sub = btc.loc[wf_mask]

                            fig_wf = go.Figure()
                            fig_wf.add_trace(go.Scatter(
                                x=wf_sub.index, y=wf_sub['close'],
                                mode='lines', name='BTC 價格',
                                line=dict(color='gray', width=1),
                            ))

                            # 繪製防守線
                            if wf_exit_ma in wf_sub.columns:
                                fig_wf.add_trace(go.Scatter(
                                    x=wf_sub.index, y=wf_sub[wf_exit_ma],
                                    mode='lines', name=f'{wf_exit_ma} (防守線)',
                                    line=dict(color='orange', width=1.5, dash='dash'),
                                ))

                            # 標記進場點
                            entry_dates = pd.to_datetime(wf_trades['entry_date'])
                            entry_prices = wf_trades['entry_price'].values
                            fig_wf.add_trace(go.Scatter(
                                x=entry_dates, y=entry_prices,
                                mode='markers+text', name='進場',
                                marker=dict(color='#00ff88', symbol='triangle-up', size=10),
                                text=[f"+{p:.0f}" for p in wf_trades['pnl_pct'].values],
                                textposition='top center',
                            ))

                            # 標記出場點
                            exit_dates = pd.to_datetime(wf_trades['exit_date'])
                            exit_prices = wf_trades['exit_price'].values
                            fig_wf.add_trace(go.Scatter(
                                x=exit_dates, y=exit_prices,
                                mode='markers', name='出場',
                                marker=dict(color='#ff4b4b', symbol='triangle-down', size=10),
                            ))

                            fig_wf.update_layout(
                                title=f"Walk-Forward 回測買賣點（{wf_start}～{wf_end}）",
                                height=500, template="plotly_dark",
                                hovermode='x unified',
                            )
                            st.plotly_chart(fig_wf, use_container_width=True)

                            # ── 交易明細表 ──
                            with st.expander("📋 詳細交易紀錄"):
                                st.dataframe(wf_trades, use_container_width=True)
                            st.download_button(
                                label="⬇️ 下載 Walk-Forward 交易紀錄 (.csv)",
                                data=_df_to_csv_bytes(wf_trades),
                                file_name=f"walkforward_trades_{wf_start}_{wf_end}.csv",
                                mime="text/csv", key="wf_download",
                            )
                        else:
                            st.warning("⚠️ 此期間無任何進場訊號。可嘗試放寬進場條件或延長回測區間。")

                        with st.expander("📖 Walk-Forward 邏輯說明"):
                            st.markdown(f"""
                            **核心設計（無先視偏誤）**：
                            - 每日逐一推進，該日只能看到該日及以前的資料
                            - 訊號在「前一日」收盤確認，「當日」開盤執行（shift(1) 防護）
                            - 進場掃描頻率：每 {wf_scan} 日掃描一次（降低計算成本）
                            - 持倉中每日檢查出場條件（多層次）

                            **進場條件（五合一）**：
                            1. 價格 > SMA200（年線多頭）
                            2. RSI14 > {wf_rsi}（動能）
                            3. {wf_dist:.1f}% ≤ EMA20 乖離 ≤ 1.5%（甜蜜點）
                            4. MACD > Signal（多頭交叉）
                            5. ADX > {wf_adx}（趨勢強度）

                            **六層出場機制（優先級）**：
                            ① Climax Exit：正乖離>30% 或爆量+長上影線（隔日強制）
                            ② ATR 停損：跌破進場 - {wf_atr_sl:.2f}×ATR
                            ③ ATR 目標：達到進場 + {wf_atr_tp:.2f}×ATR
                            ④ Chandelier：最高 - 2.0×ATR（追蹤止利）
                            ⑤ Time Stop：持倉≥15日 且 淨報酬<5%
                            ⑥ EMA 停損：跌破 {wf_exit_ma}

                            **交易成本**：
                            - 進場：費用 + 滑點 ≈ 0.15%
                            - 出場：費用 + 滑點 ≈ 0.15%
                            - 往返摩擦成本 ≈ 0.3%
                            """)
