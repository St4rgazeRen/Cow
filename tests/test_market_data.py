"""
tests/test_market_data.py
BTC 市場數據診斷測試

執行方式:
  pytest tests/test_market_data.py -v -s

功能:
  - 確認 yfinance 版本與下載行為
  - 確認 MultiIndex 欄位標準化
  - 確認 SQLite 讀寫往返（含大小寫 index 欄位問題）
  - 確認 data_manager._df_from_sqlite / _df_to_sqlite 正常工作
  - 確認完整 fetch_market_data() 流程（需網路）
"""
import sys
import os
import tempfile
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 確保可以 import 專案模組
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────
# Section 1: yfinance 診斷
# ─────────────────────────────────────────────

def test_yfinance_version():
    """印出 yfinance 版本，確認已安裝。"""
    import yfinance as yf
    version = getattr(yf, '__version__', 'unknown')
    print(f"\n[yfinance] version = {version}")
    assert yf is not None, "yfinance 未安裝"


def test_yfinance_download_short_range():
    """
    下載近 30 天 BTC 數據，驗證:
    - 回傳非空 DataFrame
    - 包含 close / open / high / low / volume 欄位（或 MultiIndex 形式）
    - index 為 DatetimeIndex
    """
    import yfinance as yf
    start = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    print(f"\n[test] yf.download('BTC-USD', start={start})")

    df = yf.download("BTC-USD", start=start, interval="1d",
                     progress=False, auto_adjust=True)

    print(f"  shape       = {df.shape}")
    print(f"  columns     = {list(df.columns)}")
    print(f"  index dtype = {df.index.dtype}")
    print(f"  index name  = {df.index.name}")
    print(f"  tz-aware    = {df.index.tz is not None}")
    print(f"  empty       = {df.empty}")
    if not df.empty:
        print(f"  head:\n{df.head(2)}")

    assert not df.empty, (
        "yf.download() 回傳空 DataFrame！\n"
        "可能原因: 網路問題 / Yahoo Finance 封鎖此 IP / yfinance API 變更"
    )


def test_yfinance_ticker_history():
    """
    使用 Ticker().history() 備援下載，驗證欄位格式。
    """
    import yfinance as yf
    start = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
    print(f"\n[test] yf.Ticker('BTC-USD').history(start={start})")

    ticker_obj = yf.Ticker("BTC-USD")
    df = ticker_obj.history(start=start, interval="1d", auto_adjust=True)

    print(f"  shape       = {df.shape}")
    print(f"  columns     = {list(df.columns)}")
    print(f"  index name  = {df.index.name}")
    print(f"  tz-aware    = {df.index.tz is not None}")
    print(f"  empty       = {df.empty}")

    assert not df.empty, (
        "yf.Ticker.history() 也回傳空 DataFrame！\n"
        "yfinance 在此環境可能無法連線 Yahoo Finance。"
    )


# ─────────────────────────────────────────────
# Section 2: MultiIndex 欄位正規化
# ─────────────────────────────────────────────

def test_normalize_multiindex_columns():
    """模擬 yfinance 0.2.x MultiIndex 欄位，驗證 _normalize_yf_columns() 正確展平。"""
    from service.market_data import _normalize_yf_columns

    # 模擬 MultiIndex [('Close','BTC-USD'), ('Open','BTC-USD'), ...]
    idx = pd.MultiIndex.from_tuples(
        [('Close', 'BTC-USD'), ('High', 'BTC-USD'),
         ('Low', 'BTC-USD'), ('Open', 'BTC-USD'), ('Volume', 'BTC-USD')],
        names=['Price', 'Ticker']
    )
    df = pd.DataFrame(
        np.ones((3, 5)),
        columns=idx,
        index=pd.date_range('2025-01-01', periods=3),
    )
    result = _normalize_yf_columns(df.copy())
    print(f"\n[test] MultiIndex normalized → {list(result.columns)}")
    assert list(result.columns) == ['close', 'high', 'low', 'open', 'volume'], \
        f"欄位標準化失敗: {list(result.columns)}"


def test_normalize_flat_columns():
    """模擬 yfinance 舊版平坦欄位，驗證轉小寫正確。"""
    from service.market_data import _normalize_yf_columns

    df = pd.DataFrame(
        np.ones((3, 5)),
        columns=['Open', 'High', 'Low', 'Close', 'Volume'],
        index=pd.date_range('2025-01-01', periods=3),
    )
    result = _normalize_yf_columns(df.copy())
    print(f"\n[test] Flat columns normalized → {list(result.columns)}")
    assert list(result.columns) == ['open', 'high', 'low', 'close', 'volume'], \
        f"欄位標準化失敗: {list(result.columns)}"


# ─────────────────────────────────────────────
# Section 3: SQLite 讀寫往返
# ─────────────────────────────────────────────

def _patch_db_path(tmp_dir: str):
    """
    將 data_manager 的 DB_PATH 改指向暫存目錄，
    避免污染正式數據庫。
    """
    import data_manager
    orig_path = data_manager.DB_PATH
    data_manager.DB_PATH = os.path.join(tmp_dir, "test_cow.db")
    return orig_path


def _restore_db_path(orig_path: str):
    import data_manager
    data_manager.DB_PATH = orig_path


