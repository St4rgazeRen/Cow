# Cow — 比特幣投資戰情室

> 比特幣多週期量化分析工具，整合技術指標、鏈上數據、期權與波段策略。

**Live App:** https://mfyyo9qf5mymsrouxkfdgj.streamlit.app

---

## 功能總覽

| Tab | 名稱 | 核心功能 |
|-----|------|----------|
| 1 | 🧭 長週期羅盤 | -100~+100 牛熊複合評分 + 油表 Gauge、AHR999/MVRV/Pi Cycle 等 8 大指標底部探測（含**指標明細分解 expander**）、三層分析框架（散戶/機構/宏觀）、市場相位判斷、M2/CPI/日圓/量子威脅、**四季理論目標價預測** |
| 2 | 🌊 波段狙擊 | Antigravity v4.1 進出場信號（EMA20+SMA200+RSI+MACD+ADX 五合一過濾）、**2x3 條件監控儀表板**、動態策略建議、自訂防守線（SMA50/EMA20/SMA200）、OI 未平倉量、Kelly 倉位計算機 |
| 3 | 💰 雙幣理財 | Black-Scholes APY 試算、行權價梯形視覺化、Delta 風險估算、動態無風險利率 |
| 4 | ⏳ 時光機回測 | 自訂區間波段 PnL（可調參數滑桿 + 🔬 最佳參數搜尋，並行加速）、雙幣滾倉回測、牛市雷達準確度驗證（含 MA50 視覺化）、**📈 多週期回測（日線宏觀過濾 + 15m 精確進場，防先視偏誤）** |
| 🤖 | 決策速報推播 | 透過 GitHub Actions 每日雙時段 (09:23, 15:39) 自動抓取大盤與指標數據，並發送高質感 Flex Message 視覺化決策面板至 LINE |

---

## 架構

```text
app.py              入口點（組合各層，不含業務邏輯；今日大盤速覽 6 大 Metric 以 @st.fragment(run_every=60) 每 60 秒自動更新）
config.py           集中設定（均線週期、交易成本、倉位風控參數）

collector/
  btc_price_collector.py  本地端 15m K 線收集器（Binance + Kraken 雙源）

db/                 年度分割 SQLite 資料庫（本地收集後 push 至雲端）
  btcusdt_15m_2013.db
  ...
  btcusdt_15m_2026.db

core/
  indicators.py       技術指標 + AHR999 計算（純函數，無 Streamlit 依賴）
  bear_bottom.py      熊市底部 8 大指標評分引擎 + -100~+100 牛熊複合評分
  season_forecast.py  四季理論目標價預測引擎（減半週期判斷、歷史倍數遞減模型）

service/
  local_db_reader.py  讀取本地 SQLite（15m 原始 / 重採樣日線），TTL 快取，全面 UTC 時區
  market_data.py      BTC / DXY 歷史數據（五層備援：本地DB→Yahoo→Binance→Kraken→CryptoCompare）+ T 日數據縫合，全面 UTC 時區（修正 UTC+8 偏移 8 小時 bug）
  onchain.py          鏈上輔助數據（非同步 httpx 分頁，TVL/穩定幣/資金費率）
  realtime.py         即時報價（棄用 ccxt，直接呼叫 Binance API 取得資金費率/OI，並加入 Header 偽裝與 SSL 繞過，TTL=60s）
  macro_data.py       宏觀數據（FRED M2/CPI、Yahoo 日圓、量子威脅評估）
  mock.py             代理指標與模擬數據（API 失敗降級備援）

strategy/
  swing.py          Antigravity v4.1 波段策略引擎（防先視偏誤、日頻 Sharpe、多週期回測引擎）
  dual_invest.py    雙幣期權策略引擎（Black-Scholes，動態無風險利率）
  notifier.py       LINE Bot 主動推播通知模組

scripts/
  daily_line_notify.py   GitHub Actions 雲端自動推播腳本（內建 Kraken 備援）
  test_flex_message.py   本地端測試 LINE Flex Message 排版的除錯腳本

handler/
  layout.py          頁面設置、側欄（精簡化：只保留日期區間，策略參數移至各 Tab）
  tab_macro_compass.py Tab 1：長週期羅盤（雙 Gauge + 評分公式 expander + 三層框架 + 底部 8 指標 + 四季預測）
  tab_swing.py       Tab 2：波段狙擊（3 行式 K 線子圖、2x3 條件儀表板、動態建議、倉位計算）
  tab_dual_invest.py Tab 3：雙幣理財（行權價梯形視覺化）
  tab_backtest.py    Tab 4：時光機回測（參數滑桿 + Grid Search 並行搜尋 + 多週期回測）
```

