"""
service/notifier.py
推播通知服務 — LINE Bot + Telegram

[Task #9] 封裝 LINE Messaging API 推播邏輯。
[Task 4 (UX)] 新增 TelegramNotifier，支援同時或擇一推播至 LINE 與 Telegram。

支援兩種觸發情境:
  1. 波段策略訊號 (BUY / SELL / WAIT) - 由 handler/tab_swing.py 或 app.py 呼叫
  2. 雙幣理財 APY 達標 - 由 handler/tab_dual_invest.py 呼叫

使用前提（LINE）:
  - pip install line-bot-sdk
  - 在 .env 或 Streamlit Secrets 設定:
    LINE_CHANNEL_ACCESS_TOKEN=your_token
    LINE_USER_ID=Uxxxx

使用前提（Telegram）:
  - 在 .env 或 Streamlit Secrets 設定:
    TELEGRAM_BOT_TOKEN=123456:ABCxxx   ← 從 @BotFather 取得
    TELEGRAM_CHAT_ID=-100xxxxx         ← 頻道 ID 或個人 chat_id
  - 取得 TELEGRAM_CHAT_ID 的方法:
    1. 將 Bot 加入頻道/群組，並設為管理員
    2. 發一則訊息，再打開 https://api.telegram.org/bot{TOKEN}/getUpdates
    3. 找到 "chat": {"id": -100xxxxx} 這個值

架構說明:
  ┌─────────────────────────────────────────────────────┐
  │                  高階介面 (Public API)               │
  │  notify_swing_signal()   notify_dual_invest_apy()   │
  └──────────────┬──────────────────────────────────────┘
                 │ 呼叫底層發送器
       ┌─────────┴─────────┐
       │                   │
  _send_line_message()  _send_telegram_message()
  (LINE Messaging API)  (Telegram Bot API)

  所有函式都有 try/except，推播失敗不影響主程式運作。

[Task #1] verify=SSL_VERIFY 動態 SSL（本地 False，雲端 True）
[Task #8] 所有敏感資訊從 .env / Streamlit Secrets 讀取，不寫死在程式碼中
"""
import os
import json
import requests
import urllib3
from datetime import datetime
from dotenv import load_dotenv  # [Task #8]

# 從集中設定檔讀取 SSL 旗標
from config import SSL_VERIFY

# [Task #1] 動態 SSL：本地開發環境才關閉警告
if not SSL_VERIFY:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# [Task #8] 載入 .env 設定（Streamlit Cloud 使用 st.secrets，本地使用 .env）
load_dotenv()

# ── LINE Bot 憑證 ────────────────────────────────────────────────────────────
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_USER_ID              = os.getenv("LINE_USER_ID", "")
_LINE_PUSH_URL            = "https://api.line.me/v2/bot/message/push"

# ── Telegram Bot 憑證 ────────────────────────────────────────────────────────
# TELEGRAM_BOT_TOKEN  : @BotFather 建立 Bot 後取得的 Token（格式：123456:ABCxxx）
# TELEGRAM_CHAT_ID    : 推播目標的 Chat ID（個人 / 群組 / 頻道皆可）
#   - 個人 Chat ID: 正整數（如 123456789）
#   - 群組/頻道:    負整數（如 -100123456789）
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
# Telegram Bot API 發送訊息端點（{token} 在呼叫時動態填入）
_TELEGRAM_API_URL  = "https://api.telegram.org/bot{token}/sendMessage"


# ==============================================================================
# 連線狀態檢查
# ==============================================================================

def _is_line_configured() -> bool:
    """
    檢查 LINE Bot 憑證是否已設定。
    若未設定，LINE 推播函式會靜默跳過（不拋出例外）。
    """
    return bool(LINE_CHANNEL_ACCESS_TOKEN and LINE_USER_ID)


def _is_telegram_configured() -> bool:
    """
    檢查 Telegram Bot 憑證是否已設定。
    若未設定，Telegram 推播函式會靜默跳過（不拋出例外）。
    """
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


# ==============================================================================
# 底層發送函式
# ==============================================================================

def _send_line_message(messages: list[dict]) -> bool:
    """
    底層 LINE Messaging API 發送函式。

    messages: list of LINE message objects，例如:
        [{"type": "text", "text": "Hello!"}]

    LINE Messaging API 文件:
        https://developers.line.biz/en/reference/messaging-api/#send-push-message

    返回: True = 成功，False = 失敗

    [Task #1] verify=SSL_VERIFY 動態 SSL 驗證
    [Task #3] 發送失敗時打印錯誤訊息，但不拋出例外
    """
    if not _is_line_configured():
        print("[LINE Notifier] 未設定，跳過（請在 .env 設定 LINE_CHANNEL_ACCESS_TOKEN）")
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
            verify=SSL_VERIFY,  # 動態 SSL：本地 False / 雲端 True
        )
        if resp.status_code == 200:
            print(f"[LINE Notifier] 推播成功: HTTP {resp.status_code}")
            return True
        else:
            print(f"[LINE Notifier] 推播失敗: HTTP {resp.status_code} - {resp.text[:200]}")
            return False
    except requests.exceptions.Timeout:
        print("[LINE Notifier] 推播逾時")
        return False
    except Exception as e:
        print(f"[LINE Notifier] 推播例外: {e}")
        return False


