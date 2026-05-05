"""
scripts/daily_line_notify.py
用於 GitHub Actions 的戰情室自動推播腳本。
同步更新：補齊分數計算、MA200對比、0.03%費率燈號及五段式建議邏輯。
v2: 整合原 JustVibe 四季日報內容（季節徽章 + 底部支撐三指標），統一單一推播。
"""

import os
import sys
import math
import urllib3
import requests
import pandas as pd
from datetime import datetime, timezone

# ── 底部支撐參考的常數（自原 JustVibe btc_seasons.py 移植）─────────────────
BTC_GENESIS          = datetime(2009, 1, 3, tzinfo=timezone.utc)
MINER_EFFICIENCY_JTH = 30      # J/TH，全網平均效率（含舊機台保守估計）
ELECTRICITY_RATE     = 0.055   # USD/kWh
BTC_PER_DAY          = 450     # 2024 減半後每日礦獎（3.125 × 144 blocks）

SEASON_BG_COLOR = {
    "spring": "#27AE60",
    "summer": "#E67E22",
    "autumn": "#E74C3C",
    "winter": "#2980B9",
}

SEASON_LIGHT_BG = {
    "spring": "#E8F5E9",
    "summer": "#FFF3E0",
    "autumn": "#FFEBEE",
    "winter": "#E3F2FD",
}

SEASON_DESC = {
    "spring": "減半後 0–12 個月，市場低調吸籌",
    "summer": "減半後 12–18 個月，主升浪爆發",
    "autumn": "減半後 18–36 個月，獲利了結回落",
    "winter": "減半後 36–48 個月，長期底部整理",
}

# 把舊深色主題用的螢光色映射為白底可讀的深色版
LIGHT_REMAP = {
    "#00ff88": "#27AE60",
    "#ff4b4b": "#E74C3C",
    "#ffeb3b": "#F39C12",
    "#aaaaaa": "#888888",
    "#ffffff": "#2C3E50",
    "#ffcc66": "#E67E22",
}


def _light(c: str) -> str:
    """把深色主題的色值映射成白底可讀的版本；其他色不動。"""
    return LIGHT_REMAP.get(c, c)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.append(_REPO_ROOT)

# ==============================================================================
# 環境設定：與 config.py 共用 SSL_VERIFY 旗標，避免重複推導邏輯
# ==============================================================================
from config import SSL_VERIFY
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from service.realtime import fetch_realtime_data
from service.market_data import fetch_market_data
from service.onchain import _fetch_funding_rate_history
from core.indicators import calculate_technical_indicators, calculate_ahr999
from core.bear_bottom import calculate_bear_bottom_indicators, calculate_market_cycle_score
from core.season_forecast import forecast_price, STATS as _SEASON_STATS


def _miner_cost_from_ths(hashrate_ths: float) -> float:
    """將算力（TH/s）換算成礦工電費盈虧平衡價（USD/BTC）。"""
    cost_per_day = hashrate_ths * MINER_EFFICIENCY_JTH / 1000 * 24 * ELECTRICITY_RATE
    return cost_per_day / BTC_PER_DAY


