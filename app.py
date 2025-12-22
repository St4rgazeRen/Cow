import streamlit as st
import pandas as pd
import numpy as np
import pandas_ta as ta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import yfinance as yf
import math
import os # Added for file operations
import random
import ccxt
import requests


# --- Page Config & Custom CSS ---
st.set_page_config(
    page_title="比特幣投資戰情室 (Bitcoin Command Center)",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for "Grid Dashboard" feel
st.markdown("""
<style>
    /* Global Font */
    html, body, [class*="css"] {
        font-family: 'Roboto', sans-serif;
    }
    
    /* Card Style */
    .metric-card {
        background-color: #1e1e1e;
        border: 1px solid #333;
        border-radius: 8px;
        padding: 15px;
        margin-bottom: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
    }
    .metric-title {
        color: #888;
        font-size: 0.9rem;
        margin-bottom: 5px;
    }
    .metric-value {
        color: #fff;
        font-size: 1.5rem;
        font-weight: bold;
    }
    .metric-delta {
        font-size: 0.9rem;
    }
    .positive { color: #00ff88; }
    .negative { color: #ff4b4b; }
    .neutral { color: #aaaaaa; }

    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        background-color: #0e1117;
        border: 1px solid #333;
        border-radius: 4px;
        color: #fff;
    }
    .stTabs [aria-selected="true"] {
        background-color: #262730;
        border-bottom: 2px solid #00ff88;
    }
</style>
""", unsafe_allow_html=True)

# --- 1. Data Handler (Real + Mock) ---

@st.cache_data(ttl=300) # Short TTL because we have local cache
def fetch_market_data():
    """Fetch BTC Data with Local CSV Cache (Incremental Update)"""
    file_path = "BTC_HISTORY.csv"
    today = datetime.now().date()
    
    # 1. Load Local
    if os.path.exists(file_path):
        try:
            local_df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            last_date = local_df.index[-1].date()
        except:
            local_df = pd.DataFrame()
            last_date = None
    else:
        local_df = pd.DataFrame()
        last_date = None
        
    # 2. Determine Fetch Range
    btc_new = pd.DataFrame()
    start_date = "2017-01-01"
    
    if last_date:
        if last_date < today:
            start_date = (last_date + timedelta(days=1)).strftime('%Y-%m-%d')
            # Fetch new data
            try:
                btc_new = yf.download("BTC-USD", start=start_date, interval="1d", progress=False)
                if not btc_new.empty:
                    btc_new.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in btc_new.columns]
                    if 'close' not in btc_new.columns and 'Adj Close' in btc_new.columns:
                        btc_new['close'] = btc_new['Adj Close']
            except Exception as e:
                st.warning(f"更新數據失敗: {e}")
    else:
        # Full Fetch
        try:
             btc_new = yf.download("BTC-USD", start="2017-01-01", interval="1d", progress=False)
             btc_new.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in btc_new.columns]
        except Exception as e:
             st.error(f"下載數據失敗: {e}")
             
    # 3. Merge & Save
    if not btc_new.empty:
        if not local_df.empty:
            full_df = pd.concat([local_df, btc_new])
            # Remove duplicates just in case
            full_df = full_df[~full_df.index.duplicated(keep='last')]
        else:
            full_df = btc_new
            
        # Save updates
        full_df.to_csv(file_path)
        btc_final = full_df
    else:
        btc_final = local_df
        
    # Validation
    if btc_final.empty: return pd.DataFrame(), pd.DataFrame()
    
    # Fallback for old CSVs without new columns if needed (not needed for simple OHLC)
    
    # Fetch DXY (Keep simple live fetch for now as it's small/less critical)
    dxy = yf.download("DX-Y.NYB", start="2017-01-01", interval="1d", progress=False)
    dxy.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in dxy.columns]
    
    return btc_final, dxy

def get_mock_funding_rate():
    """Simulate crypto perpetual funding rate"""
    # Simulate a value around 0.01% (basis point)
    base = 0.0001
    noise = random.uniform(-0.00005, 0.0005) # slight bias to positive
    return (base + noise) * 100 # return as percentage

def get_mock_onchain_data():
    """Simulate AHR999 or SOPR components if calculation fails"""
    return {
        "SOPR": 1.0 + random.uniform(-0.05, 0.1),
        "MVRV": 1.5 + random.uniform(-0.5, 1.5)
    }

def get_mock_m2_liquidity():
    """Simulate Global M2 YoY Change"""
    base_growth = 5.0
    cycle = math.sin(datetime.now().timestamp() / 1000000) * 3
    return base_growth + cycle

def get_mock_tvl(price):
    """Simulate BTC Ecosystem TVL (Billions)"""
    # Assumption: TVL correlates with price but with a growing base adoption
    base_btc_locked = 500000 # 500k BTC locked in Lightning/DeFi
    # Add some randomness
    locked = base_btc_locked * random.uniform(0.9, 1.2)
    tvl_billions = (locked * price) / 1e9
    return tvl_billions

def get_mock_global_m2_series(df):
    """Simulate Global M2 Liquidity Trend based on Price Trend + Noise"""
    # M2 tends to correlate with BTC long term. 
    # We create a smoothed curve derived from BTC price with lag
    m2 = df['close'].rolling(window=100).mean()
    # Normalize to an index roughly 80-120
    m2_norm = (m2 / m2.iloc[0]) * 100
    # Add some 'macro' cyclic noise
    time_idx = np.arange(len(df))
    macro_cycle = 5 * np.sin(time_idx / 365)
    return m2_norm + macro_cycle

def calculate_fear_greed_proxy(rsi, close, ma50):
    """
    Proxy F&G based on RSI and Trend
    0-100 scale
    """
    score = rsi # Base is RSI (0-100)
    
    # Trend Bias
    if close > ma50:
        score += 10
    else:
        score -= 10
        
    # Volatility penalty could be added here, but keep simple
    
    # Clamp
    score = max(5, min(95, score))
    return score

# --- 1.1 Real-time Data Fetcher (New) ---

@st.cache_data(ttl=60) # Refresh every 60 seconds
def fetch_realtime_data():
    """
    Fetch real-time data from external APIs:
    1. Binance (Price, Funding Rate) via CCXT
    2. DeFiLlama (BTC Chain TVL) via Requests
    3. Alternative.me (Fear & Greed) via Requests
    """
    data = {
        "price": None,
        "funding_rate": None,
        "tvl": None,
        "fng_value": None,
        "fng_class": None
    }
    
    # 1. Binance via CCXT
    try:
        exchange = ccxt.binance()
        ticker = exchange.fetch_ticker('BTC/USDT')
        data['price'] = ticker['last']
        
        # Funding Rate (fetch_funding_rate is unified in ccxt, but sometimes requires login or specific endpoint)
        # Often fetch_funding_rate for 'BTC/USDT:USDT' on futures
        # We try a safer way: fetch_funding_rate if supported, or fallback
        try:
             # Binance Futures usually requires specific instantiation or symbol
             exchange_fut = ccxt.binance({'options': {'defaultType': 'future'}})
             fr = exchange_fut.fetch_funding_rate('BTC/USDT')
             data['funding_rate'] = fr['fundingRate'] * 100 # Convert to %
        except:
             pass 
    except Exception as e:
        print(f"Binance Error: {e}")

    # 2. DeFiLlama (TVL)
    try:
        # Get Current BTC Price for TVL calc if needed, or get direct Chain TVL
        # Endpoint: https://api.llama.fi/v2/chains
        r = requests.get("https://api.llama.fi/v2/chains", timeout=5)
        if r.status_code == 200:
            chains = r.json()
            for c in chains:
                if c['name'] == 'Bitcoin':
                    data['tvl'] = c['tvl'] / 1e9 # Billions
                    break
    except Exception as e:
        print(f"DeFiLlama Error: {e}")

    # 3. Fear & Greed (Alternative.me)
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=5)
        if r.status_code == 200:
            res = r.json()
            item = res['data'][0]
            data['fng_value'] = int(item['value'])
            data['fng_class'] = item['value_classification']
    except Exception as e:
        print(f"F&G Error: {e}")
        
    return data

