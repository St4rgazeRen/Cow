"""
service/macro_data.py
宏觀經濟數據服務 — 全球流動性 M2、日圓匯率、美國 CPI、量子威脅等級

數據源（全部免費、無需 API Key）:
  - 美國 M2 週頻: FRED 公開 CSV API (WM2NS)
  - 日圓匯率: Yahoo Finance (USDJPY=X)
  - 美國 CPI: FRED 公開 CSV API (CPIAUCSL)
  - 量子威脅: 靜態評估（無即時 API，基於公開量子計算里程碑）

FRED 公開 CSV API 說明:
  端點: https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}
  - 無需 API Key，直接 GET 訪問
  - WM2NS  : 美國 M2 貨幣供應量（週頻，十億美元）
  - CPIAUCSL: 美國城市消費者物價指數（月頻，季節調整）
  - DEXJPUS : 美元兌日圓（日頻）
"""
import io
import math
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import streamlit as st

from config import SSL_VERIFY

# 不需要 API Key 的 FRED 公開 CSV 端點
_FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def _fred_fetch(series_id: str, timeout: int = 15) -> pd.DataFrame:
    """
    從 FRED 公開 CSV 端點抓取時間序列，返回 DatetimeIndex DataFrame。
    FRED 以 '.' 代表缺失值，需先替換為 NaN。
    """
    url = _FRED_CSV.format(sid=series_id)
    resp = requests.get(url, timeout=timeout, verify=SSL_VERIFY)
    resp.raise_for_status()
    df = pd.read_csv(
        io.StringIO(resp.text),
        parse_dates=["DATE"],
        index_col="DATE",
        na_values=["."],
    )
    # 強制轉為數字（FRED 偶爾回傳帶空白字元的字串）
    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    return df


@st.cache_data(ttl=86_400)  # M2 為週頻數據，每天快取一次即可
def fetch_m2_series() -> pd.DataFrame:
    """
    抓取美國 M2 貨幣供應量週頻歷史序列（FRED WM2NS）。
    作為全球流動性代理指標（美元為世界儲備貨幣，與全球 M2 相關性最高）。

    返回:
        pd.DataFrame  index=DATE（週頻）, columns=['m2_billions']
        單位: 十億美元（Billions of USD, Seasonally Adjusted）
        若抓取失敗: 空 DataFrame
    """
    try:
        df = _fred_fetch("WM2NS")
        df.columns = ["m2_billions"]
        return df
    except Exception as e:
        print(f"[M2] FRED WM2NS 抓取失敗: {e}")
        return pd.DataFrame(columns=["m2_billions"])


@st.cache_data(ttl=3_600)  # 匯率每小時刷新
def fetch_usdjpy() -> dict:
    """
    抓取當前 USD/JPY 匯率（Yahoo Finance USDJPY=X）。

    返回 dict:
        rate        : float  當前匯率（日圓/美元）, None 代表失敗
        change_pct  : float  日變化率（%）
        prev_close  : float  前收盤價
        trend       : str    '日圓貶值 (USD↑)' | '日圓升值 (USD↓)' | 'N/A'
        source      : str    數據來源標籤
    """
    try:
        # Yahoo Finance USDJPY=X = 每 1 美元兌換多少日圓
        hist = yf.download("USDJPY=X", period="5d", progress=False, auto_adjust=True)
        if hist.empty or len(hist) < 2:
            raise ValueError("Yahoo Finance USDJPY=X 無資料")

        # 處理 MultiIndex columns（yfinance 新版可能回傳 MultiIndex）
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        hist.columns = [c.lower() for c in hist.columns]

        latest = float(hist["close"].iloc[-1])
        prev   = float(hist["close"].iloc[-2])
        change = (latest / prev - 1) * 100

        return {
            "rate":       latest,
            "prev_close": prev,
            "change_pct": change,
            "trend":      "日圓貶值 (USD↑)" if change > 0.05 else (
                          "日圓升值 (USD↓)" if change < -0.05 else "橫盤"),
            "source":     "Yahoo Finance",
        }
    except Exception as e:
        print(f"[JPY] Yahoo Finance 抓取失敗: {e}")
        # Fallback: 嘗試 FRED DEXJPUS（日圓/美元，日頻）
        try:
            df = _fred_fetch("DEXJPUS")
            df.columns = ["jpy"]
            latest = float(df["jpy"].iloc[-1])
            prev   = float(df["jpy"].iloc[-2]) if len(df) >= 2 else latest
            change = (latest / prev - 1) * 100
            return {
                "rate":       latest,
                "prev_close": prev,
                "change_pct": change,
                "trend":      "日圓貶值 (USD↑)" if change > 0.05 else (
                              "日圓升值 (USD↓)" if change < -0.05 else "橫盤"),
                "source":     "FRED DEXJPUS",
            }
        except Exception as e2:
            print(f"[JPY] FRED DEXJPUS 也失敗: {e2}")
            return {"rate": None, "change_pct": None, "trend": "N/A", "source": "失敗"}


