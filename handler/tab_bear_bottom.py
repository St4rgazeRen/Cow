"""
handler/tab_bear_bottom.py
Tab 5: 熊市底部獵人 (Bear Bottom Hunter)

[Task #7] Session State 圖表快取:
tab_bear_bottom 有兩個特別昂貴的操作：
  1. fig_hist: 3 行子圖，包含 SMA_1400/SMA_350x2/SMA_111/PowerLaw 等多條長期均線
  2. fig_score: 需先執行 score_series(btc.tail(1460)) 計算 4 年底部評分序列，
     再建立 2 行子圖。

快取策略（與 tab_bull_radar 一致）:
  - cache_key = MD5(btc.index[-1] + len(btc))[:16]
  - 側邊欄參數改變時 btc 不變 → key 不變 → 直接複用圖表物件 (< 5ms)
  - 只有 BTC 日線更新（新的一天）時才重建圖表 (200-400ms)

[新增] 四季理論目標價預測 (Section F):
  - 依減半週期判斷當前季節
  - 牛季 → 預測未來12個月最高價
  - 熊季 → 預測未來12個月最低價
  - 含歷史週期比較表 + 冪律走廊圖
"""
import hashlib
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime

from core.bear_bottom import calculate_bear_bottom_score, score_series
from core.season_forecast import (
    forecast_price,
    get_cycle_comparison_table,
    get_power_law_forecast,
    get_current_season,
    HALVING_DATES,
    CYCLE_HISTORY,
)


def _make_bb_cache_key(btc: pd.DataFrame) -> str:
    """
    根據 BTC DataFrame 的最後一筆時間戳與總資料長度生成快取鍵。
    [Task #7] 使用 MD5 hash 避免大型 DataFrame == 比較的效能損耗。
    """
    last_idx = str(btc.index[-1]) if not btc.empty else "empty"
    raw = f"{last_idx}|{len(btc)}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


# 歷史已知熊市底部區間（用於圖表標註橙色區域）
KNOWN_BOTTOMS = [
    ("2015-08-01", "2015-09-30", "2015 Bear Bottom"),
    ("2018-11-01", "2019-02-28", "2018-19 Bear Bottom"),
    ("2020-03-01", "2020-04-30", "2020 COVID Crash"),
    ("2022-11-01", "2023-01-31", "2022 FTX Bear Bottom"),
]


def _score_to_meta(score):
    """將評分轉換為等級標籤、顏色與操作建議"""
    if score >= 75:
        return "🔴 歷史極值底部", "#ff4444", "All-In 信號！歷史上極為罕見的買入機會，建議全力積累。"
    elif score >= 60:
        return "🟠 明確底部區間", "#ff8800", "積極積累區。多項指標共振確認底部，建議重倉布局。"
    elif score >= 45:
        return "🟡 可能底部區", "#ffcc00", "謹慎試探。部分指標出現底部信號，建議小倉試探，分批建倉。"
    elif score >= 25:
        return "⚪ 震盪修正區", "#aaaaaa", "觀望為主。市場處於修正階段，尚未出現明確底部信號。"
    else:
        return "🟢 牛市/高估區", "#00ff88", "非底部時機。當前估值偏高，持有或減倉，等待下一個熊市底部。"


# ══════════════════════════════════════════════════════════════════
# Section F 輔助函數
# ══════════════════════════════════════════════════════════════════

def _season_css_color(season: str) -> str:
    return {
        "spring": "#00e676",
        "summer": "#ffeb3b",
        "autumn": "#ff9800",
        "winter": "#42a5f5",
    }.get(season, "#ffffff")