def _send_telegram_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    底層 Telegram Bot API 發送函式。

    text       : 訊息內文（支援 HTML 或 Markdown 格式）
    parse_mode : 'HTML' | 'Markdown' | 'MarkdownV2'（預設 HTML，最穩定）

    Telegram Bot API 文件:
        https://core.telegram.org/bots/api#sendmessage

    HTML 格式範例（parse_mode='HTML'）:
        <b>粗體</b>  <i>斜體</i>  <code>程式碼</code>  <pre>區塊</pre>

    返回: True = 成功，False = 失敗

    [Task #1] verify=SSL_VERIFY 動態 SSL 驗證
    """
    if not _is_telegram_configured():
        print("[Telegram Notifier] 未設定，跳過（請在 .env 設定 TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID）")
        return False

    # 動態填入 Bot Token 組裝 API URL
    url = _TELEGRAM_API_URL.format(token=TELEGRAM_BOT_TOKEN)
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": parse_mode,
        # disable_web_page_preview: 避免 URL 展開預覽（保持訊息簡潔）
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(
            url,
            json=payload,
            timeout=8,
            verify=SSL_VERIFY,  # 動態 SSL：本地 False / 雲端 True
        )
        if resp.status_code == 200:
            print(f"[Telegram Notifier] 推播成功: HTTP {resp.status_code}")
            return True
        else:
            # Telegram API 會在回應 JSON 中附帶錯誤描述
            err_desc = resp.json().get('description', resp.text[:200])
            print(f"[Telegram Notifier] 推播失敗: HTTP {resp.status_code} - {err_desc}")
            return False
    except requests.exceptions.Timeout:
        print("[Telegram Notifier] 推播逾時")
        return False
    except Exception as e:
        print(f"[Telegram Notifier] 推播例外: {e}")
        return False


# ==============================================================================
# 高階推播介面（公開 API）
# ==============================================================================

def notify_swing_signal(
    signal_type: str,
    price: float,
    ema20: float,
    dist_pct: float,
    stop_price: float,
    capital: float = 0.0,
    use_line: bool = True,
    use_telegram: bool = True,
) -> dict:
    """
    波段策略訊號推播（同時支援 LINE + Telegram）。

    signal_type  : 'BUY' | 'SELL' | 'WAIT'
    price        : 當前 BTC 價格
    ema20        : EMA20 均線值
    dist_pct     : 價格與 EMA20 的乖離率 (%)
    stop_price   : 建議止損價格
    capital      : 總資金（用於計算建議倉位，可選）
    use_line     : 是否推播至 LINE（預設 True）
    use_telegram : 是否推播至 Telegram（預設 True）

    返回: {'line': bool, 'telegram': bool}（各平台的推播結果）

    訊息格式範例:
    ┌─────────────────────────────┐
    │ 🎯 波段訊號: BUY            │
    │ 時間: 2024-01-15 14:30     │
    │ 現價: $67,500              │
    │ EMA20: $67,000 (乖離+0.7%)│
    │ 止損: $65,800              │
    └─────────────────────────────┘
    """
    result = {'line': False, 'telegram': False}

    # 根據訊號類型設定 emoji 與描述
    signal_map = {
        'BUY':  ("🟢", "買進訊號 (BUY)", "甜蜜點！趨勢向上且回踩均線"),
        'SELL': ("🔴", "賣出訊號 (SELL)", "跌破均線，短期趨勢轉弱"),
        'WAIT': ("🟡", "乖離過大 (WAIT)", f"偏離 {dist_pct:.2f}%，勿追高"),
    }
    emoji, title, desc = signal_map.get(signal_type.upper(), ("🔵", signal_type, ""))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ── 組裝訊息內容（純文字版本，LINE & Telegram 共用）──────────────
    text_lines = [
        f"{emoji} 【Antigravity v4】{title}",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 時間: {now_str}",
        f"💰 BTC 現價: ${price:,.0f}",
        f"📐 EMA20: ${ema20:,.0f} (乖離 {dist_pct:+.2f}%)",
        f"🛑 建議止損: ${stop_price:,.0f}",
        "",
        f"📝 {desc}",
    ]
    if capital > 0:
        text_lines.append(f"💼 總資金: ${capital:,.0f}")
    plain_text = "\n".join(text_lines)

    # ── LINE 推播 ──────────────────────────────────────────────────────
    if use_line and _is_line_configured():
        result['line'] = _send_line_message([{"type": "text", "text": plain_text}])

    # ── Telegram 推播（使用 HTML 格式增強可讀性）──────────────────────
    if use_telegram and _is_telegram_configured():
        # Telegram 支援 HTML 格式，加粗關鍵數字以提升可讀性
        tg_lines = [
            f"{emoji} <b>【Antigravity v4】{title}</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"📅 時間: <code>{now_str}</code>",
            f"💰 BTC 現價: <b>${price:,.0f}</b>",
            f"📐 EMA20: ${ema20:,.0f} (乖離 <b>{dist_pct:+.2f}%</b>)",
            f"🛑 建議止損: <b>${stop_price:,.0f}</b>",
            "",
            f"📝 {desc}",
        ]
        if capital > 0:
            tg_lines.append(f"💼 總資金: <b>${capital:,.0f}</b>")
        result['telegram'] = _send_telegram_message("\n".join(tg_lines))

    return result


def notify_dual_invest_apy(
    product_type: str,
    strike: float,
    apy_pct: float,
    current_price: float,
    t_days: int,
    threshold_pct: float = 20.0,
    use_line: bool = True,
    use_telegram: bool = True,
) -> dict:
    """
    雙幣理財 APY 達標推播（同時支援 LINE + Telegram）。

    product_type  : 'SELL_HIGH' | 'BUY_LOW'
    strike        : 行權價格
    apy_pct       : 年化 APY (百分比，如 25.3)
    current_price : 當前 BTC 價格
    t_days        : 產品期限（天）
    threshold_pct : 觸發推播的 APY 門檻（預設 20%，超過才推）
    use_line      : 是否推播至 LINE（預設 True）
    use_telegram  : 是否推播至 Telegram（預設 True）

    返回: {'line': bool, 'telegram': bool}

    只有 APY 超過門檻時才發送推播，避免無意義的噪音通知。
    """
    result = {'line': False, 'telegram': False}

    # APY 未達門檻，不推播（靜默返回，不打印任何訊息）
    if apy_pct < threshold_pct:
        return result

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

    # ── 組裝訊息內容 ──────────────────────────────────────────────────
    text_lines = [
        f"{emoji} 【雙幣理財】APY 達標通知",
        "━━━━━━━━━━━━━━━━━━",
        f"📅 時間: {now_str}",
        f"📦 產品: {product_name} ({option_type})",
        f"💰 BTC 現價: ${current_price:,.0f}",
        f"🎯 行權價: ${strike:,.0f}（{direction}現價 {distance_pct:.1f}%）",
        f"⏰ 期限: {t_days} 天",
        f"🔥 年化 APY: {apy_pct:.1f}% (門檻 {threshold_pct:.0f}%)",
        "",
        "⚠️ 注意：此為模型估算值，請結合市場情況判斷。",
    ]
    plain_text = "\n".join(text_lines)

    # ── LINE 推播 ──────────────────────────────────────────────────────
    if use_line and _is_line_configured():
        result['line'] = _send_line_message([{"type": "text", "text": plain_text}])

    # ── Telegram 推播（HTML 格式）──────────────────────────────────────
    if use_telegram and _is_telegram_configured():
        tg_lines = [
            f"{emoji} <b>【雙幣理財】APY 達標通知</b>",
            "━━━━━━━━━━━━━━━━━━",
            f"📅 時間: <code>{now_str}</code>",
            f"📦 產品: <b>{product_name}</b> ({option_type})",
            f"💰 BTC 現價: <b>${current_price:,.0f}</b>",
            f"🎯 行權價: <b>${strike:,.0f}</b>（{direction}現價 {distance_pct:.1f}%）",
            f"⏰ 期限: {t_days} 天",
            f"🔥 年化 APY: <b>{apy_pct:.1f}%</b>（門檻 {threshold_pct:.0f}%）",
            "",
            "⚠️ 注意：此為模型估算值，請結合市場情況判斷。",
        ]
        result['telegram'] = _send_telegram_message("\n".join(tg_lines))

    return result


def send_test_message(platform: str = "all") -> dict:
    """
    發送測試訊息，驗證推播設定是否正確。

    platform: 'line' | 'telegram' | 'all'（預設 all）

    使用方式:
        python -c "from service.notifier import send_test_message; send_test_message()"

    返回: {'line': bool, 'telegram': bool}
    """
    result = {'line': False, 'telegram': False}
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    test_text = (
        "✅ 比特幣投資戰情室 推播連線成功！\n"
        f"時間: {now_str}\n"
        "波段訊號與 APY 達標通知已啟用。"
    )

    if platform in ('line', 'all') and _is_line_configured():
        result['line'] = _send_line_message([{"type": "text", "text": test_text}])

    if platform in ('telegram', 'all') and _is_telegram_configured():
        tg_text = (
            "✅ <b>比特幣投資戰情室 Telegram Bot 連線成功！</b>\n"
            f"時間: <code>{now_str}</code>\n"
            "波段訊號與 APY 達標通知已啟用。"
        )
        result['telegram'] = _send_telegram_message(tg_text)

    return result
