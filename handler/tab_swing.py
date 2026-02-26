"""
handler/tab_swing.py
Tab 2: 波段狙擊 — Antigravity v4 核心策略引擎

視覺化增強（UI Improvement）:
- 頁面頂部加入 3 行式 Plotly 圖表：
    Row 1: K線 (90日) + EMA20 + Bollinger Bands + 進場甜蜜點高亮 + 動態防守線
    Row 2: RSI_14 + 超買/超賣線 + 50 中線
    Row 3: MACD 直方圖 + Signal Line (趨勢動能確認)
- [Task #7] Session State 快取：圖表按 (btc.index[-1], len(btc), exit_ma) hash 快取
"""
# 關閉 SSL 驗證警告，避免本地端公司網路環境報錯
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import hashlib
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np


def _make_swing_cache_key(btc: pd.DataFrame, exit_ma_key: str) -> str:
    """Tab 2 圖表快取鍵，基於 BTC 最後一筆時間戳、總長度與出場均線選擇"""
    last_idx = str(btc.index[-1]) if not btc.empty else "empty"
    raw = f"{last_idx}|{len(btc)}|{exit_ma_key}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _build_swing_chart(btc: pd.DataFrame, curr: pd.Series, exit_ma_key: str) -> go.Figure:
    """
    建立波段策略技術分析圖（3 行子圖）。
    僅在快取未命中時呼叫，耗時約 100-200ms。
    """
    df = btc.tail(90).copy()

    # 判斷進場甜蜜點（解除最大乖離限制，抓突破與趨勢確認）
    dist_pct = (df['close'] / df['EMA_20'] - 1) * 100
    macd_cond = (
        (df['MACD_12_26_9'] > df['MACDs_12_26_9']).fillna(False)
        if ('MACD_12_26_9' in df.columns and 'MACDs_12_26_9' in df.columns)
        else pd.Series(True, index=df.index)
    )
    adx_cond = (df['ADX'] > 20).fillna(False) if 'ADX' in df.columns else pd.Series(True, index=df.index)
    
    entry_zone = (
        (df['close'] > df['SMA_200']) &
        (df['RSI_14'] > 50) &
        (dist_pct >= 0) & 
        macd_cond & adx_cond
    )

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

    # EMA 20（核心均線，進場依據）
    fig.add_trace(go.Scatter(
        x=df.index, y=df['EMA_20'],
        line=dict(color='#ffeb3b', width=2), name='EMA 20 (進場線)',
    ), row=1, col=1)

    # 用戶自訂的波段防守線（出場依據）
    if exit_ma_key in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df[exit_ma_key],
            line=dict(color='#00e5ff', width=1.5, dash='dash'), name=f'{exit_ma_key} (防守線)',
        ), row=1, col=1)

    # SMA 200（趨勢濾網）
    fig.add_trace(go.Scatter(
        x=df.index, y=df['SMA_200'],
        line=dict(color='#ff9800', width=1.5, dash='dot'), name='SMA 200',
    ), row=1, col=1)

    # Bollinger Bands
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

    # 進場甜蜜點標記
    entry_pts = df[entry_zone]
    if not entry_pts.empty:
        fig.add_trace(go.Scatter(
            x=entry_pts.index, y=entry_pts['low'] * 0.997,
            mode='markers', name='甜蜜點 ✅',
            marker=dict(color='#00e5ff', symbol='triangle-up', size=12, opacity=0.85),
        ), row=1, col=1)

    # 動態跌破防守線出場標記 (優化：放大標籤、改亮紅色、加白邊)
    if exit_ma_key in df.columns:
        below_ma = df[df['close'] < df[exit_ma_key]]
        if not below_ma.empty:
            exit_mask = below_ma.index.isin(
                below_ma.index[np.diff(np.where(df['close'] < df[exit_ma_key])[0], prepend=-2) > 1]
            )
            exit_pts = below_ma[exit_mask]
            if not exit_pts.empty:
                fig.add_trace(go.Scatter(
                    x=exit_pts.index, y=exit_pts['high'] * 1.01, # 稍微調高避免被K線遮擋
                    mode='markers', name=f'出場信號 🔴 (破 {exit_ma_key})',
                    marker=dict(
                        color='#ff1744',       # 極度亮眼的螢光紅
                        symbol='triangle-down', 
                        size=18,               # 放大標記尺寸
                        opacity=1.0,           # 取消半透明，100% 實心
                        line=dict(color='white', width=2) # 加上明顯白邊增加對比
                    ),
                ), row=1, col=1)

    # ── Row 2: RSI_14 ──
    if 'RSI_14' in df.columns:
        rsi_colors = [
            '#ff4b4b' if v > 70 else ('#00ff88' if v < 30 else '#64b5f6')
            for v in df['RSI_14'].fillna(50)
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df['RSI_14'],
            marker_color=rsi_colors, name='RSI_14', showlegend=False,
        ), row=2, col=1)
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