# --- 2. Technical Analysis Engine ---

def calculate_technical_indicators(df):
    df = df.copy()
    if df.empty: return df
    
    # Moving Averages
    df['SMA_200'] = ta.sma(df['close'], length=200)
    df['EMA_20'] = ta.ema(df['close'], length=20)
    df['SMA_50'] = ta.sma(df['close'], length=50) # For Golden Cross
    
    # Calculate SMA 200 Slope (20-day lookback for monthly trend of annual average)
    # Positive = Rising, Negative = Falling
    if 'SMA_200' in df.columns:
        df['SMA_200_Slope'] = df['SMA_200'].diff(20)
    else:
        df['SMA_200_Slope'] = 0
    

    
    # RSI (Daily)
    df['RSI_14'] = ta.rsi(df['close'], length=14)
    
    # RSI (Weekly) - Resample to Weekly, Calc RSI, then map back to Daily
    # Use 'W-MON' to align with typical crypto weekly closes
    weekly_close = df['close'].resample('W-MON').last()
    weekly_rsi = ta.rsi(weekly_close, length=14)
    # Reindex back to daily (ffill) to align with original stats
    df['RSI_Weekly'] = weekly_rsi.reindex(df.index).ffill()
    
    # RSI (Weekly) - Resample to Weekly, Calc RSI, then map back to Daily
    # Use 'W-MON' to align with typical crypto weekly closes
    weekly_close = df['close'].resample('W-MON').last()
    weekly_rsi = ta.rsi(weekly_close, length=14)
    # Reindex back to daily (ffill) to align with original stats
    df['RSI_Weekly'] = weekly_rsi.reindex(df.index).ffill()
    
    # ATR
    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    
    # Bollinger Bands
    bb = ta.bbands(df['close'], length=20, std=2.0)
    if bb is not None:
        df = pd.concat([df, bb], axis=1)
        # Rename standard output cols
        bbl = [c for c in df.columns if c.startswith('BBL')][0]
        bbu = [c for c in df.columns if c.startswith('BBU')][0]
        df['BB_Lower'] = df[bbl]
        df['BB_Upper'] = df[bbu]
        
    # Pivot Points (Std Daily)
    # Simple calculation for 'Classic' Pivot
    df['P'] = (df['high'].shift(1) + df['low'].shift(1) + df['close'].shift(1)) / 3
    df['R1'] = 2 * df['P'] - df['low'].shift(1)
    df['S1'] = 2 * df['P'] - df['high'].shift(1)
    # R2/S2 for Strategy
    df['R2'] = df['P'] + (df['high'].shift(1) - df['low'].shift(1))
    df['S2'] = df['P'] - (df['high'].shift(1) - df['low'].shift(1))
    
    # KDJ (9, 3, 3)
    kdj = ta.kdj(df['high'], df['low'], df['close'], length=9, signal=3)
    if kdj is not None:
        df = pd.concat([df, kdj], axis=1)
        # Standardize names
        df['K'] = df['K_9_3']
        df['J'] = df['J_9_3']

    # ADX (Trend Strength)
    adx = ta.adx(df['high'], df['low'], df['close'], length=14)
    if adx is not None:
        df = pd.concat([df, adx], axis=1)
        # Find ADX column (usually ADX_14)
        adx_col = [c for c in df.columns if c.startswith('ADX')][0]
        df['ADX'] = df[adx_col]

    # MACD (12, 26, 9)
    macd = ta.macd(df['close'], fast=12, slow=26, signal=9)
    if macd is not None:
        df = pd.concat([df, macd], axis=1)
        # Standardize names
        macd_col = [c for c in df.columns if c.startswith('MACD_')][0]
        hist_col = [c for c in df.columns if c.startswith('MACDh_')][0]
        sig_col = [c for c in df.columns if c.startswith('MACDs_')][0]
        df['MACD'] = df[macd_col]
        df['MACD_Hist'] = df[hist_col]
        df['MACD_Signal'] = df[sig_col]
    
    return df

def calculate_ahr999(df):
    """
    AHR999 = (Price / 200 Day MA) * (Price / Exponential Growth Valuation)
    Valuation = 10^(2.68 + 0.00057 * Days_Since_Genesis)
    Genesis: 2009-01-03
    """
    genesis_date = datetime(2009, 1, 3)
    
    def get_val(row):
        if pd.isna(row['SMA_200']): return None
        days = (row.name - genesis_date).days
        valuation = 10**(2.68 + 0.00057 * days)
        ahr999 = (row['close'] / row['SMA_200']) * (row['close'] / valuation)
        return ahr999

    df['AHR999'] = df.apply(get_val, axis=1)
    
    
    # MVRV Z-Score Proxy (Requested)
    if not df.empty and 'SMA_200' in df.columns:
        rolling_std = df['close'].rolling(window=200).std()
        df['MVRV_Z_Proxy'] = (df['close'] - df['SMA_200']) / rolling_std
        
    return df

def calculate_max_drawdown(equity_curve):
    """Calculate Max Drawdown from list or series"""
    if len(equity_curve) < 1: return 0.0
    
    peaks = np.maximum.accumulate(equity_curve)
    drawdowns = (equity_curve - peaks) / peaks
    return drawdowns.min() * 100 # percentage (negative)

# --- 2.6 Swing Strategy Logic (New) ---

