"""
core/season_forecast.py
四季理論目標價預測系統
─────────────────────────────────────────────────────────────────────
比特幣減半週期四季定義（時間 + 真實市場狀態雙重校正）:

  Spring 春 (月  0-11): 減半後復甦，多頭啟動
  Summer 夏 (月 12-23): 牛市高峰，預測最高價
  Autumn 秋 (月 24-35): 泡沫破裂，空頭開始
  Winter 冬 (月 36-47): 熊市底部，預測最低價

[重要] 市場狀態校正邏輯:
  純時間季節 (time_season) 僅作為「參考基礎」。
  系統同時計算「真實市場季節 (real_season)」，當兩者衝突時，
  以真實市場狀態為主，顯示警告並調整預測方向。

  真實市場季節判斷規則（優先序由高到低）:
    R1. 跌幅 > 30% AND 年線下方 → 強制 winter（深熊）
    R2. 跌幅 > 20% AND 年線下方 → 強制 autumn（熊市初期）
    R3. 跌幅 > 15% AND 年線下方 AND 時間在春/夏 → 提前入秋
    R4. 跌幅 10-15% AND 年線下方 AND 時間在春/夏 → 牛市受阻（秋）
    R5. 跌幅 < 10% OR 年線上方 → 維持時間季節

歷史減半日:
  Halving 1: 2012-11-28
  Halving 2: 2016-07-09
  Halving 3: 2020-05-11
  Halving 4: 2024-04-19
  Halving 5: ~2028-04-17 (預估)

純 Python，無 Streamlit 依賴
"""

from datetime import datetime, timedelta
import numpy as np
import pandas as pd


HALVING_DATES = [
    datetime(2012, 11, 28),
    datetime(2016, 7,   9),
    datetime(2020, 5,  11),
    datetime(2024, 4,  19),
    datetime(2028, 4,  17),
]

CYCLE_HISTORY = [
    {
        "halving":       datetime(2012, 11, 28),
        "halving_price": 12.35,
        "ath_price":     1163.0,
        "ath_date":      datetime(2013, 11, 29),
        "bear_low":      152.40,
        "bear_low_date": datetime(2015, 1, 14),
        "peak_mult":     94.2,
        "bottom_mult":   0.131,
        "peak_days":     366,
        "bottom_days":   777,
    },
    {
        "halving":       datetime(2016, 7, 9),
        "halving_price": 650.0,
        "ath_price":     19891.0,
        "ath_date":      datetime(2017, 12, 17),
        "bear_low":      3122.0,
        "bear_low_date": datetime(2018, 12, 15),
        "peak_mult":     30.6,
        "bottom_mult":   0.157,
        "peak_days":     526,
        "bottom_days":   889,
    },
    {
        "halving":       datetime(2020, 5, 11),
        "halving_price": 8571.0,
        "ath_price":     68789.0,
        "ath_date":      datetime(2021, 11, 10),
        "bear_low":      15476.0,
        "bear_low_date": datetime(2022, 11, 21),
        "peak_mult":     8.03,
        "bottom_mult":   0.225,
        "peak_days":     549,
        "bottom_days":   925,
    },
]

_peak_mults       = [c["peak_mult"]   for c in CYCLE_HISTORY]
_bottom_mults     = [c["bottom_mult"] for c in CYCLE_HISTORY]
_peak_days_list   = [c["peak_days"]   for c in CYCLE_HISTORY]
_bottom_days_list = [c["bottom_days"] for c in CYCLE_HISTORY]

STATS = {
    "peak_mult_median":   float(np.exp(np.median(np.log(_peak_mults)))),
    "peak_mult_p25":      float(np.exp(np.percentile(np.log(_peak_mults), 25))),
    "peak_mult_p75":      float(np.exp(np.percentile(np.log(_peak_mults), 75))),
    "bottom_mult_median": float(np.median(_bottom_mults)),
    "bottom_mult_p25":    float(np.percentile(_bottom_mults, 25)),
    "bottom_mult_p75":    float(np.percentile(_bottom_mults, 75)),
    "peak_days_median":   int(np.median(_peak_days_list)),
    "bottom_days_median": int(np.median(_bottom_days_list)),
}