def render(btc, curr, funding_rate, proxies,
           capital=None, risk_per_trade=None,
           open_interest=None, open_interest_usd=None, oi_change_pct=None):
    """
    波段狙擊 Tab 渲染入口
    """
    st.markdown("### 🌊 Antigravity v4 核心策略引擎")

    # 讓使用者設定出場條件
    st.markdown("##### 🛡️ 防守策略設定")
    exit_ma_key = st.selectbox(
        "選擇波段防守線 (出場條件)",
        options=["SMA_50", "EMA_20", "SMA_200"],
        index=0,
        help="選擇做為出場防守的均線。當價格跌破此均線即觸發賣出。"
    )

    # ──────────────────────────────────────────────────────────────
    # [Task #7] 主技術圖表（Session State 快取）
    # ──────────────────────────────────────────────────────────────
    cache_key    = _make_swing_cache_key(btc, exit_ma_key)
    ss_hash_key  = "tab_swing_cache_key"
    ss_chart_key = f"tab_swing_fig_{cache_key}"

    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_chart_key in st.session_state):
        fig_main = st.session_state[ss_chart_key]
    else:
        fig_main = _build_swing_chart(btc, curr, exit_ma_key)
        st.session_state[ss_chart_key] = fig_main
        st.session_state[ss_hash_key]  = cache_key

    st.plotly_chart(fig_main, width='stretch')

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # A. 策略條件監控 (儀表板美化版：2列 x 3欄)
    # ──────────────────────────────────────────────────────────────
    st.subheader("A. 策略條件監控 (進出場邏輯)")

    # 條件計算
    bull_ma        = curr['close'] > curr['SMA_200']
    bull_rsi       = curr.get('RSI_14', 50) > 50
    not_overheated = funding_rate < 0.05

    macd_val   = curr.get('MACD_12_26_9') or curr.get('MACD', 0)
    macd_sig   = curr.get('MACDs_12_26_9') or curr.get('MACD_Signal', 0)
    bull_macd  = (macd_val is not None and macd_sig is not None
                  and macd_val == macd_val and macd_sig == macd_sig
                  and float(macd_val) > float(macd_sig))

    adx_val      = curr.get('ADX', 0) or 0
    adx_trending = float(adx_val) > 20
    above_ema20  = curr['close'] >= curr['EMA_20']

    st.markdown("#### 🟢 進場條件 (以下 6 項全數通過即觸發買進)")
    
    # 將進場條件改為 2 列 x 3 欄的 metric 儀表板設計，漂亮且易讀
    r1c1, r1c2, r1c3 = st.columns(3)
    r2c1, r2c2, r2c3 = st.columns(3)

    r1c1.metric("① 趨勢向上 (Price > MA200)", "✅ 通過" if bull_ma else "❌ 未通過")
    r1c2.metric("② 動能偏多 (RSI_14 > 50)", "✅ 通過" if bull_rsi else "❌ 未通過")
    r1c3.metric("③ MACD金叉 (> Signal)", "✅ 通過" if bull_macd else "❌ 未通過")
    
    r2c1.metric("④ 趨勢成型 (ADX > 20)", f"✅ 通過 ({adx_val:.1f})" if adx_trending else f"❌ 盤整 ({adx_val:.1f})")
    r2c2.metric("⑤ 資金健康 (費率 < 0.05%)", "✅ 通過" if not_overheated else "⚠️ 過熱")
    r2c3.metric("⑥ 站上短均 (Price ≥ EMA20)", "✅ 通過" if above_ema20 else "❌ 未達標")

    can_long = bull_ma and bull_rsi and bull_macd and adx_trending and not_overheated and above_ema20

    st.markdown("#### 🔴 出場條件")
    is_exit = curr['close'] < curr.get(exit_ma_key, curr['close'])
    e_col1, e_col2, e_col3 = st.columns(3)
    e_col1.metric(f"① 跌破防守線 (Price < {exit_ma_key})", "🔴 觸發出場" if is_exit else "✅ 安全 (未跌破)")

    # ── 未平倉量 (Open Interest) 顯示區塊 ──
    if open_interest is not None:
        st.markdown("##### 📊 BTC 永續合約未平倉量 (Open Interest)")
        oi_col1, oi_col2, oi_col3 = st.columns(3)

        oi_col1.metric("未平倉量 (OI)", f"{open_interest:,.0f} BTC")
        if open_interest_usd is not None:
            oi_col2.metric("OI 市值", f"${open_interest_usd:.2f} 億")

        if oi_change_pct is not None:
            oi_trend = "建倉增加 ↑" if oi_change_pct > 0.5 else ("平倉減少 ↓" if oi_change_pct < -0.5 else "橫盤震盪 →")
            oi_col3.metric(
                label="OI 60s 變化",
                value=f"{oi_change_pct:+.3f}%",
                delta=oi_trend,
                delta_color="normal" if oi_change_pct >= 0 else "inverse",
            )
        else:
            oi_col3.metric("OI 60s 變化", "等待下次刷新")

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # B & C: 智能進出場 + 動態止損
    # ──────────────────────────────────────────────────────────────
    logic_col1, logic_col2 = st.columns(2)
    ema_20       = curr['EMA_20']
    stop_price   = curr.get(exit_ma_key, curr['close'])  # 動態防守線
    dist_pct     = (curr['close'] / ema_20 - 1) * 100
    atr_val      = curr['ATR']
    risk_dist_pct = (curr['close'] - stop_price) / curr['close']

    with logic_col1:
        st.subheader("B. 智能進出場 (Entries & Exits)")
        cex_flow = proxies['cex_flow']
        st.metric(
            "CEX 資金流向 (24h Proxy)", f"{cex_flow:+.0f} BTC",
            "交易所淨流出 (吸籌)" if cex_flow < 0 else "交易所淨流入 (拋壓)",
            delta_color="normal" if cex_flow < 0 else "inverse",
        )
        
        m_col1, m_col2 = st.columns(2)
        m_col1.metric("EMA 20 (進場線)", f"${ema_20:,.0f}", f"乖離率 {dist_pct:.2f}%")
        m_col2.metric(f"{exit_ma_key} (防守線)", f"${stop_price:,.0f}")

        if is_exit:
            st.error(f"🔴 **賣出訊號 (SELL)**\n\n跌破波段防守線 ({exit_ma_key})，趨勢轉弱。")
            st.metric("建議回補價", f"${curr['BB_Lower']:,.0f}", "布林下軌支撐")
        elif can_long:
            st.success("🟢 **買進訊號 (BUY)**\n\n進場條件全數通過，多頭動能確認！")
            st.metric("建議止盈價", f"${curr['BB_Upper']:,.0f}", "布林上軌壓力")
        else:
            st.info("🔵 **持倉續抱 / 觀望 (HOLD / WAIT)**\n\n等待明確進出場信號。")
            st.metric("波段防守價", f"${stop_price:,.0f}", f"{exit_ma_key}")

    with logic_col2:
        st.subheader("C. 動態止損 & 清算地圖")
        st.caption("🔥 鏈上清算熱區 (Liquidation Clusters)")
        for heat in proxies['liq_map']:
            st.markdown(f"- **${heat['price']:,.0f}** ({heat['side']} {heat['vol']})")

        st.metric(
            f"建議防守價 ({exit_ma_key})", f"${stop_price:,.0f}",
            f"預計虧損幅度 -{risk_dist_pct * 100:.2f}%",
        )
        if risk_dist_pct < 0:
            st.error("⚠️ 當前價格已低於建議止損價！")

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

    d_cap_col, d_risk_col = st.columns(2)
    with d_cap_col:
        capital = st.number_input(
            "總本金 (USDT)", value=int(capital) if capital else 10_000, step=1_000,
        )
    with d_risk_col:
        risk_per_trade = st.number_input(
            "單筆風險 (%)", value=float(risk_per_trade) if risk_per_trade else 2.0,
            step=0.1, max_value=10.0,
        )

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