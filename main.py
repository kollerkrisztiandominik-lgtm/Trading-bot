import logging
import threading
import os
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

BOT_TOKEN = "8718239953:AAFokieIL3T-ER7ythkFQFqYKn1ifKOGPRg"
ALPHA_VANTAGE_KEY = "34TCBI9OSY59H2VR"

OTC_PAIRS = ["AUD/CAD","AUD/CHF","AUD/NZD","AUD/USD","EUR/GBP","EUR/NZD","EUR/TRY","EUR/USD","GBP/JPY","GBP/USD"]
AV_SYMBOLS = {"AUD/CAD":("AUD","CAD"),"AUD/CHF":("AUD","CHF"),"AUD/NZD":("AUD","NZD"),"AUD/USD":("AUD","USD"),"EUR/GBP":("EUR","GBP"),"EUR/NZD":("EUR","NZD"),"EUR/TRY":("EUR","TRY"),"EUR/USD":("EUR","USD"),"GBP/JPY":("GBP","JPY"),"GBP/USD":("GBP","USD")}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot running!")
    def log_message(self, format, *args):
        pass

def run_web():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()

def fetch_prices(from_cur, to_cur):
    try:
        url = f"https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol={from_cur}&to_symbol={to_cur}&interval=1min&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}"
        data = requests.get(url, timeout=10).json()
        key = "Time Series FX (1min)"
        if key not in data:
            return []
        closes = [float(v["4. close"]) for v in list(data[key].values())[:60]]
        closes.reverse()
        return closes
    except:
        return []

def analyze(prices):
    if len(prices) < 30:
        return {"signal":"WAIT","confidence":0,"reason":"Nincs adat"}
    gains,losses = [],[]
    for i in range(1,len(prices)):
        d = prices[i]-prices[i-1]
        gains.append(max(d,0))
        losses.append(max(-d,0))
    ag = sum(gains[-14:])/14
    al = sum(losses[-14:])/14
    rsi = 100-(100/(1+ag/al)) if al != 0 else 100
    buy,sell,reasons = 0,0,[]
    if rsi < 30: buy+=2; reasons.append("RSI tuladott")
    elif rsi < 45: buy+=1
    elif rsi > 70: sell+=2; reasons.append("RSI tulvett")
    elif rsi > 55: sell+=1
    if prices[-1] > prices[-5]: buy+=1
    else: sell+=1
    mid = sum(prices[-20:])/20
    std = (sum((p-mid)**2 for p in prices[-20:])/20)**0.5
    if prices[-1] < mid-2*std: buy+=2; reasons.append("BB also")
    elif prices[-1] > mid+2*std: sell+=2; reasons.append("BB felso")
    total = buy+sell
    if total == 0:
        return {"signal":"WAIT","confidence":0,"reason":"Semleges"}
    if buy > sell:
        conf = int(buy/total*100)
        if conf >= 60: return {"signal":"BUY","confidence":conf,"reason":" | ".join(reasons)}
    elif sell > buy:
        conf = int(sell/total*100)
        if conf >= 60: return {"signal":"SELL","confidence":conf,"reason":" | ".join(reasons)}
    return {"signal":"WAIT","confidence":50,"reason":"Gyenge jelzes"}

def get_signals_text():
    now = datetime.now().strftime("%H:%M:%S")
    msg = "Trading Jelzesek - " + now + "\n\n"
    for pair in OTC_PAIRS:
        fc,tc = AV_SYMBOLS[pair]
        prices = fetch_prices(fc,tc)
        res = analyze(prices) if prices else {"signal":"WAIT","confidence":0,"reason":"Adat hiba"}
        sig = res["signal"]
        action = "VETEL" if sig=="BUY" else "ELADAS" if sig=="SELL" else "VARJ"
        msg += pair + " - " + action
        if res["confidence"] > 0:
            msg += " (" + str(res["confidence"]) + "%)"
        msg += "\n"
        if res.get("reason"):
            msg += "  " + res["reason"] + "\n"
        msg += "\n"
    msg += "Max kockazat: $2-5"
    return msg

def start(update: Update, context: CallbackContext):
    kb = [[InlineKeyboardButton("Jelzes kerese", callback_data="signal")],[InlineKeyboardButton("Sugo", callback_data="help")]]
    update.message.reply_text("Pocket Option OTC Trading Bot\n\nBUY/SELL jelzesek technikai elemzes alapjan.", reply_markup=InlineKeyboardMarkup(kb))

def signal_cmd(update: Update, context: CallbackContext):
    update.message.reply_text("Elemzes folyamatban...")
    update.message.reply_text(get_signals_text())

def button(update: Update, context: CallbackContext):
    q = update.callback_query
    q.answer()
    if q.data == "signal":
        q.message.reply_text("Elemzes folyamatban...")
        q.message.reply_text(get_signals_text())
    elif q.data == "help":
        q.message.reply_text("VETEL = felfelé\nELADAS = lefelé\nVARJ = gyenge jelzes\n\n70%+ = eros jelzes")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("signal", signal_cmd))
    dp.add_handler(CallbackQueryHandler(button))
    updater.start_polling()
    print("Bot fut!")
    updater.idle()

if __name__ == "__main__":
    main()
