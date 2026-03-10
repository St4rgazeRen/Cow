# CLAUDE.md — Cow（BTC 投資戰情室）

**路徑：** `D:\Users\63191\Documents\GitHub\Cow`
**Live App：** https://mfyyo9qf5mymsrouxkfdgj.streamlit.app
**Streamlit 版本：** 1.37.1

---

## 執行指令

```bash
# 本地開發（必須用 Anaconda Python）
D:\Users\63191\AppData\Local\anaconda3\python.exe -m streamlit run app.py

# 增量更新 BTC K 線並推送 GitHub
D:\Users\63191\AppData\Local\anaconda3\python.exe collector/btc_price_collector.py --push
```

---

## 架構分層

```
app.py          入口點（不含業務邏輯）
config.py       集中設定（均線週期、交易成本、倉位風控、SSL_VERIFY）
core/           純函數層（技術指標、熊市底部評分、四季目標價預測）
service/        資料取得層（歷史：本地DB→Yahoo→Binance→Kraken→CryptoCompare
                           即時：Binance→Kraken→本地DB）
strategy/       策略引擎（波段 Antigravity v4.1、雙幣期權 Black-Scholes、LINE 推播）
handler/        Streamlit UI 各 Tab 實作
collector/      BTC 15m K 線收集器（年度分割 SQLite）
scripts/        GitHub Actions 推播腳本（09:23 / 15:39 台灣時間）
db/             btcusdt_15m_YYYY.db（年度分割，雲端直接讀 repo 內 db）
```

---

## 已知陷阱

### 1. `@st.fragment` 靜默失效（現價停止自動更新）

根因：`@st.fragment(run_every=60)` 傳入 DataFrame/Series 時序列化失敗，fragment 停止重跑但不報錯。

```python
# ❌ 傳 DataFrame/Series 會靜默失效
@st.fragment(run_every=60)
def render(btc, curr): ...

# ✅ 只傳 float scalar
@st.fragment(run_every=60)
def render(prev_close: float, rsi14: float, ...): ...
render(
    prev_close=float(btc['close'].iloc[-2]),
    rsi14=float(curr['RSI_14']) if 'RSI_14' in curr.index else 50.0,
)
```

### 2. `@st.cache_data(ttl=60)` + `run_every=60` 衝突

根因：fragment 60 秒重跑，TTL 也 60 秒 → 永遠命中快取 → 數據不刷新。
修法：`fetch_realtime_data()` 不掛 `@st.cache_data`。

### 3. pandas Series `.get()` 不可靠

`curr.get('RSI_14', 50)` 在 Series 上有時不回傳預設值。
修法：`float(curr['RSI_14']) if 'RSI_14' in curr.index else 50.0`

### 4. NaN 判斷

避免 `val == val`。改用 `import math; not math.isnan(val)`。

### 5. 企業防火牆封鎖 Binance

確認方式：看 fragment 內「數據更新時間」是否每分鐘更新。
- 有更新 = fragment 正常，是 API 連線問題
- 沒更新 = fragment 本身沒跑

即時價格備援鏈（已實作）：Binance 現貨 → Kraken Ticker → 本地 15m DB 最新一筆

```
Kraken：GET https://api.kraken.com/0/public/Ticker?pair=XBTUSD
取 result['XXBTZUSD']['c'][0]
```

### 6. service 層來源追蹤慣例

`fetch_realtime_data()` 回傳 dict 含 `price_source`、`funding_rate_source`、`tvl_source`。
- UI 層（app.py）直接讀 `rt.get('price_source', '歷史收盤')`
- **不在 UI 層做 `rt['field'] is not None` 判斷**（leaky abstraction）
- `get_latest_local_price()`：不帶 `@st.cache_data`，供即時備援
- `read_btc_15m()`：有 `ttl=86400` 快取，**不可**用於即時價格

### 7. `dict.get(key, default)` 對 `None` 值不觸發預設

`data = {'source': None}`；`data.get('source', '模擬值')` → 回傳 `None`。
修法：`data.get('source') or '模擬值'`

### 8. `reindex(method='nearest')` 早於資料起點填充定值

```python
# fund_hist 從 2021 年起，chart_df 從 2015 年起
fund_sub = fund_hist.reindex(chart_df.index, method='nearest')
# 2021 年前會填成第一筆值（常數線）→ 手動清除
fund_sub.loc[fund_sub.index < fund_hist.index[0]] = np.nan
```

### 9. 資金費率即時備援鏈

| 來源 | URL | 欄位 |
|------|-----|------|
| Binance fapi | `fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT` | `lastFundingRate` × 100 |
| Bybit | `api.bybit.com/v5/market/tickers?category=linear&symbol=BTCUSDT` | `result.list[0].fundingRate` × 100 |
| OKX | `www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP` | `data[0].fundingRate` × 100 |

### 10. 圖表欄位名稱與顯示標籤混淆

欄位名 `EMA_20`（含底線）直接用在圖例易被誤讀為 `SMA 20`。
修法：`_ma_label(col)` helper → `col.replace("_", " ")` → `EMA 20` / `SMA 50`。
當 `exit_ma_key == 'EMA_20'` 時，進場線與防守線同一條，合併標籤：`"EMA 20 (進場 ＆ 防守線)"`。
