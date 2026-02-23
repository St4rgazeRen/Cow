"""
core/bear_bottom.py
熊市底部獵人 — 指標計算與複合評分系統
純 Python，無 Streamlit 依賴
"""
import math
import numpy as np
import pandas as pd
import pandas_ta as ta
from datetime import datetime


def calculate_bear_bottom_indicators(df):
    """
    計算 6 大熊市底部識別指標:
    1. Pi Cycle Bottom (SMA_111 vs 2×SMA_350)
    2. 200-Week SMA (SMA_1400)
    3. Puell Multiple Proxy (Price / SMA_365)
    4. Monthly RSI
    5. Power Law Support (Giovanni Santostasi 冪律模型)
    6. Mayer Multiple (Price / SMA_730)
    """
    df = df.copy()
    if df.empty:
        return df

    # 1. Pi Cycle Bottom
    df['SMA_111'] = ta.sma(df['close'], length=111)
    df['SMA_350'] = ta.sma(df['close'], length=350)
    df['SMA_350x2'] = df['SMA_350'] * 2
    df['PiCycle_Gap'] = (df['SMA_111'] / df['SMA_350x2'] - 1) * 100

    # 2. 200-Week SMA (1400 days)
    df['SMA_1400'] = ta.sma(df['close'], length=1400)
    df['SMA200W_Ratio'] = df['close'] / df['SMA_1400'].where(df['SMA_1400'] > 0)

    # 3. Puell Multiple Proxy
    df['SMA_365'] = ta.sma(df['close'], length=365)
    df['Puell_Proxy'] = df['close'] / df['SMA_365'].where(df['SMA_365'] > 0)

    # 4. Monthly RSI
    monthly_close = df['close'].resample('MS').last()
    monthly_rsi = ta.rsi(monthly_close, length=14)
    df['RSI_Monthly'] = monthly_rsi.reindex(df.index).ffill()

    # 5. Power Law Support
    genesis_date = datetime(2009, 1, 3)
    days_arr = np.array([
        (d.to_pydatetime() - genesis_date).days
        if hasattr(d, 'to_pydatetime') else (d - genesis_date).days
        for d in df.index
    ], dtype=float)
    days_arr = np.clip(days_arr, 1, None)
    df['PowerLaw_Support'] = 10 ** (-17.01467 + 5.84 * np.log10(days_arr))
    df['PowerLaw_Ratio'] = df['close'] / df['PowerLaw_Support'].where(df['PowerLaw_Support'] > 0)

    # 6. Mayer Multiple (2年均線)
    df['SMA_730'] = ta.sma(df['close'], length=730)
    df['Mayer_Multiple'] = df['close'] / df['SMA_730'].where(df['SMA_730'] > 0)

    return df


