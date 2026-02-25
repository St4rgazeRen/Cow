"""
core/season_forecast.py
四季理論目標價預測系統
─────────────────────────────────────────────────────────────────────
比特幣減半週期四季定義（以最近一次減半日起算）:
  Spring 春 (月  0-11): 減半後復甦，多頭啟動
  Summer 夏 (月 12-23): 牛市高峰，預測最高價
  Autumn 秋 (月 24-35): 泡沫破裂，空頭開始
  Winter 冬 (月 36-47): 熊市底部，預測最低價

歷史減半日:
  Halving 1: 2012-11-28
  Halving 2: 2016-07-09
  Halving 3: 2020-05-11
  Halving 4: 2024-04-19  ← 最新
  Halving 5: ~2028-04-xx (預估)

預測邏輯:
  1. 判斷當前處於哪個減半週期的哪個「季」
  2. 根據歷史各週期的漲跌倍數（中位數）計算目標價
  3. 牛季 → 預測未來12個月最高價 (以當前價 × 牛市目標倍數)
  4. 熊季 → 預測未來12個月最低價 (以前一個牛市高點 × 熊市折損比)
  5. 提供信心區間（25th ~ 75th 百分位）

純 Python，無 Streamlit 依賴
"""

from datetime import datetime, timedelta
import numpy as np
import pandas as pd


# ──────────────────────────────────────────────────────────────────
# 歷史減半日
# ──────────────────────────────────────────────────────────────────
HALVING_DATES = [
    datetime(2012, 11, 28),
    datetime(2016, 7,   9),
    datetime(2020, 5,  11),
    datetime(2024, 4,  19),
    datetime(2028, 4,  17),   # 預估值
]

# ──────────────────────────────────────────────────────────────────
# 歷史四季統計（手動整理自各週期真實數據）
# peak_mult   : 牛市最高點 / 減半時價格 (ATH multiple from halving price)
# bottom_mult : 熊市最低點 / 前一個牛市ATH (drawdown from ATH to bear bottom)
# peak_days   : 減半後幾天達到牛市高點
# bottom_days : 減半後幾天達到熊市最低點
# ──────────────────────────────────────────────────────────────────
CYCLE_HISTORY = [
    {
        "halving": datetime(2012, 11, 28),
        "halving_price": 12.35,
        "ath_price":     1163.0,   # 2013-11-29
        "ath_date":      datetime(2013, 11, 29),
        "bear_low":      152.40,   # 2015-01-14
        "bear_low_date": datetime(2015, 1, 14),
        "peak_mult":     94.2,     # 1163 / 12.35
        "bottom_mult":   0.131,    # 152.4 / 1163
        "peak_days":     366,
        "bottom_days":   777,
    },
    {
        "halving": datetime(2016, 7, 9),
        "halving_price": 650.0,
        "ath_price":     19891.0,  # 2017-12-17
        "ath_date":      datetime(2017, 12, 17),
        "bear_low":      3122.0,   # 2018-12-15
        "bear_low_date": datetime(2018, 12, 15),
        "peak_mult":     30.6,     # 19891 / 650
        "bottom_mult":   0.157,    # 3122 / 19891
        "peak_days":     526,
        "bottom_days":   889,
    },
    {
        "halving": datetime(2020, 5, 11),
        "halving_price": 8571.0,
        "ath_price":     68789.0,  # 2021-11-10
        "ath_date":      datetime(2021, 11, 10),
        "bear_low":      15476.0,  # 2022-11-21
        "bear_low_date": datetime(2022, 11, 21),
        "peak_mult":     8.03,     # 68789 / 8571
        "bottom_mult":   0.225,    # 15476 / 68789
        "peak_days":     549,
        "bottom_days":   925,
    },
]

# ──────────────────────────────────────────────────────────────────
# 計算歷史統計中位數與分位數
# ──────────────────────────────────────────────────────────────────
_peak_mults   = [c["peak_mult"]   for c in CYCLE_HISTORY]
_bottom_mults = [c["bottom_mult"] for c in CYCLE_HISTORY]
_peak_days_list   = [c["peak_days"]   for c in CYCLE_HISTORY]
_bottom_days_list = [c["bottom_days"] for c in CYCLE_HISTORY]

