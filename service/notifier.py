"""
service/notifier.py
LINE Bot 推播通知服務

[Task #9] 封裝 LINE Messaging API 推播邏輯。
支援兩種觸發情境:
  1. 波段策略訊號 (BUY / SELL) - 由 handler/tab_swing.py 或 app.py 呼叫
  2. 雙幣理財 APY 達標 - 由 handler/tab_dual_invest.py 呼叫

使用前提:
  - pip install line-bot-sdk
  - 在 .env 設定 LINE_CHANNEL_ACCESS_TOKEN 與 LINE_USER_ID
  - LINE Bot 必須已加入好友（點對點推播需要 User ID）

架構說明:
  - _send_line_message() 為底層 HTTP 發送函式
  - notify_swing_signal() 為波段訊號推播的高階介面
  - notify_dual_invest_apy() 為雙幣 APY 達標推播的高階介面
  - 所有函式都有 try/except，推播失敗不影響主程式運作

[Task #1] verify=False 用於 SSL 繞過（LINE API 在企業網路也可能被擋）
[Task #8] 所有敏感資訊從 .env 讀取，不寫死在程式碼中
"""
import os
import json
import requests
import urllib3
from datetime import datetime
from dotenv import load_dotenv  # [Task #8]

# [Task #1] 靜默 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# [Task #8] 載入 .env 設定
load_dotenv()

# 從環境變數讀取 LINE Bot 憑證
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID              = os.getenv("LINE_USER_ID", "")

# LINE Messaging API 推送端點
_LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


def _is_configured() -> bool:
    """
    檢查 LINE Bot 憑證是否已設定。
    若未設定，推播函式會靜默跳過（不拋出例外）。
    """
    return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID)


