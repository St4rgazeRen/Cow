"""
handler/tab_swing.py
Tab 2: 波段狙擊 — Antigravity v4 核心策略引擎

視覺化增強（UI Improvement）:
- 頁面頂部加入 3 行式 Plotly 圖表：
    Row 1: K線 (90日) + EMA20 + Bollinger Bands + 進場甜蜜點高亮
    Row 2: RSI_14 + 超買/超賣線 + 50 中線
    Row 3: MACD 直方圖 + Signal Line (趨勢動能確認)
- [Task #7] Session State 快取：圖表按 (btc.index[-1], len(btc)) hash 快取，
  側邊欄互動不觸發重建
"""
import hashlib
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


def _make_swing_cache_key(btc: pd.DataFrame) -> str:
    """Tab 2 圖表快取鍵，基於 BTC 最後一筆時間戳與總長度"""
    last_idx = str(btc.index[-1]) if not btc.empty else "empty"
    raw = f"{last_idx}|{len(btc)}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _build_swing_chart(btc: pd.DataFrame, curr: pd.Series) -> go.Figure:
    """
    建立波段策略技術分析圖（3 行子圖）。
    僅在快取未命中時呼叫，耗時約 100-200ms。

    Row 1: K線 (近 90 日) + EMA20 + BB 帶 + 進場區高亮
    Row 2: RSI_14 + 超買 (70) / 超賣 (30) / 中線 (50)
    Row 3: MACD 直方圖 + Signal Line
    """
    # 取最近 90 天數據，圖表不宜過長
    df = btc.tail(90).copy()

    # 判斷進場甜蜜點：0% ≤ dist_from_EMA20 ≤ 1.5% 且趨勢多頭
    dist_pct = (df['close'] / df['EMA_20'] - 1) * 100
    entry_zone = (df['close'] > df['SMA_200']) & (df['RSI_14'] > 50) & (dist_pct >= 0) & (dist_pct <= 1.5)

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=(
            "近 90 日走勢 + Antigravity v4 進場帶 (EMA20 ± Bollinger)",
            "RSI_14 動能指標",
            "MACD 動能確認",
        ),
    )

    # ── Row 1: K 線 + 均線 + BB ──
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df['open'], high=df['high'],
        low=df['low'], close=df['close'],
        name='BTC/USDT',
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350',
    ), row=1, col=1)

    # EMA 20（核心均線，進出場依據）
    fig.add_trace(go.Scatter(
        x=df.index, y=df['EMA_20'],
        line=dict(color='#ffeb3b', width=2), name='EMA 20',
    ), row=1, col=1)

    # SMA 200（趨勢濾網）
    fig.add_trace(go.Scatter(
        x=df.index, y=df['SMA_200'],
        line=dict(color='#ff9800', width=1.5, dash='dot'), name='SMA 200',
    ), row=1, col=1)

    # Bollinger Bands（進出場目標區）
    if 'BB_Upper' in df.columns and 'BB_Lower' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df['BB_Upper'],
            line=dict(color='rgba(0,230,118,0.5)', width=1), name='BB 上軌',
            showlegend=True,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['BB_Lower'],
            line=dict(color='rgba(0,230,118,0.5)', width=1), name='BB 下軌',
            fill='tonexty', fillcolor='rgba(0,230,118,0.04)',
            showlegend=True,
        ), row=1, col=1)

    # 進場甜蜜點標記（青色三角）
    entry_pts = df[entry_zone]
    if not entry_pts.empty:
        fig.add_trace(go.Scatter(
            x=entry_pts.index, y=entry_pts['low'] * 0.997,
            mode='markers', name='甜蜜點 ✅',
            marker=dict(color='#00e5ff', symbol='triangle-up', size=12, opacity=0.85),
        ), row=1, col=1)

    # 跌破 EMA20 出場標記（紅色三角向下）
    below_ema = df[df['close'] < df['EMA_20']]
    if not below_ema.empty:
        # 只標記連續跌破的首日（避免密集標記）
        exit_mask = below_ema.index.isin(
            below_ema.index[np.diff(np.where(df['close'] < df['EMA_20'])[0], prepend=-2) > 1]
        )
        exit_pts = below_ema[exit_mask]
        if not exit_pts.empty:
            fig.add_trace(go.Scatter(
                x=exit_pts.index, y=exit_pts['high'] * 1.003,
                mode='markers', name='出場信號 🔴',
                marker=dict(color='#ff4b4b', symbol='triangle-down', size=10, opacity=0.8),
            ), row=1, col=1)

    # ── Row 2: RSI_14 ──
    if 'RSI_14' in df.columns:
        # RSI 顏色：超買紅、超賣綠、中性藍
        rsi_colors = [
            '#ff4b4b' if v > 70 else ('#00ff88' if v < 30 else '#64b5f6')
            for v in df['RSI_14'].fillna(50)
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df['RSI_14'],
            marker_color=rsi_colors, name='RSI_14', showlegend=False,
        ), row=2, col=1)
        # 超買 / 超賣 / 中線
        for lvl, col, label in [(70, '#ff4b4b', '超買 70'), (50, '#aaaaaa', '中線 50'), (30, '#00ff88', '超賣 30')]:
            fig.add_hline(y=lvl, line_color=col, line_width=1,
                          line_dash='dash', annotation_text=label, row=2, col=1)

    # ── Row 3: MACD ──
    if 'MACD_12_26_9' in df.columns and 'MACDh_12_26_9' in df.columns:
        hist_col = ['#26a69a' if v >= 0 else '#ef5350'
                    for v in df['MACDh_12_26_9'].fillna(0)]
        fig.add_trace(go.Bar(
            x=df.index, y=df['MACDh_12_26_9'],
            marker_color=hist_col, name='MACD Hist', showlegend=False,
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['MACD_12_26_9'],
            line=dict(color='#64b5f6', width=1.5), name='MACD', showlegend=False,
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df['MACDs_12_26_9'],
            line=dict(color='#ff9800', width=1.5), name='Signal', showlegend=False,
        ), row=3, col=1)
        fig.add_hline(y=0, line_color='white', line_width=0.5, opacity=0.4, row=3, col=1)

    fig.update_layout(
        height=700, template="plotly_dark",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(t=40, b=10),
    )
    return fig


