"""
handler/layout.py
頁面設定、全局 CSS、側邊欄
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
    渲染側邊欄控制面板
    返回: dict，包含所有使用者輸入參數
    """
    with st.sidebar:
        st.header("⚙️ 戰情室設定")
        capital = st.number_input("總本金 (USDT)", value=10_000, step=1_000)
        risk_per_trade = st.number_input(
            "單筆風險 (%)", value=2.0, step=0.1, max_value=10.0
        )

        st.markdown("---")
        st.caption("雙幣理財偏好設定")
        call_risk = st.number_input(
            "Sell High 風險係數", value=0.5, step=0.1, help="越大掛越遠 (保守)"
        )
        put_risk = st.number_input(
            "Buy Low 風險係數", value=0.5, step=0.1, help="越大掛越遠 (保守)"
        )

        st.markdown("---")
        st.caption("回測參數 (Tab 4 & 5)")
        ahr_threshold = st.slider("AHR999 抄底閾值", 0.3, 1.5, 0.45, 0.05)

        st.markdown("---")
        with st.expander("📊 圖表設定", expanded=True):
            default_start = datetime.now() - timedelta(days=365)
            c_start = st.date_input("起始日期", value=default_start)
            c_end = st.date_input("結束日期", value=datetime.now())

        st.markdown("---")
        st.markdown("### 關於與免責聲明")
        st.info("""
        **Antigravity v4 Engine**
        本工具僅供輔助分析，不構成投資建議。
        加密貨幣市場波動劇烈，請做好風險管理。
        """)

    return {
        "capital": capital,
        "risk_per_trade": risk_per_trade,
        "call_risk": call_risk,
        "put_risk": put_risk,
        "ahr_threshold": ahr_threshold,
        "c_start": c_start,
        "c_end": c_end,
    }
