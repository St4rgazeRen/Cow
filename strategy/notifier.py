"""
strategy/notifier.py
LINE Bot 主動推播通知模組

[Task #9] 整合 LINE Messaging API：
  - 波段策略出現 BUY / SELL 訊號時推播
  - 雙幣理財 APY 達到指定門檻時推播
  - 熊市底部評分達到指定門檻時推播

設定方式：
  1. 複製 .env.example → .env
  2. 填入 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_USER_ID
  3. 若未設定，所有推播函式靜默跳過（不會崩潰）

依賴：
  - requests（已在 requirements.txt）
  - python-dotenv（Task #8 加入）
  - [Task #1] verify=False 繞過企業 SSL

使用範例:
  from strategy.notifier import notify_swing_signal, notify_bear_bottom_score
  notify_swing_signal('BUY', price=50000, ema20=49500, rsi=55.3, dist_pct=1.0)
  notify_bear_bottom_score(score=72)
"""
import os
import requests
import urllib3
from datetime import datetime
from dotenv import load_dotenv
from config import SSL_VERIFY

# [Task #8] 從 .env 讀取憑證
load_dotenv()

# 只在本地開發（SSL_VERIFY=False）時關閉警告
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# LINE Messaging API 推播端點（點對點，需 User ID）
_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _get_credentials() -> tuple[str, str]:
    """
    從環境變數讀取 LINE Bot 憑證。
    返回: (channel_access_token, user_id)
    若未設定則返回空字串，呼叫端應檢查並靜默跳過。
    """
    token   = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    user_id = os.getenv("LINE_USER_ID", "")
    return token, user_id