def calculate_bear_bottom_score(row):
    """
    綜合熊市底部評分系統 (0-100分)
    分數越高 = 越接近歷史性底部，積累信號越強

    評分區間:
    - 0-25:  牛市/高估區，非抄底時機
    - 25-45: 震盪修正，觀望
    - 45-60: 可能底部區，開始小倉試探
    - 60-75: 底部信號明確，積極積累
    - 75-100: 歷史極值底部，All-In 信號

    返回: (score: int, signals: dict)
    """
    score = 0
    signals = {}

    def _is_nan(v):
        return v is None or (isinstance(v, float) and math.isnan(v))

    # 1. AHR999 囤幣指標 (最高 20 分)
    ahr = row.get('AHR999')
    if not _is_nan(ahr):
        if ahr < 0.45:
            s, label = 20, "🟢 歷史抄底區 (<0.45)"
        elif ahr < 0.8:
            s, label = 13, "🟡 偏低估 (0.45-0.8)"
        elif ahr < 1.2:
            s, label = 5, "⚪ 合理區間 (0.8-1.2)"
        else:
            s, label = 0, "🔴 高估 (>1.2)"
        score += s
        signals['AHR999'] = {'value': f"{ahr:.3f}", 'score': s, 'max': 20, 'label': label}

    # 2. MVRV Z-Score Proxy (最高 18 分)
    mvrv = row.get('MVRV_Z_Proxy')
    if not _is_nan(mvrv):
        if mvrv < -1.0:
            s, label = 18, "🟢 強力底部 (Z<-1)"
        elif mvrv < 0:
            s, label = 12, "🟡 低估 (-1~0)"
        elif mvrv < 2.0:
            s, label = 4, "⚪ 中性 (0~2)"
        else:
            s, label = 0, "🔴 高估/頂部 (>2)"
        score += s
        signals['MVRV_Z_Proxy'] = {'value': f"{mvrv:.2f}", 'score': s, 'max': 18, 'label': label}

    # 3. Pi Cycle Gap (最高 15 分)
    pi_gap = row.get('PiCycle_Gap')
    if not _is_nan(pi_gap):
        if pi_gap < -10:
            s, label = 15, "🟢 Pi週期深度底部區"
        elif pi_gap < -3:
            s, label = 10, "🟡 Pi週期底部接近"
        elif pi_gap < 5:
            s, label = 4, "⚪ Pi週期中性"
        else:
            s, label = 0, "🔴 遠離Pi週期底部"
        score += s
        signals['Pi_Cycle'] = {'value': f"{pi_gap:.1f}%", 'score': s, 'max': 15, 'label': label}

    # 4. 200-Week SMA Ratio (最高 15 分)
    sma200w = row.get('SMA200W_Ratio')
    if not _is_nan(sma200w):
        if sma200w < 1.0:
            s, label = 15, "🟢 跌破200週均 (歷史絕對底部)"
        elif sma200w < 1.3:
            s, label = 11, "🟡 接近200週均 (<1.3x)"
        elif sma200w < 2.0:
            s, label = 5, "⚪ 正常範圍 (1.3-2x)"
        elif sma200w < 4.0:
            s, label = 1, "🔴 偏高 (2-4x)"
        else:
            s, label = 0, "🔴🔴 極度高估 (>4x)"
        score += s
        signals['SMA_200W'] = {'value': f"{sma200w:.2f}x", 'score': s, 'max': 15, 'label': label}

    # 5. Puell Multiple Proxy (最高 12 分)
    puell = row.get('Puell_Proxy')
    if not _is_nan(puell):
        if puell < 0.5:
            s, label = 12, "🟢 礦工恐慌/投降 (底部信號)"
        elif puell < 0.8:
            s, label = 8, "🟡 礦工承壓"
        elif puell < 1.5:
            s, label = 3, "⚪ 礦工正常獲利"
        else:
            s, label = 0, "🔴 礦工獲利豐厚/暴利"
        score += s
        signals['Puell_Multiple'] = {'value': f"{puell:.2f}", 'score': s, 'max': 12, 'label': label}

    # 6. Monthly RSI (最高 10 分)
    rsi_m = row.get('RSI_Monthly')
    if not _is_nan(rsi_m):
        if rsi_m < 30:
            s, label = 10, "🟢 月線嚴重超賣"
        elif rsi_m < 40:
            s, label = 7, "🟡 月線超賣"
        elif rsi_m < 55:
            s, label = 2, "⚪ 月線中性"
        else:
            s, label = 0, "🔴 月線強勢"
        score += s
        signals['RSI_Monthly'] = {'value': f"{rsi_m:.1f}", 'score': s, 'max': 10, 'label': label}

    # 7. Power Law Ratio (最高 5 分)
    pl_ratio = row.get('PowerLaw_Ratio')
    if not _is_nan(pl_ratio):
        if pl_ratio < 2.0:
            s, label = 5, "🟢 接近冪律支撐線"
        elif pl_ratio < 5.0:
            s, label = 3, "🟡 略高於冪律支撐"
        elif pl_ratio < 10.0:
            s, label = 1, "⚪ 正常範圍"
        else:
            s, label = 0, "🔴 遠高於冪律支撐"
        score += s
        signals['PowerLaw'] = {'value': f"{pl_ratio:.1f}x", 'score': s, 'max': 5, 'label': label}

    # 8. Mayer Multiple (最高 5 分)
    mayer = row.get('Mayer_Multiple')
    if not _is_nan(mayer):
        if mayer < 0.8:
            s, label = 5, "🟢 低於2年均線 (極度低估)"
        elif mayer < 1.0:
            s, label = 3, "🟡 低於2年均線"
        elif mayer < 1.5:
            s, label = 1, "⚪ 合理範圍"
        else:
            s, label = 0, "🔴 高於2年均線"
        score += s
        signals['Mayer_Multiple'] = {'value': f"{mayer:.2f}x", 'score': s, 'max': 5, 'label': label}

    return score, signals
