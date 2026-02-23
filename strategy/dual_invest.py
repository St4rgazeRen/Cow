"""
strategy/dual_invest.py
雙幣理財策略引擎
- Black-Scholes APY 計算
- 梯形行權價建議
- 每日滾倉回測
純 Python，無 Streamlit 依賴
"""
import math
import numpy as np
import pandas as pd
from datetime import timedelta


def calculate_bs_apy(S, K, T_days, sigma_annual, option_type='call'):
    """Black-Scholes 期權定價 → 年化 APY"""
    if T_days <= 0:
        return 0.0
    T = T_days / 365.0
    r = 0.04  # 無風險利率 4%

    def norm_cdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    d1 = (np.log(S / K) + (r + 0.5 * sigma_annual ** 2) * T) / (sigma_annual * np.sqrt(T))
    d2 = d1 - sigma_annual * np.sqrt(T)

    if option_type == 'call':
        price = S * norm_cdf(d1) - K * np.exp(-r * T) * norm_cdf(d2)
        principal = S
    else:
        price = K * np.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
        principal = K

    apy = (price / principal) * (365 / T_days)
    return max(apy, 0.05)


def calculate_ladder_strategy(row, product_type):
    """
    生成 3 檔梯形行權價建議
    product_type: 'SELL_HIGH' | 'BUY_LOW'
    """
    atr = row['ATR']
    close = row['close']
    vol_factor = 1.2 if (atr / close) > 0.02 else 1.0
    targets = []

    if product_type == "SELL_HIGH":
        base = max(row['BB_Upper'], row.get('R1', row['BB_Upper']))
        s1 = max(base + atr * 1.0 * vol_factor, close * 1.015)
        s2 = max(base + atr * 2.0 * vol_factor, row.get('R2', 0), s1 * 1.01)
        s3 = max(base + atr * 3.5 * vol_factor, s2 * 1.01)
        targets = [
            {"Type": "激進", "Strike": s1, "Weight": "30%", "Distance": (s1 / close - 1) * 100},
            {"Type": "中性", "Strike": s2, "Weight": "30%", "Distance": (s2 / close - 1) * 100},
            {"Type": "保守", "Strike": s3, "Weight": "40%", "Distance": (s3 / close - 1) * 100},
        ]
    elif product_type == "BUY_LOW":
        base = min(row['BB_Lower'], row.get('S1', row['BB_Lower']))
        s1 = min(base - atr * 1.0 * vol_factor, close * 0.985)
        s2 = min(base - atr * 2.0 * vol_factor, row.get('S2', 999_999), s1 * 0.99)
        s3 = min(base - atr * 3.5 * vol_factor, s2 * 0.99)
        targets = [
            {"Type": "激進", "Strike": s1, "Weight": "30%", "Distance": (close / s1 - 1) * 100},
            {"Type": "中性", "Strike": s2, "Weight": "30%", "Distance": (close / s2 - 1) * 100},
            {"Type": "保守", "Strike": s3, "Weight": "40%", "Distance": (close / s3 - 1) * 100},
        ]

    return targets


def get_current_suggestion(df, ma_short_col='EMA_20', ma_long_col='SMA_50'):
    """生成當前雙幣理財建議（含梯形行權價）"""
    if df.empty:
        return None
    curr_row = df.iloc[-1]
    curr_time = curr_row.name
    weekday = curr_time.weekday()

    is_bearish = curr_row[ma_short_col] < curr_row[ma_long_col]
    is_weekend = weekday >= 5

    sell_ladder = [] if is_weekend else calculate_ladder_strategy(curr_row, "SELL_HIGH")
    buy_ladder = [] if (is_weekend or is_bearish) else calculate_ladder_strategy(curr_row, "BUY_LOW")

    reasons = []
    if is_weekend:
        reasons.append("⚠️ **週末濾網**: 流動性較差，建議觀望。")
    if is_bearish:
        reasons.append("⚠️ **趨勢濾網**: 短均線 < 長均線 (空頭)，禁止 Buy Low。")
    reasons.append(
        f"**MA**: 短均(${curr_row[ma_short_col]:,.0f}) "
        f"{'<' if is_bearish else '>'} 長均(${curr_row[ma_long_col]:,.0f})"
    )
    reasons.append(f"**RSI**: {curr_row['RSI_14']:.1f}")
    if 'J' in curr_row:
        reasons.append(f"**KDJ(J)**: {curr_row['J']:.1f}")
    if 'ADX' in curr_row:
        reasons.append(f"**ADX**: {curr_row['ADX']:.1f} ({'強趨勢' if curr_row['ADX'] > 25 else '盤整'})")

    return {
        "time": curr_time,
        "close": curr_row['close'],
        "sell_ladder": sell_ladder,
        "buy_ladder": buy_ladder,
        "explanation": reasons,
    }