---

## 核心指標說明

### Tab 1：🧭 長週期羅盤

將總體經濟、鏈上數據與技術分析融合，提供由宏觀到微觀的完整市場週期定位。

#### 1. 綜合牛熊狀態 (Market Cycle Score)
由 8 組對稱指標組成，計算出 **-100 ~ +100 的牛熊複合評分**（`bull_total - bear_total`）。
* **-100** = 極度深熊（All-In 信號）
* **0** = 中性區間
* **+100** = 狂熱牛頂（逃頂信號）

搭配 Plotly `go.Indicator` 油表雙量程顯示，並輔以 0-5 級的「市場相位量表」。

油錶圖下方新增 **📐 多空評分計算公式** 展開面板，可即時查看 8 大指標各自的當前值、熊底貢獻分數、牛頂貢獻分數與淨貢獻（牛-熊），方便驗證分數合理性。分數若長時間維持穩定屬正常現象，代表鏈上週期確實處於同一區間。

#### 2. 三層分析框架 (Micro to Macro)
| 層次 | 指標 | 說明 |
|------|------|------|
| **散戶視角 (Level 1)** | 趨勢結構 | SMA50 vs SMA200 黃金/死亡交叉 + 年線斜率 |
| | 道氏理論 | 20日高點 vs 前20日高點（HH/LH 判斷） |
| | 情緒指數 | Alternative.me Fear & Greed，或 RSI/動能代理 |
| **機構視角 (Level 2)** | AHR999 | (Price/SMA200)×(Price/指數增長估值)，< 0.45 = 歷史抄底 |
| | MVRV Z-Score | (Price - SMA200) / 200日標準差，< 0 = 低估 |
| | BTC 生態 TVL | DeFiLlama 鏈上鎖倉量，判斷資金流入/流出趨勢 |
| | 資金費率 | 幣安永續合約當期費率，> 0.03% = 多頭過熱 |
| **宏觀視角 (Level 3)** | BTC vs DXY | 90日滾動相關係數，< -0.5 = 正常負相關 |
| | 全球穩定幣市值 | 流動性代理，> $100B = 流動性充沛 |
| | 美國 M2 | FRED WM2NS 週頻，流動性環境評估 |
| | 日圓匯率 | USD/JPY，套息交易 (Carry Trade) 風險指標 |

#### 3. 熊市底部探測 (8 大指標)
專門用於尋找歷史級別的長期買點，總分 100 分。評分 75+ 代表歷史極值底部，45 以下代表脫離底部區間。
包含：**AHR999** (滿分20)、**MVRV Z-Score** (18)、**Pi Cycle Gap** (15)、**200週均線比值** (15)、**Puell Multiple** (12)、**月線 RSI** (10)、**冪律支撐倍數** (5)、**Mayer Multiple** (5)。

#### 4. 四季理論目標價預測
基於比特幣減半週期（約4年）劃分四季，整合歷史漲跌倍數遞減規律與冪律模型，預測未來 12 個月目標價。
* **春 (月0-11)**：多頭啟動 / **夏 (月12-23)**：FOMO蔓延 / **秋 (月24-35)**：空頭確立 / **冬 (月36-47)**：恐慌拋售。
* 演算法結合「歷史中位數倍數遞減 (÷3.5) 模型」與「冪律走廊 (Power Law)」，給出保守、中位數、樂觀三種目標價與信心區間。

---

### Tab 2：🌊 波段狙擊 (Antigravity v4.1)

專為中期波段交易設計，結合趨勢過濾與動能確認，並具備嚴格的出場防守機制。

#### 1. 進場條件 (五合一過濾，全部滿足才亮燈)
改用 **2x3 條件監控儀表板** 顯示，全數通過即觸發買進建議：
1. **趨勢向上**：Price > SMA200 (年線多頭)
2. **動能偏多**：RSI_14 > 50
3. **MACD 金叉**：MACD > Signal
4. **趨勢成型**：ADX > 20 (過濾無方向盤整)
5. **資金健康**：資金費率 < 0.05% (未過熱)
6. **站上短均**：Price ≥ EMA20 (解除原乖離限制，改抓突破)

#### 2. 動態出場防守線
使用者可從 UI 下拉選單自訂波段防守線（**SMA_50**, **EMA_20**, **SMA_200**）。當價格跌破選定均線時，即觸發紅色出場信號。

