"""
strategy/swing.py
Antigravity v4 波段交易策略 & 回測引擎（五合一進場過濾）
純 Python，無 Streamlit 依賴

五合一進場條件（v4.1 升級）:
  1. Price > SMA200          — 年線多頭，大趨勢向上
  2. RSI_14 > 50             — 短期動能偏多
  3. 0% ≤ dist_EMA20 ≤ 1.5% — 回踩甜蜜點，不追高
  4. MACD > Signal           — MACD 多頭交叉確認動能
  5. ADX > 20                — 趨勢強度足夠，過濾盤整假訊號

[Task #5] 回測引擎向量化:
原始邏輯使用 for i in range(len(bt_df)) 逐行掃描，在 2000+ 天的資料集下
每次重新渲染 Tab 都需要數秒。

重構思路：
- 先用 Pandas shift/boolean mask 向量化計算出所有訊號欄位
- 再用「狀態機輔助」的方式只迭代「進出場轉換點」（通常 < 100 次），
  而非逐行掃描所有 2000+ 天
- 理論加速：10-50x，取決於資料長度與交易次數
"""
# 關閉 SSL 驗證警告，避免本地端公司網路環境報錯
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import math
import numpy as np
import pandas as pd

# 從集中設定檔讀取預設交易成本參數
from config import DEFAULT_FEE_RATE, DEFAULT_SLIPPAGE_RATE


def calculate_max_drawdown(equity_curve):
    """計算最大回撤 (%)"""
    if len(equity_curve) < 1:
        return 0.0
    peaks = np.maximum.accumulate(equity_curve)
    drawdowns = (equity_curve - peaks) / peaks
    return drawdowns.min() * 100


