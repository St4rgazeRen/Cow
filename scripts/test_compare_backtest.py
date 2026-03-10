#!/usr/bin/env python3
"""
scripts/test_compare_backtest.py
比較 swing.py vs walkforward_backtest.py 在相同參數下的結果
"""
import sys, os, warnings
warnings.filterwarnings('ignore')

from unittest.mock import MagicMock
sys.modules['streamlit'] = MagicMock()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd
import pandas_ta as ta
from service.local_db_reader import _read_single_year, get_available_years

# ── 載入 BTC 日線 ──
years = get_available_years()
print(f"可用年份：{years}")

dfs = [_read_single_year(y) for y in years]
df_15m = pd.concat([d for d in dfs if not d.empty])
df_15m = df_15m[~df_15m.index.duplicated(keep='last')].sort_index()
print(f"15m rows: {len(df_15m)}, {str(df_15m.index[0])[:10]} ~ {str(df_15m.index[-1])[:10]}")

btc = df_15m.resample('1D').agg(
    open=('open','first'), high=('high','max'),
    low=('low','min'), close=('close','last'), volume=('volume','sum')
).dropna(subset=['close'])
print(f"日線 rows: {len(btc)}")

# ── 計算技術指標 ──
btc['SMA_200'] = ta.sma(btc['close'], length=200)
btc['EMA_20']  = ta.ema(btc['close'], length=20)
btc['SMA_50']  = ta.sma(btc['close'], length=50)
btc['RSI_14']  = ta.rsi(btc['close'], length=14)

adx = ta.adx(btc['high'], btc['low'], btc['close'], length=14)
if adx is not None:
    btc = pd.concat([btc, adx], axis=1)
    adx_col = [c for c in btc.columns if c.startswith('ADX_') or c == 'ADX'][0]
    btc['ADX'] = btc[adx_col]

macd = ta.macd(btc['close'], fast=12, slow=26, signal=9)
if macd is not None:
    btc = pd.concat([btc, macd], axis=1)

# ── 回測共用參數 ──
START   = "2020-01-01"
END     = "2025-12-31"
CAP     = 10_000
DIST    = 0.0
RSI     = 50
ADX_MIN = 20
EXIT_MA = "SMA_50"

print(f"\n== 回測參數 ==")
print(f"區間: {START} ~ {END}, 資金: ${CAP:,}")
print(f"EMA20 乖離 >= {DIST}%（無上限）, RSI>{RSI}, ADX>{ADX_MIN}, 防守線={EXIT_MA}")

# ── 子分頁1：swing.py ──
from strategy.swing import run_swing_strategy_backtest
_, final_s, roi_s, n_s, mdd_s, stats_s = run_swing_strategy_backtest(
    btc, START, END, CAP,
    entry_dist_min_pct=DIST, rsi_min=RSI, adx_min=ADX_MIN, exit_ma=EXIT_MA,
)
print(f"\n[Sub-Tab 1] swing.py")
print(f"  ROI: {roi_s:+.2f}%  交易: {n_s}次  勝率: {stats_s['win_rate']:.1f}%  MDD: {mdd_s:.2f}%")

# ── 子分頁5：Walk-Forward 修復後（無上限 + scan=1）──
from strategy.walkforward_backtest import WalkForwardBacktester
bt = WalkForwardBacktester()
wf_new = bt.run_walkforward(
    df=btc, start_date=START, end_date=END, initial_capital=CAP,
    scan_freq=1, exit_ma=EXIT_MA,
    entry_dist_min_pct=DIST, entry_dist_max_pct=None,
    rsi_min=RSI, adx_min=ADX_MIN, exit_mode="simple",
)
print(f"\n[Sub-Tab 5] Walk-Forward 修復後（scan=1, 無上限）")
print(f"  ROI: {wf_new['stock_return']:+.2f}%  交易: {wf_new['trade_count']}次  勝率: {wf_new['win_rate']:.1f}%  MDD: {wf_new['max_drawdown']:.2f}%")

# ── 舊版對照（dist_max=1.5%, scan=5）──
wf_old = bt.run_walkforward(
    df=btc, start_date=START, end_date=END, initial_capital=CAP,
    scan_freq=5, exit_ma=EXIT_MA,
    entry_dist_min_pct=DIST, entry_dist_max_pct=1.5,
    rsi_min=RSI, adx_min=ADX_MIN, exit_mode="simple",
)
print(f"\n[舊版對照] Walk-Forward（dist_max=1.5%, scan=5）")
print(f"  ROI: {wf_old['stock_return']:+.2f}%  交易: {wf_old['trade_count']}次  勝率: {wf_old['win_rate']:.1f}%  MDD: {wf_old['max_drawdown']:.2f}%")

# ── 結論 ──
diff = wf_new['stock_return'] - roi_s
print(f"\n== 差距分析 ==")
print(f"  swing vs walk-forward(修復後): {diff:+.2f}%")
print(f"  舊版 walk-forward ROI: {wf_old['stock_return']:+.2f}%（問題版）")
if abs(diff) < 100:
    print("  ✅ 修復有效：兩者差距已縮小到合理範圍")
else:
    print("  ⚠️  差距仍大，需進一步排查")