def _send_line_message(messages: list[dict]) -> bool:
    """
    底層 LINE Messaging API 發送函式。

    messages: list of LINE message objects，例如:
        [{"type": "text", "text": "Hello!"}]

    LINE Messaging API 文件:
        https://developers.line.biz/en/reference/messaging-api/#send-push-message

    返回: True = 成功，False = 失敗

    [Task #1] verify=False 繞過企業 SSL 憑證阻擋
    [Task #3] 發送失敗時打印錯誤訊息，但不拋出例外
    """
    if not _is_configured():
        print("[Notifier] LINE Bot 未設定，跳過推播（請在 .env 設定 LINE_CHANNEL_ACCESS_TOKEN）")
        return False

    headers = {
        "Content-Type":  "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
    }
    payload = {
        "to":       LINE_USER_ID,
        "messages": messages,
    }

    try:
        resp = requests.post(
            _LINE_PUSH_URL,
            headers=headers,
            data=json.dumps(payload, ensure_ascii=False),
            timeout=8,
            verify=False  # [Task #1] 企業網路 SSL 繞過
        )
        if resp.status_code == 200:
            print(f"[Notifier] LINE 推播成功: {resp.status_code}")
            return True
        else:
            print(f"[Notifier] LINE 推播失敗: HTTP {resp.status_code} - {resp.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print("[Notifier] LINE 推播逾時")
        return False
    except Exception as e:
        print(f"[Notifier] LINE 推播例外: {e}")
        return False


def notify_swing_signal(signal_type: str, price: float, ema20: float,
                        dist_pct: float, stop_price: float,
                        capital: float = 0.0) -> bool:
    """
    波段策略訊號推播。

    signal_type: 'BUY' | 'SELL' | 'WAIT'
    price:       當前 BTC 價格
    ema20:       EMA20 均線值
    dist_pct:    價格與 EMA20 的乖離率 (%)
    stop_price:  建議止損價格
    capital:     總資金（用於計算建議倉位，可選）

    推播格式（Flex Message 純文字版本）:
    ┌─────────────────────────────┐
    │ 🎯 波段訊號: BUY            │
    │ 時間: 2024-01-15 14:30     │
    │ 現價: $67,500              │
    │ EMA20: $67,000 (乖離+0.7%)│
    │ 止損: $65,800              │
    └─────────────────────────────┘
    """
    if not _is_configured():
        return False

    # 根據訊號類型設定 emoji 與描述
    signal_map = {
        'BUY':  ("🟢", "買進訊號 (BUY)", "甜蜜點！趨勢向上且回踩均線"),
        'SELL': ("🔴", "賣出訊號 (SELL)", "跌破均線，短期趨勢轉弱"),
        'WAIT': ("🟡", "乖離過大 (WAIT)", f"偏離 {dist_pct:.2f}%，勿追高"),
    }
    emoji, title, desc = signal_map.get(signal_type.upper(), ("🔵", signal_type, ""))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 組裝純文字推播訊息（LINE Flex Message 需要更複雜的 JSON，此處用 text 型）
    lines = [
        f"{emoji} 【Antigravity v4】{title}",
        f"━━━━━━━━━━━━━━━━━━",
        f"📅 時間: {now_str}",
        f"💰 BTC 現價: ${price:,.0f}",
        f"📐 EMA20: ${ema20:,.0f} (乖離 {dist_pct:+.2f}%)",
        f"🛑 建議止損: ${stop_price:,.0f}",
        f"",
        f"📝 {desc}",
    ]
    if capital > 0:
        lines.append(f"💼 總資金: ${capital:,.0f}")

    message_text = "\n".join(lines)

    return _send_line_message([{"type": "text", "text": message_text}])


def notify_dual_invest_apy(product_type: str, strike: float, apy_pct: float,
                           current_price: float, t_days: int,
                           threshold_pct: float = 20.0) -> bool:
    """
    雙幣理財 APY 達標推播。

    product_type:  'SELL_HIGH' | 'BUY_LOW'
    strike:        行權價格
    apy_pct:       年化 APY (百分比，如 25.3)
    current_price: 當前 BTC 價格
    t_days:        產品期限（天）
    threshold_pct: 觸發推播的 APY 門檻（預設 20%，超過才推）

    只有 APY 超過門檻時才發送推播，避免無意義的噪音通知。
    """
    if not _is_configured():
        return False

    # APY 未達門檻，不推播
    if apy_pct < threshold_pct:
        return False

    product_map = {
        'SELL_HIGH': ("📈", "高賣 (持有BTC)", "Call Option"),
        'BUY_LOW':   ("📉", "低買 (持有USDT)", "Put Option"),
    }
    emoji, product_name, option_type = product_map.get(
        product_type.upper(), ("💰", product_type, "Unknown")
    )

    distance_pct = abs(strike / current_price - 1) * 100
    direction    = "高於" if product_type == 'SELL_HIGH' else "低於"
    now_str      = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"{emoji} 【雙幣理財】APY 達標通知",
        f"━━━━━━━━━━━━━━━━━━",
        f"📅 時間: {now_str}",
        f"📦 產品: {product_name} ({option_type})",
        f"💰 BTC 現價: ${current_price:,.0f}",
        f"🎯 行權價: ${strike:,.0f}（{direction}現價 {distance_pct:.1f}%）",
        f"⏰ 期限: {t_days} 天",
        f"🔥 年化 APY: {apy_pct:.1f}% (門檻 {threshold_pct:.0f}%)",
        f"",
        f"⚠️ 注意：此為模型估算值，請結合市場情況判斷。",
    ]

    message_text = "\n".join(lines)
    return _send_line_message([{"type": "text", "text": message_text}])


def send_test_message() -> bool:
    """
    發送測試訊息，驗證 LINE Bot 設定是否正確。
    使用方式: python -c "from service.notifier import send_test_message; send_test_message()"
    """
    return _send_line_message([{
        "type": "text",
        "text": (
            "✅ 比特幣投資戰情室 LINE Bot 連線成功！\n"
            f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            "波段訊號與 APY 達標通知已啟用。"
        )
    }])