#### 3. 輔助決策模組
* **綜合策略建議**：依據當前乖離率、RSI、趨勢狀態，動態給出「絕佳進場買點」、「乖離過大不宜追高」、「跌破短期均線觀望」等文字與顏色提示。
* **未平倉量 (OI) 監控**：即時抓取 Binance 永續合約 OI 與 60 秒變化率，輔助判斷趨勢是建倉推動還是平倉衰竭。
* **Kelly 倉位計算機**：輸入總本金與單筆風險 (1-5%)，依據進場價與防守線距離，自動計算安全的開倉 BTC 數量與建議槓桿。

---

## 數據來源

| 類別 | 來源 | 說明 |
|------|------|------|
| BTC 15m K 線 | **本地 SQLite DB** (0th) | 由 collector 預先收集並 push 至 repo，Streamlit 直接讀取 |
| BTC 歷史 OHLCV | Yahoo Finance → Binance → Kraken → **CryptoCompare** | 四層備援（無本地 DB 時啟用），覆蓋 2010 年起完整歷史 |
| 即時價格/OI/費率 | Binance REST API | 採用 `requests` + Header 偽裝，繞過企業 SSL 與 WAF 阻擋 |
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

## 🤖 LINE 決策速報自動推播設定 (GitHub Actions)

本功能將每日市場快照升級為「決策輔助面板」，透過 GitHub Actions 定時觸發，無需本機常駐即可自動發送高質感 LINE Flex Message。

**雙時段排程：** 已在 `.github/workflows/daily_line_notify.yml` 中設定每日自動執行：
- UTC 01:23（台灣時間 **09:23**）— 早盤決策參考
- UTC 07:39（台灣時間 **15:39**）— 午後盤勢確認

**設定步驟：**
1. GitHub Repo → **Settings → Secrets and variables → Actions**
2. 新增 `LINE_CHANNEL_ACCESS_TOKEN` 與 `LINE_USER_ID`。
3. 推送後 Actions 將依排程自動執行，亦可手動觸發 `workflow_dispatch` 測試。

**本地端除錯：**
```bash
# 使用 test_flex_message.py 在本地預覽 Flex Message 排版，不實際發送至 LINE
python scripts/test_flex_message.py
```

---

## 歷史數據收集器

Streamlit Cloud 因 IP 封鎖等原因有時無法取得完整歷史數據。
**解法：在本地端一次性收集，commit push 到 GitHub，雲端直接讀取 repo 內的 SQLite 檔案。**

```bash
# 日常增量更新（自動 push 至 Repo）
python collector/btc_price_collector.py --push

# 只更新特定年份
python collector/btc_price_collector.py --year 2021 --push
```

### 五層備援優先序
1. `0th` 本地 SQLite DB（最穩，毫秒級讀取）
2. `1st` Yahoo Finance（加入 User-Agent 偽裝）
3. `2nd` Binance REST（部分 Cloud IP 受封鎖）
4. `3rd` Kraken（無地理封鎖）
5. `4th` CryptoCompare（最強歷史覆蓋率）

---

## Streamlit 防休眠設定

Streamlit Community Cloud 在 **7 天無流量**後自動休眠。本專案使用 GitHub Actions 每日兩次自動 Ping 保持喚醒。
* 於 Repo Secrets 新增 `STREAMLIT_APP_URL` 即可啟動 `.github/workflows/keepalive.yml`。

---

## 版本紀錄

### v2.5 (2026-03-05)
- **fix(app)**: 移除 `streamlit-autorefresh` 第三方套件（在 Streamlit Cloud 新版本上不穩定），改用 Streamlit 內建 `@st.fragment(run_every=60)` 將今日大盤速覽包成 fragment，每 60 秒獨立重跑並重取即時數據，不觸發全頁重載，效率與穩定性皆提升。
- **chore(deps)**: `requirements.txt` 移除 `streamlit-autorefresh`。

### v2.4 (2026-03-05)
- **fix(backtest)**: `run_swing_strategy_backtest` 加入 `shift(1)` 防先視偏誤（Look-Ahead Bias）：訊號在第 N 根收盤確認，改於第 N+1 根**開盤價**執行，而非錯誤地使用訊號當根收盤。
- **fix(backtest)**: Sharpe Ratio 改由**日線市值曲線**（equity_daily）計算年化值，取代原本在逐筆交易報酬上乘 √252 的錯誤公式。
- **feat(swing)**: 新增 `run_multitf_backtest()` 多週期回測引擎：日線宏觀過濾（SMA200/金叉）shift(1) 確認後，才允許在 15m 上進場；15m 訊號同樣 shift(1) 執行，並支援固定停損。
- **feat(tab_backtest)**: 新增「📈 多週期回測 (Multi-TF)」子分頁，含日線過濾開關、15m EMA 週期、RSI 閾值、停損百分比等參數，買賣點疊加在日線圖上呈現，停損出場另以橘色 ✗ 標記。
- **perf(tab_backtest)**: 參數最佳化 Grid Search 改用 `ThreadPoolExecutor(max_workers=4)` 並行執行，速度提升 ~3-4x。
- **fix(timezone)**: `service/market_data.py` 與 `service/local_db_reader.py` 全面改用 `timezone.utc`，修正在 UTC+8 環境下 `datetime.strptime().timestamp()` 偏移 8 小時的 bug（影響 DB 查詢邊界與 Binance/Kraken API 起始時間）。