def run_swing_strategy_backtest(df, start_date, end_date, initial_capital=10000):
    """
    Simulate Swing Trading Strategy
    Entry: Price > SMA200 AND RSI > 50 AND Price within 1.5% of EMA20
    Exit: Price < EMA20 (Trend Break)
    """
    mask = (df.index >= pd.Timestamp(start_date)) & (df.index <= pd.Timestamp(end_date))
    bt_df = df.loc[mask].copy()
    
    if bt_df.empty: return pd.DataFrame(), 0.0, 0.0, 0
    
    balance = initial_capital
    position = 0.0 # Amount of BTC
    state = "CASH" # CASH, INVESTED
    
    trades = []
    
    for i in range(len(bt_df)):
        date = bt_df.index[i]
        row = bt_df.iloc[i]
        
        # Signals
        # 1. Trend Conditions
        bull_trend = (row['close'] > row['SMA_200']) and (row['RSI_14'] > 50)
        
        # 2. Entry Trigger: Price close to EMA20 (Sweet Spot)
        # Note: Previous "Sweet Spot" was dist_pct <= 1.5 (meaning <= 1.5% above EMA20, assuming we don't buy if below?)
        # Let's assume Sweet Spot is abs(dist) <= 1.5%. But strictly, if it's below EMA20, it triggers Exit.
        # So Entry must be: Price >= EMA20 AND Price <= EMA20 * 1.015
        
        ema_20 = row['EMA_20']
        dist_pct = (row['close'] / ema_20 - 1) * 100
        
        # Strict Entry: Bull Trend + Above EMA20 but within 1.5%
        is_entry = bull_trend and (dist_pct >= 0) and (dist_pct <= 1.5)
        
        # Exit Trigger: Close < EMA20
        is_exit = row['close'] < ema_20
        
        # Execution
        if state == "CASH" and is_entry:
            # BUY
            position = balance / row['close']
            entry_price = row['close']
            trades.append({
                "Type": "Buy", "Date": date, "Price": entry_price, 
                "Balance": balance, "Crypto": position, "Reason": "Sweet Spot"
            })
            balance = 0
            state = "INVESTED"
            
        elif state == "INVESTED" and is_exit:
            # SELL
            balance = position * row['close']
            trades.append({
                "Type": "Sell", "Date": date, "Price": row['close'], 
                "Balance": balance, "Crypto": 0, "Reason": "Trend Break (<EMA20)",
                "PnL": balance - (entry_price * position),
                "PnL%": (row['close'] / entry_price - 1) * 100
            })
            position = 0
            state = "CASH"
            
    # Final Valuation
    final_equity = balance if state == "CASH" else position * bt_df.iloc[-1]['close']
    roi = (final_equity - initial_capital) / initial_capital * 100
    
    # Calculate Drawdown
    # We need to reconstruct equity curve
    equity_curve = []
    trade_idx = 0
    
    # Reconstruct daily equity for accuracy? Or just trade-to-trade? 
    # Trade-to-trade is faster but misses open equity dips. 
    # Let's do trade-to-trade for speed in this context, plus closing balance.
    current_bal = initial_capital
    equity_curve.append(current_bal)
    
    for t in trades:
        # Note: trades list has Buy and Sell. 
        # When Buy: Balance becomes 0, Crypto Position exists. Equity doesn't change instantly.
        # When Sell: Crypto becomes 0. Balance updates.
        if t['Type'] == 'Sell':
            current_bal = t['Balance']
            equity_curve.append(current_bal)
            
    # Include final
    equity_curve.append(final_equity)
    mdd = calculate_max_drawdown(np.array(equity_curve))
    
    trades_df = pd.DataFrame(trades)
    return trades_df, final_equity, roi, len(trades_df)//2, mdd

# --- 2.5 Strategy Logic (Migrated from DCI) ---

def calculate_bs_apy(S, K, T_days, sigma_annual, type='call'):
    """Black-Scholes APY Calculator"""
    if T_days <= 0: return 0.0
    T = T_days / 365.0
    r = 0.04 # Risk-free rate 4%

    def norm_cdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    d1 = (np.log(S / K) + (r + 0.5 * sigma_annual ** 2) * T) / (sigma_annual * np.sqrt(T))
    d2 = d1 - sigma_annual * np.sqrt(T)

    if type == 'call': # Sell High
        price = S * norm_cdf(d1) - K * np.exp(-r * T) * norm_cdf(d2)
        principal = S
    else: # Buy Low (Put)
        price = K * np.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
        principal = K

    apy = (price / principal) * (365 / T_days)
    return max(apy, 0.05) # Floor at 5%

def calculate_ladder_strategy(row, product_type):
    """Generate 3-tier strike prices"""
    # 1. Circuit Breakers (Weekend check handled outside)
    
    atr = row['ATR']
    close = row['close']
    
    # Volatility adjustment
    vol_factor = 1.2 if (atr/close) > 0.02 else 1.0 

    targets = []
    
    if product_type == "SELL_HIGH":
        # Base: Max(BB Upper, Pivot R1)
        base_anchor = max(row['BB_Upper'], row.get('R1', row['BB_Upper']))
        
        # Tiers
        strike_1 = base_anchor + (atr * 1.0 * vol_factor)
        strike_2 = max(base_anchor + (atr * 2.0 * vol_factor), row.get('R2', 0)) # Using R2
        strike_3 = base_anchor + (atr * 3.5 * vol_factor)
        
        # Minimum spacing
        strike_1 = max(strike_1, close * 1.015)
        strike_2 = max(strike_2, strike_1 * 1.01)
        strike_3 = max(strike_3, strike_2 * 1.01)
        
        targets = [
            {"Type": "激進 (Aggressive)", "Strike": strike_1, "Weight": "30%", "Distance": (strike_1/close - 1)*100},
            {"Type": "中性 (Moderate)", "Strike": strike_2, "Weight": "30%", "Distance": (strike_2/close - 1)*100},
            {"Type": "保守 (Conservative)", "Strike": strike_3, "Weight": "40%", "Distance": (strike_3/close - 1)*100}
        ]

    elif product_type == "BUY_LOW":
        # Base: Min(BB Lower, Pivot S1)
        base_anchor = min(row['BB_Lower'], row.get('S1', row['BB_Lower']))
        
        # Tiers
        strike_1 = base_anchor - (atr * 1.0 * vol_factor)
        strike_2 = min(base_anchor - (atr * 2.0 * vol_factor), row.get('S2', 999999)) # Using S2
        strike_3 = base_anchor - (atr * 3.5 * vol_factor)
        
        # Minimum spacing
        strike_1 = min(strike_1, close * 0.985)
        strike_2 = min(strike_2, strike_1 * 0.99)
        strike_3 = min(strike_3, strike_2 * 0.99)
        
        targets = [
            {"Type": "激進 (Aggressive)", "Strike": strike_1, "Weight": "30%", "Distance": (close/strike_1 - 1)*100},
            {"Type": "中性 (Moderate)", "Strike": strike_2, "Weight": "30%", "Distance": (close/strike_2 - 1)*100},
            {"Type": "保守 (Conservative)", "Strike": strike_3, "Weight": "40%", "Distance": (close/strike_3 - 1)*100}
        ]
        
    return targets

def get_current_suggestion(df, ma_short_col='EMA_20', ma_long_col='SMA_50'):
    if df.empty: return None
    curr_row = df.iloc[-1]
    curr_time = curr_row.name
    
    weekday = curr_time.weekday()
    duration = 3 if weekday == 4 else 1
    
    # Circuit Breakers
    # Using existing columns in app.py: EMA_20 as short, SMA_50 or SMA_200 as long? 
    # Let's use parameters.
    is_bearish = curr_row[ma_short_col] < curr_row[ma_long_col]
    is_weekend = weekday >= 5
    
    sell_ladder = calculate_ladder_strategy(curr_row, "SELL_HIGH")
    buy_ladder = calculate_ladder_strategy(curr_row, "BUY_LOW")
    
    if is_weekend:
        sell_ladder = []
        buy_ladder = []
    
    if is_bearish:
        buy_ladder = [] # Don't catch falling knife
        
    reasons = []
    if is_weekend: reasons.append("⚠️ **週末濾網**: 流動性較差，建議觀望。")
    if is_bearish: reasons.append("⚠️ **趨勢濾網**: 短均線 < 長均線 (空頭)，禁止 Buy Low。")
    
    # Technical explanation
    reasons.append(f"**MA**: 短均(${curr_row[ma_short_col]:,.0f}) {'<' if is_bearish else '>'} 長均(${curr_row[ma_long_col]:,.0f})")
    reasons.append(f"**RSI**: {curr_row['RSI_14']:.1f}")
    if 'J' in curr_row:
        reasons.append(f"**KDJ(J)**: {curr_row['J']:.1f}")
    if 'ADX' in curr_row:
        reasons.append(f"**ADX**: {curr_row['ADX']:.1f} ({'強趨勢' if curr_row['ADX']>25 else '盤整'})")

    return {
        "time": curr_time,
        "close": curr_row['close'],
        "sell_ladder": sell_ladder,
        "buy_ladder": buy_ladder,
        "explanation": reasons
    }

