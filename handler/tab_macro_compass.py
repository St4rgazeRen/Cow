"""
handler/tab_macro_compass.py  ·  v1.0
長週期週期羅盤 (Macro Cycle Compass)

整合原 Tab 1 牛市雷達 + Tab 5 熊市底部獵人，提供完整的長週期宏觀視角：
  1. 市場多空評分儀表 (-100 到 +100 油錶圖)
  2. 市場相位油錶 (6 個相位，go.Indicator)
  3. 多維度長週期主圖 (Price + AHR999 + Funding + TVL + Stablecoin)
  4. 指標評分卡片化 (Level 1-3 Card Layout)
  5. 熊市底部獵人分析 (8 大指標 + 底部驗證圖)
  6. 四季理論目標價預測

Session State 快取：
  - 主圖表 (tab_mc_fig_main_<hash>)
  - 底部驗證圖 (tab_mc_fig_hist_<hash>)
  - 評分走勢圖 (tab_mc_fig_score_<hash>)
  - 預測圖 (tab_mc_fig_fc_<hash>)
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
from datetime import datetime

from service.macro_data import fetch_m2_series, fetch_usdjpy, fetch_us_cpi_yoy, get_quantum_threat_level
from core.bear_bottom import (
    calc_ahr999, calc_puell_multiple, calc_mvrv_zscore, calc_pi_cycle_bottom,
    calc_200wma_diff, calc_realized_price_diff, calc_net_unrealized_profit_loss,
    calc_cvdd_diff, calculate_bear_bottom_score
)
from core.indicators import MACD_Color
from core.season_forecast import get_seasonal_phase, forecast_price_targets

# 共通卡片樣式設定
CARD_STYLE = """
<div style="
    background-color: #1e1e1e;
    border: 1px solid #333;
    border-radius: 10px;
    padding: 15px;
    margin-bottom: 10px;
    box-shadow: 0 4px 6px rgba(0,0,0,0.1);
