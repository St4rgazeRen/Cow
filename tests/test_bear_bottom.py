"""
tests/test_bear_bottom.py
針對 core/bear_bottom.py 的計分邏輯自動化測試

測試範圍:
  1. calculate_bear_bottom_score() - 單筆即時評分
     - 各指標邊界值測試
     - 總分計算正確性
     - NaN 值處理
  2. score_series() - 向量化批量計算
     - 與單筆計分結果一致性
     - 空 DataFrame 處理
     - 最大/最小分數邊界

執行方式:
  cd /home/user/Cow
  pytest tests/test_bear_bottom.py -v

[Task #10] pytest 測試，覆蓋 bear_bottom.py 核心評分邏輯
"""
import math
import pytest
import numpy as np
import pandas as pd

# 將專案根目錄加入 Python 路徑，確保可以直接 import
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.bear_bottom import calculate_bear_bottom_score, score_series


# ────────────────────────────────────────────────────────────────
# 共用 Fixture
# ────────────────────────────────────────────────────────────────

def _make_row(ahr=1.0, mvrv=1.0, pi_gap=5.0, sma200w=2.0,
              puell=1.0, rsi_m=50.0, pl_ratio=5.0, mayer=1.2) -> dict:
    """
    建立單行測試資料 (dict 格式，對應 calculate_bear_bottom_score(row) 的輸入)。
    預設值設定為中性分數（每個指標得 0 或最低分），方便逐項測試。
    """
    return {
        'AHR999':         ahr,
        'MVRV_Z_Proxy':   mvrv,
        'PiCycle_Gap':    pi_gap,
        'SMA200W_Ratio':  sma200w,
        'Puell_Proxy':    puell,
        'RSI_Monthly':    rsi_m,
        'PowerLaw_Ratio': pl_ratio,
        'Mayer_Multiple': mayer,
    }


def _make_df(rows: list[dict]) -> pd.DataFrame:
    """
    建立批量測試 DataFrame (對應 score_series(df) 的輸入)。
    """
    return pd.DataFrame(rows, index=pd.date_range('2021-01-01', periods=len(rows), freq='D'))


# ────────────────────────────────────────────────────────────────
# 測試群組 1: AHR999 指標 (最高 20 分)
# ────────────────────────────────────────────────────────────────

class TestAhr999Scoring:
    """AHR999 囤幣指標評分邏輯測試"""

    def test_ahr999_extreme_bottom(self):
        """< 0.45 → 20 分（歷史抄底區）"""
        row = _make_row(ahr=0.44)
        score, signals = calculate_bear_bottom_score(row)
        assert signals['AHR999']['score'] == 20

    def test_ahr999_undervalued(self):
        """0.45 ~ 0.8 → 13 分（偏低估）"""
        row = _make_row(ahr=0.60)
        score, signals = calculate_bear_bottom_score(row)
        assert signals['AHR999']['score'] == 13

    def test_ahr999_fair_value(self):
        """0.8 ~ 1.2 → 5 分（合理區間）"""
        row = _make_row(ahr=1.0)
        score, signals = calculate_bear_bottom_score(row)
        assert signals['AHR999']['score'] == 5

    def test_ahr999_overvalued(self):
        """>= 1.2 → 0 分（高估）"""
        row = _make_row(ahr=1.5)
        score, signals = calculate_bear_bottom_score(row)
        assert signals['AHR999']['score'] == 0

    def test_ahr999_boundary_exact(self):
        """邊界值精確測試：0.45 本身應得 13 分（0.45 <= v < 0.8）"""
        row = _make_row(ahr=0.45)
        score, signals = calculate_bear_bottom_score(row)
        assert signals['AHR999']['score'] == 13

    def test_ahr999_boundary_upper(self):
        """邊界值精確測試：0.8 本身應得 5 分"""
        row = _make_row(ahr=0.80)
        score, signals = calculate_bear_bottom_score(row)
        assert signals['AHR999']['score'] == 5


# ────────────────────────────────────────────────────────────────
# 測試群組 2: MVRV Z-Score (最高 18 分)
# ────────────────────────────────────────────────────────────────