def fetch_floor_indicators(now: datetime, btc_df: pd.DataFrame) -> dict:
    """
    計算三項底部支撐參考指標（任一失敗均不影響其他）。
      1. power_law_floor : Giovanni Santostasi 冪律下界（純數學）
      2. ma200w          : 200 週均線（從 btc_df 日線重採樣為週收盤後 SMA200）
      3. miner_cost      : 礦工電費盈虧平衡價（blockchain.info 即時算力）
    """
    result = {"ma200w": None, "power_law_floor": None, "miner_cost": None}

    # ── 1. 冪律模型下界（中位數 × 10^-0.45，對應 1σ 下方）
    days_genesis = (now - BTC_GENESIS).days
    if days_genesis > 0:
        pl_median = 10 ** (-17.01467 + 5.84 * math.log10(days_genesis))
        result["power_law_floor"] = pl_median * (10 ** -0.45)

    # ── 2. 200 週均線（直接由日線 btc_df 重採樣）
    try:
        if btc_df is not None and not btc_df.empty and "close" in btc_df.columns:
            df_w = btc_df.copy()
            if df_w.index.tz is not None:
                df_w.index = df_w.index.tz_localize(None)
            weekly = df_w["close"].resample("W").last().dropna()
            if len(weekly) >= 200:
                result["ma200w"] = float(weekly.tail(200).mean())
    except Exception as e:
        print(f"[WARN] 200w MA: {e}")

    # ── 3. 礦工電費盈虧平衡價（blockchain.info stats → mempool.space 備援）
    try:
        resp = requests.get(
            "https://api.blockchain.info/stats",
            timeout=10, verify=SSL_VERIFY,
        )
        resp.raise_for_status()
        hashrate_ghs = float(resp.json()["hash_rate"])  # GH/s
        result["miner_cost"] = _miner_cost_from_ths(hashrate_ghs / 1000)
    except Exception as e:
        print(f"[WARN] Miner cost (blockchain.info): {e}")
        try:
            resp = requests.get(
                "https://mempool.space/api/v1/mining/hashrate/1d",
                timeout=10, verify=SSL_VERIFY,
            )
            resp.raise_for_status()
            hashrate_ths = float(resp.json()["currentHashrate"]) / 1e12  # H/s → TH/s
            result["miner_cost"] = _miner_cost_from_ths(hashrate_ths)
        except Exception as e2:
            print(f"[WARN] Miner cost (mempool.space): {e2}")

    return result


def _get_cycle_meta(score: int):
    if score >= 75: return "🔥 狂熱牛頂", "#ff4b4b", "風險極高，建議分批止盈。"
    elif score >= 40: return "🐂 牛市主升段", "#ff9800", "趨勢多頭排列，可持有並設移動止盈。"
    elif score >= 15: return "🌱 初牛復甦", "#8bc34a", "市場轉暖，分批建倉機會。"
    elif score >= -15: return "⚪ 中性過渡", "#9e9e9e", "多空均衡，觀望為主。"
    elif score >= -40: return "📉 轉折回調", "#7986cb", "趨勢轉弱，建議輕倉。"
    elif score >= -75: return "❄️ 熊市築底", "#42a5f5", "開始定投積累。"
    else: return "🟦 歷史極值底部", "#00bcd4", "All-In 信號！歷史罕見買入機會。"