def test_sqlite_write_read_roundtrip():
    """
    驗證 _df_to_sqlite → _df_from_sqlite 往返一致，
    特別測試 yfinance 常見的 'Date'（大寫）index 名稱。
    """
    import data_manager

    with tempfile.TemporaryDirectory() as tmp:
        orig = _patch_db_path(tmp)
        try:
            # 建立模擬 BTC DataFrame，index 名稱為 'Date'（yfinance 實際返回值）
            idx = pd.date_range('2025-01-01', periods=5, name='Date')
            df_write = pd.DataFrame({
                'open':   [10.0, 11.0, 12.0, 13.0, 14.0],
                'close':  [10.5, 11.5, 12.5, 13.5, 14.5],
                'high':   [11.0, 12.0, 13.0, 14.0, 15.0],
                'low':    [ 9.5, 10.5, 11.5, 12.5, 13.5],
                'volume': [100.0, 200.0, 300.0, 400.0, 500.0],
            }, index=idx)

            print(f"\n[test] 寫入 DataFrame, index.name='{df_write.index.name}', shape={df_write.shape}")
            data_manager._df_to_sqlite(df_write, 'btc_history')

            df_read = data_manager._df_from_sqlite('btc_history')
            print(f"[test] 讀回 DataFrame, shape={df_read.shape}, index.name='{df_read.index.name}'")
            print(f"[test] 讀回欄位: {list(df_read.columns)}")

            assert not df_read.empty, (
                "_df_from_sqlite 回傳空 DataFrame！\n"
                "很可能是 SQLite 欄位大小寫問題（'Date' vs 'date'）。"
            )
            assert len(df_read) == len(df_write), \
                f"資料列數不符: 寫入 {len(df_write)}, 讀回 {len(df_read)}"
            assert 'close' in df_read.columns, \
                f"讀回 DataFrame 缺少 'close' 欄位，欄位列表: {list(df_read.columns)}"
            pd.testing.assert_index_equal(
                df_read.index.normalize(),
                df_write.index.normalize(),
                check_names=False,
            )
            print("[test] SQLite 讀寫往返 ✅ 通過")
        finally:
            _restore_db_path(orig)


def test_sqlite_empty_on_missing_table():
    """確認表格不存在時 _df_from_sqlite 回傳空 DataFrame 而非拋出例外。"""
    import data_manager

    with tempfile.TemporaryDirectory() as tmp:
        orig = _patch_db_path(tmp)
        try:
            result = data_manager._df_from_sqlite('nonexistent_table')
            print(f"\n[test] 不存在的表格 → empty={result.empty}")
            assert result.empty, "不存在的表格應回傳空 DataFrame"
            print("[test] 缺失表格行為 ✅ 正確")
        finally:
            _restore_db_path(orig)


# ─────────────────────────────────────────────
# Section 4: 完整 _download_yf 流程
# ─────────────────────────────────────────────

def test_download_yf_btc_recent():
    """
    完整測試 _download_yf()（需網路連線）。
    驗證回傳 DataFrame 含有必要欄位且 index 無時區。
    """
    from service.market_data import _download_yf

    start = (datetime.now() - timedelta(days=14)).strftime('%Y-%m-%d')
    print(f"\n[test] _download_yf('BTC-USD', start={start})")
    df = _download_yf("BTC-USD", start=start)

    print(f"  shape   = {df.shape}")
    print(f"  columns = {list(df.columns)}")
    print(f"  tz-aware = {df.index.tz is not None if not df.empty else 'N/A'}")
    if not df.empty:
        print(f"  head:\n{df.head(2)}")

    assert not df.empty, (
        "_download_yf('BTC-USD') 回傳空 DataFrame！\n"
        "請檢查 Streamlit Cloud 日誌中 [yfinance] 開頭的訊息，確認是哪個方法失敗。"
    )
    required = {'close', 'open', 'high', 'low', 'volume'}
    missing = required - set(df.columns)
    assert not missing, f"缺少必要欄位: {missing}，實際欄位: {list(df.columns)}"
    assert df.index.tz is None, f"index 帶有時區 {df.index.tz}，應為 tz-naive"
    print("[test] _download_yf ✅ 通過")


# ─────────────────────────────────────────────
# Section 5: 端對端 fetch_market_data（標記網路依賴）
# ─────────────────────────────────────────────

@pytest.mark.network
def test_fetch_market_data_returns_nonempty():
    """
    完整 fetch_market_data() 端對端測試（需網路 + 無 Streamlit 環境）。
    由於使用 @st.cache_data，此測試直接呼叫底層邏輯。
    """
    from service.market_data import _download_yf
    import data_manager

    with tempfile.TemporaryDirectory() as tmp:
        orig = _patch_db_path(tmp)
        try:
            # 模擬 fetch_market_data 核心邏輯（繞過 @st.cache_data）
            local_df = data_manager._df_from_sqlite('btc_history')
            print(f"\n[test] 初始 SQLite 讀取: empty={local_df.empty}")

            start = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
            btc_new = _download_yf("BTC-USD", start=start)
            print(f"[test] 下載結果: shape={btc_new.shape}, empty={btc_new.empty}")

            assert not btc_new.empty, "下載失敗，回傳空 DataFrame"

            # 寫入 SQLite
            data_manager._df_to_sqlite(btc_new, 'btc_history')
            # 重新讀取
            df_cached = data_manager._df_from_sqlite('btc_history')
            print(f"[test] 快取讀回: shape={df_cached.shape}, empty={df_cached.empty}")
            assert not df_cached.empty, "SQLite 快取讀回失敗"
            print("[test] 端對端流程 ✅ 通過")
        finally:
            _restore_db_path(orig)