def analyze_market_state(current_price: float, df: pd.DataFrame, current_halving: datetime):
    """
    分析真實市場狀態。
    返回 dict: cycle_ath, cycle_ath_date, drawdown_from_ath,
               price_vs_sma200, sma200, is_above_sma200
    """
    result = {
        "cycle_ath":         current_price,
        "cycle_ath_date":    datetime.utcnow(),
        "drawdown_from_ath": 0.0,
        "price_vs_sma200":   1.0,
        "sma200":            current_price,
        "is_above_sma200":   True,
    }

    if df is None or df.empty or "close" not in df.columns:
        return result

    mask_cycle = df.index >= pd.Timestamp(current_halving)
    if mask_cycle.any():
        cycle_data   = df.loc[mask_cycle, "close"]
        cycle_ath    = float(cycle_data.max())
        cycle_ath_dt = cycle_data.idxmax()
        if hasattr(cycle_ath_dt, "to_pydatetime"):
            cycle_ath_dt = cycle_ath_dt.to_pydatetime()
        result["cycle_ath"]      = cycle_ath
        result["cycle_ath_date"] = cycle_ath_dt

    result["drawdown_from_ath"] = (current_price - result["cycle_ath"]) / result["cycle_ath"]

    sma200 = float(df["close"].rolling(200).mean().iloc[-1]) if len(df) >= 200 else float(df["close"].mean())
    result["sma200"]          = sma200
    result["price_vs_sma200"] = current_price / sma200 if sma200 > 0 else 1.0
    result["is_above_sma200"] = current_price > sma200

    return result


def _derive_real_season(time_season, drawdown, is_above_sma200, month_in_cycle):
    """
    根據真實市場狀態推導有效季節。
    返回: (real_season, real_season_zh, real_emoji, correction_reason, is_corrected)
    """
    # R1: 深熊
    if drawdown < -0.30 and not is_above_sma200:
        reason = (f"⚠️ 市場校正：從當前週期 ATH 跌幅 {abs(drawdown)*100:.1f}%，"
                  f"已跌破年線，實際處於深熊（冬季）。時間季節（{time_season}）僅供參考。")
        return "winter", "冬季 — 深熊底部", "❄️", reason, time_season not in ("autumn", "winter")

    # R2: 熊市初期
    if drawdown < -0.20 and not is_above_sma200:
        reason = (f"⚠️ 市場校正：從當前週期 ATH 跌幅 {abs(drawdown)*100:.1f}%，"
                  f"已跌破年線，實際處於熊市初期（秋季）。時間季節（{time_season}）僅供參考。")
        return "autumn", "秋季 — 熊市初期", "🍂", reason, time_season not in ("autumn", "winter")

    # R3: 提前入秋（時間仍在春/夏）
    if drawdown < -0.15 and not is_above_sma200 and time_season in ("spring", "summer"):
        reason = (f"⚠️ 市場校正：時間位置為{time_season}（月{month_in_cycle}），"
                  f"但跌幅 {abs(drawdown)*100:.1f}% 且跌破年線，提前進入秋季修正。")
        return "autumn", "秋季 — 提前入秋", "🍂", reason, True

    # R4: 牛市受阻
    if drawdown < -0.10 and not is_above_sma200 and time_season in ("spring", "summer"):
        reason = (f"⚠️ 市場警示：跌幅 {abs(drawdown)*100:.1f}% 且跌破年線，"
                  f"牛市動能受阻，以秋季修正視角預測。")
        return "autumn", "秋季 — 牛市受阻", "🍂", reason, True

    # R5: 正常，維持時間季節
    label_map = {
        "spring": ("春季 — 復甦期",    "🌱"),
        "summer": ("夏季 — 牛市高峰",  "☀️"),
        "autumn": ("秋季 — 泡沫破裂",  "🍂"),
        "winter": ("冬季 — 熊市底部",  "❄️"),
    }
    s_zh, emoji = label_map.get(time_season, ("未知", "❓"))
    return time_season, s_zh, emoji, None, False


def get_current_season(as_of: datetime = None):
    """
    計算「時間季節」（純減半週期時間位置，不含市場校正）。
    """
    if as_of is None:
        as_of = datetime.utcnow()

    past_halvings = [h for h in HALVING_DATES if h <= as_of]
    if not past_halvings:
        return None
    current_halving = past_halvings[-1]

    future_halvings = [h for h in HALVING_DATES if h > as_of]
    next_halving    = future_halvings[0] if future_halvings else current_halving + timedelta(days=1460)

    days_since     = (as_of - current_halving).days
    days_total     = (next_halving - current_halving).days
    days_to_next   = (next_halving - as_of).days
    month_in_cycle = int(days_since / 30.44)
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
    diminish_factor = 3.5
    ref_cycle = len(CYCLE_HISTORY) - 1
    delta = cycle_index - ref_cycle
    if delta <= 0:
        return base_mult
    return base_mult / (diminish_factor ** delta)