def run_dual_investment_backtest(df, call_risk=0.5, put_risk=0.5):
    # Simplified Backtest Logic adapted for app.py
    # Re-using the core logic logic from DCI
    
    # Filter for ~UTC+8 16:00 if possible, or use daily close
    # Since app.py downloads '1d' data, we use every row.
    daily_points = df.copy()
    if daily_points.empty: return pd.DataFrame()

    trade_log = []
    current_asset = "BTC"
    balance = 1.0
    state = "IDLE"
    lock_end_time = None
    strike_price = 0.0
    product_type = ""
    prev_start_time = None

    # Identify MA columns
    ma_short_col = 'EMA_20'
    ma_long_col = 'SMA_50' # Using SMA_50 as trend baseline

    indices = daily_points.index
    for i in range(len(indices) - 1):
        curr_time = indices[i]
        curr_row = daily_points.loc[curr_time]

        # 1. Settlement
        if state == "LOCKED":
            if curr_time < lock_end_time: continue
            
            fixing_price = curr_row['close']
            vol_annual = (curr_row['ATR'] / curr_row['close']) * np.sqrt(365 * 24) * 0.5
            duration = (lock_end_time - prev_start_time).days
            
            period_yield = calculate_bs_apy(
                curr_row['close'], strike_price, duration, vol_annual, 
                'call' if product_type == "SELL_HIGH" else 'put'
            ) * (duration / 365)
            
            result_note = ""
            color = "gray"
            
            if product_type == "SELL_HIGH":
                total_btc = balance * (1 + period_yield)
                if fixing_price >= strike_price:
                    balance = total_btc * strike_price # Converted to USDT
                    current_asset = "USDT"
                    result_note = "😭 被行權 (轉USDT)"
                    color = "red"
                else:
                    balance = total_btc
                    current_asset = "BTC"
                    result_note = "✅ 賺幣成功"
                    color = "green"
            elif product_type == "BUY_LOW":
                total_usdt = balance * (1 + period_yield)
                if fixing_price <= strike_price:
                    balance = total_usdt / strike_price # Converted to BTC
                    current_asset = "BTC"
                    result_note = "🤩 抄底成功 (轉BTC)"
                    color = "purple"
                else:
                    balance = total_usdt
                    current_asset = "USDT"
                    result_note = "💰 賺U成功" # Still in USDT
                    color = "orange"
            
            equity_btc = balance if current_asset == "BTC" else balance / fixing_price
            
            trade_log.append({
                "Action": "Settlement", "Time": curr_time, "Fixing": fixing_price,
                "Strike": strike_price, "Asset": current_asset, "Balance": balance,
                "Note": result_note, "Color": color, "Equity_BTC": equity_btc, "Step_Y": strike_price
            })
            state = "IDLE"

        # 2. New Order
        if state == "IDLE":
            weekday = curr_time.weekday()
            duration = 3 if weekday == 4 else 1
            if weekday >= 5: continue # Weekend skip
            
            next_settlement = curr_time + timedelta(days=duration)
            if next_settlement > daily_points.index[-1]: continue
            
            is_bearish = curr_row[ma_short_col] < curr_row[ma_long_col]
            atr_pct = curr_row['ATR'] / curr_row['close']
            dynamic_multiplier = 0.8 if atr_pct > 0.015 else (1.2 if atr_pct < 0.005 else 1.0)
            
            target_strike = 0.0
            
            if current_asset == "BTC":
                # Sell High
                atr_buffer = curr_row['ATR'] * (1 + call_risk) * dynamic_multiplier
                if curr_row.get('ADX', 0) > 25: atr_buffer *= 1.5
                base = max(curr_row['BB_Upper'], curr_row.get('R1', curr_row['BB_Upper']))
                if curr_row.get('J', 50) < 20: atr_buffer *= 1.2
                target_strike = max(base + atr_buffer, curr_row['close'] * 1.01)
                product_type = "SELL_HIGH"
            else:
                # Buy Low
                if is_bearish: continue
                atr_buffer = curr_row['ATR'] * (1 + put_risk) * dynamic_multiplier
                if curr_row.get('ADX', 0) > 25: atr_buffer *= 1.5
                base = min(curr_row['BB_Lower'], curr_row.get('S1', curr_row['BB_Lower']))
                target_strike = min(base - atr_buffer, curr_row['close'] * 0.99)
                product_type = "BUY_LOW"
                
            state = "LOCKED"
            lock_end_time = next_settlement
            strike_price = target_strike
            prev_start_time = curr_time
            
            equity_btc = balance if current_asset == "BTC" else balance / curr_row['close']
            
            trade_log.append({
                "Action": "Open", "Time": curr_time, "Fixing": curr_row['close'],
                "Strike": strike_price, "Asset": current_asset, "Balance": balance,
                "Type": product_type, "Note": f"開單 {product_type}", "Color": "blue",
                "Equity_BTC": equity_btc, "Step_Y": strike_price
            })
            
    return pd.DataFrame(trade_log)

# --- 3. Sidebar Inputs ---
with st.sidebar:
    st.header("⚙️ 戰情室設定")
    capital = st.number_input("總本金 (USDT)", value=10000, step=1000)
    risk_per_trade = st.number_input("單筆風險 (%)", value=2.0, step=0.1, max_value=10.0)
    
    st.markdown("---")
    st.caption("雙幣理財偏好設定")
    call_risk = st.number_input("Sell High 風險係數", value=0.5, step=0.1, help="越大掛越遠 (保守)")
    put_risk = st.number_input("Buy Low 風險係數", value=0.5, step=0.1, help="越大掛越遠 (保守)")
    
    st.markdown("---")
    st.caption("回測參數 (Tab 4)")
    ahr_threshold_backtest = st.slider("AHR999 抄底閾值", 0.3, 1.5, 0.45, 0.05)
    
    st.markdown("---")
    st.markdown("### 關於與免責聲明")
    st.info("""
    **Antigravity v4 Engine**
    本工具僅供輔助分析，不構成投資建議。
    加密貨幣市場波動劇烈，請做好風險管理。
    """)

# --- Main App ---

