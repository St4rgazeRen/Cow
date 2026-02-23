"""
handler/tab_dual_invest.py
Tab 3: 雙幣理財顧問

視覺化增強（UI Improvement）:
- 頁面頂部加入「行權價梯形圖」：
    以 K 線 (近 60 日) 為背景，
    在圖上疊加 SELL_HIGH 行權梯（紅色水平線）與 BUY_LOW 梯（綠色水平線），
    並以 ATR Band 顯示隱含波動範圍，幫助直觀判斷各檔位合理性
- 右側新增「APY 機會成本雷達圖」：比較各檔 APY vs DeFi 活存利率
- [Task #7] 梯形圖按 (btc.index[-1], t_days) hash 快取，切換期限才重建
"""
import hashlib
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np

from strategy.dual_invest import get_current_suggestion, calculate_ladder_strategy


def _make_dual_cache_key(btc: pd.DataFrame, t_days: int) -> str:
    """Tab 3 快取鍵：數據最後時間戳 + 產品期限"""
    last_idx = str(btc.index[-1]) if not btc.empty else "empty"
    raw = f"{last_idx}|{len(btc)}|t{t_days}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def _build_ladder_chart(btc: pd.DataFrame, suggestion: dict,
                        curr_row: pd.Series, t_days: int,
                        defi_yield: float) -> go.Figure:
    """
    建立行權價梯形視覺化圖（2 行子圖）。
    Row 1 (主圖): K線 (近 60 日) + EMA20 + ATR Band + 行權梯
    Row 2 (輔助): 各檔 APY 橫向對比長條圖
    """
    df60 = btc.tail(60).copy()
    price = curr_row['close']
    atr   = curr_row['ATR']

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=False,
        vertical_spacing=0.12,
        row_heights=[0.65, 0.35],
        subplot_titles=(
            f"行權價梯形圖 (近 60 日 K 線 | 產品期限 {t_days} 天)",
            "各檔 APY 對比 (vs DeFi 活存機會成本)",
        ),
    )

    # ── Row 1: K 線 + 技術指標 + 行權梯 ──

    # K 線
    fig.add_trace(go.Candlestick(
        x=df60.index,
        open=df60['open'], high=df60['high'],
        low=df60['low'],  close=df60['close'],
        name='BTC/USDT',
        increasing_line_color='#26a69a',
        decreasing_line_color='#ef5350',
        showlegend=False,
    ), row=1, col=1)

    # EMA 20
    if 'EMA_20' in df60.columns:
        fig.add_trace(go.Scatter(
            x=df60.index, y=df60['EMA_20'],
            line=dict(color='#ffeb3b', width=1.5), name='EMA 20',
        ), row=1, col=1)

    # ATR Band（隱含 1-σ 波動帶）
    fig.add_trace(go.Scatter(
        x=df60.index, y=df60['close'] + df60['ATR'] * t_days ** 0.5,
        line=dict(color='rgba(163,46,255,0.5)', width=1, dash='dot'), name=f'+ATR√{t_days}d',
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df60.index, y=df60['close'] - df60['ATR'] * t_days ** 0.5,
        line=dict(color='rgba(163,46,255,0.5)', width=1, dash='dot'), name=f'-ATR√{t_days}d',
        fill='tonexty', fillcolor='rgba(163,46,255,0.05)',
    ), row=1, col=1)

    # 現價基準線
    fig.add_hline(
        y=price, line_color='#ffffff', line_width=1.5,
        annotation_text=f"現價 ${price:,.0f}", annotation_position="right",
        row=1, col=1,
    )

    # SELL_HIGH 行權梯（紅色系）
    sell_colors = ['#ff6b6b', '#ff4b4b', '#cc0000']
    if suggestion and suggestion.get('sell_ladder'):
        for i, tier in enumerate(suggestion['sell_ladder']):
            strike = tier['Strike']
            fig.add_hline(
                y=strike, line_color=sell_colors[i], line_width=1.5, line_dash='dash',
                annotation_text=f"賣高-{tier['Type']} ${strike:,.0f} ({tier['APY(年化)']})",
                annotation_position="right",
                row=1, col=1,
            )

    # BUY_LOW 行權梯（綠色系）
    buy_colors = ['#69f0ae', '#00e676', '#009624']
    if suggestion and suggestion.get('buy_ladder'):
        for i, tier in enumerate(suggestion['buy_ladder']):
            strike = tier['Strike']
            fig.add_hline(
                y=strike, line_color=buy_colors[i], line_width=1.5, line_dash='dash',
                annotation_text=f"買低-{tier['Type']} ${strike:,.0f} ({tier['APY(年化)']})",
                annotation_position="right",
                row=1, col=1,
            )

    # ── Row 2: APY 橫向長條對比 ──
    apy_labels, apy_values, apy_colors_bar = [], [], []

    # DeFi 活存基準線
    apy_labels.append(f"DeFi 活存 (基準)")
    apy_values.append(defi_yield)
    apy_colors_bar.append('#64b5f6')

    # SELL_HIGH 各檔
    if suggestion and suggestion.get('sell_ladder'):
        for tier in suggestion['sell_ladder']:
            apy_labels.append(f"賣高-{tier['Type']}")
            try:
                apy_values.append(float(tier['APY(年化)'].rstrip('%')))
            except Exception:
                apy_values.append(0.0)
            apy_colors_bar.append('#ff6b6b')

    # BUY_LOW 各檔
    if suggestion and suggestion.get('buy_ladder'):
        for tier in suggestion['buy_ladder']:
            apy_labels.append(f"買低-{tier['Type']}")
            try:
                apy_values.append(float(tier['APY(年化)'].rstrip('%')))
            except Exception:
                apy_values.append(0.0)
            apy_colors_bar.append('#69f0ae')

    if apy_labels:
        fig.add_trace(go.Bar(
            x=apy_labels, y=apy_values,
            marker_color=apy_colors_bar, name='APY %',
            text=[f"{v:.1f}%" for v in apy_values], textposition='outside',
            showlegend=False,
        ), row=2, col=1)
        # DeFi 活存基準虛線
        fig.add_hline(y=defi_yield, line_color='#64b5f6', line_dash='dash',
                      annotation_text=f"機會成本 {defi_yield:.1f}%", row=2, col=1)

    fig.update_layout(
        height=700, template="plotly_dark",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        margin=dict(t=50, b=10),
    )
    return fig