def _render_season_timeline(season_info: dict):
    """
    用 Plotly 繪製週期進度條（四季色塊 + 當前位置指針）
    """
    fig = go.Figure()

    # 四季色塊
    season_colors = ["#1b5e20", "#f9a825", "#e65100", "#0d47a1"]
    season_labels = ["🌱 春 (月0-11)", "☀️ 夏 (月12-23)", "🍂 秋 (月24-35)", "❄️ 冬 (月36-47)"]
    for i, (col, lab) in enumerate(zip(season_colors, season_labels)):
        fig.add_shape(
            type="rect",
            x0=i * 12, x1=(i + 1) * 12,
            y0=0, y1=1,
            fillcolor=col, opacity=0.4, layer="below", line_width=0,
        )
        fig.add_annotation(
            x=i * 12 + 6, y=0.5,
            text=lab, showarrow=False,
            font=dict(size=11, color="white"),
        )

    # 當前位置指針
    m = season_info["month_in_cycle"]
    fig.add_shape(
        type="line",
        x0=m, x1=m, y0=0, y1=1,
        line=dict(color="#ffffff", width=3),
    )
    fig.add_annotation(
        x=m, y=1.05,
        text=f"現在 (月{m})",
        showarrow=False,
        font=dict(size=12, color="white", family="bold"),
    )

    fig.update_layout(
        height=120,
        margin=dict(l=10, r=10, t=30, b=10),
        template="plotly_dark",
        xaxis=dict(range=[0, 48], showticklabels=False, showgrid=False, zeroline=False),
        yaxis=dict(range=[0, 1.2], showticklabels=False, showgrid=False, zeroline=False),
        paper_bgcolor="#0e1117",
        plot_bgcolor="#0e1117",
    )
    return fig


