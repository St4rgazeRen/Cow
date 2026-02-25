"""
handler/layout.py
頁面設定、全局 CSS、側邊欄

v2.0 重構：
  - 側邊欄精簡化，只保留「日期區間設定」與全域資訊
  - 移除各 Tab 專屬參數（capital / risk_per_trade / call_risk / put_risk / ahr_threshold）
    → 這些參數已移至各自 Tab 內部設定
"""
import streamlit as st
from datetime import datetime, timedelta

CUSTOM_CSS = """
<style>
    html, body, [class*="css"] { font-family: 'Roboto', sans-serif; }

    .metric-card {
        background-color: #1e1e1e;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .metric-title  { color: #888; font-size: 0.9rem; margin-bottom: 5px; }
    .metric-value  { color: #fff; font-size: 1.5rem; font-weight: bold; }
    .metric-delta  { font-size: 0.9rem; }
    .positive { color: #00ff88; }
    .negative { color: #ff4b4b; }
    .neutral  { color: #aaaaaa; }

    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background-color: #0e1117;
        border: 1px solid #333;
        border-radius: 4px;
        color: #fff;
    }
    .stTabs [aria-selected="true"] {
        background-color: #262730;
        border-bottom: 2px solid #00ff88;
    }

    /* Overview metric row */
    .overview-metric {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #2a2a4a;
        border-radius: 10px;
        padding: 14px 18px;
        text-align: center;
    }
</style>
"""


def setup_page():
    """設定頁面配置與 CSS"""
    st.set_page_config(
        page_title="比特幣投資戰情室 (Bitcoin Command Center)",
        page_icon="🦅",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_sidebar():
    """
    渲染側邊欄控制面板（精簡版 v2.0）

    只保留：
      1. 圖表日期區間（全域共用）
      2. 關於與免責聲明

    各策略專屬參數（capital, risk, call_risk, put_risk, ahr_threshold）
    已移至對應 Tab 內部，不在此設定。

    返回: dict，僅包含 c_start, c_end
    """
    with st.sidebar:
        st.header("⚙️ 戰情室設定")

        with st.expander("📊 圖表日期區間", expanded=True):
            default_start = datetime.now() - timedelta(days=365)
            c_start = st.date_input("起始日期", value=default_start)
            c_end   = st.date_input("結束日期",  value=datetime.now())

        st.markdown("---")
        st.markdown("### 關於與免責聲明")
        st.info("""
        **Antigravity v4 Engine**

        本工具僅供輔助分析，不構成投資建議。
        加密貨幣市場波動劇烈，請做好風險管理。

        各 Tab 內可分別設定對應策略參數。
        """)

    return {
        "c_start": c_start,
        "c_end":   c_end,
    }