def get_decision_data():
    summary = {
        "price": "N/A", "current_price": 0.0,
        "cycle_score": 0, "cycle_name": "N/A", "cycle_color": "#aaaaaa", "cycle_advice": "",
        "ma200_label": "N/A", "funding_text": "N/A", "funding_color": "#aaaaaa",
        "trend_text": "N/A", "trend_color": "#aaaaaa",
        "rsi_text": "N/A", "rsi_color": "#aaaaaa",
        "macd_text": "N/A", "macd_color": "#aaaaaa",
        "adx_text": "N/A", "adx_color": "#aaaaaa",
        "ema_dist_text": "N/A", "ema_dist_color": "#aaaaaa",
        "swing_advice": "N/A", "swing_advice_color": "#aaaaaa",
        "forecast_type": "bear_bottom", "target_low": 0, "target_median": 0, "target_high": 0,
        "label_low": "最深", "label_high": "最淺",
        "forecast_estimated_date": "N/A", "forecast_ath_ref": 0,
        # ── 四季區塊（自原 JustVibe 四季日報整合）──
        "season_emoji": "❓", "season_zh": "N/A", "season_color": "#888888", "season_desc": "",
        "halving_date_str": "N/A", "days_since_halving": 0, "cycle_progress_pct": 0,
        "cycle_ath": 0, "cycle_ath_date": "N/A", "from_high_pct": 0.0,
        # ── 底部支撐三指標 ──
        "floor_ma200w": None, "floor_power_law": None, "floor_miner_cost": None,
    }

    current_price = None
    try:
        # Coinbase 公開 API：GitHub Actions 伺服器在美國，Binance 會 451 Geo-block
        url = "https://api.coinbase.com/v2/prices/BTC-USD/spot"
        response = requests.get(url, verify=SSL_VERIFY, timeout=10)
        response.raise_for_status()
        current_price = float(response.json()['data']['amount'])
        print(f"✅ 成功透過 Coinbase API 抓取最新 BTC 價格: {current_price}")

    except Exception as e:
        print(f"❌ 抓取 Coinbase 即時價格失敗，錯誤原因: {e}")

    try:
        btc_df, _ = fetch_market_data()
        funding_df = _fetch_funding_rate_history()

        latest_funding = 0.0
        if not funding_df.empty:
            latest_funding = funding_df['fundingRate'].iloc[-1]
            f_is_hot = latest_funding >= 0.03
            summary["funding_text"] = f"{'🔴' if f_is_hot else '🟢'} {latest_funding:.4f}%"
            summary["funding_color"] = "#ff4b4b" if f_is_hot else "#00ff88"

        if not btc_df.empty:
            # 補齊所有指標計算以對齊羅盤分數
            btc_df = calculate_technical_indicators(btc_df)
            btc_df = calculate_ahr999(btc_df)
            btc_df = calculate_bear_bottom_indicators(btc_df)

            curr = btc_df.iloc[-1].copy()

            # 若上方 Coinbase API 抓取失敗，則使用歷史 K 棒的最後一筆收盤價作為備用
            if current_price is None:
                current_price = float(curr['close'])

            curr['close'] = current_price
            summary["price"] = f"${current_price:,.0f}"
            summary["current_price"] = current_price
            curr['funding_rate'] = latest_funding

            # MA200 狀態標籤
            ma200 = curr.get('SMA_200', 0)
            ma_is_higher = ma200 > current_price
            summary["ma200_label"] = f"{'🔴' if ma_is_higher else '🟢'} ${ma200:,.0f} ({'>' if ma_is_higher else '<'} 現價)"

            # 預測區塊（同步抓出季節資訊填入四季徽章）
            f_res = forecast_price(current_price, btc_df)
            if f_res:
                summary.update({
                    "forecast_type": f_res["forecast_type"],
                    "target_low": f_res["target_low"], "target_median": f_res["target_median"], "target_high": f_res["target_high"],
                    "label_low": "最深" if "bear" in f_res["forecast_type"] else "保守",
                    "label_high": "最淺" if "bear" in f_res["forecast_type"] else "樂觀",
                    "forecast_ath_ref": f_res.get("ath_ref") or 0,
                })
                est = f_res.get("estimated_date")
                if est:
                    summary["forecast_estimated_date"] = est.strftime("%Y-%m")

                season_info  = f_res.get("season_info") or {}
                eff_season   = f_res.get("effective_season") or {}
                market_state = f_res.get("market_state") or {}

                season_key = eff_season.get("season") or season_info.get("season") or "spring"
                summary["season_emoji"] = eff_season.get("emoji") or season_info.get("emoji") or "❓"
                summary["season_zh"]    = eff_season.get("season_zh") or season_info.get("season_zh") or "N/A"
                summary["season_color"] = SEASON_BG_COLOR.get(season_key, "#888888")
                summary["season_desc"]  = SEASON_DESC.get(season_key, "")

                halving_dt = season_info.get("halving_date")
                if halving_dt:
                    summary["halving_date_str"]  = halving_dt.strftime("%Y-%m-%d")
                summary["days_since_halving"] = season_info.get("days_since", 0)
                summary["cycle_progress_pct"] = int(min(season_info.get("cycle_progress", 0.0), 1.0) * 100)

                cycle_ath = market_state.get("cycle_ath", 0) or 0
                cycle_ath_dt = market_state.get("cycle_ath_date")
                summary["cycle_ath"] = cycle_ath
                if cycle_ath_dt:
                    summary["cycle_ath_date"] = cycle_ath_dt.strftime("%Y-%m-%d")
                if cycle_ath > 0:
                    summary["from_high_pct"] = (current_price - cycle_ath) / cycle_ath * 100

            # 底部支撐三指標
            now_utc = datetime.now(timezone.utc)
            floor_data = fetch_floor_indicators(now_utc, btc_df)
            summary["floor_ma200w"]    = floor_data["ma200w"]
            summary["floor_power_law"] = floor_data["power_law_floor"]
            summary["floor_miner_cost"] = floor_data["miner_cost"]

            # 分數計算
            score = calculate_market_cycle_score(curr)
            summary["cycle_score"] = score
            summary["cycle_name"], summary["cycle_color"], summary["cycle_advice"] = _get_cycle_meta(score)

            # 波段雷達與五段式建議邏輯
            sma50 = curr.get('SMA_50', 0)
            is_bull_trend = current_price > ma200 and sma50 > ma200
            summary["trend_text"] = "🟢 多頭排列" if is_bull_trend else "🔴 空頭/震盪"
            summary["trend_color"] = "#00ff88" if is_bull_trend else "#ff4b4b"

            rsi = curr.get('RSI_14', 0)
            summary["rsi_text"] = f"{'🟢' if rsi > 50 else '🔴'} ({rsi:.1f})"
            summary["rsi_color"] = "#00ff88" if rsi > 50 else "#ff4b4b"

            macd, macd_sig = curr.get('MACD', 0), curr.get('MACD_Signal', 0)
            summary["macd_text"] = "🟢 金叉" if macd > macd_sig else "🔴 死叉"
            summary["macd_color"] = "#00ff88" if macd > macd_sig else "#ff4b4b"

            adx = curr.get('ADX_14', 0)
            summary["adx_text"] = f"{'🟢' if adx > 20 else '🔴'} ({adx:.1f})"
            summary["adx_color"] = "#00ff88" if adx > 20 else "#ff4b4b"

            ema20 = curr.get('EMA_20', 0)
            ema_dist = (current_price - ema20) / ema20 * 100 if ema20 > 0 else 0
            summary["ema_dist_text"] = f"{'🟢' if 0 <= ema_dist <= 1.5 else '🔴'} ({ema_dist:.1f}%)"
            summary["ema_dist_color"] = "#00ff88" if 0 <= ema_dist <= 1.5 else "#ff4b4b"

            # 綜合建議判斷
            if is_bull_trend:
                if 0 <= ema_dist <= 1.5 and rsi > 50 and macd > macd_sig and adx > 20:
                    summary["swing_advice"] = "🚀 動能共振！絕佳進場買點"
                    summary["swing_advice_color"] = "#00ff88"
                elif ema_dist > 1.5:
                    summary["swing_advice"] = "📈 趨勢偏多，但乖離過大不宜追高"
                    summary["swing_advice_color"] = "#ffeb3b"
                else:
                    summary["swing_advice"] = "🟡 多頭排列，等待動能指標轉強"
                    summary["swing_advice_color"] = "#ffeb3b"
            else:
                if ema_dist < 0:
                    summary["swing_advice"] = "❄️ 跌破短期均線，建議觀望"
                    summary["swing_advice_color"] = "#ff4b4b"
                else:
                    summary["swing_advice"] = "⚪ 趨勢偏弱，空頭或震盪格局"
                    summary["swing_advice_color"] = "#aaaaaa"

    except Exception as e: print(f"Data error: {e}")
    return summary