def _render_forecast_chart(btc: pd.DataFrame, fc: dict):
    """
    繪製目標價預測圖：
    - 過去 2 年 BTC 收盤價
    - 目標價區間（ribbon）+ 中位數線
    - 冪律走廊（未來12個月）
    - 預計達標日期標記
    """
    hist_2y = btc.tail(365 * 2)
    future_pl = get_power_law_forecast(btc, months_ahead=12)

    is_bull = fc["forecast_type"] == "bull_peak"
    ribbon_color = "rgba(255,235,59,0.18)" if is_bull else "rgba(66,165,245,0.18)"
    median_color = "#ffeb3b" if is_bull else "#42a5f5"

    fig = go.Figure()

    # 冪律走廊（未來，背景）
    fig.add_trace(go.Scatter(
        x=list(future_pl.index) + list(future_pl.index[::-1]),
        y=list(future_pl["upper"]) + list(future_pl["lower"][::-1]),
        fill="toself",
        fillcolor="rgba(255,204,0,0.07)",
        line=dict(color="rgba(0,0,0,0)"),
        name="冪律走廊",
        showlegend=True,
    ))
    fig.add_trace(go.Scatter(
        x=future_pl.index, y=future_pl["median"],
        mode="lines",
        line=dict(color="#ffcc00", width=1, dash="dot"),
        name="冪律中線",
    ))

    # 歷史收盤價
    fig.add_trace(go.Scatter(
        x=hist_2y.index, y=hist_2y["close"],
        mode="lines", name="BTC 歷史收盤",
        line=dict(color="#ffffff", width=2),
    ))

    # 目標價區間 ribbon（從今天延伸到預計達標日）
    est_date = fc["estimated_date"]
    today = datetime.utcnow()
    ribbon_x = [today, est_date, est_date, today]
    ribbon_y_high = [fc["target_high"]] * 2 + [fc["target_low"]] * 2

    fig.add_trace(go.Scatter(
        x=ribbon_x + [today],
        y=ribbon_y_high + [fc["target_high"]],
        fill="toself",
        fillcolor=ribbon_color,
        line=dict(color="rgba(0,0,0,0)"),
        name="目標價區間",
        showlegend=True,
    ))

    # 中位數目標線
    fig.add_shape(
        type="line",
        x0=str(today.date()), x1=str(est_date.date()),
        y0=fc["target_median"], y1=fc["target_median"],
        line=dict(color=median_color, width=2.5, dash="dash"),
    )

    # 目標價標註
    label = "🎯 牛市目標高點" if is_bull else "🎯 熊市目標低點"
    fig.add_annotation(
        x=est_date, y=fc["target_median"],
        text=f"{label}<br>${fc['target_median']:,.0f}",
        showarrow=True, arrowhead=2,
        font=dict(color=median_color, size=12),
        bgcolor="#1e1e1e", bordercolor=median_color, borderwidth=1,
    )

    # 上下界標線
    for val, clr, lbl in [
        (fc["target_high"], "#ff9800", "樂觀目標"),
        (fc["target_low"],  "#78909c", "保守目標"),
    ]:
        fig.add_shape(
            type="line",
            x0=str(today.date()), x1=str(est_date.date()),
            y0=val, y1=val,
            line=dict(color=clr, width=1.2, dash="dot"),
        )
        fig.add_annotation(
            x=est_date, y=val,
            text=f"{lbl}: ${val:,.0f}",
            showarrow=False, xanchor="left",
            font=dict(color=clr, size=10),
        )

    # 今日垂直線
    fig.add_vline(
        x=str(today.date()),
        line=dict(color="#888888", width=1, dash="dash"),
        annotation_text="今日",
        annotation_font_color="#888888",
    )

    fig.update_layout(
        height=500,
        template="plotly_dark",
        yaxis_type="log",
        title=dict(
            text=f"{'📈 牛市最高價' if is_bull else '📉 熊市最低價'} 預測 — 未來 12 個月",
            font=dict(size=16),
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        paper_bgcolor="#0e1117",
    )
    return fig


def _render_cycle_waterfall(fc: dict):
    """
    瀑布圖：展示各週期牛市倍數遞減趨勢，並標出當前週期預測值。
    """
    labels = [f"第{i+1}週期\n({c['halving'].year})" for i, c in enumerate(CYCLE_HISTORY)]
    values = [c["peak_mult"] for c in CYCLE_HISTORY]

    # 加上當前預測
    from core.season_forecast import _apply_diminishing_returns, STATS
    curr_idx = fc["current_cycle_idx"]
    pred_mult = _apply_diminishing_returns(STATS["peak_mult_median"], curr_idx)
    labels.append(f"第{curr_idx+1}週期\n({HALVING_DATES[curr_idx].year}) 預測")
    values.append(pred_mult)

    colors = ["#ff9800", "#ff9800", "#ff9800", "#42a5f5"]

    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker_color=colors,
        text=[f"{v:.1f}x" for v in values],
        textposition="outside",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=values,
        mode="lines+markers",
        line=dict(color="#ffffff", width=1.5, dash="dot"),
        showlegend=False,
    ))
    fig.update_layout(
        height=320,
        template="plotly_dark",
        title="歷史牛市漲幅遞減規律（相對減半時價格）",
        yaxis_title="倍數 (x)",
        paper_bgcolor="#0e1117",
        showlegend=False,
    )
    return fig


# ══════════════════════════════════════════════════════════════════
# 主渲染函數
# ══════════════════════════════════════════════════════════════════

