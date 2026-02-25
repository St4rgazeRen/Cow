# Cow — 比特幣投資戰情室

> 比特幣多週期量化分析工具，整合技術指標、鏈上數據、期權與波段策略。

**Live App:** https://mfyyo9qf5mymsrouxkfdgj.streamlit.app

---

## 功能總覽

| Tab | 名稱 | 核心功能 |
|-----|------|----------|
| 1 | 🐂 牛市雷達 | AHR999 彩色柱狀圖、三層分析框架（散戶/機構/宏觀）、市場相位判斷、M2/CPI/日圓/量子威脅 |
| 2 | 🌊 波段狙擊 | Antigravity v4 進出場信號（EMA20+SMA200+RSI+MACD+ADX 五合一過濾）、OI 未平倉量、Kelly 倉位計算 |
| 3 | 💰 雙幣理財 | Black-Scholes APY 試算、行權價梯形視覺化、Delta 風險估算、動態無風險利率 |
| 4 | ⏳ 時光機回測 | 自訂區間波段 PnL、雙幣滾倉回測、牛市雷達準確度驗證（命中率/誤報/踏空統計） |
| 5 | 🐻 熊市底部獵人 | 8 大鏈上+技術指標複合評分（0-100 分）、歷史底部驗證圖、評分走勢分析、**四季理論目標價預測** |

---

## 架構

```
app.py              入口點（組合各層，不含業務邏輯）
config.py           集中設定（均線週期、交易成本、倉位風控參數）

collector/
  btc_price_collector.py  本地端 15m K 線收集器（Binance + Kraken 雙源）

db/                 年度分割 SQLite 資料庫（本地收集後 push 至雲端）
  btcusdt_15m_2013.db
  btcusdt_15m_2014.db
  ...
  btcusdt_15m_2026.db

core/
  indicators.py     技術指標 + AHR999 計算（純函數，無 Streamlit 依賴）
  bear_bottom.py    熊市底部 8 大指標評分引擎（向量化，20-50x 效能提升）
  season_forecast.py  四季理論目標價預測引擎（減半週期判斷、歷史倍數遞減模型）

service/
  local_db_reader.py  讀取本地 SQLite（15m 原始 / 重採樣日線）
  market_data.py    BTC / DXY 歷史數據（五層備援：本地DB→Yahoo→Binance→Kraken→CryptoCompare）
  onchain.py        鏈上輔助數據（非同步 httpx 分頁，TVL/穩定幣/資金費率）
  realtime.py       即時報價（SSL 繞過 + 指數退避重試）
  macro_data.py     宏觀數據（FRED M2/CPI、Yahoo 日圓、量子威脅靜態評估）
  mock.py           資金費率 / TVL / 恐慌貪婪代理指標（API 失敗降級）

strategy/
  swing.py          Antigravity v4 波段策略引擎（向量化回測，含手續費/滑點）
  dual_invest.py    雙幣期權策略引擎（Black-Scholes，動態無風險利率）
  notifier.py       LINE Bot 主動推播通知

handler/
  layout.py         頁面設置、側欄參數
  tab_bull_radar.py Tab 1：牛市雷達（Session State 圖表快取）
  tab_swing.py      Tab 2：波段狙擊（三行子圖：K線+RSI+MACD）
  tab_dual_invest.py Tab 3：雙幣理財（行權價梯形視覺化）
  tab_backtest.py   Tab 4：時光機回測（PnL / 雙幣滾倉 / 牛市準確度）
  tab_bear_bottom.py Tab 5：熊市底部獵人（Gauge + 8 指標卡片 + 歷史驗證 + 四季預測）

tests/
  test_bear_bottom.py   熊市底部評分單元測試（8 案例）
  test_dual_invest.py   雙幣期權 APY 單元測試（18 案例）
  test_market_data.py   市場數據抓取測試

.env.example        環境變數模板（API Key 設定）
.github/workflows/
  keepalive.yml     自動 Ping，防止 Streamlit 休眠
```