def _build_season_box(s):
    """四季徽章區塊（季節 + 減半天數 + 週期進度 + 本輪峰值）。"""
    if s["season_zh"] == "N/A":
        return None

    season_key = "winter"
    for k, color in SEASON_BG_COLOR.items():
        if color == s["season_color"]:
            season_key = k
            break

    contents = [
        {"type": "text", "text": f"{s['season_emoji']} {s['season_zh']}",
         "color": s["season_color"], "weight": "bold", "size": "md"},
    ]
    if s["season_desc"]:
        contents.append({"type": "text", "text": s["season_desc"],
                         "color": "#666666", "size": "xs", "margin": "xs", "wrap": True})

    meta_text = f"距上次減半 {s['days_since_halving']} 天（{s['halving_date_str']}）｜週期進度 {s['cycle_progress_pct']}%"
    contents.append({"type": "text", "text": meta_text,
                     "color": "#888888", "size": "xxs", "margin": "sm", "wrap": True})

    if s["cycle_ath"] > 0:
        peak_line = f"📈 本輪峰值 ${s['cycle_ath']:,.0f}（{s['cycle_ath_date']}）｜距峰 {s['from_high_pct']:+.1f}%"
        contents.append({"type": "text", "text": peak_line,
                         "color": "#E67E22", "size": "xxs", "margin": "xs", "wrap": True})

    return {
        "type": "box", "layout": "vertical",
        "margin": "md",
        "backgroundColor": SEASON_LIGHT_BG.get(season_key, "#F8F8F8"),
        "cornerRadius": "8px",
        "paddingAll": "md",
        "contents": contents,
    }