def render(btc, curr, funding_rate, proxies, capital, risk_per_trade):
    st.markdown("### 🌊 Antigravity v4 核心策略引擎")

    # ──────────────────────────────────────────────────────────────
    # [Task #7] 主技術圖表（Session State 快取）
    # ──────────────────────────────────────────────────────────────
    cache_key    = _make_swing_cache_key(btc)
    ss_hash_key  = "tab_swing_cache_key"
    ss_chart_key = f"tab_swing_fig_{cache_key}"

    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_chart_key in st.session_state):
        fig_main = st.session_state[ss_chart_key]
    else:
        fig_main = _build_swing_chart(btc, curr)
        st.session_state[ss_chart_key] = fig_main
        st.session_state[ss_hash_key]  = cache_key

    st.plotly_chart(fig_main, use_container_width=True)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # A. 趨勢濾網 (Trend Filter)
    # ──────────────────────────────────────────────────────────────
    st.subheader("A. 趨勢濾網 (Trend Filter)")
    f_col1, f_col2, f_col3 = st.columns(3)

    bull_ma        = curr['close'] > curr['SMA_200']
    bull_rsi       = curr.get('RSI_Weekly', 50) > 50
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

    # ──────────────────────────────────────────────────────────────
    # B & C: 智能進出場 + 動態止損
    # ──────────────────────────────────────────────────────────────
    logic_col1, logic_col2 = st.columns(2)
    ema_20       = curr['EMA_20']
    dist_pct     = (curr['close'] / ema_20 - 1) * 100
    atr_val      = curr['ATR']
    stop_price   = ema_20 - (2.0 * atr_val)
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

        # 額外技術指標概覽
        st.markdown("#### 技術指標速覽")
        i1, i2 = st.columns(2)
        i1.metric("RSI_14", f"{curr.get('RSI_14', 0):.1f}",
                  "超買" if curr.get('RSI_14', 50) > 70 else ("超賣" if curr.get('RSI_14', 50) < 30 else "中性"))
        i2.metric("ATR", f"${atr_val:,.0f}", f"{atr_val/curr['close']*100:.2f}% 波動")
        if 'ADX' in curr:
            i1.metric("ADX", f"{curr['ADX']:.1f}", "強趨勢" if curr['ADX'] > 25 else "盤整")
        if 'J' in curr:
            i2.metric("KDJ(J)", f"{curr['J']:.1f}",
                      "超買" if curr['J'] > 80 else ("超賣" if curr['J'] < 20 else "中性"))

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # D. 倉位計算機 (Risk Calculator)
    # ──────────────────────────────────────────────────────────────
    st.subheader("D. 倉位計算機 (Risk Calculator)")
    entry_price  = st.number_input("預計進場價格 (預設現價)", value=float(curr['close']))
    manual_stop  = st.number_input("止損價格 (預設系統建議)", value=float(stop_price))

    if st.button("計算建議倉位"):
        if entry_price <= manual_stop:
            st.error("❌ 進場價必須高於止損價")
        else:
            risk_amt       = capital * (risk_per_trade / 100)
            stop_dist_usd  = entry_price - manual_stop
            pos_size_btc   = risk_amt / stop_dist_usd
            pos_size_usdt  = pos_size_btc * entry_price
            leverage       = pos_size_usdt / capital

            st.markdown(f"""
            #### 🧮 計算結果
            - **風險金額**: `${risk_amt:.2f}` ({risk_per_trade}%)
            - **止損距離**: `${stop_dist_usd:.2f}` ({(stop_dist_usd / entry_price) * 100:.2f}%)
            """)

            res_col1, res_col2 = st.columns(2)
            if leverage > 1.5:
                res_col1.warning(f"⚠️ 原始計算槓桿: {leverage:.2f}x (超過 1.5x 上限)")
                capped_usdt = capital * 1.5
                capped_btc  = capped_usdt / entry_price
                new_risk    = ((capped_btc * stop_dist_usd) / capital) * 100
                res_col1.metric("建議開倉 (經風控)", f"{capped_btc:.4f} BTC", f"總值 ${capped_usdt:,.0f}")
                res_col2.metric("實際風險", f"{new_risk:.2f}%", f"原本 {risk_per_trade}%")
            else:
                res_col1.metric("建議開倉", f"{pos_size_btc:.4f} BTC", f"總值 ${pos_size_usdt:,.0f}")
                res_col2.metric("槓桿倍數", f"{leverage:.2f}x", "安全範圍")