---

## 核心指標說明

### Tab 1：牛市雷達 — 三層分析框架

| 層次 | 指標 | 說明 |
|------|------|------|
| **Level 1 散戶視角** | 趨勢結構 | SMA50 vs SMA200 黃金/死亡交叉 + 年線斜率 |
| | 道氏理論 | 20日高點 vs 前20日高點（HH/LH 判斷） |
| | 情緒指數 | Alternative.me Fear & Greed，或 RSI/動能代理 |
| **Level 2 機構視角** | AHR999 | (Price/SMA200)×(Price/指數增長估值)，< 0.45 = 歷史抄底 |
| | MVRV Z-Score | (Price - SMA200) / 200日標準差，< 0 = 低估 |
| | BTC 生態 TVL | DeFiLlama 鏈上鎖倉量，資金流入/流出趨勢 |
| | 現貨 ETF 流量 | 24h 機構資金動向（代理估算） |
| | 資金費率 | 幣安永續合約資金費率，> 0.03% = 多頭過熱 |
| **Level 3 宏觀視角** | BTC vs DXY 相關性 | 90日滾動相關係數，< -0.5 = 正常負相關 |
| | 全球穩定幣市值 | 流動性代理，> $100B = 流動性充沛 |
| | 美國 M2 | FRED WM2NS 週頻，流動性環境評估 |
| | 日圓匯率 | USD/JPY，套息交易風險指標 |
| | 美國 CPI YoY | FRED CPIAUCSL，通膨壓力評估 |
| | 量子威脅等級 | secp256k1 破解可行性評估（當前: 極低） |

---

### Tab 2：波段狙擊 — Antigravity v4

**進場條件（五合一過濾，全部滿足才進場）：**

| 條件 | 指標 | 標準 | 意義 |
|------|------|------|------|
| 趨勢過濾 | SMA 200 | Price > SMA200 | 年線多頭，大趨勢向上 |
| 動能確認 | RSI 14 | RSI > 50 | 短期動能偏多 |
| 進場甜蜜點 | EMA 20 距離 | 0% ≤ 乖離率 ≤ 1.5% | 回踩均線，非追高 |
| MACD 確認 | MACD vs Signal | MACD > Signal 線 | 多頭動能交叉確認 |
| 趨勢強度 | ADX | ADX > 20 | 市場有趨勢，非盤整 |

**出場條件：** Price < EMA20（跌破短期趨勢線）

**風控：** Kelly 倉位（風控 1-5%），止損 EMA20 - 2×ATR

---

### Tab 5：熊市底部獵人 — 8 大指標評分

| 指標 | 滿分 | 底部閾值 | 說明 |
|------|------|---------|------|
| AHR999 | 20 | < 0.45 | 囤幣指數歷史抄底區 |
| MVRV Z-Score | 18 | < 0 | 市場價值 vs 已實現價值 |
| Pi Cycle Gap | 15 | < -5% | SMA111 vs 2×SMA350 |
| 200週均線比值 | 15 | < 1.0x | 跌破200週均 = 歷史絕對底部 |
| Puell Multiple | 12 | < 0.5 | 礦工收入 vs 年均（投降信號） |
| 月線 RSI | 10 | < 30 | 月線嚴重超賣 |
| 冪律支撐倍數 | 5 | < 2x | Giovanni Santostasi 冪律模型 |
| Mayer Multiple | 5 | < 0.8x | Price vs 2年均線 |

**評分解讀：** 75+ = 歷史極值底部（All-In信號） | 60-75 = 積極積累 | 45-60 = 謹慎試探 | 25-45 = 觀望

---

### Tab 5：四季理論目標價預測

基於比特幣減半週期（約4年）劃分四季，整合歷史漲跌倍數遞減規律與冪律模型，預測未來12個月目標價。

**四季定義（以最近一次減半日起算）：**

