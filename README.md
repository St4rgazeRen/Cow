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
| 5 | 🐻 熊市底部獵人 | 8 大鏈上+技術指標複合評分（0-100 分）、歷史底部驗證圖、評分走勢分析 |

---

## 架構

```
app.py              入口點（組合各層，不含業務邏輯）
config.py           集中設定（均線週期、交易成本、倉位風控參數）

core/
  indicators.py     技術指標 + AHR999 計算（純函數，無 Streamlit 依賴）
  bear_bottom.py    熊市底部 8 大指標評分引擎（向量化，20-50x 效能提升）

service/
  market_data.py    BTC / DXY 歷史數據（四層備援：Yahoo→Binance→Kraken→CryptoCompare）
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
  tab_bear_bottom.py Tab 5：熊市底部獵人（Gauge + 8 指標卡片 + 歷史驗證）

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

## 數據來源

| 類別 | 來源 | 說明 |
|------|------|------|
| BTC 歷史 OHLCV | Yahoo Finance → Binance → Kraken → **CryptoCompare** | 四層備援，覆蓋 2015 年起完整歷史 |
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