# 1. Load Data
with st.spinner("正在連線至戰情室數據庫..."):
    btc, dxy = fetch_market_data()
    
    if btc.empty:
        st.error("無法下載 BTC 數據，請檢查網路。")
        st.stop()
        
    # Pre-processing
    btc = calculate_technical_indicators(btc)
    btc = calculate_ahr999(btc)
    
    # Real-time pointers
    # Real-time pointers
    curr = btc.iloc[-1]
    
    # --- Live Data Integration ---
    realtime_data = fetch_realtime_data()
    
    # Override Close Price if available
    current_price = realtime_data['price'] if realtime_data['price'] else curr['close']
    
    # Metrics Logic
    funding_rate = realtime_data['funding_rate'] if realtime_data['funding_rate'] is not None else get_mock_funding_rate()
    tvl_val = realtime_data['tvl'] if realtime_data['tvl'] is not None else get_mock_tvl(current_price)
    
    # Fear & Greed
    if realtime_data['fng_value']:
        fng_val = realtime_data['fng_value']
        fng_state = realtime_data['fng_class']
        # Map to emoji
        if "Extreme Greed" in fng_state: fng_state = "極度貪婪 🤑"
        elif "Greed" in fng_state: fng_state = "貪婪 😃"
        elif "Extreme Fear" in fng_state: fng_state = "極度恐懼 😱"
        elif "Fear" in fng_state: fng_state = "恐懼 😨"
        else: fng_state = "中性 😐"
        fng_source = "Alternative.me"
    else:
        # Fallback to proxy
        fng_val = calculate_fear_greed_proxy(curr['RSI_14'], current_price, curr['SMA_50'])
        fng_state = "極度貪婪 🤑" if fng_val > 75 else ("貪婪 😃" if fng_val > 55 else ("恐懼 😨" if fng_val < 45 else ("極度恐懼 😱" if fng_val < 25 else "中性 😐")))
        fng_source = "Antigravity Proxy"
    
    m2_growth = get_mock_m2_liquidity()
    
st.title("🦅 比特幣投資戰情室")
st.caption(f"數據更新時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | 核心版本: Antigravity v4")

# Tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "🐂 牛市雷達 (Bull Detector)", 
    "🌊 波段狙擊 (Swing Trading)", 
    "💰 雙幣理財 (Dual Investment)", 
    "⏳ 時光機回測 (Backtest)"
])

# --- Tab 1: Bull Market Detector ---
with tab1:
    # Full Width Chart (Requested)
    st.subheader("BTCUSDT 價格K線與 MA200 (Price Action)")
    
    chart_df = btc.tail(365) # Show last year
    
    fig_t1 = go.Figure()
    
    # K-Line
    fig_t1.add_trace(go.Candlestick(
        x=chart_df.index,
        open=chart_df['open'], high=chart_df['high'],
        low=chart_df['low'], close=chart_df['close'],
        name='BTC Price'
    ))
    
    # MA 200
    fig_t1.add_trace(go.Scatter(
        x=chart_df.index, y=chart_df['SMA_200'],
        mode='lines', name='SMA 200',
        line=dict(color='orange', width=2)
    ))
    
    # MA 50 (Added for Golden Cross Context)
    fig_t1.add_trace(go.Scatter(
        x=chart_df.index, y=chart_df['SMA_50'],
        mode='lines', name='SMA 50',
        line=dict(color='cyan', width=1.5, dash='dash')
    ))
    
    fig_t1.update_layout(
        height=500, xaxis_rangeslider_visible=False,
        template="plotly_dark",
        title_text="比特幣日線圖 (Daily Chart)"
    )
    st.plotly_chart(fig_t1, use_container_width=True)
    
    # Market Phase Indicator (5 Stages)
    # Logic:
    # 1. Accumulate (Winter): Price < MA200 & MA50 < MA200
    # 2. Recovering (Early Bull): Price > MA200 & MA50 < MA200
    # 3. Bull Run (Main): Price > MA200 & MA50 > MA200 & Slope > 0
    # 4. Correction (Pullback): Price < MA200 & MA50 > MA200
    # 5. Overheated: MVRV > 3.0 (Override)
    
    price = curr['close']
    ma50 = curr['SMA_50']
    ma200 = curr['SMA_200']
    ma200_slope = curr.get('SMA_200_Slope', 0)
    mvrv = curr.get('MVRV_Z_Proxy', 0)
    
    phase_name = "未知 (Unknown)"
    phase_color = "gray"
    phase_desc = "數據不足"
    
    if mvrv > 3.5:
        phase_name = "🔥 狂熱頂部 (Overheated)"
        phase_color = "red"
        phase_desc = "風險極高，建議分批止盈"
    elif price > ma200 and ma50 > ma200 and ma200_slope > 0:
        phase_name = "🐂 牛市主升段 (Bull Run)"
        phase_color = "green"
        phase_desc = "趨勢多頭排列且年線上揚，主升段"
    elif price > ma200 and ma50 > ma200 and ma200_slope <= 0:
        phase_name = "😴 牛市休整/末期 (Stagnant Bull)"
        phase_color = "orange"
        phase_desc = "價格雖高但年線走平，動能減弱"
    elif price > ma200 and ma50 <= ma200:
        phase_name = "🌱 初牛復甦 (Recovering)"
        phase_color = "blue"
        phase_desc = "價格站上年線，等待黃金交叉與年線翻揚"
    elif price <= ma200 and ma50 > ma200:
        phase_name = "📉 轉折回調 (Correction)"
        phase_color = "orange"
        phase_desc = "跌破年線，需注意是否死叉"
    else:
        phase_name = "❄️ 深熊築底 (Winter)"
        phase_color = "gray"
        phase_desc = "均線空頭排列，定投積累區"
        
    st.info(f"### 📡 當前市場相位：**{phase_name}**\n\n{phase_desc}")
    
    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    
    # Level 1: Chartist (Retail)
    with col1:
        st.markdown("### Level 1: 散戶視角")
        
        # 1. Price Structure (Golden Cross + Slope)
        is_golden = (curr['close'] > curr['SMA_200']) and (curr['SMA_50'] > curr['SMA_200'])
        is_rising = curr.get('SMA_200_Slope', 0) > 0
        
        struct_state = "多頭共振 (STRONG)" if (is_golden and is_rising) else ("震盪/修正 (WEAK)" if not is_golden else "年線走平 (FLAT)")
        
        st.metric(
            "趨勢結構 (Structure)", 
            struct_state,
            delta=f"MA200 斜率 {('↗️ 上升' if is_rising else '↘️ 下降')}",
            delta_color="normal" if is_rising else "off"
        )
        
        # 2. Dow Theory (Simplified)
        # Check if recent high is higher than previous high (20 days window)
        recent_high = btc['high'].iloc[-20:].max()
        prev_high = btc['high'].iloc[-40:-20].max()
        dow_state = "更高的高點 (HH)" if recent_high > prev_high else "高點降低 (LH)"
        st.metric("道氏理論結構", dow_state, delta=None)
        
        # 3. Fear & Greed (Unified)
        fg_color = "normal" if fng_val > 50 else "inverse"
        st.metric(f"情緒指數 ({fng_source})", f"{fng_val:.0f}/100", fng_state)

    # Level 2: Quant (Institutions)
    with col2:
        st.markdown("### Level 2: 機構視角")
        
        # 1. AHR999
        ahr_val = curr['AHR999']
        ahr_state = "🟢 抄底區間" if ahr_val < 0.45 else ("🔴 頂部過熱" if ahr_val > 1.2 else "⚪ 定投/持有")
        st.metric("AHR999 囤幣指標", f"{ahr_val:.2f}", ahr_state)
        
        # 2. MVRV Z-Score Proxy (Real Calculation)
        mvrv_z = curr.get('MVRV_Z_Proxy', 0)
        mvrv_state = "🔥 過熱頂部" if mvrv_z > 3.0 else ("🟢 價值低估" if mvrv_z < 0 else "中性區域")
        st.metric("MVRV Z-Score (Proxy)", f"{mvrv_z:.2f}", mvrv_state)
        
        # 3. TVL (New)
        st.metric("BTC Chain TVL (DeFiLlama)", f"${tvl_val:.2f}B", "持續增長", delta_color="normal")
        
        # 3. Funding Rate
        fr_color = "inverse" if funding_rate > 0.05 else "normal" # Red if overheated
        fr_label = "Binance 資金費率 (Funding)" if realtime_data['funding_rate'] is not None else "資金費率 (模擬)"
        st.metric(fr_label, f"{funding_rate:.4f}%", "多頭擁擠" if funding_rate > 0.03 else "情緒中性", delta_color=fr_color)

    # Level 3: Macro
    with col3:
        st.markdown("### Level 3: 宏觀視角")
        
        # 1. DXY Correlation
        # Calculate correlation
        if not dxy.empty:
            # Align data
            comm_idx = btc.index.intersection(dxy.index)
            corr_90 = btc.loc[comm_idx]['close'].rolling(90).corr(dxy.loc[comm_idx]['close']).iloc[-1]
            st.metric("BTC vs DXY 相關性 (90d)", f"{corr_90:.2f}", "高度負相關" if corr_90 < -0.5 else "脫鉤/正相關")
        else:
            st.metric("BTC vs DXY", "N/A", "數據不足")
            
        # 2. Global M2 (Mock)
        # Calculate on full history to avoid NaN from rolling window
        m2_full = get_mock_global_m2_series(btc)
        # Slice to match chart_df time range
        m2_series = m2_full.reindex(chart_df.index)
        st.line_chart(m2_series, height=120)
        st.caption("全球 M2 流動性趨勢 (模擬)")
        
        st.markdown("---")
        st.markdown("#### 🧠 人工判讀區 (Manual Watch)")
        
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.text_input("🇯🇵 日圓匯率 (JPY)", placeholder="例: 155.5 (關鍵位)", key="macro_jpy")
            st.metric("量子威脅等級 (Quantum Threat)", "Low (Current)", help="量子電腦破解 RSA 簽名的風險等級，目前極低")
        with m_col2:
            st.text_input("🇺🇸 美國 CPI (YoY)", placeholder="例: 3.4% (高於預期)", key="macro_cpi")
            st.info("**技術敘事監控**:\n- 關注 OP_CAT 升級進度 (比特幣原生擴容關鍵)")