def forecast_price(current_price: float, df: pd.DataFrame = None, as_of: datetime = None):
    """
    主要預測函數。整合時間季節 + 真實市場狀態，預測未來12個月目標價。
    """
    if as_of is None:
        as_of = datetime.utcnow()

    season_info = get_current_season(as_of)
    if season_info is None:
        return None

    current_halving   = season_info["halving_date"]
    current_cycle_idx = HALVING_DATES.index(current_halving)

    # 取得減半當天價格與前一牛市 ATH
    halving_price = current_price
    prev_ath      = None

    if df is not None and not df.empty and "close" in df.columns:
        halving_mask = df.index >= pd.Timestamp(current_halving)
        if halving_mask.any():
            halving_price = float(df.loc[halving_mask, "close"].iloc[0])

        if current_cycle_idx > 0:
            prev_halving = HALVING_DATES[current_cycle_idx - 1]
            mask_prev    = (df.index >= pd.Timestamp(prev_halving)) & \
                           (df.index < pd.Timestamp(current_halving))
            if mask_prev.any():
                prev_ath = float(df.loc[mask_prev, "close"].max())

    if prev_ath is None and len(CYCLE_HISTORY) > 0:
        prev_ath = CYCLE_HISTORY[-1]["ath_price"]

    # 真實市場狀態分析
    market_state = analyze_market_state(current_price, df, current_halving)

    # 推導有效季節
    real_season, real_season_zh, real_emoji, correction_reason, is_corrected = _derive_real_season(
        time_season     = season_info["season"],
        drawdown        = market_state["drawdown_from_ath"],
        is_above_sma200 = market_state["is_above_sma200"],
        month_in_cycle  = season_info["month_in_cycle"],
    )

    effective_season = {
        "season":    real_season,
        "season_zh": real_season_zh,
        "emoji":     real_emoji,
    }

    adj_peak_med = _apply_diminishing_returns(STATS["peak_mult_median"], current_cycle_idx)
    adj_peak_p25 = _apply_diminishing_returns(STATS["peak_mult_p25"],    current_cycle_idx)
    adj_peak_p75 = _apply_diminishing_returns(STATS["peak_mult_p75"],    current_cycle_idx)

    days_since = season_info["days_since"]

    if real_season in ("spring", "summer"):
        # ═══ 牛市預測 ═══
        forecast_type = "bull_peak"

        ath_target_med = halving_price * adj_peak_med
        ath_target_p25 = halving_price * adj_peak_p25
        ath_target_p75 = halving_price * adj_peak_p75

        if current_price > ath_target_med:
            remaining_mult = adj_peak_p75 / adj_peak_med
            ath_target_med = current_price * remaining_mult
            ath_target_p75 = ath_target_med * 1.3
            ath_target_p25 = ath_target_med * 0.75

        target_median = max(ath_target_med, current_price)
        target_low    = max(ath_target_p25, current_price)
        target_high   = max(ath_target_p75, current_price)

        days_to_peak   = max(STATS["peak_days_median"] - days_since, 30)
        estimated_date = as_of + timedelta(days=days_to_peak)

        rationale = (
            f"【有效季節】{real_emoji} {real_season_zh}\n"
            f"時間位置：第 {current_cycle_idx+1} 次減半後第 {season_info['month_in_cycle']} 個月\n"
            f"歷史中位數：減半後約 {STATS['peak_days_median']} 天達到牛市高點，"
            f"相對減半價漲幅中位數 {adj_peak_med:.1f}x\n"
            f"減半時價格: ${halving_price:,.0f}\n"
            f"預計牛市高點區間: ${target_low:,.0f} ~ ${target_high:,.0f}"
        )

        confidence = min(int(80 - abs(days_since - STATS["peak_days_median"]) / 5), 85)
        confidence = max(confidence, 40)
        if market_state["drawdown_from_ath"] < -0.10:
            confidence = max(confidence - 15, 25)

    else:
        # ═══ 熊市預測 ═══
        forecast_type = "bear_bottom"

        cycle_ath = market_state.get("cycle_ath", None)
        if cycle_ath and cycle_ath > current_price * 1.05:
            ath_ref       = cycle_ath
            ath_ref_label = f"當前週期 ATH ${cycle_ath:,.0f}"
        else:
            ath_ref       = prev_ath if prev_ath else current_price * 1.5
            ath_ref_label = f"前一週期 ATH ${ath_ref:,.0f}"

        bottom_med = ath_ref * STATS["bottom_mult_median"]
        bottom_p25 = ath_ref * STATS["bottom_mult_p25"]
        bottom_p75 = ath_ref * STATS["bottom_mult_p75"]

        target_median = min(bottom_med, current_price)
        target_low    = min(bottom_p25, current_price)
        target_high   = min(bottom_p75, current_price)

        days_to_bottom = max(STATS["bottom_days_median"] - days_since, 30)
        estimated_date = as_of + timedelta(days=days_to_bottom)

        drawdown_pct = abs(market_state["drawdown_from_ath"]) * 100
        rationale = (
            f"【有效季節】{real_emoji} {real_season_zh}\n"
            f"時間位置：第 {current_cycle_idx+1} 次減半後第 {season_info['month_in_cycle']} 個月 "
            f"（時間季節：{season_info['season_zh']}）\n"
            f"距 ATH 跌幅: {drawdown_pct:.1f}%  |  "
            f"{'跌破' if not market_state['is_above_sma200'] else '站上'} 200日均線 "
            f"(${market_state['sma200']:,.0f})\n"
            f"參考基準: {ath_ref_label}\n"
            f"歷史底部跌幅中位數 {STATS['bottom_mult_median']*100:.0f}%\n"
            f"預計熊市底部區間: ${target_low:,.0f} ~ ${target_high:,.0f}"
        )

        confidence = min(int(80 - abs(days_since - STATS["bottom_days_median"]) / 5), 80)
        confidence = max(confidence, 35)
        if market_state["drawdown_from_ath"] < -0.25:
            confidence = min(confidence + 10, 75)

    return {
        "season_info":         season_info,
        "market_state":        market_state,
        "effective_season":    effective_season,
        "forecast_type":       forecast_type,
        "target_median":       round(target_median, 0),
        "target_low":          round(target_low,    0),
        "target_high":         round(target_high,   0),
        "estimated_date":      estimated_date,
        "rationale":           rationale,
        "confidence":          confidence,
        "current_cycle_idx":   current_cycle_idx,
        "halving_price":       round(halving_price, 0),
        "prev_ath":            round(prev_ath, 0) if prev_ath else None,
        "is_season_corrected": is_corrected,
        "correction_reason":   correction_reason,
    }


