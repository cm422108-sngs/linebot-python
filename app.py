from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage

import requests
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta

from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import os

import threading
import time
import requests

# =============================
# Flask & LINE Bot 基本設定
# =============================
app = Flask(__name__)

line_bot_api = LineBotApi(os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    return

# =============================
# 基金資料 API
# =============================

def fetch_fundclear_history(fund_no, org_id="A0036"):
    today = datetime.today()
    end_date = today.strftime("%Y/%m/%d")
    start_date = (today - relativedelta(years=5)).strftime("%Y/%m/%d")

    url = "https://www.fundclear.com.tw/api/onshore/nav-profit/query-history"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://www.fundclear.com.tw",
        "Referer": "https://www.fundclear.com.tw/onshore/nav-profit/fund-nav?type=history",
        "User-Agent": "Mozilla/5.0"
    }

    payload = {
        "orgId": org_id,
        "fundNo": fund_no,
        "fundClassCode": fund_no,
        "startDate": start_date,
        "endDate": end_date
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()


# =============================
# MA36 計算
# =============================

def calculate_ma36(fund_no):
    data = fetch_fundclear_history(fund_no)

    df = pd.DataFrame(data["tableList"])
    df = df.drop(["navValueDiffRate", "lastDayNav"], axis=1)

    df["navTxnDate"] = pd.to_datetime(df["navTxnDate"])
    df["navValue"] = df["navValue"].astype(float)

    df = df.sort_values("navTxnDate")

    monthly = (
        df
        .set_index("navTxnDate")
        .resample("ME")
        .last()
        .dropna()
    )

    today_nav = df.iloc[-1]["navValue"]
    this_month = df.iloc[-1]["navTxnDate"].to_period("M")

    monthly_35 = monthly[
        monthly.index.to_period("M") < this_month
    ].tail(35)

    ma36 = (monthly_35["navValue"].sum() + today_nav) / 36

    return {
        "fund_no": fund_no,
        "date": df.iloc[-1]["navTxnDate"].date(),
        "today_nav": today_nav,
        "ma36": ma36,
        "ratio": ma36 / today_nav * 100
    }

# =============================
# 每日排程任務
# =============================

def daily_job():
    fund_no = "18480065"   # ← 你要的基金代碼

    try:
        result = calculate_ma36(fund_no)

        print("================================")
        print("📊 每日自動執行 MA36 計算")
        print("基金代碼:", result["fund_no"])
        print("最新日期:", result["date"])
        print("今日淨值:", f"{result['today_nav']:.2f}")
        print("MA36:", f"{result['ma36']:.2f}")
        print("比例:", f"{result['ratio']:.2f}%")
        print("================================")

    except Exception as e:
        print("❌ 每日任務執行失敗")
        print(str(e))
# =============================
# 啟動排程器（台灣時間）
# =============================

scheduler = BackgroundScheduler(timezone="Asia/Taipei")

# ⏰ 每天 09:00 執行
scheduler.add_job(
    daily_job,
    trigger="cron",
    hour=16,
    minute=10
)

scheduler.start()

atexit.register(lambda: scheduler.shutdown())


# =============================
# 啟動 Flask
# =============================
def keep_awake():
    url = os.getenv("RENDER_URL")  # 你 Render 網址，放在環境變數
    if not url:
        print("❌ RENDER_URL 未設定，無法自我喚醒")
        return

    while True:
        try:
            r = requests.get(url)
            print(f"⏱ Ping 自我喚醒: {r.status_code}")
        except Exception as e:
            print("❌ Ping 失敗:", str(e))
        time.sleep(25 * 60)  # 每 25 分鐘 ping 一次


if __name__ == "__main__":
    # 啟動 keep_awake 的背景執行緒，daemon=True 表示程式結束時自動結束此執行緒
    threading.Thread(target=keep_awake, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)

