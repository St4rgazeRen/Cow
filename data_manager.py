import pandas as pd
import requests
import ccxt
import os
from datetime import datetime, timedelta
import asyncio

DATA_DIR = "data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# --- 1. DeFiLlama TVL History ---
def update_tvl_history():
    """Fetch Bitcoin Chain TVL History from DeFiLlama and cache to CSV."""
    file_path = os.path.join(DATA_DIR, "TVL_HISTORY.csv")
    
    # Check last date
    last_ts = 0
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path)
            last_ts = df['date'].iloc[-1]
        except:
            pass
            
    # If data is fresh (updated today), skip? 
    # Let's just fetch full if simple, or incremental if supported.
    # DeFiLlama historical endpoint is full-dump usually. It's small enough to just overwrite/merge daily.
    
    try:
        url = "https://api.llama.fi/v2/historicalChainTvl/Bitcoin"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # Format: {'date': 12345678, 'tvl': 12345.5}
            new_df = pd.DataFrame(data)
            new_df['date'] = pd.to_datetime(new_df['date'], unit='s', utc=True)
            new_df['date'] = new_df['date'].dt.tz_localize(None) # Remove TZ info to match yfinance naive
            new_df.set_index('date', inplace=True)
            
            # Merge logic for robustness (though full fetch overrides)
            new_df.to_csv(file_path)
            return new_df
    except Exception as e:
        print(f"Error fetching TVL: {e}")
        if os.path.exists(file_path):
            return pd.read_csv(file_path, index_col=0, parse_dates=True)
            
    return pd.DataFrame()

# --- 2. Global Stablecoin Market Cap History ---
def update_stablecoin_history():
    """Fetch Global Stablecoin Market Cap History from DeFiLlama."""
    file_path = os.path.join(DATA_DIR, "STABLECOIN_HISTORY.csv")
    
    try:
        # Endpoint for Total Stablecoin Market Cap Chart
        url = "https://stablecoins.llama.fi/stablecoincharts/all"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # Format: [{'date': 16000000, 'totalCirculating': {'usd': 10000}}, ...]
            
            processed = []
            for item in data:
                ts = int(item['date'])
                mcap = item['totalCirculating'].get('usd', 0)
                
                # Skip invalid or zero values
                if mcap <= 1000: # Threshold to filter 0 or dust
                    continue
                    
                # Use UTC-TIMESTAMP to avoid local time issues
                dt_obj = datetime.utcfromtimestamp(ts)
                processed.append({'date': dt_obj, 'mcap': mcap})
            
            if not processed:
                print("Warning: No valid stablecoin data found.")
                
            new_df = pd.DataFrame(processed)
            if not new_df.empty:
                new_df.set_index('date', inplace=True)
                # Ensure naive
                if new_df.index.tz is not None:
                    new_df.index = new_df.index.tz_localize(None)
                new_df.to_csv(file_path)
                return new_df
    except Exception as e:
        print(f"Error fetching Stablecoins: {e}")
        if os.path.exists(file_path):
            return pd.read_csv(file_path, index_col=0, parse_dates=True)

    return pd.DataFrame()

# --- 3. Binance Funding Rate History (Incremental) ---
def update_funding_history(symbol='BTC/USDT', limit=1000):
    """Fetch and cache Funding Rate history for BTC/USDT Futures."""
    file_path = os.path.join(DATA_DIR, "FUNDING_HISTORY.csv")
    
    # Load existing
    existing_df = pd.DataFrame()
    since_ts = None # Default: CCXT default or last 1000
    
    if os.path.exists(file_path):
        try:
            existing_df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            if not existing_df.empty:
                # Get last timestamp in ms
                last_dt = existing_df.index[-1]
                since_ts = int(last_dt.timestamp() * 1000) + 1
        except:
            pass
            
    # If no existing data, maybe fetch more than 1000? 
    # For now, let's just get the last 1000 items (approx 1 year of 8h rates) to avoid rate limits on startup
    # User asked for 'checks timestamp and only downloads missing'.
    
    exchange = ccxt.binance({'options': {'defaultType': 'future'}})
    
    try:
        if since_ts:
            # Incremental fetch
            rates = exchange.fetch_funding_rate_history(symbol, since=since_ts, limit=1000)
        else:
            # First fetch (Last 1000 periods)
            rates = exchange.fetch_funding_rate_history(symbol, limit=1000)
            
        if rates:
            new_data = []
            for r in rates:
                new_data.append({
                    'date': r['datetime'], # CCXT returns ISO string usually or timestamp
                    'fundingRate': r['fundingRate'] * 100 # Percent
                })
            
            fetched_df = pd.DataFrame(new_data)
            fetched_df['date'] = pd.to_datetime(fetched_df['date'], utc=True)
            fetched_df['date'] = fetched_df['date'].dt.tz_localize(None)
            fetched_df.set_index('date', inplace=True)
            
            if not existing_df.empty:
                # Combine
                full_df = pd.concat([existing_df, fetched_df])
                full_df = full_df[~full_df.index.duplicated(keep='last')]
                full_df.sort_index(inplace=True)
            else:
                full_df = fetched_df
                
            full_df.to_csv(file_path)
            return full_df
        else:
            return existing_df
            
    except Exception as e:
        print(f"Error fetching funding history: {e}")
        return existing_df

def load_all_historical_data():
    """Master function to trigger updates and return DataFrames."""
    print("Updating Historical Data...")
    tvl = update_tvl_history()
    stable = update_stablecoin_history()
    funding = update_funding_history()
    return tvl, stable, funding