@st.cache_data(ttl=86_400)  # CPI 為月頻，每天快取一次
def fetch_us_cpi_yoy() -> dict:
    """
    抓取美國 CPI 年增率（FRED CPIAUCSL，月頻季節調整）。

    YoY 計算: (當月 CPI - 去年同月 CPI) / 去年同月 CPI × 100

    返回 dict:
        yoy_pct     : float  最新 CPI YoY（%），None 代表失敗
        latest_date : str    最新數據月份（格式 "YYYY-MM"）
        mom_pct     : float  環比（月增率 %）
        trend       : str    '通膨升溫 ↑' | '通膨降溫 ↓' | '穩定 →'
        source      : str    'FRED CPIAUCSL'
    """
    try:
        df = _fred_fetch("CPIAUCSL")
        df.columns = ["cpi"]
        df = df.sort_index()

        # YoY: 與去年同月比較（月頻 pct_change(12) = 12個月前）
        yoy = df["cpi"].pct_change(12) * 100
        mom = df["cpi"].pct_change(1) * 100  # 月增率

        yoy_curr = float(yoy.iloc[-1])
        yoy_prev = float(yoy.iloc[-2]) if len(yoy) >= 2 else yoy_curr
        mom_curr = float(mom.iloc[-1])

        # 判斷趨勢：連續兩個月 YoY 變化方向
        if yoy_curr > yoy_prev + 0.15:
            trend = "通膨升溫 ↑"
        elif yoy_curr < yoy_prev - 0.15:
            trend = "通膨降溫 ↓"
        else:
            trend = "穩定 →"

        return {
            "yoy_pct":     yoy_curr,
            "mom_pct":     mom_curr,
            "latest_date": df.index[-1].strftime("%Y-%m"),
            "trend":       trend,
            "source":      "FRED CPIAUCSL",
        }
    except Exception as e:
        print(f"[CPI] FRED CPIAUCSL 抓取失敗: {e}")
        return {
            "yoy_pct": None, "mom_pct": None,
            "latest_date": "N/A", "trend": "N/A", "source": "失敗",
        }


def get_quantum_threat_level() -> dict:
    """
    量子計算對比特幣威脅等級的靜態評估。

    威脅模型:
    - 比特幣使用 secp256k1 橢圓曲線加密，256 位元密鑰
    - Shor 演算法可破解，所需量子資源估算:
        ~400 萬實體量子位元（容錯邏輯位元: ~4,000）
    - 現況 (2026): IBM Heron r2 = 156 物理位元，Google Willow = 105 物理位元
    - 容錯量子電腦距成熟仍需 10-20 年

    NIST PQC 參考: https://csrc.nist.gov/projects/post-quantum-cryptography
    (NIST 後量子密碼標準已於 2024 年正式發布 ML-KEM/ML-DSA/SLH-DSA)

    返回 dict:
        level     : str  威脅等級文字
        level_num : int  1-5（1=最低）
        color     : str  顯示顏色（hex）
        status    : str  簡短狀態
        desc      : str  詳細說明
        year_est  : str  預估威脅成熟年份
        ref_url   : str  參考連結
    """
    # 2026 年評估: Level 1 (Very Low)
    # 現有最佳量子電腦距破解 Bitcoin 仍有 3-4 個數量級的差距
    return {
        "level":     "極低",          # 縮短文字避免 st.metric 截斷
        "level_num": 1,
        "color":     "#00ff88",
        "status":    "🟢 目前無威脅 (Level 1/5)",
        "desc": (
            "Google Willow: 105 物理量子位元｜IBM Heron r2: 156 位元\n"
            "破解 secp256k1 需 ~400 萬容錯實體位元，差距 4 個數量級\n"
            "NIST PQC 標準已於 2024 正式發布 (ML-KEM / ML-DSA)"
        ),
        "year_est": "2035–2045+",
        "ref_url":  "https://csrc.nist.gov/projects/post-quantum-cryptography",
        "updated":  "2026-Q1 靜態評估",
    }
