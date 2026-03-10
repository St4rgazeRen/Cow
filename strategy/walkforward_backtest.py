#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
strategy/walkforward_backtest.py
================================
BTC 波段交易 Walk-Forward Backtester（無先視偏誤）

設計哲學（改編自 tw_stock_climber v4.8）：
  1. 逐日推進迴圈，每個時間點 t 只能看到 Date <= t 的資料
  2. 每 N 日掃描一次進場條件（Antigravity v4.1：5 合 1 過濾）
  3. 多層出場機制：Climax Exit → ATR 停損/目標 → Chandelier → Time Stop → EMA 停損
  4. 交易摩擦成本：手續費 + 滑點（無融資/証交稅）

出場條件優先級：
  ① Climax Exit（爆量正乖離或長上影線）→ 隔日強制出場
  ② ATR 停損 → 立即出場
  ③ ATR 目標價 → 停利出場
  ④ Chandelier Exit（追蹤止利 = 最高 - 2×ATR）
  ⑤ Time Stop（≥15日 且 淨報酬 < 5%）
  ⑥ EMA 停損（跌破防守線）
"""
import logging
import math
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any
from strategy.swing import calculate_max_drawdown
from config import WALK_FORWARD_EXIT_MODES

logger = logging.getLogger('Cow.walkforward')


class WalkForwardBacktester:
    """BTC 波段策略 Walk-Forward 回測器（防先視偏誤）"""

    # 交易成本
    FEE_RATE     = 0.001      # 單邊手續費（Taker 0.1%）
    SLIPPAGE_RATE = 0.0005    # 滑點（0.05%）

    def __init__(self):
        self.annual_days = 365
        self.risk_free   = 0.02
        logger.info('WalkForwardBacktester 初始化')

    def sharpe_ratio(self, returns: pd.Series) -> float:
        """計算年化夏普比率"""
        if returns.empty or returns.std() == 0:
            return 0.0
        daily_rf = self.risk_free / self.annual_days
        excess = returns - daily_rf
        sharpe = excess.mean() / excess.std() * np.sqrt(self.annual_days)
        return round(float(sharpe), 2)

    def run_walkforward(
        self,
        df: pd.DataFrame,
        start_date: str,
        end_date: str,
        initial_capital: float = 10_000,
        scan_freq: int = 5,
        exit_ma: str = "SMA_50",
        # 進場參數
        entry_dist_min_pct: float = 0.0,
        rsi_min: int = 50,
        adx_min: int = 20,
        # 出場參數
        exit_mode: str = "simple",       # 'simple' (只用EMA) 或 'multi' (六層機制)
        atr_period: int = 14,
        atr_sl_multiplier: float = 2.0,   # 停損倍數
        atr_tp_multiplier: float = 3.0,   # 目標價倍數
        min_hold_days: int = 3,
    ) -> Dict[str, Any]:
        """
        ⭐ Walk-Forward 無先視偏誤回測

        :param df:                    BTC 日線 DataFrame（含所有技術指標）
        :param start_date:            回測起始日期（YYYY-MM-DD）
        :param end_date:              回測截止日期（YYYY-MM-DD）
        :param initial_capital:       初始資金（USDT）
        :param scan_freq:             進場掃描頻率（交易日數）
        :param exit_ma:               出場防守線（SMA_50 / EMA_20 / SMA_200）
        :param entry_dist_min_pct:    EMA20 最小乖離 (%)
        :param rsi_min:               RSI 最小值（預設 50）
        :param adx_min:               ADX 最小值（預設 20）
        :param atr_period:            ATR 週期（預設 14）
        :param atr_sl_multiplier:     ATR 停損倍數（預設 2.0）
        :param atr_tp_multiplier:     ATR 目標倍數（預設 3.0）
        :param min_hold_days:         最少持倉天數（預設 3）
        :return:                      回測結果字典（含 trades 明細）
        """
        # 驗證 exit_mode 參數
        if exit_mode not in WALK_FORWARD_EXIT_MODES:
            raise ValueError(
                f"exit_mode 必須為 {list(WALK_FORWARD_EXIT_MODES.keys())}，"
                f"不支援 {exit_mode!r}"
            )

        # Step 1：篩選日期區間
        mask = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
        bt_df = df.loc[mask].copy()

        if bt_df.empty or len(bt_df) < atr_period + 10:
            logger.warning(f'WalkForward：資料不足（{len(bt_df)} 天）')
            return self._empty_result(start_date, end_date)

        # Step 2：預計算輔助序列
        close = bt_df['close'].values
        dates = bt_df.index

        # EMA20 乖離
        ema20 = bt_df['EMA_20'].ffill().values
        dist_pct = np.where(ema20 > 0, (close / ema20 - 1) * 100, np.nan)

        # ATR（供停損/目標 + Chandelier 用）
        high = bt_df['high'].values
        low = bt_df['low'].values
        prev_close = np.concatenate([[close[0]], close[:-1]])
        tr = np.maximum(
            high - low,
            np.maximum(np.abs(high - prev_close), np.abs(low - prev_close))
        )
        atr_series = pd.Series(tr).rolling(atr_period, min_periods=1).mean().values

        # MA20（供 Climax Exit 正乖離判斷）
        ma20 = bt_df['close'].rolling(20, min_periods=1).mean().values

        # 成交量（供 Climax Exit 爆量判斷）
        volume = bt_df.get('volume', pd.Series(1, index=bt_df.index)).values
        vol_ma20 = pd.Series(volume).rolling(20, min_periods=1).mean().values

        # 防守線（出場用）
        if exit_ma not in bt_df.columns:
            exit_ma = 'EMA_20'
        defend_line = bt_df[exit_ma].ffill().values

        # Step 3：向量化計算進場訊號
        open_vals = bt_df['open'].values
        close_shifted = np.concatenate([[np.nan], close[:-1]])  # 防先視：前一日收盤
        ema20_shifted = np.concatenate([[np.nan], ema20[:-1]])

        bull_trend = (close_shifted > bt_df['SMA_200'].fillna(0).values) & \
                     (bt_df['RSI_14'].fillna(0).values > rsi_min)

        dist_ok = (dist_pct >= entry_dist_min_pct) & (dist_pct <= 1.5)

        macd_ok = ((bt_df.get('MACD_12_26_9', 0).fillna(0).values >
                    bt_df.get('MACDs_12_26_9', 0).fillna(0).values)
                   if 'MACD_12_26_9' in bt_df.columns else np.ones(len(bt_df), dtype=bool))

        adx_ok = ((bt_df.get('ADX', 0).fillna(0).values > adx_min)
                  if 'ADX' in bt_df.columns else np.ones(len(bt_df), dtype=bool))

        entry_signal = bull_trend & dist_ok & macd_ok & adx_ok
        entry_signal_shifted = np.concatenate([[False], entry_signal[:-1]])  # shift(1)

        # Step 4：時間迴圈
        trades: List[Dict[str, Any]] = []
        capital = initial_capital
        in_trade = False
        entry_idx = 0
        entry_price = 0.0
        entry_reason = ""
        highest_high = 0.0
        trade_stop_loss = None
        trade_target = None
        climax_pending = False
        _pending_climax_reason = ""
        all_rets: List[pd.Series] = []

        for day_num, (i, date) in enumerate(zip(range(len(bt_df)), dates)):
            cur_price = close[i]
            cur_high = high[i]
            cur_low = low[i]
            date_str = date.strftime('%Y-%m-%d')

            if i < atr_period:
                continue  # 跳過 ATR 未計算的早期日期

            if in_trade:
                # ── 更新持倉最高價 ──
                highest_high = max(highest_high, cur_high)
                hold_days = day_num - entry_idx

                # ── 出場判斷 ──
                do_exit = False
                exit_reason = ""

                # 簡化模式：只用 EMA 防守線
                if exit_mode == "simple":
                    if hold_days >= min_hold_days and cur_price < defend_line[i]:
                        do_exit = True
                        exit_reason = f'跌破{exit_ma} {defend_line[i]:.2f}'
                else:
                    # 多層機制：六層出場條件
                    # ① Climax Exit（隔日執行）
                    if climax_pending:
                        do_exit = True
                        exit_reason = _pending_climax_reason
                        climax_pending = False
                    else:
                        climax_today = False

                        # 正乖離 > 30%
                        if not math.isnan(ma20[i]) and ma20[i] > 0:
                            if cur_price > ma20[i] * 1.3:
                                climax_today = True
                                _pending_climax_reason = (
                                    f'極端出貨：正乖離MA20達'
                                    f'{(cur_price/ma20[i]-1)*100:.1f}%（Climax Exit，隔日強制）'
                                )

                        # 爆量 + 長上影線
                        if not climax_today and not math.isnan(vol_ma20[i]) and vol_ma20[i] > 0:
                            if volume[i] > 5 * vol_ma20[i]:
                                open_val = open_vals[i]
                                body = abs(cur_price - open_val)
                                upper_shadow = cur_high - max(cur_price, open_val)
                                if upper_shadow > body * 0.5 or cur_price < open_val:
                                    climax_today = True
                                    _pending_climax_reason = (
                                        f'極端出貨：爆量{volume[i]/vol_ma20[i]:.1f}倍+'
                                        f'{"長上影線" if upper_shadow>body*0.5 else "收黑"}（Climax Exit）'
                                    )

                        if climax_today:
                            climax_pending = True

                        # ② ATR 停損
                        if trade_stop_loss is not None and cur_price <= trade_stop_loss:
                            do_exit = True
                            exit_reason = f'ATR停損 {trade_stop_loss:.2f}'

                        # ③ ATR 目標
                        elif trade_target is not None and cur_price >= trade_target:
                            upside = (trade_target / entry_price - 1) * 100
                            do_exit = True
                            exit_reason = f'ATR目標 {trade_target:.2f}（+{upside:.1f}%）'

                        # ④ Chandelier Exit
                        elif hold_days >= min_hold_days and atr_series[i] > 0:
                            chandelier_stop = highest_high - 2.0 * atr_series[i]
                            if cur_price < chandelier_stop:
                                do_exit = True
                                exit_reason = f'Chandelier止利 {chandelier_stop:.2f}'

                        # ⑤ Time Stop（15日 + 報酬 < 5%）
                        elif hold_days >= 15:
                            gross_ret = (cur_price / entry_price - 1) * 100
                            friction = (self.FEE_RATE + self.SLIPPAGE_RATE) * 2 * 100  # 往返
                            net_ret = gross_ret - friction
                            if net_ret < 5.0:
                                do_exit = True
                                exit_reason = f'時間停損：持倉{hold_days}日，報酬{net_ret:.1f}%'

                        # ⑥ EMA 停損
                        elif hold_days >= min_hold_days and cur_price < defend_line[i]:
                            do_exit = True
                            exit_reason = f'跌破{exit_ma} {defend_line[i]:.2f}'

                if do_exit:
                    # 計算損益（含摩擦成本）
                    friction_out = self.FEE_RATE + self.SLIPPAGE_RATE
                    exit_price_net = cur_price * (1.0 - friction_out)
                    balance = position * exit_price_net
                    pnl = balance - capital
                    pnl_pct = (exit_price_net / entry_price - 1) * 100

                    trades.append({
                        'entry_date': dates[entry_idx].strftime('%Y-%m-%d'),
                        'exit_date': date_str,
                        'entry_price': entry_price,
                        'exit_price': cur_price,
                        'hold_days': hold_days,
                        'entry_reason': entry_reason,
                        'exit_reason': exit_reason,
                        'position': position,
                        'pnl': round(pnl, 2),
                        'pnl_pct': round(pnl_pct, 2),
                        'final_balance': round(balance, 2),
                    })

                    # 收集日報酬序列
                    seg = pd.Series(close[entry_idx:i+1]).pct_change().dropna()
                    if len(seg) > 0:
                        all_rets.append(seg)

                    capital = balance
                    in_trade = False
                    trade_stop_loss = None
                    trade_target = None
                    highest_high = 0.0

            else:
                # ── 進場掃描（每 scan_freq 天）──
                if day_num % scan_freq == 0 and entry_signal_shifted[i]:
                    # 計算進場成本
                    friction_in = self.FEE_RATE + self.SLIPPAGE_RATE
                    entry_price_net = cur_price * (1.0 + friction_in)
                    position = capital / entry_price_net

                    if position <= 0:
                        continue

                    entry_price = entry_price_net
                    in_trade = True
                    entry_idx = day_num
                    entry_reason = f'Antigravity 5合1 ({exit_ma}防守)'
                    highest_high = cur_price
                    climax_pending = False

                    # 計算 ATR 動態停損/目標
                    cur_atr = atr_series[i]
                    if cur_atr > 0:
                        trade_stop_loss = cur_price - atr_sl_multiplier * cur_atr
                        trade_target = cur_price + atr_tp_multiplier * cur_atr
                    else:
                        trade_stop_loss = None
                        trade_target = None

        # 若持倉至結尾
        if in_trade and len(trades) >= 0:
            last_close = close[-1]
            last_date = dates[-1]
            friction_out = self.FEE_RATE + self.SLIPPAGE_RATE
            exit_price_net = last_close * (1.0 - friction_out)
            balance = position * exit_price_net
            pnl = balance - capital
            pnl_pct = (exit_price_net / entry_price - 1) * 100

            trades.append({
                'entry_date': dates[entry_idx].strftime('%Y-%m-%d'),
                'exit_date': last_date.strftime('%Y-%m-%d'),
                'entry_price': entry_price,
                'exit_price': last_close,
                'hold_days': len(bt_df) - 1 - entry_idx,
                'entry_reason': entry_reason,
                'exit_reason': '持有至回測結尾',
                'position': position,
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'final_balance': round(balance, 2),
            })
            capital = balance

        # Step 5：統計結果
        trades = [t for t in trades if t['exit_date'] != '']

        if not trades:
            logger.info(f'WalkForward {start_date}～{end_date}：無進場訊號')
            return self._empty_result(start_date, end_date)

        final_balance = round(capital, 2)
        roi = (capital / initial_capital - 1) * 100

        # Buy & Hold 基準
        start_idx = 0
        end_idx = len(bt_df) - 1
        bh_start = close[start_idx]
        bh_end = close[end_idx]
        bh_roi = (bh_end / bh_start - 1) * 100
        alpha = roi - bh_roi

        # Sharpe / MDD
        sharpe = 0.0
        mdd = 0.0
        if all_rets:
            combined = pd.concat(all_rets)
            sharpe = self.sharpe_ratio(combined)
            cum_ret = (1 + combined).cumprod().values
            mdd = calculate_max_drawdown(cum_ret)

        # 勝率
        win_trades = [t for t in trades if t['pnl'] > 0]
        win_rate = len(win_trades) / len(trades) * 100 if trades else 0.0

        result = {
            'mode': 'walk_forward',
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': initial_capital,
            'final_balance': final_balance,
            'stock_return': round(roi, 2),
            'benchmark_return': round(bh_roi, 2),
            'alpha': round(alpha, 2),
            'trade_count': len(trades),
            'win_rate': round(win_rate, 1),
            'sharpe': sharpe,
            'max_drawdown': round(mdd, 2),
            'trades': pd.DataFrame(trades),
        }

        logger.info(
            f'WalkForward 完成：{len(trades)} 次交易，'
            f'報酬 {roi:.2f}%，Alpha {alpha:.2f}%，'
            f'Sharpe {sharpe:.2f}，MDD {mdd:.2f}%'
        )

        return result

    @staticmethod
    def _empty_result(start_date: str, end_date: str) -> Dict[str, Any]:
        """返回空結果"""
        return {
            'mode': 'walk_forward',
            'start_date': start_date,
            'end_date': end_date,
            'stock_return': 0.0,
            'benchmark_return': 0.0,
            'alpha': 0.0,
            'trade_count': 0,
            'win_rate': 0.0,
            'sharpe': 0.0,
            'max_drawdown': 0.0,
            'trades': pd.DataFrame(),
        }