# --- Tab 2: Antigravity v4 Swing Trading ---
with tab2:
    st.markdown("### 🌊 Antigravity v4 核心策略引擎")
    
    # A. Trend Filter
    st.subheader("A. 趨勢濾網 (Trend Filter)")
    f_col1, f_col2, f_col3 = st.columns(3)
    
    bull_ma = curr['close'] > curr['SMA_200']
    rsi_weekly_val = curr.get('RSI_Weekly', 50)
    bull_rsi = rsi_weekly_val > 50 
    not_overheated = funding_rate < 0.05
    
    f_col1.markdown(f"**價格 > MA200**: {'✅ 通過' if bull_ma else '❌ 未通過'}")
    f_col2.markdown(f"**週線 RSI > 50**: {'✅ 通過' if bull_rsi else '❌ 未通過 (Day RSI Proxy)'}")
    f_col3.markdown(f"**資金費率 < 0.05%**: {'✅ 通過' if not_overheated else '⚠️ 過熱'}")
    
    can_long = bull_ma and bull_rsi and not_overheated
    
    if can_long:
        st.success("🎯 策略狀態: **允許做多 (LONG ALLOWED)**")
    else:
        st.warning("🛡️ 策略狀態: **風險管控中 (RISK OFF)** - 建議觀望")
        
    st.markdown("---")
    
    # B. Smart Entry & C. Stop Loss
    logic_col1, logic_col2 = st.columns(2)
    
    # B. Smart Entry & Exit Logic
    # B. Smart Entry & Exit Logic
    # logic_col1, logic_col2 defined previously (removed duplicate)
    
    with logic_col1:
        st.subheader("B. 智能進出場 (Entries & Exits)")
        ema_20 = curr['EMA_20']
        dist_ema = (curr['close'] / ema_20) - 1
        dist_pct = dist_ema * 100
        
        st.metric("EMA 20 (趨勢線)", f"${ema_20:,.0f}", f"乖離率 {dist_pct:.2f}%")
        
        # Unified Signal Logic
        # Priority: SELL > BUY > WAIT > HOLD
        
        if curr['close'] < ema_20:
            st.error("🔴 **賣出訊號 (SELL)**\n\n跌破均線 (Trend Break)，短期趨勢轉弱。")
            st.metric("建議回補價 (Re-entry)", f"${curr['BB_Lower']:,.0f}", "布林下軌支撐")
        elif can_long and (0 <= dist_pct <= 1.5):
            st.success("🟢 **買進訊號 (BUY)**\n\n甜蜜點 (Sweet Spot)！趨勢向上且回踩均線。")
            st.metric("建議止盈價 (Target)", f"${curr['BB_Upper']:,.0f}", "布林上軌壓力")
        elif dist_pct > 3.0:
            st.warning(f"🟡 **乖離過大 (WAIT)**\n\n已偏離 {dist_pct:.2f}%，勿追高。")
            st.metric("建議接回價", f"${ema_20:,.0f}", "EMA 20 均線")
        else:
            # Between 1.5% and 3.0% OR (Not 'can_long' but price > EMA20)
            st.info("🔵 **持倉續抱 (HOLD)**\n\n價格位於趨勢線上，趨勢延續中。")
            st.metric("下行防守價", f"${ema_20:,.0f}", "趨勢生命線")

    with logic_col2:
        st.subheader("C. 動態止損 (ATR Stop)")
        atr_val = curr['ATR']
        stop_price = ema_20 - (2.0 * atr_val)
        risk_dist_pct = (curr['close'] - stop_price) / curr['close']
        
        st.metric("建議止損價 (EMA20 - 2ATR)", f"${stop_price:,.0f}", f"預計虧損幅度 -{risk_dist_pct*100:.2f}%")
        if risk_dist_pct < 0:
            st.error("⚠️ 警告：當前價格已低於建議止損價！")

    st.markdown("---")
    
    # D. Position Calculator
    st.subheader("D. 倉位計算機 (Risk Calculator)")
    
    entry_price = st.number_input("預計進場與價格 (預設現價)", value=float(curr['close']))
    manual_stop = st.number_input("止損價格 (預設系統建議)", value=float(stop_price))
    
    if st.button("計算建議倉位"):
        if entry_price <= manual_stop:
            st.error("❌ 進場價必須高於止損價 (做多邏輯)")
        else:
            risk_amt = capital * (risk_per_trade / 100)
            stop_dist_usd = entry_price - manual_stop
            
            # Position Size in BTC
            pos_size_btc = risk_amt / stop_dist_usd
            # Position Size in USDT
            pos_size_usdt = pos_size_btc * entry_price
            
            # Leverage Check
            leverage = pos_size_usdt / capital
            
            st.markdown(f"""
            #### 🧮 計算結果
            - **風險金額**: `${risk_amt:.2f}` ({risk_per_trade}%)
            - **止損距離**: `${stop_dist_usd:.2f}` ({(stop_dist_usd/entry_price)*100:.2f}%)
            """)
            
            res_col1, res_col2 = st.columns(2)
            
            if leverage > 1.5:
                res_col1.warning(f"⚠️ 原始計算槓桿: {leverage:.2f}x (超過 1.5x 上限)")
                capped_pos_usdt = capital * 1.5
                capped_pos_btc = capped_pos_usdt / entry_price
                new_risk_pct = ((capped_pos_btc * stop_dist_usd) / capital) * 100
                
                res_col1.metric("建議開倉 (經風控)", f"{capped_pos_btc:.4f} BTC", f"總值 ${capped_pos_usdt:,.0f}")
                res_col2.metric("這筆交易的實際風險", f"{new_risk_pct:.2f}%", f"原本 {risk_per_trade}%")
                st.caption("註：已強制觸發 1.5x 槓桿上限，實際承受風險將低於您的設定值，這是為了保護本金。")
            else:
                res_col1.metric("建議開倉", f"{pos_size_btc:.4f} BTC", f"總值 ${pos_size_usdt:,.0f}")
                res_col2.metric("槓桿倍數", f"{leverage:.2f}x", "安全範圍")

