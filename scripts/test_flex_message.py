"""
scripts/test_flex_message.py
用於本地端測試 LINE Flex Message 排版與 API 連線。
(加入：Kraken 即時價格備援 + 動態價格覆寫指標)
"""

import os
import sys
import urllib3
import requests
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

# ==============================================================================
# 環境設定與安全限制覆寫 (強制關閉全域 SSL 驗證)
# ==============================================================================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_SCRIPT_DIR)
sys.path.append(_REPO_ROOT)

env_path = os.path.join(_REPO_ROOT, '.env')
print(f"🔍 嘗試讀取憑證檔案路徑: {env_path}")
load_dotenv(dotenv_path=env_path)

from service.realtime import fetch_realtime_data
from service.market_data import fetch_market_data
from service.local_db_reader import read_btc_daily
from core.indicators import calculate_technical_indicators, calculate_ahr999
from core.bear_bottom import calculate_bear_bottom_score, calculate_market_cycle_score

def _get_cycle_meta(score: int):
    if score >= 75: return "🔥 狂熱牛頂", "#ff4b4b", "風險極高，建議分批止盈。此區域歷史上出現牛市最終頂部。"
    elif score >= 40: return "🐂 牛市主升段", "#ff9800", "趨勢多頭排列，可持有並設移動止盈，避免頂部追高。"
    elif score >= 15: return "🌱 初牛復甦", "#8bc34a", "市場轉暖，分批建倉機會。等待黃金交叉與年線翻揚確認。"
    elif score >= -15: return "⚪ 中性過渡", "#9e9e9e", "多空力量均衡，觀望為主，等待方向確認。"
    elif score >= -40: return "📉 轉折回調", "#7986cb", "跌破關鍵均線，趨勢轉弱，建議輕倉或觀望。"
    elif score >= -75: return "❄️ 熊市築底", "#42a5f5", "熊市中後期，多指標出現底部信號，開始定投積累。"
    else: return "🟦 歷史極值底部", "#00bcd4", "All-In 信號！歷史上極為罕見的買入機會，建議全力積累。"

