"""
strategy/dual_invest.py
雙幣理財策略引擎
- Black-Scholes APY 計算
- 梯形行權價建議
- 每日滾倉回測
純 Python，無 Streamlit 依賴

[Task #6] 動態無風險利率:
原始: r = 0.04  (寫死 4%，與市場脫節)
新版: 優先從 DeFiLlama Aave USDT 供應利率取得，
      網路失敗時 fallback 到 MakerDAO DSR，
      最終 fallback 到固定 4%。
利率每次呼叫 calculate_bs_apy() 都是動態獲取（帶本地快取避免重複請求）。
"""
import math
import time
import numpy as np
import pandas as pd
import requests
import urllib3          # [Task #1] SSL 警告靜默（與其他模組一致）
from datetime import timedelta

# 從集中設定檔讀取環境參數與雙幣策略參數
from config import SSL_VERIFY, DUAL_INVEST_COOLDOWN_DAYS

# [Task #1] 動態 SSL：本地端關閉警告；雲端 SSL_VERIFY=True 不需要關閉
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────────────────────────────────────────────────────────
# [Task #6] 動態無風險利率快取
# 使用模組等級變數做簡單 TTL 快取（避免每次 BS 計算都發 HTTP 請求）
# TTL = 3600 秒（1 小時）
# ──────────────────────────────────────────────────────────────────────────────
_risk_free_rate_cache  = {"rate": None, "ts": 0.0}  # {rate: float, ts: unix timestamp}
_RISK_FREE_CACHE_TTL   = 3600  # 快取有效期（秒）
_RISK_FREE_FALLBACK    = 0.04  # 最終 fallback: 4%


def _fetch_aave_usdt_rate() -> float | None:
    """
    從 DeFiLlama 抓取 Aave V3 (Ethereum) 的 USDT 供應利率（APY）作為無風險利率基準。

    DeFiLlama pools endpoint 回傳所有 DeFi 協議的 pool 數據，
    我們篩選 Aave V3 (Ethereum) 的 USDT 供應池，取 apyBase（基礎利率，不含獎勵）。

    [Task #1] verify=False 繞過企業 SSL
    """
    try:
        resp = requests.get(
            "https://yields.llama.fi/pools",
            timeout=8,
            verify=SSL_VERIFY,  # [Task #1] 動態 SSL：本地 False / 雲端 True
        )
        if resp.status_code != 200:
            return None

        pools = resp.json().get('data', [])
        for pool in pools:
            # 篩選條件：Aave V3、Ethereum 主網、USDT 供應池
            if (pool.get('project') == 'aave-v3'
                    and pool.get('chain') == 'Ethereum'
                    and pool.get('symbol') == 'USDT'):
                apy_base = pool.get('apyBase')  # 年化基礎利率（百分比）
                if apy_base is not None and apy_base > 0:
                    # DeFiLlama 的 apyBase 以百分比表示（如 5.2 代表 5.2%）
                    # Black-Scholes 需要小數形式（0.052）
                    rate = float(apy_base) / 100.0
                    print(f"[DynRate] Aave V3 USDT APY: {apy_base:.2f}%")
                    return rate
    except Exception as e:
        print(f"[DynRate] Aave 利率抓取失敗: {e}")
    return None


def _fetch_makerdao_dsr() -> float | None:
    """
    備援：從 DeFiLlama 抓取 MakerDAO DSR (DAI Savings Rate) 作為無風險利率。
    MakerDAO DSR 是 DeFi 世界公認的基準無風險利率之一。

    [Task #1] verify=False 繞過企業 SSL
    """
    try:
        resp = requests.get(
            "https://yields.llama.fi/pools",
            timeout=8,
            verify=SSL_VERIFY,  # [Task #1] 動態 SSL：本地 False / 雲端 True
        )
        if resp.status_code != 200:
            return None

        pools = resp.json().get('data', [])
        for pool in pools:
            # MakerDAO DSR 池
            if (pool.get('project') == 'makerdao'
                    and pool.get('symbol') in ('DAI', 'sDAI')
                    and pool.get('chain') == 'Ethereum'):
                apy_base = pool.get('apyBase')
                if apy_base is not None and apy_base > 0:
                    rate = float(apy_base) / 100.0
                    print(f"[DynRate] MakerDAO DSR: {apy_base:.2f}%")
                    return rate
    except Exception as e:
        print(f"[DynRate] MakerDAO DSR 抓取失敗: {e}")
    return None


