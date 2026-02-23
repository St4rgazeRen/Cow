# Cow — 比特幣投資戰情室

> 比特幣多週期量化分析工具，整合技術指標、鏈上數據、期權與波段策略。

**Live App:** https://mfyyo9qf5mymsrouxkfdgj.streamlit.app

---

## 功能模組

| Tab | 名稱 | 說明 |
|-----|------|------|
| 1 | 多頭雷達 | AHR999 指數、技術指標綜合評分、多空判斷 |
| 2 | 波段策略 | ATR 停損/停利、Kelly 倉位計算 |
| 3 | 雙幣策略 | 期權掛單 APY 試算、Delta 風險估算 |
| 4 | 波段回測 | 歷史波段勝率、夏普比率、最大回撤統計 |
| 5 | 熊市底部獵人 | 多維度底部訊號評分（鏈上 + 技術面）|

---

## 架構

```
app.py              入口點（組合各層，不含業務邏輯）
core/
  indicators.py     技術指標 + AHR999 計算（純函數，無 Streamlit 依賴）
  bear_bottom.py    熊市底部多維度評分
service/
  market_data.py    BTC / DXY 歷史數據（SQLite 增量緩存）
  onchain.py        鏈上輔助數據（非同步 httpx 分頁抓取）
  realtime.py       即時報價（SSL 繞過 + 重試機制）
  mock.py           資金費率 / TVL / 恐慌貪婪代理指標
strategy/
  swing.py          波段策略引擎（向量化回測）
  dual_invest.py    雙幣期權策略引擎（動態無風險利率）
  notifier.py       LINE Bot 主動推播通知
handler/
  layout.py         頁面設置、側欄參數
  tab_*.py          各 Tab 的 Streamlit UI（Session State 圖表快取）
data/
  cow_history.db    SQLite 歷史數據庫（BTC/TVL/穩定幣/資金費率）
tests/
  test_bear_bottom.py   熊市底部評分單元測試
  test_dual_invest.py   雙幣期權 APY 單元測試
.env.example        環境變數模板（API Key 設定）
.github/workflows/
  keepalive.yml     自動 Ping，防止 Streamlit 休眠
```

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

> **技術說明：** Streamlit Community Cloud 的 proxy 對所有請求做多層跳轉（含 `/_stcore/health`）。Workflow 採用不追蹤重定向的方式，任何 HTTP 回應（2xx / 3xx / 4xx）均視為 Ping 成功。只有完全無法連線（HTTP 000）才算失敗。

---

## 版本紀錄

### v1.5 (2026-02-23)

#### Bug Fix
- **fix(market_data):** yfinance SSL 驗證失敗導致 BTC 歷史數據無法載入
  - `ssl._create_unverified_context` 全域覆寫預設 SSL context
  - 建立 `verify=False` 的 `requests.Session` 並注入 `yfinance.download()`
  - 根本解決企業 Proxy 攔截 HTTPS 導致的「無法取得 BTC 歷史數據」錯誤

#### 10 項核心優化（完整實作）
- **#1 SSL 繞過:** `service/realtime.py`, `service/onchain.py`, `data_manager.py`, `service/market_data.py` 全面加入 `urllib3.disable_warnings()` + `verify=False`
- **#2 非同步請求:** `service/onchain.py` 的 `_fetch_funding_rate_history` 改用 `httpx.AsyncClient` 並行抓取 20 頁資金費率分頁
- **#3 API 重試:** `data_manager.py` 加入 `_retry_request()` 指數退避重試（最多 3 次，1s/2s/4s 間隔）；CCXT 呼叫加入 3 次重試迴圈
- **#4 SQLite:** `data_manager.py` 新增 `_df_to_sqlite()` / `_df_from_sqlite()`，配合 WAL 模式與 `_db_lock` 解決多執行緒寫入衝突
- **#5 回測向量化:** `strategy/swing.py` 保留可讀性；核心評分計算已在 v1.1 向量化
- **#6 動態無風險利率:** `strategy/dual_invest.py` 新增 `get_dynamic_risk_free_rate()`，優先從 DeFiLlama Aave V3 USDT 供應利率取得，備援 MakerDAO DSR，最終 fallback 4%，帶 1 小時快取
- **#7 Session State:** `handler/tab_bull_radar.py` + `handler/tab_bear_bottom.py` + `handler/tab_swing.py` + `handler/tab_dual_invest.py` 全面加入 MD5 hash 快取鍵，側邊欄互動不觸發圖表重建
- **#8 環境變數:** 引入 `python-dotenv`，CCXT API Key 與 LINE Token 均從 `.env` 讀取；提供 `.env.example` 模板
- **#9 LINE Bot:** 新增 `strategy/notifier.py`，封裝 `notify_swing_signal()` / `notify_dual_invest_apy()` / `notify_bear_bottom_score()` / `notify_custom()` 四個推播函式
- **#10 單元測試:** 新增 `tests/test_bear_bottom.py`（8 項評分邏輯測試）與 `tests/test_dual_invest.py`（動態利率 + BS APY + 梯形策略，共 18 個測試案例）

#### UI 視覺化全面升級
- **Tab 1 (牛市雷達):** 主圖從 4 行擴充為 5 行，新增 AHR999 彩色柱狀圖（帶閾值標註）+ EMA20 均線
- **Tab 2 (波段狙擊):** 頁面頂部新增 3 行 Plotly 圖表：K線+EMA20+BB+進場甜蜜點標記 / RSI_14 / MACD 直方圖，配合 Session State 快取
- **Tab 3 (雙幣理財):** 新增「行權價梯形視覺化圖」：K線背景 + 各檔行權水平線 + ATR波動帶 + APY 橫向對比長條圖（配機會成本基準線）
- **Tab 5 (熊市底部):** 修正 Session State if/else 縮排 bug，C/D 兩組圖表快取邏輯現在正確運作

### v1.4 (2026-02-23)
- **fix:** keepalive workflow 改用不追蹤重定向策略
  - 移除 `-L` 旗標，不再追蹤 301/303
  - 任何非 000 的 HTTP 回應均視為 Ping 成功
  - 根本解決 Streamlit Community Cloud proxy 多層跳轉導致的 exit code 47 問題

### v1.3 (2026-02-23)
- **fix:** keepalive workflow 多次迭代修復
  - 嘗試 `/_stcore/health` 端點（仍被 proxy 攔截）
  - 加入 `BASE="${APP_URL%/}"` 處理尾端斜線
  - 設定 `--max-redirs 3 / 10`（不足以應對多層跳轉）
  - 修復 YAML 空表達式解析錯誤
  - 修復 Step Summary HTTP 碼空白問題

### v1.2 (2026-02-23)
- **feat:** GitHub Actions keepalive.yml 防休眠 workflow
- **feat:** Tab 3 加入每檔掛單 APY 顯示
- **feat:** Tab 4 波段回測加入進階統計（勝率、夏普比率、最大回撤）

### v1.1 (2026-02-22)
- **perf:** AHR999 計算向量化，移除 `apply()` 逐行迴圈
- **perf:** 熊市底部評分引擎向量化，解決 N+1 卡頓
- **fix:** app.py 加入錯誤邊界與數據降級方案

### v1.0 (2026-02-22)
- **refactor:** 模組化分層架構重構（core / service / strategy / handler）
- **feat:** 新增 `.gitignore`，排除 `__pycache__` 與本地數據緩存
- **feat:** 新增熊市底部獵人模組（Tab 5）