def run_dual_investment_backtest(df, call_risk=0.5, put_risk=0.5):
    """
    雙幣理財逐日滾倉回測
    以 BTC 計價，模擬每日選擇 SELL_HIGH 或 BUY_LOW
    返回: trade_log DataFrame
    """
    if df.empty:
        return pd.DataFrame()

    daily = df.copy()
    ma_short, ma_long = 'EMA_20', 'SMA_50'

    trade_log = []
    current_asset = "BTC"
    balance = 1.0
    state = "IDLE"
    lock_end_time = None
    strike_price = 0.0
    product_type = ""
    prev_start_time = None

    indices = daily.index
    for i in range(len(indices) - 1):
        curr_time = indices[i]
        curr_row = daily.loc[curr_time]

        # 結算
        if state == "LOCKED":
            if curr_time < lock_end_time:
                continue
            fixing = curr_row['close']
            vol = (curr_row['ATR'] / curr_row['close']) * np.sqrt(365 * 24) * 0.5
            duration = (lock_end_time - prev_start_time).days

            period_yield = calculate_bs_apy(
                curr_row['close'], strike_price, duration, vol,
                'call' if product_type == "SELL_HIGH" else 'put'
            ) * (duration / 365)

            if product_type == "SELL_HIGH":
                total_btc = balance * (1 + period_yield)
                if fixing >= strike_price:
                    balance = total_btc * strike_price
                    current_asset = "USDT"
                    note, color = "😭 被行權 (轉USDT)", "red"
                else:
                    balance = total_btc
                    current_asset = "BTC"
                    note, color = "✅ 賺幣成功", "green"
            else:
                total_usdt = balance * (1 + period_yield)
                if fixing <= strike_price:
                    balance = total_usdt / strike_price
                    current_asset = "BTC"
                    note, color = "🤩 抄底成功 (轉BTC)", "purple"
                else:
                    balance = total_usdt
                    current_asset = "USDT"
                    note, color = "💰 賺U成功", "orange"

            equity_btc = balance if current_asset == "BTC" else balance / fixing
            trade_log.append({
                "Action": "Settlement", "Time": curr_time, "Fixing": fixing,
                "Strike": strike_price, "Asset": current_asset, "Balance": balance,
                "Note": note, "Color": color, "Equity_BTC": equity_btc, "Step_Y": strike_price,
            })
            state = "IDLE"

        # 開單
        if state == "IDLE":
            weekday = curr_time.weekday()
            if weekday >= 5:
                continue
            duration = 3 if weekday == 4 else 1
            next_settlement = curr_time + timedelta(days=duration)
            if next_settlement > daily.index[-1]:
                continue

            is_bearish = curr_row[ma_short] < curr_row[ma_long]
            atr_pct = curr_row['ATR'] / curr_row['close']
            dyn = 0.8 if atr_pct > 0.015 else (1.2 if atr_pct < 0.005 else 1.0)

            if current_asset == "BTC":
                buf = curr_row['ATR'] * (1 + call_risk) * dyn
                if curr_row.get('ADX', 0) > 25:
                    buf *= 1.5
                if curr_row.get('J', 50) < 20:
                    buf *= 1.2
                base = max(curr_row['BB_Upper'], curr_row.get('R1', curr_row['BB_Upper']))
                strike_price = max(base + buf, curr_row['close'] * 1.01)
                product_type = "SELL_HIGH"
            else:
                if is_bearish:
                    continue
                buf = curr_row['ATR'] * (1 + put_risk) * dyn
                if curr_row.get('ADX', 0) > 25:
                    buf *= 1.5
                base = min(curr_row['BB_Lower'], curr_row.get('S1', curr_row['BB_Lower']))
                strike_price = min(base - buf, curr_row['close'] * 0.99)
                product_type = "BUY_LOW"

            state = "LOCKED"
            lock_end_time = next_settlement
            prev_start_time = curr_time
            equity_btc = balance if current_asset == "BTC" else balance / curr_row['close']
            trade_log.append({
                "Action": "Open", "Time": curr_time, "Fixing": curr_row['close'],
                "Strike": strike_price, "Asset": current_asset, "Balance": balance,
                "Type": product_type, "Note": f"開單 {product_type}", "Color": "blue",
                "Equity_BTC": equity_btc, "Step_Y": strike_price,
            })

    return pd.DataFrame(trade_log)