| 季節 | 週期月份 | 市場狀態 | 預測方向 | 操作建議 |
|------|---------|---------|---------|---------|
| 🌱 春 | 月 0–11 | 減半後復甦，多頭啟動 | 牛市最高價 ↑ | 分批建倉，佈局主流幣 |
| ☀️ 夏 | 月 12–23 | 牛市加速，FOMO蔓延 | 牛市最高價 ↑ | 持有並設移動止盈 |
| 🍂 秋 | 月 24–35 | 泡沫破裂，空頭確立 | 熊市最低價 ↓ | 逐步減倉，轉向穩定 |
| ❄️ 冬 | 月 36–47 | 熊市底部，恐慌拋售 | 熊市最低價 ↓ | 定期定額囤幣 |

**歷史減半週期統計：**

| 週期 | 減半日 | 減半時價格 | 牛市 ATH | ATH 倍數 | 熊市最低點 | ATH 跌幅 |
|------|-------|-----------|---------|---------|---------|---------|
| 第1次 | 2012-11-28 | $12 | $1,163 | 94.2x | $152 | -87% |
| 第2次 | 2016-07-09 | $650 | $19,891 | 30.6x | $3,122 | -84% |
| 第3次 | 2020-05-11 | $8,571 | $68,789 | 8.0x | $15,476 | -78% |
| 第4次 | 2024-04-19 | — | — | ~3-5x（預測） | — | — |

**預測算法：**
- **牛市目標** = 減半時價格 × 歷史中位數倍數（每週期遞減 ÷3.5）
- **熊市目標** = 前一牛市 ATH × 歷史底部跌幅中位數（約 22.5%）
- **信心區間** = 25th～75th 百分位數（對數空間計算）
- **預計達標時間** = 歷史中位數天數（ATH: ~549天，底部: ~925天）

**UI 組成（Section F）：**
- F1 — 季節狀態橫幅 + 週期進度時間軸
- F2 — 保守 / 中位數 / 樂觀三欄目標價卡片 + 信心分數進度條
- F3 — 過去2年 + 未來12個月預測走勢圖（對數坐標，含冪律走廊，Session State 快取）
- F4 — 歷史週期比較表 + 牛市倍數遞減瀑布圖
- F5 — 四季操作策略四欄卡片（當前季節高亮）

---

## 數據來源

| 類別 | 來源 | 說明 |
|------|------|------|
| BTC 15m K 線 | **本地 SQLite DB** (0th) | 由 collector 預先收集並 push 至 repo，Streamlit 直接讀取 |
| BTC 歷史 OHLCV | Yahoo Finance → Binance → Kraken → **CryptoCompare** | 四層備援（無本地 DB 時啟用），覆蓋 2015 年起完整歷史 |
| 即時價格 | Binance WebSocket | 含資金費率、OI 未平倉量 |
| 鏈上 TVL | DeFiLlama API | Bitcoin DeFi 生態鎖倉量 |
| 穩定幣市值 | DeFiLlama API | 全球穩定幣流通量 |
| 恐懼貪婪指數 | Alternative.me | 市場情緒代理 |
| M2 / CPI / 日圓 | FRED 公開 CSV API | 宏觀流動性指標 |
| DeFi 無風險利率 | DeFiLlama (Aave V3 USDT) | 雙幣策略動態折現 |

---

## 本地執行

```bash
pip install -r requirements.txt
# 設定 API Key（可選，不設定仍可運作）
cp .env.example .env
# 填入 BINANCE_API_KEY, LINE_CHANNEL_ACCESS_TOKEN 等
streamlit run app.py
```

---

## 歷史數據收集器

Streamlit Cloud 因 IP 封鎖、速率限制等原因有時無法取得完整歷史數據。
**解法：在本地端一次性收集，commit push 到 GitHub，雲端直接讀取 repo 內的 SQLite 檔案。**

### 收集 BTC/USDT 15m K 線

