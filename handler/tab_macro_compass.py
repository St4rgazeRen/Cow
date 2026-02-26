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
"""
# 關閉 SSL 驗證警告，避免本地端公司網路環境報錯
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# ✅ 修正：只引入確實存在且有用到的函數，根絕 ImportError
from core.bear_bottom import calculate_bear_bottom_score
from core.season_forecast import forecast_price

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

def render(
    btc: pd.DataFrame, 
    chart_df: pd.DataFrame, 
    tvl_hist: pd.DataFrame, 
    stable_hist: pd.DataFrame, 
    fund_hist: pd.DataFrame,
    curr: pd.Series, 
    dxy: pd.DataFrame, 
    funding_rate: float, 
    tvl_val: float,
    fng_val: float, 
    fng_state: str, 
    fng_source: str, 
    proxies: dict, 
    realtime_data: dict
):
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

    # 總經面評分 
    macro_score = 10

    # 鏈上/情緒評分
    onchain_score = 0
    if mvrv < 1.0: onchain_score += 40
    elif mvrv > 3.0: onchain_score -= 40
    if nupl < 0: onchain_score += 30
    elif nupl > 0.7: onchain_score -= 30

    if funding_rate < 0: onchain_score += 30
    elif funding_rate > 0.05: onchain_score -= 30

    # 總體多空分數
    total_bull_bear_score = (tech_score * 0.5) + (macro_score * 0.2) + (onchain_score * 0.3)
    total_bull_bear_score = max(-100, min(100, total_bull_bear_score))

    # ✅ 修正：完美對接 season_forecast.py (v1.3) 的預測函數
    forecast = forecast_price(curr_close, btc)
    
    if forecast:
        si = forecast["season_info"]
        eff = forecast["effective_season"]
        # 將季節對應到市場相位與顏色
        phase_map = {
            "winter": (1, '#0d47a1'), 
            "spring": (2, '#2e7d32'), 
            "summer": (3, '#f57f17'), 
            "autumn": (5, '#e65100')
        }
        phase_num, phase_color = phase_map.get(eff["season"], (1, '#0d47a1'))
    else:
        si = {"emoji": "❓", "season_zh": "未知", "month_in_cycle": 0, "cycle_progress": 0}
        eff = {"emoji": "❓", "season_zh": "未知", "season": "unknown"}
        phase_num, phase_color = 1, "gray"

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
                    {'range': [-100, -50], 'color': '#d32f2f'}, 
                    {'range': [-50, 0], 'color': '#ef5350'},    
                    {'range': [0, 50], 'color': '#66bb6a'},     
                    {'range': [50, 100], 'color': '#2e7d32'},   
                ],
            }
        ))
        fig_meter1.update_layout(height=250, margin=dict(t=40, b=10, l=10, r=10), template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_meter1, use_container_width=True)

    with dash_c2:
        # 市場相位油錶 (1~6 相位)
        phase_names = ["1.深熊", "2.初牛", "3.狂暴牛", "4.見頂", "5.初熊", "6.尋底"]

        fig_meter2 = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=phase_num,
            domain={'x': [0, 1], 'y': [0, 1]},
            title={'text': f"市場狀態: {eff['emoji']} {eff['season_zh']}", 'font': {'size': 16, 'color': 'white'}},
            gauge={
                'axis': {'range': [1, 6], 'tickmode': 'array', 'tickvals': [1,2,3,4,5,6], 'ticktext': phase_names, 'tickcolor': "white"},
                'bar': {'color': phase_color},
                'bgcolor': "rgba(0,0,0,0)",
                'borderwidth': 2,
                'bordercolor': "gray",
                'steps': [
                    {'range': [1, 2], 'color': '#0d47a1'}, 
                    {'range': [2, 3], 'color': '#2e7d32'}, 
                    {'range': [3, 4], 'color': '#f57f17'}, 
                    {'range': [4, 5], 'color': '#d32f2f'}, 
                    {'range': [5, 6], 'color': '#e65100'}, 
                    {'range': [6, 7], 'color': '#1565c0'}, 
                ],
            }
        ))
        fig_meter2.update_layout(height=250, margin=dict(t=40, b=10, l=10, r=10), template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig_meter2, use_container_width=True)

    st.markdown("---")

    # ──────────────────────────────────────────────────────────────
    # 區塊 2: 細項指標評分卡片化 
    # ──────────────────────────────────────────────────────────────
    st.markdown("#### 2. 指標監測面板")
    c1, c2, c3 = st.columns(3)

    # 卡片 1: 資金與籌碼
    with c1:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### 💰 資金與籌碼面")
        st.metric("資金費率 (Funding Rate)", f"{proxies.get('funding_rate', 0):.4f}%")
        
        cex_flow = proxies.get('cex_flow', 0)
        cex_status = "⚠️ 數據暫不可用" if cex_flow == 0 else ("交易所淨流出 (吸籌)" if cex_flow < 0 else "交易所淨流入 (拋壓)")
        st.metric("CEX 資金流向 (24h)", f"{cex_flow:+.0f} BTC", cex_status, delta_color="normal" if cex_flow <= 0 else "inverse")
        
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

    bottom_score, signals = calculate_bear_bottom_score(curr)

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
                    {'range': [0, 30], 'color': '#1e1e1e'},   
                    {'range': [30, 60], 'color': '#fbc02d'},  
                    {'range': [60, 80], 'color': '#ff9800'},  
                    {'range': [80, 100], 'color': '#d32f2f'}, 
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
        
        col_idx = 0
        cols = st.columns(4)
        
        for name, data in signals.items():
            with cols[col_idx % 4]:
                hit = data['score'] > 0
                color = "#00e676" if hit else "#757575"
                icon = "✅" if hit else "❌"
                if data['value'] == '—':
                    icon = "⏳"
                    color = "#aaaaaa"
                
                st.markdown(f"""
                <div style="text-align:center; padding:5px; margin-bottom:10px; border:1px solid {color}; border-radius:5px; background-color:rgba(0,0,0,0.2);">
                    <div style="font-size:0.8rem; color:#aaa;">{name}</div>
                    <div style="font-size:1.1rem; font-weight:bold; color:{color};">{icon} {data['value']}</div>
                    <div style="font-size:0.7rem; color:#888;">{data['label']}</div>
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
        st.markdown(f"##### {si['emoji']} 當前時間季節: **{si['season_zh']}**")
        st.write(f"減半後第 {si.get('month_in_cycle', 0)} 個月 (週期進度 {si.get('cycle_progress', 0)*100:.1f}%)")
        
        st.markdown(f"**市場真實狀態**：{eff['emoji']} **{eff['season_zh']}**")
        
        # 顯示 v1.3 加入的市場修正警告
        if forecast and forecast.get("is_season_corrected"):
            st.warning(forecast.get("correction_reason", "市場狀態已修正"))
        elif forecast:
            st.success("目前時間季節與市場真實狀態吻合。")
            
        st.markdown(CARD_END, unsafe_allow_html=True)

    with fc_c2:
        st.markdown(CARD_STYLE, unsafe_allow_html=True)
        st.markdown("##### 🎯 週期目標預測")
        if forecast:
            st.metric(forecast.get("bear_label_low", "保守目標"), f"${forecast.get('target_low', 0):,.0f}")
            st.metric(forecast.get("bear_label_mid", "中位數目標"), f"${forecast.get('target_median', 0):,.0f}")
            st.metric(forecast.get("bear_label_high", "樂觀目標"), f"${forecast.get('target_high', 0):,.0f}")
        else:
            st.write("目前歷史資料不足以進行預測。")
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
    for col, (s_emoji, name, bg, desc) in zip(strat_cols, strategies):
        is_current = (s_emoji == eff["emoji"]) or (s_emoji == si["emoji"])
        border   = f"2px solid {phase_color}" if is_current else "1px solid #333"
        cur_tag  = (f"<div style='color:{phase_color};font-size:0.8rem;margin-top:8px;font-weight:600;'>← 當前季節</div>"
                    if is_current else "")
        col.markdown(
            f"""<div style="background:{bg}22;border:{border};border-radius:10px;padding:15px;height:100%;">
                <h4 style="margin:0;color:{bg}">{s_emoji} {name}</h4>
                <p style="font-size:0.9rem;color:#ddd;margin-top:10px;">{desc}</p>
                {cur_tag}
            </div>""",
            unsafe_allow_html=True
        )