def get_decision_data():
    print("⏳ 正在抓取市場與決策數據...")
    summary = {
        "price": "API 阻擋 (N/A)",
        "cycle_score": 0, "cycle_name": "N/A", "cycle_color": "#aaaaaa", "cycle_advice": "",
        "ahr_text": "N/A", "ahr_color": "#aaaaaa",
        "bear_score": 0, "bear_color": "#aaaaaa", "bar_text": "□□□□□□□□□□",
        "trend_text": "N/A", "trend_color": "#aaaaaa",
        "rsi_text": "N/A", "rsi_color": "#aaaaaa",
        "macd_text": "N/A", "macd_color": "#aaaaaa",
        "adx_text": "N/A", "adx_color": "#aaaaaa",
        "ema_dist_text": "N/A", "ema_dist_color": "#aaaaaa",
        "swing_advice": "N/A", "swing_advice_color": "#aaaaaa"
    }
    
    current_price = None

    # 1. 獲取即時價格 (加入 Kraken 終極備援)
    try:
        realtime_data = fetch_realtime_data()
        if realtime_data and realtime_data.get('price'):
            current_price = float(realtime_data['price'])
            summary["price"] = f"${current_price:,.0f}"
        else:
            raise ValueError("無效的即時價格")
    except Exception as e:
        print(f"⚠️ Binance 即時報價失敗，啟動 Kraken API 備援...")
        try:
            # 直接呼叫 Kraken Public API 取得最新價格
            resp = requests.get("https://api.kraken.com/0/public/Ticker?pair=XXBTZUSD", verify=False, timeout=10)
            if resp.status_code == 200:
                current_price = float(resp.json()['result']['XXBTZUSD']['c'][0])
                summary["price"] = f"${current_price:,.0f}"
                print(f"✅ 成功透過 Kraken 取得最新價格: {current_price}")
        except Exception as e2:
            print(f"⚠️ Kraken 備援也失敗: {e2}")

    # 2. 獲取歷史數據與計算指標
    try:
        btc_df, _ = fetch_market_data()
        if btc_df is None or btc_df.empty:
            print("🔄 外部 API 獲取失敗，啟動本地 DB 備援機制...")
            btc_df = read_btc_daily()
            
        if not btc_df.empty:
            btc_df = calculate_technical_indicators(btc_df)
            btc_df = calculate_ahr999(btc_df)
            curr = btc_df.iloc[-1].copy() # 複製一份，避免改到原始 DataFrame
            
            # 【關鍵修復】：如果我們有抓到真實最新價格，強行覆寫 curr['close']，
            # 這樣後續的 SMA、EMA 乖離率判斷就會使用 68000 而不是 DB 裡舊的 66000！
            if current_price is not None:
                curr['close'] = current_price
            else:
                # 若完全抓不到即時價格，才用 K 線收盤價，並加上提示
                current_price = curr['close']
                summary["price"] = f"${current_price:,.0f} (延遲)"

            # ---- [長週期多空評分] ----
            cycle_score = calculate_market_cycle_score(curr)
            c_name, c_color, c_advice = _get_cycle_meta(cycle_score)
            summary["cycle_score"] = cycle_score
            summary["cycle_name"] = c_name
            summary["cycle_color"] = c_color
            summary["cycle_advice"] = c_advice

            # ---- [底部探測器] ----
            ahr_val = curr.get('AHR999')
            if pd.notna(ahr_val):
                if ahr_val < 0.45:
                    summary["ahr_text"] = f"{ahr_val:.2f} (🟢抄底)"
                    summary["ahr_color"] = "#00ff88"
                elif ahr_val < 1.2:
                    summary["ahr_text"] = f"{ahr_val:.2f} (🟡定投)"
                    summary["ahr_color"] = "#ffeb3b"
                else:
                    summary["ahr_text"] = f"{ahr_val:.2f} (🔴高估)"
                    summary["ahr_color"] = "#ff4b4b"

            bear_score, _ = calculate_bear_bottom_score(curr)
            b_score_int = max(0, min(100, int(bear_score)))
            summary["bear_score"] = b_score_int
            
            blocks = b_score_int // 10
            summary["bar_text"] = "■" * blocks + "□" * (10 - blocks)

            if b_score_int >= 60: summary["bear_color"] = "#00ff88"
            elif b_score_int >= 45: summary["bear_color"] = "#ffeb3b"
            else: summary["bear_color"] = "#ff4b4b"

            # ---- [波段雷達 (Antigravity v4)] ----
            close = curr['close']
            sma200 = curr.get('SMA_200', 0)
            sma50 = curr.get('SMA_50', 0)
            is_bull_trend = close > sma200 and sma50 > sma200
            if is_bull_trend:
                summary["trend_text"] = "🟢 多頭排列"
                summary["trend_color"] = "#00ff88"
            else:
                summary["trend_text"] = "🔴 空頭/震盪"
                summary["trend_color"] = "#ff4b4b"

            rsi = curr.get('RSI_14', 0)
            summary["rsi_text"] = f"🟢 > 50 ({rsi:.1f})" if rsi > 50 else f"🔴 < 50 ({rsi:.1f})"
            summary["rsi_color"] = "#00ff88" if rsi > 50 else "#ff4b4b"

            macd = curr.get('MACD', 0)
            macd_sig = curr.get('MACD_Signal', 0)
            summary["macd_text"] = "🟢 金叉" if macd > macd_sig else "🔴 死叉"
            summary["macd_color"] = "#00ff88" if macd > macd_sig else "#ff4b4b"

            adx = curr.get('ADX_14', 0)
            summary["adx_text"] = f"🟢 趨勢成型 ({adx:.1f})" if adx > 20 else f"🔴 盤整 ({adx:.1f})"
            summary["adx_color"] = "#00ff88" if adx > 20 else "#ff4b4b"

            ema20 = curr.get('EMA_20', 0)
            ema_dist = 0
            if ema20 > 0:
                ema_dist = (close - ema20) / ema20 * 100
                if 0 <= ema_dist <= 1.5:
                    summary["ema_dist_text"] = f"🟢 買點區間 ({ema_dist:.1f}%)"
                    summary["ema_dist_color"] = "#00ff88"
                else:
                    summary["ema_dist_text"] = f"🔴 偏離/跌破 ({ema_dist:.1f}%)"
                    summary["ema_dist_color"] = "#ff4b4b"

            # 綜合波段建議
            if is_bull_trend:
                if 0 <= ema_dist <= 1.5 and rsi > 50 and macd > macd_sig and adx > 20:
                    summary["swing_advice"] = "🚀 動能共振！絕佳進場買點"
                    summary["swing_advice_color"] = "#00ff88"
                elif ema_dist > 1.5:
                    summary["swing_advice"] = "📈 趨勢偏多，但乖離過大不宜追高"
                    summary["swing_advice_color"] = "#ffeb3b"
                else:
                    summary["swing_advice"] = "🟡 多頭排列，等待動能指標轉強"
                    summary["swing_advice_color"] = "#ffeb3b"
            else:
                if ema_dist < 0:
                    summary["swing_advice"] = "❄️ 跌破短期均線，建議觀望"
                    summary["swing_advice_color"] = "#ff4b4b"
                else:
                    summary["swing_advice"] = "⚪ 趨勢偏弱，空頭或震盪格局"
                    summary["swing_advice_color"] = "#aaaaaa"

    except Exception as e:
        print(f"⚠️ 歷史數據獲取或指標計算失敗: {e}")

    print("✅ 數據獲取完畢！")
    return summary