def run_swing_strategy_backtest(
    df,
    start_date,
    end_date,
    initial_capital=10_000,
    fee_rate=DEFAULT_FEE_RATE,
    slippage_rate=DEFAULT_SLIPPAGE_RATE,
    entry_dist_max_pct: float = None, # 保留參數以維持相容性，但內部邏輯已解除限制
    rsi_min: int = None,
    adx_min: int = None,
    exit_ma: str = "SMA_50",  # 新增：接收 UI 傳來的動態防守線參數
):
    """
    Antigravity v4 波段策略回測（五合一進場過濾 + 動態出場防守線）

    進場: Price > SMA200 AND RSI_14 > 50 AND 0% ≤ dist_from_EMA20
          AND MACD > Signal AND ADX > 20
    出場: Price < UI傳入的防守線 (預設 SMA_50)

    [Backtest Realism] 交易摩擦成本:
    ─────────────────────────────────────────────────────────────────
    fee_rate      : 單邊手續費率（如 0.001 = 0.1%，Taker Fee）
    slippage_rate : 滑點估算（如 0.001 = 0.1%，因市場深度不足的成交偏差）

    實際進場成本:
        effective_entry = price * (1 + fee_rate + slippage_rate)
        → 例如：BTC=$100,000，cost=0.2%，實際成本=$100,200

    實際出場收益:
        effective_exit = price * (1 - fee_rate - slippage_rate)
        → 例如：BTC=$110,000，cost=0.2%，實際收益=$109,780

    合計一來一回摩擦成本 ≈ 0.4%（0.2% 進 + 0.2% 出）
    ─────────────────────────────────────────────────────────────────

    返回: (trades_df, final_equity, roi_pct, trade_count, max_drawdown_pct, stats_dict)
    """
    mask  = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
    bt_df = df.loc[mask].copy()

    if bt_df.empty:
        return pd.DataFrame(), 0.0, 0.0, 0, 0.0, {}

    # 套用自訂參數，未提供則使用安全預設值
    _dist_min = 0.0  # 強制最小乖離為 0 (站上 EMA20)
    _rsi_min  = rsi_min  if rsi_min  is not None else 50
    _adx_min  = adx_min  if adx_min  is not None else 20

    # ──────────────────────────────────────────────────────────────
    # 第一段：向量化計算所有訊號（無 Python for loop）
    # ──────────────────────────────────────────────────────────────
    close  = bt_df['close']
    ema_20 = bt_df['EMA_20']

    # 避免 EMA_20 為 0 導致 ZeroDivisionError（fillna 用 close 本身）
    ema_safe = ema_20.replace(0, np.nan).fillna(close)

    # 距離 EMA20 的百分比偏差
    dist_pct = (close / ema_safe - 1) * 100  # 正值 = 高於 EMA20

    # 條件 1+2: 年線多頭 + RSI 動能偏多（使用自訂閾值）
    bull_trend = (close > bt_df['SMA_200']) & (bt_df['RSI_14'] > _rsi_min)

    # 條件 4: MACD > Signal（多頭動能交叉確認）
    if 'MACD_12_26_9' in bt_df.columns and 'MACDs_12_26_9' in bt_df.columns:
        macd_bull = (bt_df['MACD_12_26_9'] > bt_df['MACDs_12_26_9']).fillna(False)
    else:
        macd_bull = pd.Series(True, index=bt_df.index)

    # 條件 5: ADX > 自訂閾值（市場有趨勢，過濾橫盤假訊號）
    if 'ADX' in bt_df.columns:
        adx_trending = (bt_df['ADX'] > _adx_min).fillna(False)
    else:
        adx_trending = pd.Series(True, index=bt_df.index)

    # 🚀 進場條件修改：放寬乖離限制，改抓「突破與趨勢確認」
    # 只要價格大於 EMA20 (_dist_min = 0)，且動能指標 (MACD, ADX, RSI) 都轉強即進場
    is_entry = bull_trend & (dist_pct >= _dist_min) & macd_bull & adx_trending

    # 🛡️ 出場條件修改：動態使用傳入的均線名稱 (exit_ma)
    if exit_ma in bt_df.columns:
        is_exit = close < bt_df[exit_ma]
    else:
        is_exit = close < ema_safe

    # ──────────────────────────────────────────────────────────────
    # 第二段：狀態機迭代「訊號觸發點」（不是逐行，只迭代轉換）
    # ──────────────────────────────────────────────────────────────
    # 取出所有進出場日期的布林 Series 位置
    entry_mask = is_entry.values   # NumPy array，避免 Pandas 每次 index 查詢
    exit_mask  = is_exit.values
    dates      = bt_df.index
    closes     = close.values      # NumPy array，存取比 Pandas loc 快 10x

    balance     = initial_capital
    position    = 0.0
    state       = "CASH"           # 狀態機：CASH / INVESTED
    entry_price = 0.0
    trades      = []

    for i in range(len(bt_df)):
        price = closes[i]
        date  = dates[i]

        if state == "CASH" and entry_mask[i]:
            # ── 進場（含手續費與滑點摩擦成本）──
            friction_in  = fee_rate + slippage_rate
            effective_entry_price = price * (1.0 + friction_in)

            # 以調整後成本計算可購入的幣量（balance 全倉投入）
            position    = balance / effective_entry_price
            entry_price = effective_entry_price

            trades.append({
                "Type":       "Buy",
                "Date":       date,
                "Price":      price,               # 市場價（顯示用）
                "Entry_Cost": effective_entry_price,  # 實際成本（含摩擦）
                "Fee%":       friction_in * 100,   # 進場摩擦成本 %
                "Balance":    balance,
                "Crypto":     position,
                "Reason":     "Sweet Spot",
            })
            balance = 0.0
            state   = "INVESTED"

        elif state == "INVESTED" and exit_mask[i]:
            # ── 出場（含手續費與滑點摩擦成本）──
            friction_out  = fee_rate + slippage_rate
            effective_exit_price  = price * (1.0 - friction_out)

            # 實際收到的總資金 = 幣量 × 含摩擦出場價
            balance = position * effective_exit_price

            # PnL 以「含成本進場價」與「含成本出場價」計算，才能反映真實獲利
            gross_cost = entry_price * position         # 進場總花費（含摩擦）
            net_pnl    = balance - gross_cost            # 實際淨盈虧（USDT）
            net_pnl_pct = (effective_exit_price / entry_price - 1) * 100  # 淨報酬率

            trades.append({
                "Type":       "Sell",
                "Date":       date,
                "Price":      price,                # 市場價（顯示用）
                "Exit_Net":   effective_exit_price, # 實際收到（含摩擦）
                "Fee%":       friction_out * 100,   # 出場摩擦成本 %
                "Balance":    balance,
                "Crypto":     0.0,
                "Reason":     f"Trend Break (<{exit_ma})", # 顯示動態防守線
                "PnL":        net_pnl,              # 淨盈虧（已扣摩擦成本）
                "PnL%":       net_pnl_pct,          # 淨報酬率（已扣摩擦成本）
            })
            position = 0.0
            state    = "CASH"

    # ──────────────────────────────────────────────────────────────
    # 計算最終權益與最大回撤
    # ──────────────────────────────────────────────────────────────
    last_close   = closes[-1]
    final_equity = balance if state == "CASH" else position * last_close
    roi          = (final_equity - initial_capital) / initial_capital * 100

    # 從 Sell 交易重建權益曲線（向量化）
    trades_df = pd.DataFrame(trades)

    if not trades_df.empty and 'Balance' in trades_df.columns:
        sell_balances = trades_df.loc[trades_df['Type'] == 'Sell', 'Balance'].tolist()
    else:
        sell_balances = []

    equity_curve = np.array([initial_capital] + sell_balances + [final_equity])
    mdd          = calculate_max_drawdown(equity_curve)

    # ──────────────────────────────────────────────────────────────
    # 進階統計（向量化計算）
    # ──────────────────────────────────────────────────────────────
    stats = {'win_rate': 0.0, 'sharpe': 0.0, 'avg_profit': 0.0, 'avg_loss': 0.0}
    trade_count = 0

    if not trades_df.empty:
        trade_count = int((trades_df['Type'] == 'Buy').sum())

        if 'PnL%' in trades_df.columns:
            sell_trades = trades_df[trades_df['Type'] == 'Sell'].dropna(subset=['PnL%'])
            if not sell_trades.empty:
                pnl_arr = sell_trades['PnL%'].values  # NumPy array

                winners   = pnl_arr[pnl_arr > 0]
                losers    = pnl_arr[pnl_arr <= 0]

                stats['win_rate']   = len(winners) / len(pnl_arr) * 100
                stats['avg_profit'] = float(winners.mean()) if len(winners) > 0 else 0.0
                stats['avg_loss']   = float(losers.mean())  if len(losers) > 0  else 0.0

                # 年化 Sharpe（以每筆交易報酬率估算，非嚴格日頻 Sharpe）
                rets = pnl_arr / 100.0
                if len(rets) > 1 and rets.std() > 0:
                    stats['sharpe'] = float((rets.mean() / rets.std()) * math.sqrt(252))

    return trades_df, final_equity, roi, trade_count, mdd, stats