```bash
# 首次執行：從 2013 年起全量下載（Kraken 2013-2017 + Binance 2017-今）
python collector/btc_price_collector.py --push

# 日常增量更新（只抓最新數據）
python collector/btc_price_collector.py --push

# 只更新特定年份
python collector/btc_price_collector.py --year 2021 --push

# 從指定年份開始（例如只補 Binance 上線後的數據）
python collector/btc_price_collector.py --from-year 2017 --push
```

### 數據源分工

| 時期 | 來源 | 說明 |
|------|------|------|
| 2013 – 2017-08-16 | Kraken（XBTUSD 15m） | 無地理封鎖，有 2013 年起完整歷史 |
| 2017-08-17 – 今 | Binance（BTCUSDT 15m） | 流動性最高，最可靠的 15m 數據 |

### 儲存結構

```
db/
  btcusdt_15m_2013.db   ← 每年約 1.5–3 MB
  btcusdt_15m_2014.db
  ...
  btcusdt_15m_2026.db   ← 當年持續更新
```

每次執行後 `--push` 自動 commit 並推送，Streamlit Cloud 在下次重啟時讀取最新數據。

### 五層備援優先序

```
0th  本地 SQLite DB   ← 有 db/*.db 時直接讀，毫秒級，不呼叫任何 API
1st  Yahoo Finance    ← 一般日線來源
2nd  Binance REST     ← 部分 Cloud IP 受 451 封鎖
3rd  Kraken           ← 無地理封鎖
4th  CryptoCompare    ← 覆蓋 2010 年起完整歷史
```

---

## Streamlit 防休眠設定

Streamlit Community Cloud 在 **7 天無流量**後自動休眠。本專案使用 GitHub Actions 每日兩次自動 Ping 保持喚醒。

**設定步驟：**

1. GitHub Repo → **Settings → Secrets and variables → Actions**
2. 新增 Secret：
   - Name: `STREAMLIT_APP_URL`
   - Value: `https://mfyyo9qf5mymsrouxkfdgj.streamlit.app`
3. Workflow 已設定每日 UTC 00:00 / 12:00（台灣 08:00 / 20:00）自動執行

---

## 版本紀錄

### v1.8 (2026-02-25)

- **feat(core): `core/season_forecast.py` — 四季理論目標價預測引擎**
  - `get_current_season()`: 依比特幣減半週期自動判斷當前季節（春/夏/秋/冬）
  - `forecast_price()`: 牛季預測未來12個月最高價，熊季預測最低價；信心區間採對數空間 25th～75th 百分位
  - `_apply_diminishing_returns()`: 每週期牛市漲幅遞減模型（÷3.5/週期），修正過度樂觀偏誤
  - `get_cycle_comparison_table()`: 歷史三次減半週期完整比較表（ATH 倍數、底部跌幅、達標天數）
  - `get_power_law_forecast()`: 冪律模型未來12個月價格走廊（中線 ± 1σ 對數通道）

- **feat(handler): Tab 5 新增 Section F — 四季理論目標價預測**
  - F1 季節狀態橫幅 + Plotly 週期進度時間軸（四季色塊 + 當前位置指針）
  - F2 三欄目標價卡片（保守/中位數/樂觀）+ 信心分數進度條
  - F3 目標價走勢圖（過去2年歷史 + 未來12個月預測區間 + 冪律走廊，對數坐標，Session State 快取）
  - F4 歷史週期比較表 + 牛市倍數遞減瀑布圖
  - F5 四季操作策略四欄卡片（當前季節高亮標示）

### v1.7 (2026-02-24)