class TestMvrvScoring:
    """MVRV Z-Score Proxy 評分測試"""

    def test_mvrv_strong_bottom(self):
        """< -1.0 → 18 分（強力底部）"""
        row = _make_row(mvrv=-1.5)
        _, signals = calculate_bear_bottom_score(row)
        assert signals['MVRV_Z_Proxy']['score'] == 18

    def test_mvrv_undervalued(self):
        """-1.0 ~ 0 → 12 分（低估）"""
        row = _make_row(mvrv=-0.5)
        _, signals = calculate_bear_bottom_score(row)
        assert signals['MVRV_Z_Proxy']['score'] == 12

    def test_mvrv_neutral(self):
        """0 ~ 2.0 → 4 分（中性）"""
        row = _make_row(mvrv=1.0)
        _, signals = calculate_bear_bottom_score(row)
        assert signals['MVRV_Z_Proxy']['score'] == 4

    def test_mvrv_overheated(self):
        """>= 2.0 → 0 分（高估/頂部）"""
        row = _make_row(mvrv=3.5)
        _, signals = calculate_bear_bottom_score(row)
        assert signals['MVRV_Z_Proxy']['score'] == 0


# ────────────────────────────────────────────────────────────────
# 測試群組 3: 複合總分計算
# ────────────────────────────────────────────────────────────────

class TestTotalScoreCalculation:
    """複合總分計算正確性測試"""

    def test_all_maximum_score(self):
        """
        所有指標都在最高分區間時，總分應等於各指標最高分之和:
        AHR999(20) + MVRV(18) + PiCycle(15) + SMA200W(15) +
        Puell(12) + RSI_M(10) + PowerLaw(5) + Mayer(5) = 100
        """
        row = _make_row(
            ahr=0.3,      # < 0.45 → 20
            mvrv=-1.5,    # < -1.0 → 18
            pi_gap=-15.0, # < -10  → 15
            sma200w=0.8,  # < 1.0  → 15
            puell=0.3,    # < 0.5  → 12
            rsi_m=25.0,   # < 30   → 10
            pl_ratio=1.5, # < 2.0  → 5
            mayer=0.7,    # < 0.8  → 5
        )
        score, signals = calculate_bear_bottom_score(row)
        assert score == 100, f"最高分應為 100，實際得 {score}"

    def test_all_zero_score(self):
        """
        所有指標都在 0 分區間時，總分應為 0
        """
        row = _make_row(
            ahr=2.0,       # >= 1.2 → 0
            mvrv=5.0,      # >= 2.0 → 0
            pi_gap=20.0,   # >= 5   → 0
            sma200w=5.0,   # >= 4.0 → 0
            puell=2.0,     # >= 1.5 → 0
            rsi_m=80.0,    # >= 55  → 0
            pl_ratio=15.0, # >= 10  → 0
            mayer=2.0,     # >= 1.5 → 0
        )
        score, signals = calculate_bear_bottom_score(row)
        assert score == 0, f"最低分應為 0，實際得 {score}"

    def test_score_is_sum_of_signals(self):
        """總分應等於各 signal 分數之和"""
        row = _make_row(ahr=0.6, mvrv=0.5, pi_gap=0.0, sma200w=1.5,
                        puell=0.6, rsi_m=35.0, pl_ratio=3.0, mayer=0.9)
        score, signals = calculate_bear_bottom_score(row)
        expected = sum(v['score'] for v in signals.values())
        assert score == expected, f"總分 {score} 不等於 signals 之和 {expected}"

    def test_score_range(self):
        """分數必須在 [0, 100] 範圍內"""
        row = _make_row(ahr=0.44, mvrv=-1.5, pi_gap=-15.0, sma200w=0.8,
                        puell=0.3, rsi_m=25.0, pl_ratio=1.5, mayer=0.7)
        score, _ = calculate_bear_bottom_score(row)
        assert 0 <= score <= 100


# ────────────────────────────────────────────────────────────────
# 測試群組 4: NaN 值處理
# ────────────────────────────────────────────────────────────────