def build_flex_message(summary):
    date_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    c_score = summary["cycle_score"]
    left_flex = int((c_score + 100) / 2)
    left_flex = max(1, min(99, left_flex))
    right_flex = 100 - left_flex
    
    flex_bubble = {
      "type": "bubble", "size": "giga",
      "header": {
        "type": "box", "layout": "vertical", "backgroundColor": "#191919",
        "contents": [
          { "type": "text", "text": "🦅 戰情室決策速報", "weight": "bold", "color": "#ffffff", "size": "xl" },
          { "type": "text", "text": f"更新時間: {date_str}", "color": "#aaaaaa", "size": "xs", "margin": "sm" }
        ]
      },
      "body": {
        "type": "box", "layout": "vertical", "backgroundColor": "#222222",
        "contents": [
          { "type": "text", "text": f"💰 BTC {summary['price']}", "weight": "bold", "size": "xxl", "color": "#00ff88", "adjustMode": "shrink-to-fit" },
          { "type": "separator", "margin": "md", "color": "#444444" },
          
          { "type": "text", "text": "🧭 長週期多空評分", "weight": "bold", "color": "#ffffff", "margin": "md" },
          { "type": "box", "layout": "horizontal", "contents": [
              { "type": "box", "layout": "vertical", "flex": 7, "contents": [
                  { "type": "text", "text": summary["cycle_name"], "color": summary["cycle_color"], "weight": "bold", "size": "md" },
                  { "type": "text", "text": summary["cycle_advice"], "color": "#aaaaaa", "size": "xs", "wrap": True, "margin": "xs" }
              ]},
              { "type": "box", "layout": "vertical", "flex": 3, "alignItems": "flex-end", "contents": [
                  { "type": "text", "text": f"{c_score:+d}", "color": summary["cycle_color"], "size": "xxl", "weight": "bold" },
                  { "type": "text", "text": "-100(深熊) → +100(狂熱)", "color": "#666666", "size": "xxs", "wrap": True, "align": "end" }
              ]}
          ]},
          { "type": "box", "layout": "horizontal", "margin": "md", "cornerRadius": "4px", "height": "8px", "contents": [
              { "type": "box", "layout": "vertical", "flex": left_flex, "backgroundColor": summary["cycle_color"], "contents": [{"type": "filler"}] },
              { "type": "box", "layout": "vertical", "flex": right_flex, "backgroundColor": "#444444", "contents": [{"type": "filler"}] }
          ]},

          { "type": "separator", "margin": "lg", "color": "#444444" },
          
          { "type": "text", "text": "🐻 底部探測", "weight": "bold", "color": "#ffffff", "margin": "md" },
          { "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
             { "type": "text", "text": "AHR999", "color": "#aaaaaa", "size": "sm", "flex": 4 },
             { "type": "text", "text": summary["ahr_text"], "color": summary["ahr_color"], "size": "sm", "weight": "bold", "flex": 6, "align": "end" }
          ]},
          { "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
             { "type": "text", "text": "底部評分", "color": "#aaaaaa", "size": "sm", "flex": 4 },
             { "type": "text", "text": f"{summary['bear_score']}/100", "color": summary["bear_color"], "size": "sm", "weight": "bold", "flex": 6, "align": "end" }
          ]},
          { "type": "text", "text": summary["bar_text"], "color": summary["bear_color"], "size": "md", "align": "end", "margin": "sm" },

          { "type": "separator", "margin": "lg", "color": "#444444" },

          { "type": "text", "text": "🐂 波段雷達", "weight": "bold", "color": "#ffffff", "margin": "md" },
          { "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
             { "type": "text", "text": "大趨勢 (SMA)", "color": "#aaaaaa", "size": "sm", "flex": 4 },
             { "type": "text", "text": summary["trend_text"], "color": summary["trend_color"], "size": "sm", "weight": "bold", "flex": 6, "align": "end" }
          ]},
          { "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
             { "type": "text", "text": "RSI 動能", "color": "#aaaaaa", "size": "sm", "flex": 4 },
             { "type": "text", "text": summary["rsi_text"], "color": summary["rsi_color"], "size": "sm", "weight": "bold", "flex": 6, "align": "end" }
          ]},
          { "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
             { "type": "text", "text": "MACD 交叉", "color": "#aaaaaa", "size": "sm", "flex": 4 },
             { "type": "text", "text": summary["macd_text"], "color": summary["macd_color"], "size": "sm", "weight": "bold", "flex": 6, "align": "end" }
          ]},
          { "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
             { "type": "text", "text": "ADX 趨勢", "color": "#aaaaaa", "size": "sm", "flex": 4 },
             { "type": "text", "text": summary["adx_text"], "color": summary["adx_color"], "size": "sm", "weight": "bold", "flex": 6, "align": "end" }
          ]},
          { "type": "box", "layout": "horizontal", "margin": "sm", "contents": [
             { "type": "text", "text": "EMA20 乖離", "color": "#aaaaaa", "size": "sm", "flex": 4 },
             { "type": "text", "text": summary["ema_dist_text"], "color": summary["ema_dist_color"], "size": "sm", "weight": "bold", "flex": 6, "align": "end" }
          ]},
          { "type": "box", "layout": "vertical", "margin": "lg", "backgroundColor": "#1a1a1a", "paddingAll": "md", "cornerRadius": "8px", "contents": [
              { "type": "text", "text": "💡 波段策略狀態", "color": "#888888", "size": "xs", "weight": "bold", "margin": "sm" },
              { "type": "text", "text": summary["swing_advice"], "color": summary["swing_advice_color"], "size": "sm", "weight": "bold", "wrap": True }
          ]}
        ]
      }
    }

    return {
        "type": "flex",
        "altText": f"🦅 決策速報: BTC {summary['price']} | 評分: {c_score}",
        "contents": flex_bubble
    }

def send_test_message(flex_payload):
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    line_user_id = os.getenv("LINE_USER_ID") 
    
    print(f"🔑 Token 結尾: {line_token[-4:] if line_token else 'None'}")
    print(f"👤 User ID 結尾: {line_user_id[-4:] if line_user_id else 'None'}")
    
    if not line_token or not line_user_id:
        print("❌ 錯誤: 找不到憑證，請確認 .env 中的變數名稱是否正確。")
        sys.exit(1)
        
    url = "https://api.line.me/v2/bot/message/push"
    headers = { "Content-Type": "application/json", "Authorization": f"Bearer {line_token}" }
    data = { "to": line_user_id, "messages": [flex_payload] }
    
    try:
        response = requests.post(url, headers=headers, json=data, verify=False, timeout=10)
        response.raise_for_status()
        print("✅ 測試推播發送成功！")
    except Exception as e:
        print(f"❌ 推播發送失敗: {e}")
        if 'response' in locals() and response is not None:
             print(f"API 回應: {response.text}")
        sys.exit(1)

if __name__ == "__main__":
    print("=== 開始執行本地端 Flex Message 測試 ===")
    summary_data = get_decision_data()
    flex_msg = build_flex_message(summary_data)
    send_test_message(flex_msg)