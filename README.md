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
  market_data.py    BTC / DXY 歷史數據
  onchain.py        鏈上輔助數據
  realtime.py       即時報價
  mock.py           資金費率 / TVL / 恐慌貪婪代理指標
strategy/
  swing.py          波段策略引擎
  dual_invest.py    雙幣期權策略引擎
handler/
  layout.py         頁面設置、側欄參數
  tab_*.py          各 Tab 的 Streamlit UI
.github/workflows/
  keepalive.yml     自動 Ping，防止 Streamlit 休眠
```

---

## 本地執行

```bash
pip install -r requirements.txt
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