def render(btc):
    st.markdown("### 🐻 熊市底部獵人 (Bear Bottom Hunter)")
    st.caption("整合 8 大鏈上+技術指標，量化評估當前是否接近歷史性熊市底部")

    curr_score, curr_signals = calculate_bear_bottom_score(btc.iloc[-1])
    score_level, score_color, score_action = _score_to_meta(curr_score)

    # ──────────────────────────────────────────────────────────────
    # A. 儀表盤 Gauge — 即時評分顯示
    # ──────────────────────────────────────────────────────────────
    fig_gauge = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=curr_score,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={
            'text': "熊市底部評分<br><span style='font-size:0.8em;color:gray'>Bear Bottom Score</span>",
            'font': {'size': 20},
        },
        delta={'reference': 50,
               'increasing': {'color': '#ff4b4b'},
               'decreasing': {'color': '#00ff88'}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': 'white'},
            'bar': {'color': score_color},
            'bgcolor': '#1e1e1e',
            'borderwidth': 2, 'bordercolor': '#333',
            'steps': [
                {'range': [0, 25],   'color': '#1a3a1a'},
                {'range': [25, 45],  'color': '#2a2a2a'},
                {'range': [45, 60],  'color': '#3a3a1a'},
                {'range': [60, 75],  'color': '#3a2a1a'},
                {'range': [75, 100], 'color': '#3a1a1a'},
            ],
            'threshold': {
                'line': {'color': '#ffffff', 'width': 3},
                'thickness': 0.75, 'value': curr_score,
            },
        },
    ))
    fig_gauge.update_layout(
        height=320, template="plotly_dark",
        paper_bgcolor="#0e1117", font={'color': 'white'},
    )

    g_col1, g_col2 = st.columns([1, 1])
    with g_col1:
        st.plotly_chart(fig_gauge, width='stretch')
    with g_col2:
        st.markdown(f"### {score_level}")
        st.markdown(f"**評分: {curr_score}/100**")
        st.info(f"📋 **操作建議**: {score_action}")
        st.markdown("""
        | 分數區間 | 市場狀態 | 建議行動 |
        |---------|---------|---------|
        | 75-100  | 歷史極值底部 | 全力積累 |
        | 60-75   | 明確底部區間 | 重倉布局 |
        | 45-60   | 可能底部區  | 分批試探 |
        | 25-45   | 震盪修正    | 觀望等待 |
        | 0-25    | 牛市高估    | 持有/減倉 |
        """)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # B. 八大指標明細卡片
    # ──────────────────────────────────────────────────────────────
    st.subheader("B. 八大指標評分明細")
    indicator_cols = st.columns(4)
    for idx, (key, sig) in enumerate(curr_signals.items()):
        col = indicator_cols[idx % 4]
        bar_pct = sig['score'] / sig['max'] * 100
        col.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">{key.replace('_', ' ')}</div>
            <div class="metric-value">{sig['value']}</div>
            <div class="metric-delta">{sig['label']}</div>
            <div style="background:#333;border-radius:4px;height:6px;margin-top:8px;">
                <div style="background:{score_color};width:{bar_pct:.0f}%;height:6px;border-radius:4px;"></div>
            </div>
            <div style="color:#888;font-size:0.75rem;text-align:right;">{sig['score']}/{sig['max']} 分</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # C. 歷史底部驗證圖
    # [Task #7] Session State 快取
    # ──────────────────────────────────────────────────────────────
    st.subheader("C. 歷史熊市底部驗證 (Bear Market Bottoms Map)")
    st.caption("橙色區域 = 已知熊市底部 | 藍線 = 200週均線 | 紅線 = Pi Cycle | 黃線 = 冪律支撐")

    cache_key   = _make_bb_cache_key(btc)
    ss_hash_key = "tab_bb_cache_key"
    ss_hist_key = f"tab_bb_fig_hist_{cache_key}"

    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_hist_key in st.session_state):
        fig_hist = st.session_state[ss_hist_key]
    else:
        fig_hist = make_subplots(
            rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
            row_heights=[0.5, 0.25, 0.25],
            subplot_titles=(
                "BTC 價格 + 底部指標均線 (對數坐標)",
                "Pi Cycle Gap (SMA111 vs 2×SMA350) — 負值觸底信號",
                "Puell Multiple Proxy — <0.5 礦工投降底部",
            ),
        )

        fig_hist.add_trace(go.Scatter(
            x=btc.index, y=btc['close'], mode='lines', name='BTC 價格',
            line=dict(color='#ffffff', width=1.5),
        ), row=1, col=1)

        if 'SMA_1400' in btc.columns and btc['SMA_1400'].notna().any():
            fig_hist.add_trace(go.Scatter(
                x=btc.index, y=btc['SMA_1400'], mode='lines', name='200週均線',
                line=dict(color='#2196F3', width=2),
            ), row=1, col=1)

        if 'SMA_350x2' in btc.columns and btc['SMA_350x2'].notna().any():
            fig_hist.add_trace(go.Scatter(
                x=btc.index, y=btc['SMA_350x2'], mode='lines', name='2×SMA350 (Pi Cycle上軌)',
                line=dict(color='#ff4b4b', width=1.5, dash='dash'),
            ), row=1, col=1)

        if 'SMA_111' in btc.columns and btc['SMA_111'].notna().any():
            fig_hist.add_trace(go.Scatter(
                x=btc.index, y=btc['SMA_111'], mode='lines', name='SMA111',
                line=dict(color='#ff8800', width=1.5),
            ), row=1, col=1)

        if 'PowerLaw_Support' in btc.columns and btc['PowerLaw_Support'].notna().any():
            fig_hist.add_trace(go.Scatter(
                x=btc.index, y=btc['PowerLaw_Support'], mode='lines', name='冪律支撐線',
                line=dict(color='#ffcc00', width=1.5, dash='dot'),
            ), row=1, col=1)

        for b_start, b_end, b_label in KNOWN_BOTTOMS:
            try:
                fig_hist.add_vrect(
                    x0=b_start, x1=b_end,
                    fillcolor="rgba(255, 140, 0, 0.15)", layer="below", line_width=0,
                    annotation_text=b_label, annotation_position="top left",
                    row=1, col=1,
                )
            except Exception:
                pass

        if 'PiCycle_Gap' in btc.columns and btc['PiCycle_Gap'].notna().any():
            pi_colors = ['#ff4b4b' if v > 0 else '#00ff88' for v in btc['PiCycle_Gap'].fillna(0)]
            fig_hist.add_trace(go.Bar(
                x=btc.index, y=btc['PiCycle_Gap'],
                marker_color=pi_colors, name='Pi Cycle Gap (%)', showlegend=False,
            ), row=2, col=1)
            fig_hist.add_hline(y=0, line_color='white', line_width=1, opacity=0.5, row=2, col=1)
            fig_hist.add_hline(y=-5, line_color='#00ff88', line_width=1, line_dash='dash',
                               annotation_text="底部信號線", row=2, col=1)

        if 'Puell_Proxy' in btc.columns and btc['Puell_Proxy'].notna().any():
            fig_hist.add_trace(go.Scatter(
                x=btc.index, y=btc['Puell_Proxy'], mode='lines',
                line=dict(color='#a32eff', width=1.5), name='Puell Proxy', showlegend=False,
            ), row=3, col=1)
            fig_hist.add_hline(y=0.5, line_color='#00ff88', line_width=1.5, line_dash='dash',
                               annotation_text="0.5 底部線", row=3, col=1)
            fig_hist.add_hline(y=4.0, line_color='#ff4b4b', line_width=1.5, line_dash='dash',
                               annotation_text="4.0 頂部線", row=3, col=1)

        fig_hist.update_layout(
            height=850, template="plotly_dark", xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        fig_hist.update_yaxes(type="log", row=1, col=1)

        st.session_state[ss_hist_key] = fig_hist
        st.session_state[ss_hash_key] = cache_key

    st.plotly_chart(fig_hist, width='stretch')

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # D. 歷史評分走勢
    # ──────────────────────────────────────────────────────────────
    st.subheader("D. 歷史底部評分走勢 (Bottom Score History)")
    st.caption("計算每日底部評分，回顧哪些時期評分最高（最接近底部）")

    ss_score_key = f"tab_bb_fig_score_{cache_key}"

    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_score_key in st.session_state):
        fig_score = st.session_state[ss_score_key]
    else:
        score_df_slice = btc.tail(365 * 4).copy()
        with st.spinner("正在計算歷史底部評分（向量化模式）..."):
            score_df_slice['BottomScore'] = score_series(score_df_slice)

        fig_score = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
            row_heights=[0.4, 0.6],
            subplot_titles=("底部評分 (0-100)", "BTC 價格 (對數)"),
        )

        score_colors_hist = [
            '#ff4b4b' if s < 25
            else ('#ffcc00' if s < 45
            else ('#ff8800' if s < 60
            else '#00ccff'))
            for s in score_df_slice['BottomScore']
        ]
        fig_score.add_trace(go.Bar(
            x=score_df_slice.index, y=score_df_slice['BottomScore'],
            marker_color=score_colors_hist, name='底部評分', showlegend=False,
        ), row=1, col=1)
        fig_score.add_hline(y=60, line_color='#00ccff', line_dash='dash',
                            annotation_text="60分 積極積累線", row=1, col=1)
        fig_score.add_hline(y=45, line_color='#ffcc00', line_dash='dot',
                            annotation_text="45分 試探線", row=1, col=1)

        fig_score.add_trace(go.Scatter(
            x=score_df_slice.index, y=score_df_slice['close'],
            mode='lines', name='BTC 價格', line=dict(color='#ffffff', width=1.5),
        ), row=2, col=1)

        high_score = score_df_slice[score_df_slice['BottomScore'] >= 60]
        if not high_score.empty:
            fig_score.add_trace(go.Scatter(
                x=high_score.index, y=high_score['close'], mode='markers',
                name='底部積累區 (≥60分)',
                marker=dict(color='#00ccff', size=5, symbol='circle', opacity=0.7),
            ), row=2, col=1)

        fig_score.update_yaxes(type="log", row=2, col=1)
        fig_score.update_layout(
            height=600, template="plotly_dark",
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )

        st.session_state[ss_score_key] = fig_score

    st.plotly_chart(fig_score, width='stretch')

    # ──────────────────────────────────────────────────────────────
    # E. 指標一覽表
    # ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("E. 當前關鍵底部指標一覽")
    curr_row = btc.iloc[-1]
    summary_data = {
        "指標": [
            "AHR999 囤幣指標", "MVRV Z-Score (Proxy)", "Pi Cycle Gap",
            "200週均線比值", "Puell Multiple (Proxy)", "月線 RSI",
            "冪律支撐倍數", "Mayer Multiple",
        ],
        "當前值": [
            f"{curr_row.get('AHR999', float('nan')):.3f}",
            f"{curr_row.get('MVRV_Z_Proxy', float('nan')):.2f}",
            f"{curr_row.get('PiCycle_Gap', float('nan')):.1f}%",
            f"{curr_row.get('SMA200W_Ratio', float('nan')):.2f}x",
            f"{curr_row.get('Puell_Proxy', float('nan')):.2f}",
            f"{curr_row.get('RSI_Monthly', float('nan')):.1f}",
            f"{curr_row.get('PowerLaw_Ratio', float('nan')):.1f}x",
            f"{curr_row.get('Mayer_Multiple', float('nan')):.2f}x",
        ],
        "底部閾值": ["< 0.45", "< 0", "< -5%", "< 1.0x", "< 0.5", "< 30", "< 2x", "< 0.8x"],
        "頂部閾值": ["> 1.2", "> 3.5", "> 10%", "> 4x", "> 4.0", "> 75", "> 10x", "> 2.4x"],
    }
    st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)

    # ══════════════════════════════════════════════════════════════
    # F. 四季理論目標價預測  ← 新增段落
    # ══════════════════════════════════════════════════════════════
    st.markdown("---")
    st.subheader("F. 🗓️ 四季理論目標價預測 (Halving Cycle Forecast)")
    st.caption(
        "依比特幣減半週期（約4年）劃分四季，整合歷史漲跌倍數與冪律模型，"
        "預測未來12個月牛市最高價或熊市最低價。"
    )

    current_price = float(btc.iloc[-1]["close"])
    fc = forecast_price(current_price, df=btc)

    if fc is None:
        st.error("無法取得減半週期資訊，請確認數據範圍。")
    else:
        si = fc["season_info"]
        is_bull = fc["forecast_type"] == "bull_peak"
        s_color = _season_css_color(si["season"])

        # ── F1. 季節狀態橫幅 ──────────────────────────────────────
        st.markdown(
            f"""
            <div style="
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                border: 1px solid {s_color};
                border-radius: 12px;
                padding: 20px 28px;
                margin-bottom: 16px;
            ">
                <div style="font-size:2rem; font-weight:700; color:{s_color};">
                    {si['emoji']} {si['season_zh']}
                </div>
                <div style="color:#ccc; margin-top:6px; font-size:1rem;">
                    第 <b style="color:white">{fc['current_cycle_idx']+1}</b> 次減半週期
                    &nbsp;｜&nbsp;
                    減半日: <b style="color:white">{si['halving_date'].strftime('%Y-%m-%d')}</b>
                    &nbsp;｜&nbsp;
                    已過 <b style="color:white">{si['days_since']}</b> 天 /
                    距下次減半還有 <b style="color:white">{si['days_to_next']}</b> 天
                </div>
                <div style="color:#aaa; margin-top:4px; font-size:0.9rem;">
                    週期月份: 第 <b style="color:white">{si['month_in_cycle']}</b> 個月
                    &nbsp;｜&nbsp;
                    週期進度: <b style="color:white">{si['cycle_progress']*100:.1f}%</b>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 週期進度時間軸
        st.plotly_chart(_render_season_timeline(si), use_container_width=True)

        st.markdown("---")

        # ── F2. 目標價卡片 ────────────────────────────────────────
        fc_type_zh = "📈 牛市最高價預測" if is_bull else "📉 熊市最低價預測"
        target_color = "#ffeb3b" if is_bull else "#42a5f5"
        conf_bar = fc["confidence"]

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.markdown(
                f"""
                <div style="background:#1e2a1e;border:1px solid {target_color};border-radius:10px;padding:18px;text-align:center;">
                    <div style="color:#888;font-size:0.8rem;">保守目標</div>
                    <div style="color:{target_color};font-size:1.6rem;font-weight:700;">${fc['target_low']:,.0f}</div>
                    <div style="color:#666;font-size:0.75rem;">25th 百分位</div>
                </div>
                """, unsafe_allow_html=True,
            )
        with col_b:
            st.markdown(
                f"""
                <div style="background:#1e2a1e;border:2px solid {target_color};border-radius:10px;padding:18px;text-align:center;box-shadow:0 0 12px {target_color}44;">
                    <div style="color:#aaa;font-size:0.85rem;">{fc_type_zh}</div>
                    <div style="color:{target_color};font-size:2.2rem;font-weight:800;">${fc['target_median']:,.0f}</div>
                    <div style="color:#999;font-size:0.8rem;">歷史中位數目標</div>
                    <div style="color:#666;font-size:0.75rem;margin-top:4px;">
                        預計達標: {fc['estimated_date'].strftime('%Y-%m-%d')}
                    </div>
                </div>
                """, unsafe_allow_html=True,
            )
        with col_c:
            st.markdown(
                f"""
                <div style="background:#1e2a1e;border:1px solid {target_color};border-radius:10px;padding:18px;text-align:center;">
                    <div style="color:#888;font-size:0.8rem;">樂觀目標</div>
                    <div style="color:{target_color};font-size:1.6rem;font-weight:700;">${fc['target_high']:,.0f}</div>
                    <div style="color:#666;font-size:0.75rem;">75th 百分位</div>
                </div>
                """, unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # 信心分數進度條
        conf_color = "#00e676" if conf_bar >= 65 else ("#ffeb3b" if conf_bar >= 45 else "#ff9800")
        st.markdown(
            f"""
            <div style="margin:8px 0 16px 0;">
                <div style="color:#aaa;font-size:0.85rem;margin-bottom:4px;">
                    預測信心分數: <b style="color:{conf_color};">{conf_bar}/100</b>
                    <span style="color:#666;font-size:0.75rem;margin-left:8px;">
                        (基於距歷史高/低點的時間距離估算)
                    </span>
                </div>
                <div style="background:#333;border-radius:6px;height:10px;">
                    <div style="background:{conf_color};width:{conf_bar}%;height:10px;border-radius:6px;transition:width 0.5s;"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 預測邏輯說明
        with st.expander("📖 預測邏輯說明", expanded=False):
            st.info(fc["rationale"])
            st.markdown(f"""
            **關鍵參考數據:**
            - 減半時 BTC 價格: **${fc['halving_price']:,.0f}**
            - 前一牛市 ATH: **${fc['prev_ath']:,.0f}** {"（熊市目標參考基礎）" if not is_bull else ""}
            - 當前季節: **{si['season_zh']}**（月 {si['month_in_cycle']}）
            - 預計達標時間: **{fc['estimated_date'].strftime('%Y年%m月%d日')}**
            """)

        st.markdown("---")

        # ── F3. 預測走勢圖 ────────────────────────────────────────
        st.markdown("#### F3. 目標價走勢圖（過去2年 + 未來12個月）")

        ss_fc_key = f"tab_bb_fig_fc_{cache_key}"
        if (st.session_state.get(ss_hash_key) == cache_key
                and ss_fc_key in st.session_state):
            fig_fc = st.session_state[ss_fc_key]
        else:
            with st.spinner("建立預測走勢圖..."):
                fig_fc = _render_forecast_chart(btc, fc)
            st.session_state[ss_fc_key] = fig_fc

        st.plotly_chart(fig_fc, use_container_width=True)

        st.markdown("---")

        # ── F4. 歷史週期比較表 ────────────────────────────────────
        st.markdown("#### F4. 歷史減半週期比較")

        col_tbl, col_bar = st.columns([1.3, 1])
        with col_tbl:
            cycle_df = get_cycle_comparison_table()
            st.dataframe(cycle_df, use_container_width=True, hide_index=True)
        with col_bar:
            st.plotly_chart(
                _render_cycle_waterfall(fc),
                use_container_width=True,
            )

        # ── F5. 四季操作策略說明 ──────────────────────────────────
        st.markdown("---")
        st.markdown("#### F5. 四季操作策略")

        strat_cols = st.columns(4)
        strategies = [
            ("🌱", "春季 (月0-11)", "#1b5e20",
             "減半後復甦期。市場情緒由恐懼轉向觀望，適合**分批建倉**，重點佈局主流幣。"),
            ("☀️", "夏季 (月12-23)", "#f57f17",
             "牛市加速期。FOMO情緒蔓延，適合**持有並設置移動止盈**，避免頂部加倉。"),
            ("🍂", "秋季 (月24-35)", "#e65100",
             "泡沫破裂期。高點已過，空頭確立，適合**逐步減倉**，轉向穩定資產。"),
            ("❄️", "冬季 (月36-47)", "#0d47a1",
             "熊市底部期。恐慌拋售為主，適合**定期定額囤幣**，等待下一個春天。"),
        ]
        for col, (emoji, name, bg, desc) in zip(strat_cols, strategies):
            is_current = name.startswith(si["emoji"])
            border = f"2px solid {s_color}" if is_current else "1px solid #333"
            col.markdown(
                f"""
                <div style="background:{bg}22;border:{border};border-radius:10px;padding:14px;min-height:160px;">
                    <div style="font-size:1.6rem;">{emoji}</div>
                    <div style="color:white;font-weight:600;margin:4px 0;">{name}</div>
                    <div style="color:#ccc;font-size:0.82rem;">{desc}</div>
                    {"<div style='color:"+s_color+";font-size:0.8rem;margin-top:8px;font-weight:600;'>← 當前季節</div>" if is_current else ""}
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.markdown("""
    ---
    > **免責聲明**: 以上指標均為技術分析工具，不構成投資建議。
    > 歷史數據不代表未來表現。加密貨幣市場波動劇烈，請嚴格控制倉位風險。
    > Pi Cycle 冪律模型參數來源: Giovanni Santostasi 比特幣冪律理論。
    > 四季理論基於歷史減半週期規律，每個週期漲幅遞減為已知趨勢，實際結果可能顯著偏離。
    """)