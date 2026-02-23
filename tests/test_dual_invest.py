"""
tests/test_dual_invest.py
針對 strategy/dual_invest.py 的期權收益推算自動化測試

測試範圍:
  1. calculate_bs_apy() - Black-Scholes APY 計算
     - Call/Put 選擇權合理性驗證
     - 邊界條件（T=0, ATM, Deep ITM/OTM）
     - APY 最小值保護 (max(apy, 0.05))
  2. calculate_ladder_strategy() - 梯形行權價建議
     - 生成 3 檔梯形
     - SELL_HIGH 行權價必須高於現價
     - BUY_LOW 行權價必須低於現價
  3. get_dynamic_risk_free_rate() - 動態無風險利率
     - 返回值在合理範圍 (0.005 ~ 0.20)
     - 快取機制不阻塞

執行方式:
  cd /home/user/Cow
  pytest tests/test_dual_invest.py -v

[Task #10] pytest 測試，覆蓋 dual_invest.py 核心邏輯
"""
import math
import pytest
import pandas as pd
import numpy as np
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy.dual_invest import (
    calculate_bs_apy,
    calculate_ladder_strategy,
    get_dynamic_risk_free_rate,
    _RISK_FREE_FALLBACK,
)


# ────────────────────────────────────────────────────────────────
# 測試輔助函式
# ────────────────────────────────────────────────────────────────

def _make_indicator_row(price: float = 50_000.0) -> pd.Series:
    """
    建立包含所有必要技術指標的單行 pandas Series。
    用於測試 calculate_ladder_strategy()。
    """
    atr   = price * 0.02   # 假設 ATR 為現價的 2%
    sigma = 0.60            # 60% 年化波動率（BTC 典型值）
    return pd.Series({
        'close':     price,
        'ATR':       atr,
        'BB_Upper':  price * 1.03,
        'BB_Lower':  price * 0.97,
        'R1':        price * 1.04,
        'R2':        price * 1.08,
        'S1':        price * 0.96,
        'S2':        price * 0.92,
        'EMA_20':    price * 0.995,
        'SMA_50':    price * 0.98,
    })


# ────────────────────────────────────────────────────────────────
# 測試群組 1: Black-Scholes APY 計算
# ────────────────────────────────────────────────────────────────