def _send(text: str) -> bool:
    """
    發送 LINE 文字訊息給指定 User ID。

    [Task #1] verify=False 繞過企業 SSL
    [Task #3] 網路錯誤時靜默失敗（不中斷主程式）

    參數:
      text: 要發送的訊息內容（純文字，換行用 \\n）
    返回:
      True 若發送成功，False 若失敗（憑證未設定 / 網路錯誤）
    """
    token, user_id = _get_credentials()

    # 若環境變數未設定，靜默跳過（不影響主程式運行）
    if not token or token == "your_line_channel_access_token_here":
        print("[Notifier] LINE credentials not configured, skipping push notification.")
        return False
    if not user_id or user_id.startswith("Uxxxxx"):
        print("[Notifier] LINE User ID not configured, skipping push notification.")
        return False

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": text}],
    }

    try:
        resp = requests.post(
            _LINE_PUSH_URL,
            json=payload,
            headers=headers,
            timeout=8,
            verify=SSL_VERIFY,
        )
        if resp.status_code == 200:
            # 推播成功，印出前 60 字作為日誌
            preview = text.replace('\n', ' ')[:60]
            print(f"[Notifier] ✅ LINE 推播成功: {preview}...")
            return True
        else:
            print(f"[Notifier] ❌ LINE 推播失敗 HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print("[Notifier] ❌ LINE 推播逾時（8s），靜默跳過")
        return False
    except Exception as e:
        print(f"[Notifier] ❌ LINE 推播例外: {e}")
        return False


def _now_str() -> str:
    """返回當前台灣時間字串（格式: 2026-02-23 14:30）"""
    return datetime.now().strftime('%Y-%m-%d %H:%M')


# ──────────────────────────────────────────────────────────────────────────────
# 公開推播函式
# ──────────────────────────────────────────────────────────────────────────────

def notify_swing_signal(
    signal_type: str,
    price: float,
    ema20: float,
    rsi: float,
    dist_pct: float,
) -> bool:
    """
    波段策略訊號推播。

    參數:
      signal_type: 'BUY' | 'SELL' | 'WAIT' | 'HOLD'
      price:       當前 BTC 價格（USDT）
      ema20:       EMA 20 值
      rsi:         RSI_14 值
      dist_pct:    價格對 EMA20 的乖離率（%）

    推播條件: 只有 BUY 或 SELL 訊號才推播，WAIT/HOLD 不推播（避免騷擾）
    """
    # 過濾噪音：只有明確進出場訊號才推播
    if signal_type not in ('BUY', 'SELL'):
        return False

    emoji_map = {'BUY': '🟢', 'SELL': '🔴'}
    emoji     = emoji_map[signal_type]

    text = (
        f"{emoji} 波段策略訊號: {signal_type}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 現價:  ${price:,.0f}\n"
        f"📊 EMA20: ${ema20:,.0f} (乖離 {dist_pct:+.2f}%)\n"
        f"📈 RSI_14: {rsi:.1f}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕐 時間: {_now_str()}\n"
        f"⚠️ 此為自動推播，非投資建議"
    )
    return _send(text)


def notify_dual_invest_apy(
    product_type: str,
    strike: float,
    apy_pct: float,
    current_price: float,
    tier_name: str = "未分類",
    threshold_pct: float = 20.0,
) -> bool:
    """
    雙幣理財 APY 達標推播。

    參數:
      product_type:  'SELL_HIGH' | 'BUY_LOW'
      strike:        行權價（USDT）
      apy_pct:       年化 APY（百分比，如 25.3 代表 25.3%）
      current_price: 當前 BTC 現價
      tier_name:     梯形類型（激進 / 中性 / 保守）
      threshold_pct: APY 推播門檻（預設 20%，低於此值不推播）

    推播條件: apy_pct >= threshold_pct
    """
    if apy_pct < threshold_pct:
        return False  # 未達門檻，靜默跳過

    type_name  = '賣高 (SELL HIGH) 📈' if product_type == 'SELL_HIGH' else '買低 (BUY LOW) 📉'
    dist       = (strike / current_price - 1) * 100  # 行權價 vs 現價距離%

    text = (
        f"💎 雙幣理財 APY 達標！\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📌 類型:   {type_name}\n"
        f"🎯 檔位:   {tier_name}\n"
        f"💰 現價:  ${current_price:,.0f}\n"
        f"🎪 行權價: ${strike:,.0f} ({dist:+.2f}%)\n"
        f"📊 年化 APY: {apy_pct:.1f}%  (門檻 ≥{threshold_pct:.0f}%)\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕐 時間: {_now_str()}\n"
        f"⚠️ 此為自動推播，非投資建議"
    )
    return _send(text)


def notify_bear_bottom_score(
    score: int,
    signals_summary: str = "",
    threshold: int = 60,
) -> bool:
    """
    熊市底部評分達標推播。

    參數:
      score:           當前評分（0-100）
      signals_summary: 可選的指標摘要字串（如 "AHR999=0.42, MVRV=-0.8"）
      threshold:       推播門檻（預設 60 分，低於此值不推播）

    推播條件: score >= threshold
    """
    if score < threshold:
        return False  # 未達門檻，靜默跳過

    # 根據分數決定等級文字
    if score >= 75:
        level = "🔴 歷史極值底部 (All-In!)"
        action = "強烈建議大量積累"
    elif score >= 60:
        level = "🟠 明確底部區間"
        action = "建議重倉分批佈局"
    else:
        level = "🟡 可能底部區"
        action = "謹慎小倉試探"

    sig_line = f"\n📋 指標摘要: {signals_summary}" if signals_summary else ""

    text = (
        f"🐻 熊市底部獵人警報！\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🏆 評分:  {score}/100\n"
        f"📊 狀態: {level}\n"
        f"💡 建議: {action}\n"
        f"⚙️  門檻: ≥ {threshold} 分{sig_line}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕐 時間: {_now_str()}\n"
        f"⚠️ 此為自動推播，非投資建議"
    )
    return _send(text)


def notify_58k_defense(price: float) -> bool:
    """
    BTC 跌至 $58,000 推播 — 1 BTC ROAD 觸發事件二。

    提醒關閉馬丁格爾機器人並將 USDT 換 BTC 補入幣本位機器人保證金。
    """
    text = (
        f"🛡️ BTC 跌破 $58,000！\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"💰 現價:  ${price:,.0f}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📋 待執行（觸發事件二）:\n"
        f"1. 關閉 2 台馬丁格爾機器人\n"
        f"2. 將 USDT 全數換成 BTC\n"
        f"3. 注入幣本位機器人作為額外保證金\n"
        f"4. 強評價從 ~$53,333 拉低至 ~$40,000\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕐 時間: {_now_str()}\n"
        f"⚠️ 完成操作後請至 GitHub Actions 停用 price_alert workflow"
    )
    return _send(text)


def notify_custom(title: str, body: str) -> bool:
    """
    自定義訊息推播（通用介面）。

    參數:
      title: 訊息標題（會顯示在第一行，加粗格式）
      body:  訊息內容
    """
    text = (
        f"【{title}】\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{body}\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🕐 時間: {_now_str()}"
    )
    return _send(text)