class TestNanHandling:
    """NaN/None 值不應導致程式崩潰"""

    def test_none_values_dont_crash(self):
        """None 值應被靜默忽略（該指標得 0 分但不拋出例外）"""
        row = {'AHR999': None, 'MVRV_Z_Proxy': None}
        try:
            score, signals = calculate_bear_bottom_score(row)
        except Exception as e:
            pytest.fail(f"None 值導致例外: {e}")

    def test_nan_values_dont_crash(self):
        """math.nan 值應被靜默忽略"""
        row = _make_row(ahr=float('nan'), mvrv=float('nan'))
        try:
            score, signals = calculate_bear_bottom_score(row)
        except Exception as e:
            pytest.fail(f"NaN 值導致例外: {e}")

    def test_missing_keys_dont_crash(self):
        """缺少欄位的 dict 不應崩潰（使用 row.get() 的 None fallback）"""
        row = {}  # 完全空的 row
        try:
            score, signals = calculate_bear_bottom_score(row)
            assert score == 0
        except Exception as e:
            pytest.fail(f"空 row 導致例外: {e}")


# ────────────────────────────────────────────────────────────────
# 測試群組 5: score_series() 向量化批量計算
# ────────────────────────────────────────────────────────────────

class TestScoreSeries:
    """score_series() 向量化批量計算一致性測試"""

    def test_score_series_consistency_with_single(self):
        """
        score_series() 的批量結果應與 calculate_bear_bottom_score() 的逐行結果一致。
        這是向量化重構後最重要的正確性驗證。
        """
        rows = [
            _make_row(ahr=0.3, mvrv=-1.5, pi_gap=-15.0, sma200w=0.8,
                      puell=0.3, rsi_m=25.0, pl_ratio=1.5, mayer=0.7),   # 滿分
            _make_row(ahr=1.5, mvrv=3.0, pi_gap=15.0, sma200w=5.0,
                      puell=2.0, rsi_m=70.0, pl_ratio=12.0, mayer=2.0),  # 零分
            _make_row(ahr=0.6, mvrv=-0.5, pi_gap=-5.0, sma200w=1.2,
                      puell=0.7, rsi_m=35.0, pl_ratio=3.0, mayer=0.9),   # 中間分
        ]
        df = _make_df(rows)

        # 向量化批量計算
        batch_scores = score_series(df)

        # 逐行計算對照
        for i, row in enumerate(rows):
            single_score, _ = calculate_bear_bottom_score(row)
            batch_score = int(batch_scores.iloc[i])
            assert batch_score == single_score, (
                f"第 {i} 行: score_series()={batch_score} vs "
                f"calculate_bear_bottom_score()={single_score}"
            )

    def test_score_series_empty_df(self):
        """空 DataFrame 應返回空 Series，不崩潰"""
        df = pd.DataFrame()
        result = score_series(df)
        assert len(result) == 0

    def test_score_series_max_score(self):
        """最高分 row 應得 100"""
        rows = [_make_row(ahr=0.3, mvrv=-1.5, pi_gap=-15.0, sma200w=0.8,
                          puell=0.3, rsi_m=25.0, pl_ratio=1.5, mayer=0.7)]
        df = _make_df(rows)
        scores = score_series(df)
        assert int(scores.iloc[0]) == 100

    def test_score_series_min_score(self):
        """最低分 row 應得 0"""
        rows = [_make_row(ahr=2.0, mvrv=5.0, pi_gap=20.0, sma200w=5.0,
                          puell=2.0, rsi_m=80.0, pl_ratio=15.0, mayer=2.0)]
        df = _make_df(rows)
        scores = score_series(df)
        assert int(scores.iloc[0]) == 0

    def test_score_series_returns_integers(self):
        """score_series() 應返回整數 Series（方便前端顯示）"""
        rows = [_make_row(), _make_row(ahr=0.3)]
        df = _make_df(rows)
        scores = score_series(df)
        assert scores.dtype in (int, 'int64', 'int32'), f"dtype 應為整數，實際為 {scores.dtype}"

    def test_score_series_length_matches_input(self):
        """返回長度應與輸入 DataFrame 行數一致"""
        rows = [_make_row() for _ in range(10)]
        df = _make_df(rows)
        scores = score_series(df)
        assert len(scores) == 10