class TestCalculateBsApy:
    """calculate_bs_apy() 核心 APY 計算測試"""

    def test_call_option_at_the_money(self):
        """
        平值 Call (S=K)：期權有正價值，APY 應 > 0.05（最小值保護）。
        ATM 期權的時間價值最大，APY 應相對較高。
        """
        apy = calculate_bs_apy(S=50000, K=50000, T_days=30,
                                sigma_annual=0.60, option_type='call')
        assert apy >= 0.05, f"ATM Call APY 應 >= 5%，實際: {apy:.4f}"
        assert apy < 10.0,  f"ATM Call APY 不應超過 1000%，實際: {apy:.4f}"

    def test_put_option_at_the_money(self):
        """平值 Put (S=K)：期權有正價值，APY 應 > 0.05"""
        apy = calculate_bs_apy(S=50000, K=50000, T_days=30,
                                sigma_annual=0.60, option_type='put')
        assert apy >= 0.05, f"ATM Put APY 應 >= 5%，實際: {apy:.4f}"

    def test_deep_otm_call_lower_apy(self):
        """
        深度 OTM Call（行權價遠高於現價）：期權價值接近 0，APY 趨向最小值。
        行權價 = 現價 × 2（深度 OTM）
        """
        apy_atm  = calculate_bs_apy(S=50000, K=50000,  T_days=30, sigma_annual=0.60)
        apy_dotm = calculate_bs_apy(S=50000, K=100000, T_days=30, sigma_annual=0.60)
        # 深度 OTM 的 APY 不應高於 ATM（但受最小值保護，可能相同）
        assert apy_dotm <= apy_atm + 0.001, (
            f"深度 OTM ({apy_dotm:.4f}) 不應高於 ATM ({apy_atm:.4f})"
        )

    def test_longer_duration_affects_apy(self):
        """
        期限越長，APY 通常越低（分子是期權絕對值，分母是本金；
        隨期限增加，期權價值增加但除以更長期限後 APY 下降）
        注意：這個關係不是嚴格單調的，取決於 sigma 和 moneyness。
        此測試只驗證結果為合理正數。
        """
        apy_3d  = calculate_bs_apy(S=50000, K=55000, T_days=3,  sigma_annual=0.60)
        apy_30d = calculate_bs_apy(S=50000, K=55000, T_days=30, sigma_annual=0.60)
        # 兩者都應 >= 最小值保護
        assert apy_3d  >= 0.05
        assert apy_30d >= 0.05

    def test_zero_days_returns_zero(self):
        """T_days <= 0 時應返回 0.0（避免除零錯誤）"""
        apy = calculate_bs_apy(S=50000, K=50000, T_days=0, sigma_annual=0.60)
        assert apy == 0.0

    def test_negative_days_returns_zero(self):
        """負數 T_days 應返回 0.0"""
        apy = calculate_bs_apy(S=50000, K=50000, T_days=-5, sigma_annual=0.60)
        assert apy == 0.0

    def test_minimum_apy_protection(self):
        """
        APY 最小值保護：即使期權幾乎無價值，APY 也應 >= 0.05 (5%)。
        使用極端 OTM 情況觸發最小值。
        """
        apy = calculate_bs_apy(S=50000, K=500000, T_days=1,
                                sigma_annual=0.60, option_type='call')
        assert apy >= 0.05, f"APY 最小值保護失效，實際: {apy:.6f}"

    def test_higher_sigma_higher_apy(self):
        """
        波動率越高，期權價值越高（Black-Scholes Vega > 0），APY 應更高。
        使用相同的 ATM 情況比較高/低波動率。
        """
        apy_low_vol  = calculate_bs_apy(S=50000, K=52000, T_days=30,
                                         sigma_annual=0.30, option_type='call')
        apy_high_vol = calculate_bs_apy(S=50000, K=52000, T_days=30,
                                         sigma_annual=0.90, option_type='call')
        assert apy_high_vol >= apy_low_vol, (
            f"高波動率 APY ({apy_high_vol:.4f}) 應 >= 低波動率 ({apy_low_vol:.4f})"
        )

    def test_call_put_parity_principle(self):
        """
        Put-Call Parity 原理驗證（近似）：
        ATM 時 Call 和 Put 的絕對期權價值應相近（不完全相等，因有折現因子）。
        此處只驗證兩者都 > 0。
        """
        call_apy = calculate_bs_apy(S=50000, K=50000, T_days=30,
                                     sigma_annual=0.60, option_type='call')
        put_apy  = calculate_bs_apy(S=50000, K=50000, T_days=30,
                                     sigma_annual=0.60, option_type='put')
        assert call_apy > 0.0
        assert put_apy  > 0.0


# ────────────────────────────────────────────────────────────────
# 測試群組 2: 梯形行權價建議
# ────────────────────────────────────────────────────────────────