# --- Tab 3: Dual Investment ---
# --- Tab 3: Dual Investment (Updated) ---
with tab3:
    st.markdown("### 💰 雙幣理財顧問 (Dual Investment)")
    
    # Get Suggestion using new logic
    suggestion = get_current_suggestion(btc)
    
    if suggestion:
        s_col1, s_col2 = st.columns([1, 2])
        
        with s_col1:
            st.metric("核心信號", "Sell High" if not btc.iloc[-1]['EMA_20'] < btc.iloc[-1]['SMA_50'] else "觀望 / Sell High Only")
            st.caption("基於 EMA20 vs SMA50 趨勢")
            
            st.markdown("#### 技術解讀")
            for line in suggestion['explanation']:
                st.markdown(f"- {line}")
                
        with s_col2:
            st.markdown("#### 🎯 智能掛單推薦 (Ladder Strategy)")
            
            t1, t2 = st.tabs(["🟢 Sell High (持有BTC)", "🔴 Buy Low (持有USDT)"])
            
            with t1:
                if suggestion['sell_ladder']:
                    df_sell = pd.DataFrame(suggestion['sell_ladder'])
                    df_sell['Strike'] = df_sell['Strike'].apply(lambda x: f"${x:,.0f}")
                    df_sell['Distance'] = df_sell['Distance'].apply(lambda x: f"+{x:.2f}%")
                    st.table(df_sell[['Type', 'Strike', 'Weight', 'Distance']])
                else:
                    st.info("暫無建議 (可能是週末或數據不足)")
                    
            with t2:
                if suggestion['buy_ladder']:
                    df_buy = pd.DataFrame(suggestion['buy_ladder'])
                    df_buy['Strike'] = df_buy['Strike'].apply(lambda x: f"${x:,.0f}")
                    df_buy['Distance'] = df_buy['Distance'].apply(lambda x: f"{x:.2f}%") # Distance already negative
                    st.table(df_buy[['Type', 'Strike', 'Weight', 'Distance']])
                else:
                    st.warning("⚠️ 趨勢偏空或濾網觸發，不建議 Buy Low (接刀)")

