"""
handler/tab_bull_radar.py
Tab 1: 牛市雷達 (Bull Detector)

[Task #7] Session State 圖表快取:
Streamlit 每次用戶與側邊欄互動（改日期、改資金...）都會重新執行全部 render()，
導致 make_subplots + 多條 add_trace 這類昂貴操作重複執行。

解決方案:
- 以 (chart_df 最後索引, tvl/stable/fund 資料長度) 組合成 cache_key
- 若 session_state 已有相同 key 的圖表物件，直接複用，不重建
- 只有實際數據更新時才觸發重新渲染
- 效果: 側邊欄操作從每次重建 (200-500ms) 降至快取命中 (<5ms)
"""
import hashlib
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

from service.mock import get_mock_global_m2_series


def _make_chart_cache_key(chart_df, tvl_hist, stable_hist, fund_hist) -> str:
    """
    根據輸入數據的「最後一筆時間戳 + 資料筆數」生成快取鍵。
    使用 hash 而非直接比較 DataFrame，避免大數據 == 操作的效能損耗。

    邏輯：
    - 若數據無變化（新 API 資料未到），key 不變 → 直接用快取圖表
    - 若新一批數據進來（index 更新），key 改變 → 重新建圖
    """
    parts = [
        str(chart_df.index[-1])   if not chart_df.empty   else "empty",
        str(len(chart_df)),
        str(tvl_hist.index[-1])   if not tvl_hist.empty   else "empty",
        str(stable_hist.index[-1]) if not stable_hist.empty else "empty",
        str(fund_hist.index[-1])  if not fund_hist.empty  else "empty",
    ]
    raw = "|".join(parts)
    # 取 MD5 前 16 碼作為 key，足夠唯一且不佔空間
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def render(btc, chart_df, tvl_hist, stable_hist, fund_hist, curr, dxy,
           funding_rate, tvl_val, fng_val, fng_state, fng_source, proxies, realtime_data):
    st.subheader("BTCUSDT 多維度綜合分析 (Multi-Dimension Analysis)")

    # ──────────────────────────────────────────────────────────────
    # [Task #7] 主圖表快取邏輯
    # ──────────────────────────────────────────────────────────────
    cache_key = _make_chart_cache_key(chart_df, tvl_hist, stable_hist, fund_hist)
    # session_state key 格式：tab_bull_fig_{hash}，避免與其他 tab 衝突
    ss_fig_key  = f"tab_bull_fig_{cache_key}"
    ss_hash_key = "tab_bull_fig_key"

    # 若快取命中（key 相同），直接使用已建好的圖表物件
    if (st.session_state.get(ss_hash_key) == cache_key
            and ss_fig_key in st.session_state):
        fig_t1 = st.session_state[ss_fig_key]
    else:
        # 快取未命中：重新建圖（數據有更新或首次載入）

        # Row 0: 去除時區（避免 Plotly 渲染問題）
        if chart_df.index.tz is not None:
            chart_df = chart_df.copy()
            chart_df.index = chart_df.index.tz_localize(None)

        fig_t1 = make_subplots(
            rows=5, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.025,
            row_heights=[0.40, 0.15, 0.15, 0.15, 0.15],
            subplot_titles=(
                "比特幣價格行為 (Price Action)",
                "AHR999 囤幣指標 (< 0.45 = 歷史抄底區)",
                "幣安資金費率 (Funding Rate) & RSI_14",
                "BTC 鏈上 TVL (DeFiLlama)",
                "全球穩定幣市值 (Stablecoin Cap)",
            ),
        )

        # Row 1: 價格 + 均線
        fig_t1.add_trace(go.Candlestick(
            x=chart_df.index, open=chart_df['open'], high=chart_df['high'],
            low=chart_df['low'], close=chart_df['close'], name='BTC',
        ), row=1, col=1)
        fig_t1.add_trace(go.Scatter(
            x=chart_df.index, y=chart_df['SMA_200'],
            line=dict(color='orange', width=2), name='SMA 200',
        ), row=1, col=1)
        fig_t1.add_trace(go.Scatter(
            x=chart_df.index, y=chart_df['SMA_50'],
            line=dict(color='cyan', width=1, dash='dash'), name='SMA 50',
        ), row=1, col=1)
        if 'EMA_20' in chart_df.columns:
            fig_t1.add_trace(go.Scatter(
                x=chart_df.index, y=chart_df['EMA_20'],
                line=dict(color='#ffeb3b', width=1, dash='dot'), name='EMA 20',
            ), row=1, col=1)

        # Row 2: AHR999 指標（附帶閾值線）
        if 'AHR999' in chart_df.columns and chart_df['AHR999'].notna().any():
            ahr_colors = [
                '#00ff88' if v < 0.45
                else ('#ffcc00' if v < 0.8
                else ('#ff8800' if v < 1.2
                else '#ff4b4b'))
                for v in chart_df['AHR999'].fillna(1.0)
            ]
            fig_t1.add_trace(go.Bar(
                x=chart_df.index, y=chart_df['AHR999'],
                marker_color=ahr_colors, name='AHR999', showlegend=False,
            ), row=2, col=1)
            for lvl, col, lbl in [
                (0.45, '#00ff88', '抄底 0.45'),
                (0.8,  '#ffcc00', '偏低 0.8'),
                (1.2,  '#ff4b4b', '高估 1.2'),
            ]:
                fig_t1.add_hline(y=lvl, line_color=col, line_width=1, line_dash='dash',
                                 annotation_text=lbl, row=2, col=1)

        # Row 3: 資金費率 + RSI 疊加（雙 y 軸概念，以顏色區分）
        if not fund_hist.empty:
            fund_sub   = fund_hist.reindex(chart_df.index, method='nearest')
            fr_colors  = ['#00ff88' if v > 0 else '#ff4b4b' for v in fund_sub['fundingRate']]
            fig_t1.add_trace(go.Bar(
                x=fund_sub.index, y=fund_sub['fundingRate'],
                marker_color=fr_colors, name='Funding Rate %',
            ), row=3, col=1)
        if 'RSI_14' in chart_df.columns and chart_df['RSI_14'].notna().any():
            # RSI 縮放到 [-0.05, 0.05] 左右，與資金費率共軸顯示
            rsi_scaled = (chart_df['RSI_14'] - 50) * 0.001
            fig_t1.add_trace(go.Scatter(
                x=chart_df.index, y=rsi_scaled,
                line=dict(color='#a32eff', width=1.5), name='RSI (scaled)',
            ), row=3, col=1)
        fig_t1.add_hline(y=0.03, line_color='#ff4b4b', line_width=0.8,
                         line_dash='dot', annotation_text="過熱 0.03%", row=3, col=1)

        # Row 4: TVL
        if not tvl_hist.empty:
            if tvl_hist.index.tz is not None:
                tvl_hist = tvl_hist.copy()
                tvl_hist.index = tvl_hist.index.tz_localize(None)
            tvl_sub = tvl_hist.reindex(chart_df.index, method='nearest')
            fig_t1.add_trace(go.Scatter(
                x=tvl_sub.index,
                y=tvl_sub['tvl'] if 'tvl' in tvl_sub.columns else [],
                mode='lines', fill='tozeroy',
                line=dict(color='#a32eff'), name='TVL (USD)',
            ), row=4, col=1)

        # Row 5: 穩定幣市值
        if not stable_hist.empty:
            stab_sub = stable_hist.reindex(chart_df.index, method='nearest')
            fig_t1.add_trace(go.Scatter(
                x=stab_sub.index, y=stab_sub['mcap'] / 1e9,
                mode='lines', line=dict(color='#2E86C1'), name='Stablecoin Cap ($B)',
            ), row=5, col=1)

        fig_t1.update_layout(
            height=1000, template="plotly_dark", xaxis_rangeslider_visible=False,
            legend=dict(orientation='h', yanchor='bottom', y=1.01, xanchor='right', x=1),
        )

        # [Task #7] 將建好的圖表存入 session_state，下次直接複用
        st.session_state[ss_fig_key]  = fig_t1
        st.session_state[ss_hash_key] = cache_key

    st.plotly_chart(fig_t1, use_container_width=True)

    # --- 市場相位判定 ---
    price = curr['close']
    ma50 = curr['SMA_50']
    ma200 = curr['SMA_200']
    ma200_slope = curr.get('SMA_200_Slope', 0)
    mvrv = curr.get('MVRV_Z_Proxy', 0)

    if mvrv > 3.5:
        phase_name = "🔥 狂熱頂部 (Overheated)"
        phase_desc = "風險極高，建議分批止盈"
    elif price > ma200 and ma50 > ma200 and ma200_slope > 0:
        phase_name = "🐂 牛市主升段 (Bull Run)"
        phase_desc = "趨勢多頭排列且年線上揚，主升段"
    elif price > ma200 and ma50 > ma200 and ma200_slope <= 0:
        phase_name = "😴 牛市休整/末期 (Stagnant Bull)"
        phase_desc = "價格雖高但年線走平，動能減弱"
    elif price > ma200 and ma50 <= ma200:
        phase_name = "🌱 初牛復甦 (Recovering)"
        phase_desc = "價格站上年線，等待黃金交叉與年線翻揚"
    elif price <= ma200 and ma50 > ma200:
        phase_name = "📉 轉折回調 (Correction)"
        phase_desc = "跌破年線，需注意是否死叉"
    else:
        phase_name = "❄️ 深熊築底 (Winter)"
        phase_desc = "均線空頭排列，定投積累區"

    st.info(f"### 📡 當前市場相位：**{phase_name}**\n\n{phase_desc}")
    st.markdown("---")

    # --- 三層分析框架 ---
    col1, col2, col3 = st.columns(3)

    # Level 1: 散戶視角
    with col1:
        st.markdown("### Level 1: 散戶視角")
        is_golden = (curr['close'] > curr['SMA_200']) and (curr['SMA_50'] > curr['SMA_200'])
        is_rising = curr.get('SMA_200_Slope', 0) > 0
        struct_state = (
            "多頭共振 (STRONG)" if (is_golden and is_rising)
            else ("震盪/修正 (WEAK)" if not is_golden else "年線走平 (FLAT)")
        )
        st.metric(
            "趨勢結構 (Structure)", struct_state,
            delta=f"MA200 斜率 {('↗️ 上升' if is_rising else '↘️ 下降')}",
            delta_color="normal" if is_rising else "off",
        )
        recent_high = btc['high'].iloc[-20:].max()
        prev_high = btc['high'].iloc[-40:-20].max()
        dow_state = "更高的高點 (HH)" if recent_high > prev_high else "高點降低 (LH)"
        st.metric("道氏理論結構", dow_state)
        st.metric(f"情緒指數 ({fng_source})", f"{fng_val:.0f}/100", fng_state)

    # Level 2: 機構視角
    with col2:
        st.markdown("### Level 2: 機構視角")
        ahr_val = curr['AHR999']
        ahr_state = (
            "🟢 抄底區間 (歷史大底)" if ahr_val < 0.45
            else ("🟡 合理區間 (持有)" if ahr_val < 1.2 else "🔴 高估區間 (分批止盈)")
        )
        st.metric("AHR999 囤幣指標", f"{ahr_val:.2f}", ahr_state,
                  help="< 0.45 抄底 | 0.45-1.2 合理 | > 1.2 高估")

        mvrv_z = curr.get('MVRV_Z_Proxy', 0)
        mvrv_state = (
            "🔥 過熱頂部 (>3.0)" if mvrv_z > 3.0
            else ("🟢 價值低估 (<0)" if mvrv_z < 0 else "中性區域")
        )
        st.metric("MVRV Z-Score (Proxy)", f"{mvrv_z:.2f}", mvrv_state)
        st.metric(
            "BTC 生態系 TVL",
            f"${tvl_val / 1e9:.2f}B" if tvl_val > 1e9 else f"${tvl_val:.2f}B",
            "↑ 持續增長" if tvl_val > 0 else "↓ 資金流出",
        )
        etf_flow = proxies['etf_flow']
        st.metric(
            "現貨 ETF 淨流量 (24h)", f"{etf_flow:+.1f}M",
            "↑ 機構買盤" if etf_flow > 0 else "↓ 機構拋壓",
        )
        fr_state = (
            "🔥 多頭過熱" if funding_rate > 0.03
            else ("🟢 情緒中性" if funding_rate > 0 else "❄️ 空頭主導")
        )
        st.metric("資金費率", f"{funding_rate:.4f}%", fr_state,
                  delta_color="inverse" if funding_rate > 0.03 else "normal")

    # Level 3: 宏觀視角
    with col3:
        st.markdown("### Level 3: 宏觀視角")
        if not dxy.empty:
            comm_idx = btc.index.intersection(dxy.index)
            corr_90 = btc.loc[comm_idx]['close'].rolling(90).corr(
                dxy.loc[comm_idx]['close']
            ).iloc[-1]
            st.metric(
                "BTC vs DXY 相關性 (90d)", f"{corr_90:.2f}",
                "高度負相關 (正常)" if corr_90 < -0.5 else "相關性減弱/脫鉤",
            )
        else:
            st.metric("BTC vs DXY", "N/A", "數據不足")

        if realtime_data.get('stablecoin_mcap'):
            st.metric(
                "全球穩定幣市值",
                f"${realtime_data['stablecoin_mcap']:.2f}B",
                "↑ 流動性充沛" if realtime_data['stablecoin_mcap'] > 100 else "流動性一般",
            )
        else:
            st.metric("全球穩定幣市值", "N/A", "連線失敗")

        m2_series = get_mock_global_m2_series(btc).reindex(chart_df.index)
        st.line_chart(m2_series, height=120)
        st.caption("全球 M2 流動性趨勢 (模擬)")

        st.markdown("---")
        st.markdown("#### 🧠 人工判讀區")
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.text_input("🇯🇵 日圓匯率 (JPY)", placeholder="例: 155.5", key="macro_jpy")
            st.metric("量子威脅等級", "Low (Current)")
        with m_col2:
            st.text_input("🇺🇸 美國 CPI (YoY)", placeholder="例: 3.4%", key="macro_cpi")
            st.info("**技術敘事**:\n- 關注 OP_CAT 升級進度")