def _build_floor_support_box(s):
    """底部支撐三指標區塊（200週MA / 冪律下界 / 礦工電費）。"""
    items = [
        ("200週均線", s["floor_ma200w"]),
        ("冪律下界", s["floor_power_law"]),
        ("礦工電費", s["floor_miner_cost"]),
    ]
    rows = []
    current_price = s.get("current_price", 0)
    for label, floor in items:
        if floor is None or current_price <= 0:
            continue
        diff_pct = (current_price - floor) / floor * 100
        sign = "+" if diff_pct >= 0 else ""
        color = "#27AE60" if diff_pct >= 0 else "#E74C3C"
        rows.append({
            "type": "box", "layout": "horizontal", "margin": "xs",
            "contents": [
                {"type": "text", "text": label, "color": "#555555", "size": "xs", "flex": 3},
                {"type": "text", "text": f"${floor:,.0f}", "color": "#2C3E50", "size": "xs",
                 "weight": "bold", "align": "end", "flex": 3},
                {"type": "text", "text": f"{sign}{diff_pct:.1f}%", "color": color, "size": "xs",
                 "align": "end", "flex": 2},
            ],
        })

    if not rows:
        return None

    return {
        "type": "box", "layout": "vertical",
        "margin": "lg",
        "backgroundColor": "#F0F4FF",
        "cornerRadius": "8px",
        "paddingAll": "md",
        "contents": [
            {"type": "text", "text": "📊 底部支撐參考（日更）",
             "color": "#2C3E50", "size": "sm", "weight": "bold"},
            *rows,
            {"type": "text", "text": "綠=現價在支撐上方　紅=跌破支撐",
             "color": "#AAAAAA", "size": "xxs", "margin": "sm", "wrap": True},
        ],
    }


def _radar_row(label, value_text, value_color):
    return {
        "type": "box", "layout": "horizontal", "margin": "xs",
        "contents": [
            {"type": "text", "text": label, "color": "#666666", "size": "sm"},
            {"type": "text", "text": value_text, "color": _light(value_color), "size": "sm",
             "weight": "bold", "align": "end"},
        ],
    }