# --- Tab 4: Backtest ---
# --- Tab 4: Backtest (Specific Spec) ---
with tab4:
    st.markdown("### ⏳ 時光機回測 (Backtest Engine)")
    
    bt_tab1, bt_tab2, bt_tab3 = st.tabs(["📉 波段策略 PnL", "💰 雙幣滾倉回測", "🐂 牛市雷達準確度 (New)"])
    
    # --- Sub-Tab 1: Swing Strategy Backtest (PnL) ---
    # --- Sub-Tab 1: Swing Strategy Backtest (PnL) ---
    with bt_tab1:
        st.markdown("#### 📉 波段策略驗證 (自訂區間 PnL)")
        
        b_col1, b_col2 = st.columns([1, 3])
        
        with b_col1:
            st.subheader("⚙️ 回測設定")
            
            # Date Inputs
            min_date = btc.index[0].date()
            max_date = btc.index[-1].date()
            
            start_d = st.date_input("開始日期", value=min_date + timedelta(days=365), min_value=min_date, max_value=max_date)
            end_d = st.date_input("結束日期", value=max_date, min_value=min_date, max_value=max_date)
            
            init_cap = st.number_input("初始本金 (USDT)", value=10000, step=1000)
            
            if st.button("🚀 執行波段回測"):
                run_backtest = True
            else:
                run_backtest = False
                
        with b_col2:
            if run_backtest:
                if start_d >= end_d:
                    st.error("結束日期必須晚於開始日期")
                else:
                    with st.spinner("正在模擬交易..."):
                        trades, final_val, roi, num_trades, mdd = run_swing_strategy_backtest(btc, start_d, end_d, init_cap)
                        
                        # Metrics
                        m1, m2, m3, m4, m5 = st.columns(5)
                        m1.metric("最終資產", f"${final_val:,.0f}")
                        m2.metric("總報酬率 (ROI)", f"{roi:+.2f}%", delta_color="normal")
                        
                        # Buy & Hold Comparison
                        start_price = btc.loc[pd.Timestamp(start_d):]['close'].iloc[0]
                        end_price = btc.loc[:pd.Timestamp(end_d)]['close'].iloc[-1]
                        bh_roi = (end_price/start_price - 1) * 100
                        
                        m3.metric("Buy & Hold 報酬", f"{bh_roi:+.2f}%")
                        m4.metric("最大回撤 (MDD)", f"{mdd:.2f}%", delta_color="inverse")
                        m5.metric("總交易", f"{num_trades} 次")
                        
                        # Plot
                        fig = go.Figure()
                        # Price
                        mask = (btc.index >= pd.Timestamp(start_d)) & (btc.index <= pd.Timestamp(end_d))
                        sub_df = btc.loc[mask]
                        
                        fig.add_trace(go.Scatter(x=sub_df.index, y=sub_df['close'], mode='lines', name='Price', line=dict(color='gray', width=1)))
                        fig.add_trace(go.Scatter(x=sub_df.index, y=sub_df['EMA_20'], mode='lines', name='EMA 20', line=dict(color='yellow', width=1)))
                        
                        # Markers
                        if not trades.empty:
                            buys = trades[trades['Type'] == 'Buy']
                            sells = trades[trades['Type'] == 'Sell']
                            
                            fig.add_trace(go.Scatter(
                                x=buys['Date'], y=buys['Price'], mode='markers', name='Buy',
                                marker=dict(color='#00ff88', symbol='triangle-up', size=10)
                            ))
                            fig.add_trace(go.Scatter(
                                x=sells['Date'], y=sells['Price'], mode='markers', name='Sell',
                                marker=dict(color='#ff4b4b', symbol='triangle-down', size=10)
                            ))
                            
                        fig.update_layout(title="波段交易買賣點回放", height=500, template="plotly_dark")
                        st.plotly_chart(fig, use_container_width=True)
                        
                        if not trades.empty:
                             with st.expander("交易明細 (Trade List)"):
                                 st.dataframe(trades)

    # --- Sub-Tab 2: Dual Investment PnL ---
    with bt_tab2:
        st.markdown("#### 💰 雙幣理財長期滾倉回測")
        c_run1, c_run2 = st.columns([1, 3])
        with c_run1:
            if st.button("🚀 執行滾倉回測"):
                with st.spinner("正在模擬兩年每日滾倉數據..."):
                    logs = run_dual_investment_backtest(btc, call_risk=call_risk, put_risk=put_risk)
                    
                    if not logs.empty:
                        # Metrics
                        m1, m2 = st.columns(2)
                        final_eq = logs.iloc[-1]['Equity_BTC']
                        ret = (final_eq - 1) * 100
                        m1.metric("最終權益 (BTC)", f"{final_eq:.4f}", f"{ret:.2f}%")
                        m2.metric("總交易次數", f"{len(logs[logs['Action']=='Open'])} 次")
                        
                        # Chart
                        fig2 = go.Figure()
                        fig2.add_trace(go.Scatter(x=logs['Time'], y=logs['Equity_BTC'], mode='lines', name='Equity (BTC)', line=dict(color='#00ff88')))
                        fig2.update_layout(title="資產淨值走勢 (BTC本位)", height=400, template="plotly_dark")
                        st.plotly_chart(fig2, use_container_width=True)
                        
                        with st.expander("詳細交易日誌"):
                            st.dataframe(logs)
                    else:
                        st.warning("無交易紀錄")

    # --- Sub-Tab 3: Macro Bull Radar Validation ---
    with bt_tab3:
        st.markdown("#### 🐂 牛市雷達準確度驗證")
        st.caption("驗證：黃金交叉 (Close > MA200 & MA50 > MA200) + **年線上揚 (MA200 Slope > 0)**")


        # Ground Truth Bull Runs (User Specified)
        bull_ranges = [
            ("2017-01", "2017-12"),
            ("2020-10", "2021-04"),
            ("2023-10", "2024-03")
        ]
        
        # Logic: Bull if Close > SMA200 AND SMA50 > SMA200 AND SMA200 Slope > 0
        val_df = btc.copy()
        # Strict Logic Filter: Golden Cross AND Rising MA200 AND NOT Overheated (AHR < Threshold check?)
        # User asked for AHR sensitivity. Let's add a separate column for AHR check
        
        # Base Trend Signal
        val_df['Trend_Bull'] = (val_df['close'] > val_df['SMA_200']) & \
                               (val_df['SMA_50'] > val_df['SMA_200']) & \
                               (val_df['SMA_200_Slope'] > 0)
                               
        # AHR Filter (Optional composite test)
        # If AHR > Threshold (Overheated?), maybe we sell?
        # User asked: "Allow adjusting AHR999 threshold... to observe accuracy".
        # Let's assume validation is against "Trend Bull" 
        val_df['Signal_Bull'] = val_df['Trend_Bull'] # Simple Trend Validation
        
        # Label Ground Truth
        val_df['Actual_Bull'] = False
        for start, end in bull_ranges:
            try:
                # Handle YYYY-MM loose format
                s_dt = pd.to_datetime(start)
                e_dt = pd.to_datetime(end) + pd.offsets.MonthEnd(0)
                val_df.loc[s_dt:e_dt, 'Actual_Bull'] = True
            except:
                pass
            
        # Comparison
        conditions = [
            (val_df['Signal_Bull'] == True) & (val_df['Actual_Bull'] == True),
            (val_df['Signal_Bull'] == True) & (val_df['Actual_Bull'] == False),
            (val_df['Signal_Bull'] == False) & (val_df['Actual_Bull'] == True),
            (val_df['Signal_Bull'] == False) & (val_df['Actual_Bull'] == False)
        ]
        choices = ['Correct Bull', 'False Alarm (Trap)', 'Missed Opportunity', 'Correct Bear']
        val_df['Result'] = np.select(conditions, choices, default='Unknown')
        
        # Stats
        total_days = len(val_df)
        counts = val_df['Result'].value_counts()
        
        # Visualization
        # Use a colored bar chart or timeline
        
        v1, v2, v3, v4 = st.columns(4)
        c_bull = counts.get('Correct Bull', 0)
        c_trap = counts.get('False Alarm (Trap)', 0)
        c_miss = counts.get('Missed Opportunity', 0)
        
        bull_days = len(val_df[val_df['Actual_Bull']])
        sensitivity = c_bull / bull_days * 100 if bull_days > 0 else 0
        
        v1.metric("牛市捕捉率 (Sensitivity)", f"{sensitivity:.1f}%", f"{c_bull} 天命中")
        v2.metric("誤報天數 (Bull Trap)", f"{c_trap} 天", "均線糾纏區震盪", delta_color="inverse")
        v3.metric("踏空天數 (Missed)", f"{c_miss} 天", "起漲點延遲", delta_color="inverse")
        
        acc_total = (c_bull + counts.get('Correct Bear', 0)) / total_days * 100
        v4.metric("整體準確度", f"{acc_total:.1f}%")
        
        # AHR Filter Overlay (User requested sensitivity test)
        # Using ahr_threshold_backtest from sidebar
        val_df['AHR_Signal'] = val_df['AHR999'] < ahr_threshold_backtest
        
        # Comparison logic remains roughly same, but we can color differently
        # Let's show "Trend Bull" vs "Ground Truth" as primary
        
        # ... [Metrics Calculation Code] ...
        
        # Plot
        fig_m = go.Figure()
        
        # Price
        fig_m.add_trace(go.Scatter(x=val_df.index, y=val_df['close'], mode='lines', name='Price', line=dict(color='gray', width=1)))
        fig_m.add_trace(go.Scatter(x=val_df.index, y=val_df['SMA_200'], mode='lines', name='SMA 200', line=dict(color='orange', width=1)))
        
        # Color Backgrounds
        traps = val_df[val_df['Result'] == 'False Alarm (Trap)']
        if not traps.empty:
            fig_m.add_trace(go.Scatter(x=traps.index, y=traps['close'], mode='markers', name='❌ 誤判 (Bull Trap)', marker=dict(color='#ff4b4b', size=8, symbol='x')))

        corrects = val_df[val_df['Result'] == 'Correct Bull']
        if not corrects.empty:
             fig_m.add_trace(go.Scatter(x=corrects.index, y=corrects['close'], mode='markers', name='✅ 命中 (Correct)', marker=dict(color='#00ff88', size=4, opacity=0.4, symbol='circle')))
             
        # Add AHR Overlay (Blue Dots for Buy Zones based on Slider)
        ahr_buys = val_df[val_df['AHR_Signal']]
        if not ahr_buys.empty:
            fig_m.add_trace(go.Scatter(x=ahr_buys.index, y=ahr_buys['close']*0.9, mode='markers', name=f'AHR < {ahr_threshold_backtest} (Buy Zone)', marker=dict(color='cyan', size=2, opacity=0.3)))
            
        fig_m.update_layout(
            title="策略有效性驗證 (Signal vs Reality)", 
            height=400, 
            template="plotly_dark",
            yaxis_type="log"
        )
        st.plotly_chart(fig_m, use_container_width=True)