def render(btc, realtime_data):
    st.markdown("### 💰 雙幣理財顧問 (Dual Investment)")

    defi_yield = realtime_data.get('defi_yield') or 5.0

    # ── 產品期限選擇 ──
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
    curr_row   = btc.iloc[-1]

    # ──────────────────────────────────────────────────────────────
    # [Task #7] 行權梯形圖（Session State 快取）
    # 切換期限 (t_days) 時 cache_key 改變 → 重新計算
    # ──────────────────────────────────────────────────────────────
    cache_key    = _make_dual_cache_key(btc, t_days)
    ss_hash_key  = "tab_dual_cache_key"
    ss_chart_key = f"tab_dual_fig_{cache_key}"

    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_chart_key in st.session_state):
        fig_ladder = st.session_state[ss_chart_key]
    else:
        fig_ladder = _build_ladder_chart(btc, suggestion, curr_row, t_days, defi_yield)
        st.session_state[ss_chart_key] = fig_ladder
        st.session_state[ss_hash_key]  = cache_key

    st.plotly_chart(fig_ladder, width='stretch')

    st.markdown("---")

    # ── 核心訊號 + 梯形掛單建議 ──
    if suggestion:
        s_col1, s_col2 = st.columns([1, 2])

        with s_col1:
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
                    df_sell['Strike']   = df_sell['Strike'].apply(lambda x: f"${x:,.0f}")
                    df_sell['Distance'] = df_sell['Distance'].apply(lambda x: f"+{x:.2f}%")
                    st.table(df_sell[['Type', 'Strike', 'Weight', 'Distance', 'APY(年化)']])
                else:
                    st.info("暫無建議 (可能是週末或數據不足)")

            with t2:
                if suggestion['buy_ladder']:
                    df_buy = pd.DataFrame(suggestion['buy_ladder'])
                    df_buy['Strike']   = df_buy['Strike'].apply(lambda x: f"${x:,.0f}")
                    df_buy['Distance'] = df_buy['Distance'].apply(lambda x: f"{x:.2f}%")
                    st.table(df_buy[['Type', 'Strike', 'Weight', 'Distance', 'APY(年化)']])
                else:
                    st.warning("⚠️ 趨勢偏空或濾網觸發，不建議 Buy Low (接刀)")