# 對數空間中位數（減少極端值影響）
STATS = {
    "peak_mult_median":    float(np.exp(np.median(np.log(_peak_mults)))),
    "peak_mult_p25":       float(np.exp(np.percentile(np.log(_peak_mults), 25))),
    "peak_mult_p75":       float(np.exp(np.percentile(np.log(_peak_mults), 75))),
    "bottom_mult_median":  float(np.median(_bottom_mults)),
    "bottom_mult_p25":     float(np.percentile(_bottom_mults, 25)),
    "bottom_mult_p75":     float(np.percentile(_bottom_mults, 75)),
    "peak_days_median":    int(np.median(_peak_days_list)),
    "bottom_days_median":  int(np.median(_bottom_days_list)),
}


def get_current_season(as_of: datetime = None):
    """
    計算當前處於哪個減半週期的哪個「季」。

    返回 dict:
      season        : 'spring' | 'summer' | 'autumn' | 'winter'
      season_zh     : 中文季節名稱
      emoji         : 季節 emoji
      halving_date  : 當前週期減半日
      next_halving  : 下一次減半日
      days_since    : 距當前減半已過幾天
      days_to_next  : 距下一次減半還有幾天
      cycle_progress: 0.0 ~ 1.0，週期完成進度
      month_in_cycle: 0 ~ 47，週期中的月份
    """
    if as_of is None:
        as_of = datetime.utcnow()

    # 找出最近一次已發生的減半
    past_halvings = [h for h in HALVING_DATES if h <= as_of]
    if not past_halvings:
        return None
    current_halving = past_halvings[-1]

    # 下一次減半
    future_halvings = [h for h in HALVING_DATES if h > as_of]
    next_halving = future_halvings[0] if future_halvings else current_halving + timedelta(days=1460)

    days_since = (as_of - current_halving).days
    days_total = (next_halving - current_halving).days
    days_to_next = (next_halving - as_of).days
    month_in_cycle = int(days_since / 30.44)  # 近似月份

    cycle_progress = min(days_since / days_total, 1.0)

    if month_in_cycle < 12:
        season, season_zh, emoji = "spring", "春季 — 復甦期", "🌱"
    elif month_in_cycle < 24:
        season, season_zh, emoji = "summer", "夏季 — 牛市高峰", "☀️"
    elif month_in_cycle < 36:
        season, season_zh, emoji = "autumn", "秋季 — 泡沫破裂", "🍂"
    else:
        season, season_zh, emoji = "winter", "冬季 — 熊市底部", "❄️"

    return {
        "season":         season,
        "season_zh":      season_zh,
        "emoji":          emoji,
        "halving_date":   current_halving,
        "next_halving":   next_halving,
        "days_since":     days_since,
        "days_to_next":   days_to_next,
        "cycle_progress": cycle_progress,
        "month_in_cycle": month_in_cycle,
    }


def _apply_diminishing_returns(base_mult: float, cycle_index: int) -> float:
    """
    每個週期牛市漲幅遞減約 3-4 倍。
    cycle_index: 0=第1次減半, 1=第2次, 2=第3次, 3=第4次(當前)...
    以第3週期(2020)為基準做外插。
    """
    # 歷史漲幅遞減比: 94.2 → 30.6 → 8.03 → 預測約 3-5x
    # 每週期約縮減至前週期的 1/3.5
    diminish_factor = 3.5
    ref_cycle = len(CYCLE_HISTORY) - 1  # 最後一個已知週期 index
    delta = cycle_index - ref_cycle
    if delta <= 0:
        return base_mult
    return base_mult / (diminish_factor ** delta)