### v2.3 (2026-03-04)
- **fix(ui)**: 修正 Tab 1 名稱「長週期**週期**羅盤」→「長週期羅盤」（移除重複的「週期」字）。
- **feat(bear_bottom)**: 新增 `calculate_market_cycle_score_breakdown()`，返回 `(score, bear_total, bull_total, indicator_rows)`；重構 `calculate_market_cycle_score()` 呼叫 breakdown 函數，消除邏輯重複。
- **feat(tab_macro_compass)**: 油錶圖下方新增「📐 多空評分計算公式」展開面板，逐指標顯示當前值、熊底分、牛頂分、淨貢獻與合計，方便驗證分數合理性（分數長時間不變屬正常現象，非 bug）。
- **fix(market_data)**: T 日數據縫合成功後即時將結果寫回 `BTC_HISTORY.csv`，避免下次 `fetch_market_data()` 仍重複抓取相同缺口。
- **feat(app)**: 引入 `streamlit-autorefresh`，每 60 秒自動重整頁面（後於 v2.5 改用內建 fragment 替代）。

### v2.2 (2026-02-26)
- **feat(swing)**: Tab 2 波段狙擊 UI 全面升級，新增 2x3 條件監控儀表板、動態「策略建議」區塊與外框卡片設計，並加入動態防守線（SMA_50, EMA_20, SMA_200）自訂功能。
- **perf(strategy)**: 波段策略回測引擎 `strategy/swing.py` 放寬進場乖離限制（改抓突破與趨勢確認），並重構底層邏輯支援動態出場均線。
- **feat(realtime)**: 移除 `ccxt` 依賴，全面改用直接 `requests` 呼叫 Binance REST API，並加入 `User-Agent` 偽裝與 SSL 動態驗證，徹底解決企業網路阻擋導致資金費率與未平倉量（OI）抓取失敗/顯示假數據的問題。
- **perf(market_data)**: 為 `yfinance` 建立自訂 Session 與 Header 偽裝，降低在 Streamlit Cloud 遭 Yahoo 阻擋的機率。

### v2.1 (2026-02-26)
- **feat(scripts)**: 新增 `scripts/daily_line_notify.py` 與 `scripts/test_flex_message.py`，實作高質感 LINE Flex Message 決策視覺化面板。
- **feat(github)**: 新增 `.github/workflows/daily_line_notify.yml` 排程，支援台灣時間 09:23 與 15:39 每日雙時段自動推播。
- **feat(market_data)**: 推播腳本內建 Kraken API 穿甲彈備援機制，並支援動態收盤價覆寫以確保指標精準度。

### v2.0 (2026-02-25)
- **perf(service)**: `@st.cache_data(ttl=86400)` SQLite 快取，與 T 日數據縫合技術消除均線斷層。
- **feat(app)**: 新增「今日大盤速覽 (Global Overview Panel)」，包含 6 大全域指標 Metric。
- **feat(handler)**: 合併原 Tab 1 與 Tab 5 為全新「🧭 長週期週期羅盤」，並精簡側邊欄，將策略參數移至各 Tab 內嵌。
- **feat(backtest)**: Tab 4 新增「🔬 最佳參數搜尋 (Grid Search)」，支援最高勝率/ROI 優化目標。

### v1.8 (2026-02-25)
- **feat(core)**: 實作四季理論目標價預測引擎，結合減半週期、倍數遞減模型與冪律走廊。

### v1.7 (2026-02-24)
- **feat(collector)**: 建立本地端 BTC 15m K 線收集器與多年度 SQLite 分割架構，實作第零層數據備援。

### v1.6 (2026-02-24)
- **feat(market_data)**: 新增 CryptoCompare 為第四層歷史數據備援。
- **feat(swing)**: Antigravity 策略升級至 v4，加入 MACD 與 ADX 過濾盤整假信號。

### v1.5 (2026-02-23)
- **perf**: 實作全面 SSL 繞過、非同步 API 請求、SQLite WAL 模式、向量化回測等多項效能優化。