def _build_radar_box(s):
    """波段雷達整段框起來。"""
    return {
        "type": "box", "layout": "vertical",
        "margin": "lg",
        "backgroundColor": "#F8F9FA",
        "cornerRadius": "8px",
        "paddingAll": "md",
        "contents": [
            {"type": "text", "text": "🐂 波段雷達", "weight": "bold",
             "color": "#2C3E50", "size": "sm"},
            _radar_row("MA200 支撐",  s["ma200_label"],   "#2C3E50"),
            _radar_row("資金費率",    s["funding_text"],  s["funding_color"]),
            _radar_row("趨勢方向",    s["trend_text"],    s["trend_color"]),
            _radar_row("RSI 強弱",    s["rsi_text"],      s["rsi_color"]),
            _radar_row("MACD 交叉",   s["macd_text"],     s["macd_color"]),
            _radar_row("ADX 動能",    s["adx_text"],      s["adx_color"]),
            _radar_row("EMA20 乖離",  s["ema_dist_text"], s["ema_dist_color"]),
        ],
    }


def _build_forecast_box(s):
    """牛/熊預測區塊（含算法說明 + 預測時間）。"""
    is_bear = s["forecast_type"] == "bear_bottom"
    title = "❄️ 熊市最低價預測" if is_bear else "🚀 牛市最高價預測"
    accent_color = "#2980B9" if is_bear else "#E67E22"
    bg = "#FFF8F0" if is_bear else "#F0FFF4"

    contents = [
        {"type": "text", "text": title, "color": accent_color, "size": "sm", "weight": "bold"},
        {"type": "box", "layout": "horizontal", "margin": "sm", "contents": [
            {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": s["label_low"], "color": "#666666", "size": "xxs", "align": "center"},
                {"type": "text", "text": f'${s["target_low"]:,.0f}', "color": "#2C3E50", "size": "xs", "align": "center"},
            ]},
            {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": "中位數", "color": accent_color, "size": "xxs", "align": "center"},
                {"type": "text", "text": f'${s["target_median"]:,.0f}', "color": accent_color, "size": "md", "weight": "bold", "align": "center"},
            ]},
            {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": s["label_high"], "color": "#666666", "size": "xxs", "align": "center"},
                {"type": "text", "text": f'${s["target_high"]:,.0f}', "color": "#2C3E50", "size": "xs", "align": "center"},
            ]},
        ]},
    ]

    # 算法說明 + 預測時間
    if is_bear:
        ath_ref_str = f"${s['forecast_ath_ref']:,.0f}" if s.get("forecast_ath_ref") else "本輪 ATH"
        method_text = f"算法：歷史三輪「熊底/ATH」比值（13.1% / 15.7% / 22.5%）取四分位數，乘以參考 ATH {ath_ref_str}"
    else:
        method_text = "算法：歷史三輪「ATH/減半價」倍數取四分位數（含週期遞減），乘以本輪減半收盤價"
    contents.append({"type": "text", "text": method_text,
                     "color": "#888888", "size": "xxs", "margin": "sm", "wrap": True})

    if s.get("forecast_estimated_date") and s["forecast_estimated_date"] != "N/A":
        when_label = "預估底部時間" if is_bear else "預估高點時間"
        days_med = _SEASON_STATS["bottom_days_median"] if is_bear else _SEASON_STATS["peak_days_median"]
        contents.append({"type": "text",
                         "text": f"⏳ {when_label}：約 {s['forecast_estimated_date']}（歷史中位數減半後 {days_med} 天）",
                         "color": "#888888", "size": "xxs", "margin": "xs", "wrap": True})

    return {
        "type": "box", "layout": "vertical", "margin": "lg",
        "backgroundColor": bg,
        "cornerRadius": "8px",
        "paddingAll": "md",
        "contents": contents,
    }


