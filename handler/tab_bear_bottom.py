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
"""
import hashlib
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from core.bear_bottom import calculate_bear_bottom_score, score_series


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
        st.plotly_chart(fig_gauge, use_container_width=True)
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
    # [Task #7] Session State 快取：SMA_1400 等長期均線計算量大，
    # 每次重建約 150-300ms，快取後側邊欄互動降至 < 5ms
    # ──────────────────────────────────────────────────────────────
    st.subheader("C. 歷史熊市底部驗證 (Bear Market Bottoms Map)")
    st.caption("橙色區域 = 已知熊市底部 | 藍線 = 200週均線 | 紅線 = Pi Cycle | 黃線 = 冪律支撐")

    cache_key   = _make_bb_cache_key(btc)   # 用於 D 段快取，在此計算一次
    ss_hash_key = "tab_bb_cache_key"
    ss_hist_key = f"tab_bb_fig_hist_{cache_key}"

    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_hist_key in st.session_state):
        # ── 快取命中：直接複用圖表，跳過所有 add_trace 操作 ──
        fig_hist = st.session_state[ss_hist_key]
    else:
        # ── 快取未命中：重新建圖（首次載入或數據更新） ──
        fig_hist = make_subplots(
            rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.04,
            row_heights=[0.5, 0.25, 0.25],
            subplot_titles=(
                "BTC 價格 + 底部指標均線 (對數坐標)",
                "Pi Cycle Gap (SMA111 vs 2×SMA350) — 負值觸底信號",
                "Puell Multiple Proxy — <0.5 礦工投降底部",
            ),
        )

        # Row 1: 價格主圖
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

        # 標記已知底部區間（橙色矩形）
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

        # Row 2: Pi Cycle Gap
        if 'PiCycle_Gap' in btc.columns and btc['PiCycle_Gap'].notna().any():
            pi_colors = ['#ff4b4b' if v > 0 else '#00ff88' for v in btc['PiCycle_Gap'].fillna(0)]
            fig_hist.add_trace(go.Bar(
                x=btc.index, y=btc['PiCycle_Gap'],
                marker_color=pi_colors, name='Pi Cycle Gap (%)', showlegend=False,
            ), row=2, col=1)
            fig_hist.add_hline(y=0, line_color='white', line_width=1, opacity=0.5, row=2, col=1)
            fig_hist.add_hline(y=-5, line_color='#00ff88', line_width=1, line_dash='dash',
                               annotation_text="底部信號線", row=2, col=1)

        # Row 3: Puell Multiple Proxy
        if 'Puell_Proxy' in btc.columns and btc['Puell_Proxy'].notna().any():
            fig_hist.add_trace(go.Scatter(
                x=btc.index, y=btc['Puell_Proxy'], mode='lines',
                line=dict(color='#a32eff', width=1.5), name='Puell Proxy', showlegend=False,
            ), row=3, col=1)
            fig_hist.add_hline(y=0.5, line_color='#00ff88', line_width=1.5, line_dash='dash',
                               annotation_text="0.5 底部線", row=3, col=1)
            fig_hist.add_hline(y=4.0, line_color='#ff4b4b', line_width=1.5, line_dash='dash',
                               annotation_text="4.0 頂部線", row=3, col=1)

        # 版面設定（無論 Puell 是否存在都要執行）
        fig_hist.update_layout(
            height=850, template="plotly_dark", xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        fig_hist.update_yaxes(type="log", row=1, col=1)

        # [Task #7] 寫入 session_state，下次直接複用
        st.session_state[ss_hist_key] = fig_hist
        st.session_state[ss_hash_key] = cache_key

    st.plotly_chart(fig_hist, use_container_width=True)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # D. 歷史評分走勢
    # [Task #7] Session State 快取：score_series(1460 rows) 約 50-200ms，
    # 快取後側邊欄互動降至 < 5ms
    # ──────────────────────────────────────────────────────────────
    st.subheader("D. 歷史底部評分走勢 (Bottom Score History)")
    st.caption("計算每日底部評分，回顧哪些時期評分最高（最接近底部）")

    ss_score_key = f"tab_bb_fig_score_{cache_key}"  # cache_key 已在 C 段計算

    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_score_key in st.session_state):
        # ── 快取命中：直接複用（包含已計算好的 score_series 結果） ──
        fig_score = st.session_state[ss_score_key]
    else:
        # ── 快取未命中：執行昂貴的 score_series 計算並建圖 ──
        score_df_slice = btc.tail(365 * 4).copy()
        with st.spinner("正在計算歷史底部評分（向量化模式）..."):
            # score_series 使用 np.select 向量化，比 iterrows 快 20-50x
            score_df_slice['BottomScore'] = score_series(score_df_slice)

        fig_score = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05,
            row_heights=[0.4, 0.6],
            subplot_titles=("底部評分 (0-100)", "BTC 價格 (對數)"),
        )

        # Row 1: 評分柱狀圖（顏色對應評分等級）
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

        # Row 2: BTC 價格（對數坐標）+ 高分區域標記
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

        # [Task #7] 寫入 session_state（ss_hash_key 已在 C 段設定）
        st.session_state[ss_score_key] = fig_score

    st.plotly_chart(fig_score, use_container_width=True)

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

    st.markdown("""
    ---
    > **免責聲明**: 以上指標均為技術分析工具，不構成投資建議。
    > 歷史數據不代表未來表現。加密貨幣市場波動劇烈，請嚴格控制倉位風險。
    > Pi Cycle 冪律模型參數來源: Giovanni Santostasi 比特幣冪律理論。
    """)
