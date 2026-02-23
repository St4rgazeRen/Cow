"""
strategy/swing.py
Antigravity v4 波段交易策略 & 回測引擎
純 Python，無 Streamlit 依賴
"""
import numpy as np
import pandas as pd


def calculate_max_drawdown(equity_curve):
    """計算最大回撤 (%)"""
    if len(equity_curve) < 1:
        return 0.0
    peaks = np.maximum.accumulate(equity_curve)
    drawdowns = (equity_curve - peaks) / peaks
    return drawdowns.min() * 100


def run_swing_strategy_backtest(df, start_date, end_date, initial_capital=10_000):
    """
    Antigravity v4 波段策略回測

    進場: Price > SMA200 AND RSI_14 > 50 AND 0% ≤ dist_from_EMA20 ≤ 1.5%
    出場: Price < EMA_20

    返回: (trades_df, final_equity, roi_pct, trade_count, max_drawdown_pct)
    """
    mask = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
    bt_df = df.loc[mask].copy()

    if bt_df.empty:
        return pd.DataFrame(), 0.0, 0.0, 0, 0.0

    balance = initial_capital
    position = 0.0
    state = "CASH"
    entry_price = 0.0
    trades = []

    for i in range(len(bt_df)):
        row = bt_df.iloc[i]
        date = bt_df.index[i]
        ema_20 = row['EMA_20']
        dist_pct = (row['close'] / ema_20 - 1) * 100

        bull_trend = (row['close'] > row['SMA_200']) and (row['RSI_14'] > 50)
        is_entry = bull_trend and (0 <= dist_pct <= 1.5)
        is_exit = row['close'] < ema_20

        if state == "CASH" and is_entry:
            position = balance / row['close']
            entry_price = row['close']
            trades.append({
                "Type": "Buy", "Date": date, "Price": entry_price,
                "Balance": balance, "Crypto": position, "Reason": "Sweet Spot"
            })
            balance = 0
            state = "INVESTED"

        elif state == "INVESTED" and is_exit:
            balance = position * row['close']
            trades.append({
                "Type": "Sell", "Date": date, "Price": row['close'],
                "Balance": balance, "Crypto": 0,
                "Reason": "Trend Break (<EMA20)",
                "PnL": balance - (entry_price * position),
                "PnL%": (row['close'] / entry_price - 1) * 100,
            })
            position = 0
            state = "CASH"

    final_equity = balance if state == "CASH" else position * bt_df.iloc[-1]['close']
    roi = (final_equity - initial_capital) / initial_capital * 100

    # 重建權益曲線計算最大回撤
    equity_curve = [initial_capital]
    for t in trades:
        if t['Type'] == 'Sell':
            equity_curve.append(t['Balance'])
    equity_curve.append(final_equity)
    mdd = calculate_max_drawdown(np.array(equity_curve))

    trades_df = pd.DataFrame(trades)
    trade_count = len(trades_df[trades_df['Type'] == 'Buy']) if not trades_df.empty else 0
    return trades_df, final_equity, roi, trade_count, mdd