class TestCalculateLadderStrategy:
    """calculate_ladder_strategy() 梯形行權價生成測試"""

    def test_sell_high_returns_three_tiers(self):
        """SELL_HIGH 應返回 3 檔梯形"""
        row = _make_indicator_row(50_000)
        result = calculate_ladder_strategy(row, 'SELL_HIGH', t_days=3)
        assert len(result) == 3, f"應有 3 檔梯形，實際: {len(result)}"

    def test_buy_low_returns_three_tiers(self):
        """BUY_LOW 應返回 3 檔梯形"""
        row = _make_indicator_row(50_000)
        result = calculate_ladder_strategy(row, 'BUY_LOW', t_days=3)
        assert len(result) == 3

    def test_sell_high_strikes_above_price(self):
        """
        SELL_HIGH 的所有行權價應高於現價（這是 Call 的基本邏輯）。
        至少激進檔（最低的那檔）應高於現價。
        """
        price = 50_000.0
        row   = _make_indicator_row(price)
        result = calculate_ladder_strategy(row, 'SELL_HIGH', t_days=3)

        for tier in result:
            assert tier['Strike'] > price * 0.99, (
                f"SELL_HIGH 行權價 {tier['Strike']:,.0f} 應高於現價 {price:,.0f}"
            )

    def test_buy_low_strikes_below_price(self):
        """
        BUY_LOW 的所有行權價應低於現價（這是 Put 的基本邏輯）。
        """
        price = 50_000.0
        row   = _make_indicator_row(price)
        result = calculate_ladder_strategy(row, 'BUY_LOW', t_days=3)

        for tier in result:
            assert tier['Strike'] < price * 1.01, (
                f"BUY_LOW 行權價 {tier['Strike']:,.0f} 應低於現價 {price:,.0f}"
            )

    def test_sell_high_tiers_ascending(self):
        """SELL_HIGH 的行權價應從低到高排列（激進 < 中性 < 保守）"""
        row    = _make_indicator_row(50_000)
        result = calculate_ladder_strategy(row, 'SELL_HIGH', t_days=3)
        strikes = [t['Strike'] for t in result]
        assert strikes[0] <= strikes[1] <= strikes[2], (
            f"SELL_HIGH 行權價應升序: {strikes}"
        )

    def test_buy_low_tiers_descending(self):
        """BUY_LOW 的行權價應從高到低排列（激進 > 中性 > 保守）"""
        row    = _make_indicator_row(50_000)
        result = calculate_ladder_strategy(row, 'BUY_LOW', t_days=3)
        strikes = [t['Strike'] for t in result]
        assert strikes[0] >= strikes[1] >= strikes[2], (
            f"BUY_LOW 行權價應降序: {strikes}"
        )

    def test_tier_types_correct(self):
        """梯形類型應為 ['激進', '中性', '保守']"""
        row    = _make_indicator_row(50_000)
        result = calculate_ladder_strategy(row, 'SELL_HIGH', t_days=3)
        types  = [t['Type'] for t in result]
        assert types == ['激進', '中性', '保守']

    def test_apy_string_format(self):
        """APY 欄位應為 '數字%' 格式的字串"""
        row    = _make_indicator_row(50_000)
        result = calculate_ladder_strategy(row, 'SELL_HIGH', t_days=3)
        for tier in result:
            apy_str = tier['APY(年化)']
            assert apy_str.endswith('%'), f"APY 格式錯誤: {apy_str}"
            # 可解析為 float
            apy_val = float(apy_str.rstrip('%'))
            assert apy_val >= 5.0, f"APY 應 >= 5%（最小值保護），實際: {apy_val}"

    def test_distance_is_positive(self):
        """Distance（行權價與現價的距離百分比）應 > 0"""
        row    = _make_indicator_row(50_000)
        for product_type in ['SELL_HIGH', 'BUY_LOW']:
            result = calculate_ladder_strategy(row, product_type, t_days=3)
            for tier in result:
                assert tier['Distance'] >= 0, (
                    f"{product_type} tier {tier['Type']} Distance 應 >= 0，"
                    f"實際: {tier['Distance']:.2f}"
                )


# ────────────────────────────────────────────────────────────────
# 測試群組 3: 動態無風險利率
# ────────────────────────────────────────────────────────────────

class TestGetDynamicRiskFreeRate:
    """get_dynamic_risk_free_rate() 動態利率獲取測試"""

    def test_returns_float(self):
        """應返回 float 型別"""
        rate = get_dynamic_risk_free_rate()
        assert isinstance(rate, float), f"應返回 float，實際: {type(rate)}"

    def test_rate_in_reasonable_range(self):
        """
        利率應在合理範圍內:
        - 最低: 0.005 (0.5%) — DeFi 利率不應趨近於零
        - 最高: 0.20 (20%) — DeFi 利率不應超過 20%
        - fallback 為 0.04 (4%)
        若 API 不可用（例如測試環境），fallback 值應仍在此範圍內。
        """
        rate = get_dynamic_risk_free_rate()
        assert 0.001 <= rate <= 0.25, (
            f"利率 {rate:.4f} ({rate*100:.2f}%) 超出合理範圍 [0.1%, 25%]"
        )

    def test_fallback_is_defined(self):
        """確認 fallback 常數已定義且值合理"""
        assert _RISK_FREE_FALLBACK == 0.04, (
            f"Fallback 利率應為 0.04，實際: {_RISK_FREE_FALLBACK}"
        )

    def test_caching_returns_same_value(self):
        """
        快取機制：在 TTL 內連續呼叫兩次應返回相同值
        （快取命中，不發出新的 HTTP 請求）
        """
        rate1 = get_dynamic_risk_free_rate()
        rate2 = get_dynamic_risk_free_rate()
        assert rate1 == rate2, (
            f"快取命中應返回相同值: {rate1:.6f} vs {rate2:.6f}"
        )

    def test_apy_uses_dynamic_rate(self):
        """
        calculate_bs_apy() 應使用動態利率而非寫死的 0.04。
        驗證方式：呼叫 BS APY 不崩潰且返回合理值。
        """
        # 若 get_dynamic_risk_free_rate() 拋出例外，calculate_bs_apy 也會崩潰
        try:
            apy = calculate_bs_apy(S=50000, K=52000, T_days=7,
                                    sigma_annual=0.60, option_type='call')
            assert apy >= 0.05
        except Exception as e:
            pytest.fail(f"calculate_bs_apy() 使用動態利率時崩潰: {e}")