def get_cycle_comparison_table():
    """返回歷史各週期比較表 (pd.DataFrame)。"""
    rows = []
    for i, c in enumerate(CYCLE_HISTORY):
        rows.append({
            "週期":        f"第 {i+1} 次減半",
            "減半日":      c["halving"].strftime("%Y-%m-%d"),
            "減半時價格":  f"${c['halving_price']:,.0f}",
            "牛市 ATH":    f"${c['ath_price']:,.0f}",
            "ATH 倍數":    f"{c['peak_mult']:.1f}x",
            "達 ATH 天數": f"{c['peak_days']} 天",
            "熊市最低點":  f"${c['bear_low']:,.0f}",
            "ATH 跌幅":    f"{(1-c['bottom_mult'])*100:.0f}%",
            "達底部天數":  f"{c['bottom_days']} 天",
        })
    return pd.DataFrame(rows)


def get_power_law_forecast(df: pd.DataFrame, months_ahead: int = 12):
    """冪律模型：未來 months_ahead 個月的價格走廊。"""
    genesis      = datetime(2009, 1, 3)
    future_dates = pd.date_range(
        start   = datetime.utcnow() + timedelta(days=1),
        periods = months_ahead * 30,
        freq    = "D",
    )
    days_arr   = np.array([(d.to_pydatetime() - genesis).days for d in future_dates], dtype=float)
    days_arr   = np.clip(days_arr, 1, None)
    log_median = -17.01467 + 5.84 * np.log10(days_arr)

    return pd.DataFrame({
        "median": 10 ** log_median,
        "upper":  10 ** (log_median + 0.45),
        "lower":  10 ** (log_median - 0.45),
    }, index=future_dates)