def get_dynamic_risk_free_rate() -> float:
    """
    動態獲取無風險利率（帶 1 小時本地快取）。

    取得順序:
    1. 本地快取（TTL 1 小時內直接返回）
    2. DeFiLlama Aave V3 USDT 供應利率（首選）
    3. DeFiLlama MakerDAO DSR（備援）
    4. 固定 4%（最終 fallback）

    返回: float，年化利率（小數，如 0.052 = 5.2%）
    """
    global _risk_free_rate_cache

    now = time.time()

    # 快取命中：距上次更新不超過 TTL
    if (_risk_free_rate_cache["rate"] is not None
            and now - _risk_free_rate_cache["ts"] < _RISK_FREE_CACHE_TTL):
        return _risk_free_rate_cache["rate"]

    # 嘗試依序抓取
    rate = _fetch_aave_usdt_rate() or _fetch_makerdao_dsr()

    # 驗證合理性：DeFi 利率通常在 0.5% ~ 20% 之間，超出範圍視為異常數據
    if rate is not None and 0.005 <= rate <= 0.20:
        _risk_free_rate_cache = {"rate": rate, "ts": now}
        return rate

    # Fallback：使用固定利率，但也更新快取避免頻繁重試
    print(f"[DynRate] 使用 fallback 利率: {_RISK_FREE_FALLBACK*100:.1f}%")
    _risk_free_rate_cache = {"rate": _RISK_FREE_FALLBACK, "ts": now}
    return _RISK_FREE_FALLBACK


def calculate_bs_apy(S, K, T_days, sigma_annual, option_type='call'):
    """
    Black-Scholes 期權定價 → 年化 APY

    [Task #6] 無風險利率 r 改為動態獲取（取代寫死的 0.04）:
    - 優先使用 Aave V3 USDT 供應利率（DeFiLlama API）
    - 備援使用 MakerDAO DSR
    - 最終 fallback: 4%
    - 利率帶 1 小時本地快取，不影響 APY 計算效能
    """
    if T_days <= 0:
        return 0.0
    T = T_days / 365.0

    # [Task #6] 動態獲取無風險利率（帶快取，通常不會發出 HTTP 請求）
    r = get_dynamic_risk_free_rate()

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


def calculate_ladder_strategy(row, product_type, t_days=3):
    """
    生成 3 檔梯形行權價建議 (含 BS APY 預估)
    product_type: 'SELL_HIGH' | 'BUY_LOW'
    t_days: 產品期限（天），用於計算 APY，預設 3 天
    """
    atr = row['ATR']
    close = row['close']
    vol_factor = 1.2 if (atr / close) > 0.02 else 1.0

    # 年化波動率 (ATR 估算)
    sigma = max((atr / close) * math.sqrt(365), 0.3)
    opt_type = 'call' if product_type == "SELL_HIGH" else 'put'

    def _apy_str(strike):
        apy = calculate_bs_apy(close, strike, t_days, sigma, opt_type) * 100
        return f"{apy:.1f}%"

    targets = []

    if product_type == "SELL_HIGH":
        base = max(row['BB_Upper'], row.get('R1', row['BB_Upper']))
        s1 = max(base + atr * 1.0 * vol_factor, close * 1.015)
        s2 = max(base + atr * 2.0 * vol_factor, row.get('R2', 0), s1 * 1.01)
        s3 = max(base + atr * 3.5 * vol_factor, s2 * 1.01)
        targets = [
            {"Type": "激進", "Strike": s1, "Weight": "30%",
             "Distance": (s1 / close - 1) * 100, "APY(年化)": _apy_str(s1)},
            {"Type": "中性", "Strike": s2, "Weight": "30%",
             "Distance": (s2 / close - 1) * 100, "APY(年化)": _apy_str(s2)},
            {"Type": "保守", "Strike": s3, "Weight": "40%",
             "Distance": (s3 / close - 1) * 100, "APY(年化)": _apy_str(s3)},
        ]
    elif product_type == "BUY_LOW":
        base = min(row['BB_Lower'], row.get('S1', row['BB_Lower']))
        s1 = min(base - atr * 1.0 * vol_factor, close * 0.985)
        s2 = min(base - atr * 2.0 * vol_factor, row.get('S2', 999_999), s1 * 0.99)
        s3 = min(base - atr * 3.5 * vol_factor, s2 * 0.99)
        targets = [
            {"Type": "激進", "Strike": s1, "Weight": "30%",
             "Distance": (close / s1 - 1) * 100, "APY(年化)": _apy_str(s1)},
            {"Type": "中性", "Strike": s2, "Weight": "30%",
             "Distance": (close / s2 - 1) * 100, "APY(年化)": _apy_str(s2)},
            {"Type": "保守", "Strike": s3, "Weight": "40%",
             "Distance": (close / s3 - 1) * 100, "APY(年化)": _apy_str(s3)},
        ]

    return targets