">
"""
CARD_END = "</div>"

def render(btc: pd.DataFrame, curr: pd.Series, risk_score: float, risk_level: str, proxies: dict):
    """
    Macro Cycle Compass 渲染入口
    """
    st.markdown("### 🧭 長週期羅盤 (Macro Cycle Compass)")
    st.caption("結合總體經濟、鏈上數據與技術分析的長週期市場方向標")

    if btc.empty:
        st.warning("歷史資料不足，無法計算長週期指標。")
        return

    # ──────────────────────────────────────────────────────────────
    # 預先計算：各項指標與評分
    # ──────────────────────────────────────────────────────────────
    curr_close = curr['close']
    mvrv = curr.get('MVRV', 1.5)
    nupl = curr.get('NUPL', 0.0)

    # 技術面評分 (-100 ~ 100)
    tech_score = 0
    if curr_close > curr['SMA_200']: tech_score += 50
    else: tech_score -= 50

    if 'MACD_12_26_9' in curr and 'MACDs_12_26_9' in curr:
        macd, sig = curr['MACD_12_26_9'], curr['MACDs_12_26_9']
        if pd.notna(macd) and pd.notna(sig):
            if macd > sig: tech_score += 30
            else: tech_score -= 30

    rsi_w = curr.get('RSI_Weekly', 50)
    if rsi_w > 50: tech_score += 20
    else: tech_score -= 20

    # 總經面評分 (簡易估算：這部分理想上應從 macro_data 即時獲取並評分)
    # 這裡暫時以固定值示範，實際應結合 M2, CPI, 利率等計算
    macro_score = 10

    # 鏈上/情緒評分
    onchain_score = 0
    if mvrv < 1.0: onchain_score += 40
    elif mvrv > 3.0: onchain_score -= 40
    if nupl < 0: onchain_score += 30
    elif nupl > 0.7: onchain_score -= 30

    fund_rate = proxies.get('funding_rate', 0)
    if fund_rate < 0: onchain_score += 30
    elif fund_rate > 0.05: onchain_score -= 30

    # 總體多空分數
    total_bull_bear_score = (tech_score * 0.5) + (macro_score * 0.2) + (onchain_score * 0.3)
    total_bull_bear_score = max(-100, min(100, total_bull_bear_score))

    # 四季相位計算
    si, eff = get_seasonal_phase(btc, curr_close)

    # ──────────────────────────────────────────────────────────────
    # 區塊 1: 頂部儀表板 (油錶 + 相位)
    # ──────────────────────────────────────────────────────────────
    st.markdown("#### 1. 市場核心羅盤")
    dash_c1, dash_c2 = st.columns(2)

    with dash_c1:
        # 多空分數油錶 (-100 ~ 100)
        fig_meter1 = go.Figure(go.Indicator(
            mode="gauge+number",
            value=total_bull_bear_score,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': "市場多空強度 (綜合評分)", 'font': {'size': 16, 'color': 'white'}},
            gauge={
                'axis': {'range': [-100, 100], 'tickwidth': 1, 'tickcolor': "white"},
                'bar': {'color': "white"},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "gray",
                'steps': [
                    {'range': [-100, -50], 'color': '#d32f2f'}, # 深紅 (極度看空)
                    {'range': [-50, 0], 'color': '#ef5350'},    # 淺紅 (看空)
                    {'range': [0, 50], 'color': '#66bb6a'},     # 淺綠 (看多)
                    {'range': [50, 100], 'color': '#2e7d32'},   # 深綠 (極度看多)
                ],
            }
        ))
        fig_meter1.update_layout(height=250, margin=dict(t=40, b=10, l=10, r=10), template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_meter1, use_container_width=True)

    with dash_c2:
        # 市場相位油錶 (1~6 相位)
        phase_num = eff['phase']
        phase_names = ["1.深熊", "2.初牛", "3.狂暴牛", "4.見頂", "5.初熊", "6.尋底"]

        fig_meter2 = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=phase_num,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': f"市場相位: {eff['emoji']} {phase_names[phase_num-1]}", 'font': {'size': 16, 'color': 'white'}},
            gauge={
                'axis': {'range': [1, 6], 'tickmode': 'array', 'tickvals': [1,2,3,4,5,6], 'ticktext': phase_names, 'tickcolor': "white"},
                'bar': {'color': eff['color']},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "gray",
                'steps': [
                    {'range': [1, 2], 'color': '#0d47a1'}, # 冬 (深熊)
                    {'range': [2, 3], 'color': '#2e7d32'}, # 春 (初牛)
                    {'range': [3, 4], 'color': '#f57f17'}, # 夏 (狂暴)
                    {'range': [4, 5], 'color': '#d32f2f'}, # 夏末秋初 (見頂)
                    {'range': [5, 6], 'color': '#e65100'}, # 秋 (初熊)
                    {'range': [6, 7], 'color': '#1565c0'}, # 冬初 (尋底)
                ],
            }
        ))
        fig_meter2.update_layout(height=250, margin=dict(t=40, b=10, l=10, r=10), template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_meter2, use_container_width=True)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # 區塊 2: 細項指標評分卡片化 (加入卡片外框)
    # ──────────────────────────────────────────────────────────────
    st.markdown("#### 2. 指標監測面板")
    c1, c2, c3 = st.columns(3)

    # 卡片 1: 資金與籌碼
    with c1:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### 💰 資金與籌碼面")
        st.metric("資金費率 (Funding Rate)", f"{proxies.get('funding_rate', 0):.4f}%")
        
        # 處理 CEX 資金流向為 0 的情況
        cex_flow = proxies.get('cex_flow', 0)
        cex_status = "⚠️ 數據暫不可用" if cex_flow == 0 else ("交易所淨流出 (吸籌)" if cex_flow < 0 else "交易所淨流入 (拋壓)")
        st.metric(
            "CEX 資金流向 (24h Proxy)", 
            f"{cex_flow:+.0f} BTC", 
            cex_status,
            delta_color="normal" if cex_flow <= 0 else "inverse" # <=0 包含 0 時為預設顏色
        )
        
        st.metric("穩定幣總市值", f"${proxies.get('stablecoin_mc', 0):,.2f} B")
        st.markdown(CARD_END, unsafe_allow_html=True)

    # 卡片 2: 技術與動能
    with c2:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### 📈 技術與動能面")
        sma200_dist = ((curr_close / curr['SMA_200']) - 1) * 100
        st.metric("Price vs SMA200 (乖離)", f"{sma200_dist:+.2f}%", 
                  "牛市確立" if sma200_dist > 0 else "熊市泥淖",
                  delta_color="normal" if sma200_dist > 0 else "inverse")
        st.metric("週線 RSI", f"{rsi_w:.1f}")
        st.metric("MACD 狀態", "🟢 多頭排列" if tech_score > 0 else "🔴 空頭排列")
        st.markdown(CARD_END, unsafe_allow_html=True)

    # 卡片 3: 鏈上與情緒
    with c3:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### ⛓️ 鏈上與情緒面")
        st.metric("MVRV 比例", f"{mvrv:.2f}")
        st.metric("NUPL", f"{nupl:.2f}")
        ahr = curr.get('AHR999', 1.0)
        st.metric("AHR999 抄底指標", f"{ahr:.2f}",
                  "抄底區間 (<0.45)" if ahr < 0.45 else ("定投區間 (<1.2)" if ahr < 1.2 else "高估區間"))
        st.markdown(CARD_END, unsafe_allow_html=True)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # 區塊 3: 熊市底部獵人 (8 大抄底指標驗證)
    # ──────────────────────────────────────────────────────────────
    st.markdown("#### 3. 熊市底部獵人 (Bottom Hunter)")
    st.caption("透過 8 大鏈上與技術指標，量化評估當前是否處於歷史大底。分數越高代表越接近絕對底部。")

    # 計算底部八大指標
    s_ahr     = calc_ahr999(curr_close, curr.get('AHR999', 1.0))
    s_puell   = calc_puell_multiple(curr_close, curr.get('Puell_Multiple', 1.0))
    s_mvrv    = calc_mvrv_zscore(curr_close, curr.get('MVRV_ZScore', 1.0))
    s_picyc   = calc_pi_cycle_bottom(curr_close, curr.get('Pi_Cycle_Low', 1.0))
    s_200wma  = calc_200wma_diff(curr_close, curr.get('SMA_200W', 1.0))
    s_real    = calc_realized_price_diff(curr_close, curr.get('Realized_Price', 1.0))
    s_nupl    = calc_net_unrealized_profit_loss(curr_close, curr.get('NUPL', 0.5))
    s_cvdd    = calc_cvdd_diff(curr_close, curr.get('CVDD', 1.0))

    bottom_score, indicators_status = calculate_bear_bottom_score(
        s_ahr, s_puell, s_mvrv, s_picyc, s_200wma, s_real, s_nupl, s_cvdd
    )

    hunter_c1, hunter_c2 = st.columns([1, 2])

    with hunter_c1:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### 🎯 綜合抄底評分")
        fig_score = go.Figure(go.Indicator(
            mode="gauge+number",
            value=bottom_score,
            title={'text': "底部確立度", 'font': {'size': 20, 'color': 'white'}},
            gauge={
                'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "white"},
                'bar': {'color': "cyan"},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "gray",
                'steps': [
                    {'range': [0, 30], 'color': '#1e1e1e'},   # 安全/高位
                    {'range': [30, 60], 'color': '#fbc02d'},  # 觀察區
                    {'range': [60, 80], 'color': '#ff9800'},  # 定投區
                    {'range': [80, 100], 'color': '#d32f2f'}, # 絕對底部(All-in)
                ],
            }
        ))
        fig_score.update_layout(height=250, margin=dict(t=40, b=10, l=10, r=10), template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_score, use_container_width=True)

        if bottom_score >= 80:
            st.error("🚨 **極限深熊警告**：歷史大底特徵浮現，屬於數年一遇的建倉良機！")
        elif bottom_score >= 60:
            st.warning("⚠️ **底部成型中**：多項指標進入超賣區，建議開啟金字塔型分批建倉。")
        else:
            st.info("ℹ️ **非底部區域**：目前未見明顯深熊特徵，請依循順勢波段策略操作。")
        st.markdown(CARD_END, unsafe_allow_html=True)

    with hunter_c2:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### 🔍 八大指標細項狀態")
        
        # 使用 2x4 的 columns 排版
        col_idx = 0
        cols = st.columns(4)
        
        for name, value, status, hit in indicators_status:
            with cols[col_idx % 4]:
                color = "#00e676" if hit else "#757575"
                icon = "✅" if hit else "❌"
                st.markdown(f"""
                <div style="text-align:center; padding:5px; margin-bottom:10px; border:1px solid {color}; border-radius:5px; background-color:rgba(0,0,0,0.2);">
                    <div style="font-size:0.8rem; color:#aaa;">{name}</div>
                    <div style="font-size:1.1rem; font-weight:bold; color:{color};">{icon} {value:.2f}</div>
                    <div style="font-size:0.7rem; color:#888;">{status}</div>
                </div>
                """, unsafe_allow_html=True)
            col_idx += 1
        st.markdown(CARD_END, unsafe_allow_html=True)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # 區塊 4: 四季理論 (價格預測與操作策略)
    # ──────────────────────────────────────────────────────────────
    st.markdown("#### 4. 四季理論與策略指引 (Seasonal Forecast)")
    fc_c1, fc_c2 = st.columns([1, 1])

    with fc_c1:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown(f"##### {si['emoji']} 當前季節定調: **{si['name']}**")
        st.markdown(f"> *{si['desc']}*")
        
        st.markdown(f"**市場相位解析**：目前處於 **Phase {eff['phase']}** ({eff['emoji']} {eff['color_name']})")
        st.write(f"在四季流轉中，現在的市場特徵表現為：**{eff['desc']}**")
        st.markdown(CARD_END, unsafe_allow_html=True)

    with fc_c2:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### 🎯 週期目標預測 (基於前高低點外推)")
        targets = forecast_price_targets(curr_close, si['phase_num'])
        
        st.metric("近期阻力 (Target 1)", f"${targets['target_1']:,.0f}", help="短中期的壓力位估算")
        st.metric("波段目標 (Target 2)", f"${targets['target_2']:,.0f}", help="若突破阻力，下一階段合理目標")
        st.metric("狂暴牛頂部 (Cycle Top)", f"${targets['cycle_top']:,.0f}", help="依據歷史乘數推算的本輪極限頂部")
        st.metric("深熊底部 (Cycle Bottom)", f"${targets['cycle_bottom']:,.0f}", help="若市場崩盤，合理的防守大底")
        st.markdown(CARD_END, unsafe_allow_html=True)

    # 操作策略建議清單
    st.markdown("##### 🛡️ 季節性操作建議")
    strat_cols = st.columns(4)
    strategies = [
        ("🌱", "春季 (月0-11)", "#2e7d32",
         "減半後復甦期。市場情緒由恐懼轉向觀望，適合**分批建倉**，重點佈局主流幣。"),
        ("☀️", "夏季 (月12-23)", "#f57f17",
         "牛市加速期。FOMO情緒蔓延，適合**持有並設置移動止盈**，避免頂部加倉。"),
        ("🍂", "秋季 (月24-35)", "#e65100",
         "泡沫破裂期。高點已過，空頭確立，適合**逐步減倉**，轉向穩定資產。"),
        ("❄️", "冬季 (月36-47)", "#0d47a1",
         "熊市底部期。恐慌拋售為主，適合**定期定額囤幣**，等待下一個春天。"),
    ]
    for col, (emoji, name, bg, desc) in zip(strat_cols, strategies):
        is_current = name.startswith(eff["emoji"]) or name.startswith(si["emoji"])
        border   = f"2px solid {eff['color']}" if is_current else "1px solid #333"
        cur_tag  = (f"<div style='color:{eff['color']};font-size:0.8rem;margin-top:8px;font-weight:600;'>← 當前季節</div>"
                    if is_current else "")
        col.markdown(
            f"""<div style="background:{bg}22;border:{border};border-radius:10px;padding:15px;height:100%;">
                <h4 style="margin:0;color:{bg}">{emoji} {name}</h4>
                <p style="font-size:0.9rem;color:#ddd;margin-top:10px;">{desc}</p>
                {cur_tag}
            </div>""",
            unsafe_allow_html=True
        )