def forecast_price(current_price: float, df: pd.DataFrame = None, as_of: datetime = None):
    """
    主要預測函數。根據四季理論預測未來12個月目標價。

    參數:
      current_price : 當前 BTC 價格 (USD)
      df            : BTC 日線 DataFrame，含 'close' 欄位（用於計算前高）
      as_of         : 預測基準時間（預設 UTC 今日）

    返回 dict:
      season_info       : get_current_season() 結果
      forecast_type     : 'bull_peak' | 'bear_bottom'
      target_median     : 中位數目標價
      target_low        : 樂觀/悲觀下界（25th pct）
      target_high       : 樂觀/悲觀上界（75th pct）
      estimated_date    : 預計達到目標的日期
      rationale         : 預測邏輯說明
      confidence        : 信心分數 0-100
      current_cycle_idx : 當前週期索引（0-based）
      halving_price     : 當前週期減半時價格（若可從 df 取得）
      prev_ath          : 前一個牛市 ATH（熊市預測用）
    """
    if as_of is None:
        as_of = datetime.utcnow()

    season_info = get_current_season(as_of)
    if season_info is None:
        return None

    current_halving = season_info["halving_date"]
    current_cycle_idx = HALVING_DATES.index(current_halving)  # 0-based

    # ── 從 df 取得減半當天價格與前一牛市 ATH ──
    halving_price = current_price   # 預設用當前價（若無 df）
    prev_ath = None

    if df is not None and not df.empty and "close" in df.columns:
        # 減半當天價格
        halving_mask = df.index >= pd.Timestamp(current_halving)
        if halving_mask.any():
            halving_price = float(df.loc[halving_mask, "close"].iloc[0])

        # 前一個牛市 ATH：從上一次減半到當前減半之間的最高收盤價
        if current_cycle_idx > 0:
            prev_halving = HALVING_DATES[current_cycle_idx - 1]
            mask_prev = (df.index >= pd.Timestamp(prev_halving)) & (df.index < pd.Timestamp(current_halving))
            if mask_prev.any():
                prev_ath = float(df.loc[mask_prev, "close"].max())

    # 若無前一 ATH，用歷史最後一筆
    if prev_ath is None and len(CYCLE_HISTORY) > 0:
        prev_ath = CYCLE_HISTORY[-1]["ath_price"]

    season = season_info["season"]
    days_since = season_info["days_since"]

    # ── 計算當前週期調整後倍數（遞減規律） ──
    base_peak_mult   = STATS["peak_mult_median"]
    base_peak_p25    = STATS["peak_mult_p25"]
    base_peak_p75    = STATS["peak_mult_p75"]

    adj_peak_med  = _apply_diminishing_returns(base_peak_mult, current_cycle_idx)
    adj_peak_p25  = _apply_diminishing_returns(base_peak_p25,  current_cycle_idx)
    adj_peak_p75  = _apply_diminishing_returns(base_peak_p75,  current_cycle_idx)

    # ── 依季節選擇預測邏輯 ──
    if season in ("spring", "summer"):
        # ── 牛市：預測未來12個月最高價 ──
        forecast_type = "bull_peak"

        # 從減半價計算 ATH 目標
        ath_target_med = halving_price * adj_peak_med
        ath_target_p25 = halving_price * adj_peak_p25
        ath_target_p75 = halving_price * adj_peak_p75

        # 若當前價已超過中位數目標，以當前價為基礎往上加成
        if current_price > ath_target_med:
            # 仍在上升趨勢，目標以當前價 × 殘餘漲幅估算
            remaining_mult = adj_peak_p75 / adj_peak_med
            ath_target_med = current_price * remaining_mult
            ath_target_p75 = ath_target_med * 1.3
            ath_target_p25 = ath_target_med * 0.75

        target_median = max(ath_target_med, current_price)
        target_low    = max(ath_target_p25, current_price)
        target_high   = max(ath_target_p75, current_price)

        # 預計達到牛市高點的日期
        days_to_peak = max(STATS["peak_days_median"] - days_since, 30)
        estimated_date = as_of + timedelta(days=days_to_peak)

        rationale = (
            f"當前處於第 {current_cycle_idx+1} 次減半後{season_info['season_zh']}。\n"
            f"歷史中位數：減半後約 {STATS['peak_days_median']} 天達到牛市高點，"
            f"相對減半價漲幅中位數 {adj_peak_med:.1f}x。\n"
            f"減半時價格: ${halving_price:,.0f}，"
            f"預計牛市高點區間: ${target_low:,.0f} ~ ${target_high:,.0f}。"
        )

        # 信心分數：距預計高點越近，信心越高
        confidence = min(int(80 - abs(days_since - STATS["peak_days_median"]) / 5), 85)
        confidence = max(confidence, 40)

    else:
        # ── 熊市：預測未來12個月最低價 ──
        forecast_type = "bear_bottom"

        ath_ref = prev_ath if prev_ath else current_price * 1.5

        bottom_med = ath_ref * STATS["bottom_mult_median"]
        bottom_p25 = ath_ref * STATS["bottom_mult_p25"]   # 更深的底
        bottom_p75 = ath_ref * STATS["bottom_mult_p75"]   # 較淺的底

        # 若當前價已低於中位數目標，調整
        target_median = min(bottom_med, current_price)
        target_low    = min(bottom_p25, current_price)   # 最壞情況
        target_high   = min(bottom_p75, current_price)   # 最好情況（底部較淺）

        days_to_bottom = max(STATS["bottom_days_median"] - days_since, 30)
        estimated_date = as_of + timedelta(days=days_to_bottom)

        rationale = (
            f"當前處於第 {current_cycle_idx+1} 次減半後{season_info['season_zh']}。\n"
            f"歷史中位數：減半後約 {STATS['bottom_days_median']} 天達到熊市底部，"
            f"前一牛市高點跌幅中位數 {STATS['bottom_mult_median']*100:.0f}%。\n"
            f"前一牛市 ATH 參考: ${ath_ref:,.0f}，"
            f"預計熊市底部區間: ${target_low:,.0f} ~ ${target_high:,.0f}。"
        )

        confidence = min(int(80 - abs(days_since - STATS["bottom_days_median"]) / 5), 80)
        confidence = max(confidence, 35)

    return {
        "season_info":       season_info,
        "forecast_type":     forecast_type,
        "target_median":     round(target_median, 0),
        "target_low":        round(target_low,    0),
        "target_high":       round(target_high,   0),
        "estimated_date":    estimated_date,
        "rationale":         rationale,
        "confidence":        confidence,
        "current_cycle_idx": current_cycle_idx,
        "halving_price":     round(halving_price, 0),
        "prev_ath":          round(prev_ath, 0) if prev_ath else None,
    }


