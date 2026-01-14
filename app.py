from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import requests
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=20,
        verify=False   # 🔥 關鍵
    )

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
        df.set_index("navTxnDate")
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
# LINE 收到任何訊息就回傳結果
# =============================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    fund_no = "18480065"  # 你的基金代碼

    try:
        result = calculate_ma36(fund_no)

        reply_text = (
            "📊 MA36 即時計算結果\n"
            "====================\n"
            f"基金代碼：{result['fund_no']}\n"
            f"最新日期：{result['date']}\n"
            f"今日淨值：{result['today_nav']:.2f}\n"
            f"MA36：{result['ma36']:.2f}\n"
            f"比例：{result['ratio']:.2f}%"
        )

    except Exception as e:
        reply_text = f"❌ 計算失敗\n{str(e)}"

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply_text)
    )

# =============================
# 啟動 Flask
# =============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