- **feat(collector): 本地端 BTC/USDT 15m K 線收集器** — `collector/btc_price_collector.py`，Binance（2017+）+ Kraken（2013–2017）雙源，年度分割 SQLite，增量更新，`--push` 自動 git commit & push
- **feat(db): 多年度 SQLite 年度分割架構** — `db/btcusdt_15m_{year}.db`，WAL 模式，open_time 主鍵去重，repo 直接託管（每年約 1.5–3 MB）
- **feat(service): local_db_reader.py** — `read_btc_15m()` / `read_btc_daily()` / `get_coverage_info()`，供 Streamlit 直接讀取本地 DB
- **feat(market_data): 第零層備援（本地 DB）** — `fetch_market_data()` 優先讀取 `db/*.db`，無本地 DB 時才呼叫外部 API，徹底解決 Streamlit Cloud 抓不到 2015 年起完整歷史的問題

### v1.6 (2026-02-24)

#### 六大問題修復

1. **fix(tab1): N/A 顯示優化** — 所有數據失敗格改為 `—` 並附說明文字；DXY 相關性加入 NaN 守衛；量子威脅等級移至獨立雙欄版面，避免文字截斷

2. **feat(market_data): 第四備援 CryptoCompare** — 新增 `fetch_cryptocompare_daily()`，支援 2010 年起完整 BTC 日線歷史，分頁最多 20 頁 × 2000 筆 = 40,000 天覆蓋；將初始抓取起點設為 2015-01-01

3. **docs(README): 全面重寫** — 新增三層分析框架說明表、Antigravity v4 五合一過濾條件表、8 大底部指標評分表、四層數據備援架構說明

4. **feat(swing): Antigravity v4 升級至五合一策略** — 進場新增 MACD 多頭確認（MACD > Signal）與 ADX 趨勢強度過濾（ADX > 20），消除盤整假信號；UI 顯示區同步更新五條件狀態

5. **fix(backtest): 牛市雷達捕捉率** — 擴充牛市驗證區間至 2023-2024 + 2024-2025；加入 `fillna(False)` NaN 守衛避免 SMA 不足期間全部判定為非牛市

6. **fix(bear_bottom): Tab5 八大指標恆顯示** — `calculate_bear_bottom_score()` 改為無論值是否 NaN 都寫入 signals 字典（NaN 顯示為 `—`），確保 UI 卡片永遠顯示全部 8 個指標格

### v1.5 (2026-02-23)

#### Bug Fix
- **fix(market_data):** yfinance SSL 驗證失敗導致 BTC 歷史數據無法載入

#### 10 項核心優化
- **#1 SSL 繞過:** 全面加入 `urllib3.disable_warnings()` + `verify=False`
- **#2 非同步請求:** `service/onchain.py` 改用 `httpx.AsyncClient` 並行抓取 20 頁資金費率
- **#3 API 重試:** `data_manager.py` 加入指數退備重試（最多 3 次，1s/2s/4s）
- **#4 SQLite:** WAL 模式 + `_db_lock` 解決多執行緒寫入衝突
- **#5 回測向量化:** `strategy/swing.py` NumPy array 存取，避免 Pandas iloc overhead
- **#6 動態無風險利率:** Aave V3 USDT → MakerDAO DSR → 4% fallback，1 小時 TTL 快取
- **#7 Session State:** 全 Tab MD5 hash 快取鍵，側邊欄互動不觸發圖表重建
- **#8 環境變數:** `python-dotenv`，API Key 從 `.env` 讀取
- **#9 LINE Bot:** `strategy/notifier.py` 四種推播函式
- **#10 單元測試:** `tests/` 26 個測試案例

### v1.4 (2026-02-23)
- **fix:** keepalive workflow 改用不追蹤重定向策略

### v1.2 (2026-02-23)
- **feat:** GitHub Actions keepalive.yml 防休眠 workflow
- **feat:** Tab 4 波段回測加入進階統計（勝率、夏普比率、最大回撤）

### v1.1 (2026-02-22)
- **perf:** AHR999 計算向量化，移除 `apply()` 逐行迴圈
- **perf:** 熊市底部評分引擎向量化，解決 N+1 卡頓

### v1.0 (2026-02-22)
- **refactor:** 模組化分層架構重構（core / service / strategy / handler）
- **feat:** 新增熊市底部獵人模組（Tab 5）