def get_cycle_comparison_table():
    """
    返回歷史各週期比較表 (pd.DataFrame)，供 UI 顯示。
    """
    rows = []
    for i, c in enumerate(CYCLE_HISTORY):
        rows.append({
            "週期":            f"第 {i+1} 次減半",
            "減半日":          c["halving"].strftime("%Y-%m-%d"),
            "減半時價格":      f"${c['halving_price']:,.0f}",
            "牛市 ATH":        f"${c['ath_price']:,.0f}",
            "ATH 倍數":        f"{c['peak_mult']:.1f}x",
            "達 ATH 天數":     f"{c['peak_days']} 天",
            "熊市最低點":      f"${c['bear_low']:,.0f}",
            "ATH 跌幅":        f"{(1-c['bottom_mult'])*100:.0f}%",
            "達底部天數":      f"{c['bottom_days']} 天",
        })
    return pd.DataFrame(rows)


def get_power_law_forecast(df: pd.DataFrame, months_ahead: int = 12):
    """
    冪律模型：計算未來 months_ahead 個月的價格走廊（中線、±1σ 對數通道）。
    返回 pd.DataFrame，index 為未來日期，欄位: median, upper, lower
    """
    from datetime import datetime as dt
    genesis = dt(2009, 1, 3)
    future_dates = pd.date_range(
        start=datetime.utcnow() + timedelta(days=1),
        periods=months_ahead * 30,
        freq="D"
    )
    days_arr = np.array([(d.to_pydatetime() - genesis).days for d in future_dates], dtype=float)
    days_arr = np.clip(days_arr, 1, None)

    log_median = -17.01467 + 5.84 * np.log10(days_arr)
    log_upper  = log_median + 0.45   # 歷史 +1σ 對數通道
    log_lower  = log_median - 0.45

    result = pd.DataFrame({
        "median": 10 ** log_median,
        "upper":  10 ** log_upper,
        "lower":  10 ** log_lower,
    }, index=future_dates)
    return result