def get_current_suggestion(df, ma_short_col='EMA_20', ma_long_col='SMA_50', t_days=3):
    """生成當前雙幣理財建議（含梯形行權價與 APY 估算）"""
    if df.empty:
        return None
    curr_row = df.iloc[-1]
    curr_time = curr_row.name
    weekday = curr_time.weekday()

    is_bearish = curr_row[ma_short_col] < curr_row[ma_long_col]
    is_weekend = weekday >= 5

    sell_ladder = [] if is_weekend else calculate_ladder_strategy(curr_row, "SELL_HIGH", t_days)
    buy_ladder = [] if (is_weekend or is_bearish) else calculate_ladder_strategy(curr_row, "BUY_LOW", t_days)

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


def run_dual_investment_backtest(
    df,
    call_risk=0.5,
    put_risk=0.5,
    cooldown_days=DUAL_INVEST_COOLDOWN_DAYS,
):
    """
    雙幣理財逐日滾倉回測
    以 BTC 計價，模擬每日選擇 SELL_HIGH 或 BUY_LOW

    [Backtest Realism] 空窗期（Cooldown）模擬:
    ─────────────────────────────────────────────────────────────────
    cooldown_days: 結算後等待天數，才重新判定開單（預設 1 天）。

    真實操作中，結算後需要：
      1. 確認收到結算資產（鏈上確認 / 平台到帳）
      2. 觀察市場情緒再決定下一單方向
    直接在結算當天立即開下一單，會導致回測過度樂觀。

    實作方式：
      - 結算後記錄 cooldown_end_time = curr_time + timedelta(days=cooldown_days)
      - 在 IDLE 狀態中，若 curr_time < cooldown_end_time 則跳過開單
    ─────────────────────────────────────────────────────────────────

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

    # [Backtest Realism] 追蹤空窗期結束時間（結算後 cooldown_days 天內禁止開單）
    # 初始化為 None，代表回測開始時無空窗限制
    cooldown_end_time = None

    indices = daily.index
    for i in range(len(indices) - 1):
        curr_time = indices[i]
        curr_row = daily.loc[curr_time]

        # ── 結算邏輯 ──────────────────────────────────────────────────────
        if state == "LOCKED":
            # 尚未到結算時間，繼續等待
            if curr_time < lock_end_time:
                continue

            # 到達結算日，計算收益與行權結果
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

            # [Backtest Realism] 設定空窗期：結算當天起算，cooldown_days 天後才能開單
            # 例如 cooldown_days=1：今天結算，明天才能開下一單
            cooldown_end_time = curr_time + timedelta(days=cooldown_days)
            state = "IDLE"

        # ── 開單邏輯 ──────────────────────────────────────────────────────
        if state == "IDLE":
            # [Backtest Realism] 空窗期濾網：若尚在冷卻期內則跳過開單
            # 模擬真實操作中結算後需要觀察市場、確認到帳的等待行為
            if cooldown_end_time is not None and curr_time < cooldown_end_time:
                continue

            weekday = curr_time.weekday()
            if weekday >= 5:
                # 週末流動性差，不開單
                continue

            duration = 3 if weekday == 4 else 1  # 週五開 3 天期（跨週末）
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