def _build_score_box(s, left_flex):
    """長週期多空評分（白底版）。"""
    return {
        "type": "box", "layout": "vertical", "margin": "md",
        "backgroundColor": "#F8F9FA", "cornerRadius": "8px", "paddingAll": "md",
        "contents": [
            {"type": "text", "text": "🧭 長週期多空評分", "weight": "bold",
             "color": "#2C3E50", "size": "sm"},
            {"type": "box", "layout": "horizontal", "margin": "sm", "contents": [
                {"type": "box", "layout": "vertical", "flex": 7, "contents": [
                    {"type": "text", "text": s["cycle_name"], "color": s["cycle_color"],
                     "weight": "bold", "size": "md"},
                    {"type": "text", "text": s["cycle_advice"], "color": "#666666",
                     "size": "xs", "wrap": True},
                ]},
                {"type": "box", "layout": "vertical", "flex": 3, "alignItems": "flex-end", "contents": [
                    {"type": "text", "text": f"{s['cycle_score']:+d}", "color": s["cycle_color"],
                     "size": "xxl", "weight": "bold"},
                ]},
            ]},
            {"type": "box", "layout": "horizontal", "margin": "md", "height": "8px", "contents": [
                {"type": "box", "layout": "vertical", "flex": left_flex,
                 "backgroundColor": s["cycle_color"], "contents": []},
                {"type": "box", "layout": "vertical", "flex": 100 - left_flex,
                 "backgroundColor": "#E0E0E0", "contents": []},
            ]},
        ],
    }


def build_flex_message(s):
    date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    left_flex = max(1, min(99, int((s["cycle_score"] + 100) / 2)))

    body_contents = [
        {"type": "text", "text": f"💰 BTC {s['price']}", "weight": "bold",
         "size": "xxl", "color": "#27AE60"},
    ]

    season_box = _build_season_box(s)
    if season_box:
        body_contents.append(season_box)

    body_contents.append(_build_score_box(s, left_flex))
    body_contents.append(_build_forecast_box(s))
    body_contents.append(_build_radar_box(s))

    floor_box = _build_floor_support_box(s)
    if floor_box:
        body_contents.append(floor_box)

    body_contents.append({
        "type": "box", "layout": "vertical", "margin": "lg",
        "backgroundColor": "#FFF9E6", "paddingAll": "md", "cornerRadius": "8px",
        "contents": [
            {"type": "text", "text": "💡 策略建議", "color": "#888888", "size": "xxs", "weight": "bold"},
            {"type": "text", "text": s["swing_advice"], "color": _light(s["swing_advice_color"]),
             "size": "sm", "weight": "bold", "wrap": True, "margin": "xs"},
        ],
    })

    flex_bubble = {
        "type": "bubble", "size": "giga",
        "header": {
            "type": "box", "layout": "vertical", "backgroundColor": "#E74C3C",
            "paddingAll": "16px",
            "contents": [
                {"type": "text", "text": "🦅 戰情室決策速報", "weight": "bold",
                 "color": "#FFFFFF", "size": "xl"},
                {"type": "text", "text": f"更新時間: {date_str}", "color": "#FFFFFF",
                 "size": "xs", "margin": "sm"},
            ],
        },
        "body": {
            "type": "box", "layout": "vertical", "backgroundColor": "#FFFFFF",
            "spacing": "sm",
            "contents": body_contents,
        },
    }
    return {"type": "flex", "altText": f"🦅 決策速報: BTC {s['price']}", "contents": flex_bubble}

def send_line_message(flex_payload):
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    line_user_id = os.getenv("LINE_USER_ID")
    if not line_token or not line_user_id:
        print("❌ 錯誤: 缺少 LINE 憑證")
        sys.exit(1)
    url = "https://api.line.me/v2/bot/message/push"
    headers = { "Content-Type": "application/json", "Authorization": f"Bearer {line_token}" }
    data = { "to": line_user_id, "messages": [flex_payload] }
    try:
        response = requests.post(url, headers=headers, json=data, verify=SSL_VERIFY, timeout=10)
        response.raise_for_status()
        print("✅ LINE 速報發送成功！")
    except Exception as e:
        print(f"❌ LINE 推播失敗: {e}")
        sys.exit(1)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    data = get_decision_data()
    send_line_message(build_flex_message(data))
