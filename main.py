import logging
import asyncio
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = "8718239953:AAFokieIL3T-ER7ythkFQFqYKn1ifKOGPRg"
ALPHA_VANTAGE_KEY = "34TCBI9OSY59H2VR"

OTC_PAIRS = [
    "AUD/CAD", "AUD/CHF", "AUD/NZD", "AUD/USD",
    "EUR/GBP", "EUR/NZD", "EUR/TRY", "EUR/USD",
    "GBP/JPY", "GBP/USD"
]

AV_SYMBOLS = {
    "AUD/CAD": ("AUD", "CAD"), "AUD/CHF": ("AUD", "CHF"),
    "AUD/NZD": ("AUD", "NZD"), "AUD/USD": ("AUD", "USD"),
    "EUR/GBP": ("EUR", "GBP"), "EUR/NZD": ("EUR", "NZD"),
    "EUR/TRY": ("EUR", "TRY"), "EUR/USD": ("EUR", "USD"),
    "GBP/JPY": ("GBP", "JPY"), "GBP/USD": ("GBP", "USD"),
}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, format, *args):
        pass

def run_web():
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        diff = prices[i] - prices[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_macd(prices):
    def ema(data, period):
        if len(data) < period:
            return data[-1] if data else 0
        k = 2 / (period + 1)
        v = sum(data[:period]) / period
        for p in data[period:]:
            v = p * k + v * (1 - k)
        return v
    if len(prices) < 26:
        return 0, 0, 0
    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    macd = ema12 - ema26
    signal = macd * 0.85
    return macd, signal, macd - signal

def calculate_bollinger(prices, period=20):
    if len(prices) < period:
        mid = prices[-1] if prices else 0
        return mid, mid * 1.002, mid * 0.998
    recent = prices[-period:]
    mid = sum(recent) / period
    std = (sum((p - mid) ** 2 for p in recent) / period) ** 0.5
    return mid, mid + 2 * std, mid - 2 * std

def calculate_stochastic(prices, period=14):
    if len(prices) < period:
        return 50.0
    recent = prices[-period:]
    low, high = min(recent), max(recent)
    if high == low:
        return 50.0
    return ((prices[-1] - low) / (high - low)) * 100

def analyze_signal(prices):
    if len(prices) < 30:
        return {"signal": "WAIT", "confidence": 0, "reason": "Nincs eleg adat"}
    rsi = calculate_rsi(prices)
    macd_line, signal_line, histogram = calculate_macd(prices)
    bb_mid, bb_upper, bb_lower = calculate_bollinger(prices)
    stoch = calculate_stochastic(prices)
    current = prices[-1]
    buy, sell, reasons = 0, 0, []
    if rsi < 30:
        buy += 2
        reasons.append("RSI tuladott")
    elif rsi < 45:
        buy += 1
    elif rsi > 70:
        sell += 2
        reasons.append("RSI tulvett")
    elif rsi > 55:
        sell += 1
    if macd_line > signal_line and histogram > 0:
        buy += 2
        reasons.append("MACD bullish")
    elif macd_line < signal_line and histogram < 0:
        sell += 2
        reasons.append("MACD bearish")
    if current < bb_lower:
        buy += 2
        reasons.append("Also BB alatt")
    elif current > bb_upper:
        sell += 2
        reasons.append("Felso BB felett")
    elif current < bb_mid:
        buy += 1
    else:
        sell += 1
    if stoch < 20:
        buy += 1
        reasons.append("Stoch tuladott")
    elif stoch > 80:
        sell += 1
        reasons.append("Stoch tulvett")
    if len(prices) >= 5:
        if prices[-1] > prices[-5]:
            buy += 0.5
        else:
            sell += 0.5
    total = buy + sell
    if total == 0:
        return {"signal": "WAIT", "confidence": 0, "reason": "Semleges piac"}
    if buy > sell:
        conf = int((buy / total) * 100)
        if conf >= 60:
            return {"signal": "BUY", "confidence": conf, "reason": " | ".join(reasons[:3])}
    elif sell > buy:
        conf = int((sell / total) * 100)
        if conf >= 60:
            return {"signal": "SELL", "confidence": conf, "reason": " | ".join(reasons[:3])}
    return {"signal": "WAIT", "confidence": 50, "reason": "Gyenge jelzes"}

def fetch_prices(from_cur, to_cur):
    try:
        url = (f"https://www.alphavantage.co/query?function=FX_INTRADAY"
               f"&from_symbol={from_cur}&to_symbol={to_cur}"
               f"&interval=1min&outputsize=compact&apikey={ALPHA_VANTAGE_KEY}")
        data = requests.get(url, timeout=10).json()
        key = "Time Series FX (1min)"
        if key not in data:
            return []
        closes = [float(v["4. close"]) for v in list(data[key].values())[:60]]
        closes.reverse()
        return closes
    except:
        return []

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = [
        [InlineKeyboardButton("Jelzes kerese", callback_data="get_signal")],
        [InlineKeyboardButton("Auto BE", callback_data="auto_on"),
         InlineKeyboardButton("Auto KI", callback_data="auto_off")],
        [InlineKeyboardButton("Sugo", callback_data="help")],
    ]
    await update.message.reply_text(
        "Pocket Option OTC Trading Bot\n\nBUY/SELL jelzesek technikai elemzes alapjan.\n\nCsak azt kockaztasd amit elveszithetsz!",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def send_signals(message, context):
    await message.reply_text("Elemzes folyamatban...")
    results = []
    for pair in OTC_PAIRS:
        from_cur, to_cur = AV_SYMBOLS[pair]
        prices = fetch_prices(from_cur, to_cur)
        if prices:
            results.append((pair, analyze_signal(prices)))
        else:
            results.append((pair, {"signal": "WAIT", "confidence": 0, "reason": "Adat nem elerheto"}))
        await asyncio.sleep(0.5)
    now = datetime.now().strftime("%H:%M:%S")
    msg = "Trading Jelzesek - " + now + "\n\n"
    for pair, res in results:
        sig = res["signal"]
        conf = res.get("confidence", 0)
        if sig == "BUY":
            emoji = "VETEL"
        elif sig == "SELL":
            emoji = "ELADAS"
        else:
            emoji = "VARJ"
        msg += pair + " OTC - " + emoji + "\n"
        if conf > 0:
            msg += "Konfidencia: " + str(conf) + "%\n"
        if res.get("reason"):
            msg += "Ok: " + res["reason"] + "\n"
        msg += "\n"
    msg += "Max kockazat: $2-5 per kereskedés"
    await message.reply_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Frissites", callback_data="get_signal")]]))

async def auto_job(context: ContextTypes.DEFAULT_TYPE):
    for pair in OTC_PAIRS:
        from_cur, to_cur = AV_SYMBOLS[pair]
        prices = fetch_prices(from_cur, to_cur)
        if not prices:
            continue
        res = analyze_signal(prices)
        if res["signal"] != "WAIT" and res.get("confidence", 0) >= 70:
            action = "VETEL" if res["signal"] == "BUY" else "ELADAS"
            now = datetime.now().strftime("%H:%M:%S")
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text="EROS JELZES! - " + now + "\n\n" + pair + " OTC - " + action + "\nKonfidencia: " + str(res["confidence"]) + "%\nOk: " + res.get("reason", "") + "\n\nAjanlo lejarat: 1 perc"
            )
        await asyncio.sleep(1)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "get_signal":
        await send_signals(q.message, context)
    elif q.data == "auto_on":
        context.application.job_queue.run_repeating(auto_job, interval=300, first=10, chat_id=q.message.chat_id, name="auto_" + str(q.message.chat_id))
        await q.message.reply_text("Auto jelzesek bekapcsolva! 5 percenkent")
    elif q.data == "auto_off":
        for job in context.application.job_queue.get_jobs_by_name("auto_" + str(q.message.chat_id)):
            job.schedule_removal()
        await q.message.reply_text("Auto jelzesek kikapcsolva.")
    elif q.data == "help":
        await q.message.reply_text("VETEL = ar felfelé megy\nELADAS = ar lefelé megy\nVARJ = gyenge jelzes\n\n70%+ = eros jelzes\nMax $5 per kereskedés")

def main():
    threading.Thread(target=run_web, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", lambda u, c: send_signals(u.message, c)))
    app.add_handler(CallbackQueryHandler(button))
    print("Bot fut!")
    app.run_polling()

if __name__ == "__main__":
    main()
