import logging
import asyncio
from datetime import datetime
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = 8718239953:AAFokieIL3T-ER7ythkFQFqYKn1ifKOGPRg
ALPHA_VANTAGE_KEY = 34TCBI9OSY59H2VR

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
        return {"signal": "WAIT", "confidence": 0, "reason": "Nincs elég adat"}
    rsi = calculate_rsi(prices)
    macd_line, signal_line, histogram = calculate_macd(prices)
    bb_mid, bb_upper, bb_lower = calculate_bollinger(prices)
    stoch = calculate_stochastic(prices)
    current = prices[-1]
    buy, sell, reasons = 0, 0, []
    if rsi < 30: buy += 2; reasons.append(f"RSI túladott ({rsi:.1f})")
    elif rsi < 45: buy += 1
    elif rsi > 70: sell += 2; reasons.append(f"RSI túlvett ({rsi:.1f})")
    elif rsi > 55: sell += 1
    if macd_line > signal_line and histogram > 0: buy += 2; reasons.append("MACD bullish")
    elif macd_line < signal_line and histogram < 0: sell += 2; reasons.append("MACD bearish")
    if current < bb_lower: buy += 2; reasons.append("Alsó BB alatt")
    elif current > bb_upper: sell += 2; reasons.append("Felső BB felett")
    elif current < bb_mid: buy += 1
    else: sell += 1
    if stoch < 20: buy += 1; reasons.append(f"Stoch túladott ({stoch:.1f})")
    elif stoch > 80: sell += 1; reasons.append(f"Stoch túlvett ({stoch:.1f})")
    if len(prices) >= 5:
        if prices[-1] > prices[-5]: buy += 0.5
        else: sell += 0.5
    total = buy + sell
    if total == 0:
        return {"signal": "WAIT", "confidence": 0, "reason": "Semleges piac"}
    if buy > sell:
        conf = int((buy / total) * 100)
        if conf >= 60:
            return {"signal": "BUY", "confidence": conf, "rsi": rsi, "stoch": stoch, "reason": " | ".join(reasons[:3])}
    elif sell > buy:
        conf = int((sell / total) * 100)
        if conf >= 60:
            return {"signal": "SELL", "confidence": conf, "rsi": rsi, "stoch": stoch, "reason": " | ".join(reasons[:3])}
    return {"signal": "WAIT", "confidence": 50, "reason": "Gyenge jelzés"}

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
        [InlineKeyboardButton("📊 Jelzés kérése", callback_data="get_signal")],
        [InlineKeyboardButton("🔄 Auto BE", callback_data="auto_on"),
         InlineKeyboardButton("🛑 Auto KI", callback_data="auto_off")],
        [InlineKeyboardButton("ℹ️ Súgó", callback_data="help")],
    ]
    await update.message.reply_text(
        "🤖 *Pocket Option OTC Trading Bot*\n\n"
        "BUY/SELL jelzések technikai elemzés alapján.\n\n"
        "⚠️ Csak azt kockáztasd amit elveszíthetsz!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def send_signals(message, context):
    await message.reply_text("🔍 Elemzés folyamatban...")
    results = []
    for pair in OTC_PAIRS:
        from_cur, to_cur = AV_SYMBOLS[pair]
        prices = fetch_prices(from_cur, to_cur)
        results.append((pair, analyze_signal(prices) if prices else {"signal": "WAIT", "confidence": 0, "reason": "Adat nem elérhető"}))
        await asyncio.sleep(0.5)
    now = datetime.now().strftime("%H:%M:%S")
    msg = f"📊 *Trading Jelzések* — {now}\n━━━━━━━━━━━━━━━━\n\n"
    for pair, res in results:
        sig = res["signal"]
        conf = res.get("confidence", 0)
        emoji = "🟢" if sig == "BUY" else "🔴" if sig == "SELL" else "🟡"
        action = "VÉTEL ↑" if sig == "BUY" else "ELADÁS ↓" if sig == "SELL" else "VÁRJ ⏳"
        msg += f"{emoji} *{pair} OTC* — {action}\n"
        if conf > 0:
            msg += f"   Konfidencia: {conf}%\n"
        if res.get("reason"):
            msg += f"   Ok: {res['reason']}\n"
        msg += "\n"
    msg += "━━━━━━━━━━━━━━━━\n⚠️ Max kockázat: $2-5 / kereskedés"
    await message.reply_text(msg, parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Frissítés", callback_data="get_signal")]]))

async def auto_job(context: ContextTypes.DEFAULT_TYPE):
    for pair in OTC_PAIRS:
        from_cur, to_cur = AV_SYMBOLS[pair]
        prices = fetch_prices(from_cur, to_cur)
        if not prices:
            continue
        res = analyze_signal(prices)
        if res["signal"] != "WAIT" and res.get("confidence", 0) >= 70:
            emoji = "🟢" if res["signal"] == "BUY" else "🔴"
            action = "VÉTEL ↑" if res["signal"] == "BUY" else "ELADÁS ↓"
            await context.bot.send_message(
                chat_id=context.job.chat_id,
                text=f"🚨 *ERŐS JELZÉS!*\n\n{emoji} *{pair} OTC* — {action}\nKonfidencia: {res['confidence']}%\nOk: {res.get('reason', '')}\n\n⏱ Ajánlott lejárat: 1 perc",
                parse_mode="Markdown"
            )
        await asyncio.sleep(1)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if q.data == "get_signal":
        await send_signals(q.message, context)
    elif q.data == "auto_on":
        context.application.job_queue.run_repeating(auto_job, interval=300, first=10,
            chat_id=q.message.chat_id, name=f"auto_{q.message.chat_id}")
        await q.message.reply_text("✅ Auto jelzések bekapcsolva! (5 percenként)")
    elif q.data == "auto_off":
        for job in context.application.job_queue.get_jobs_by_name(f"auto_{q.message.chat_id}"):
            job.schedule_removal()
        await q.message.reply_text("🛑 Auto jelzések kikapcsolva.")
    elif q.data == "help":
        await q.message.reply_text(
            "📖 *Súgó*\n\n🟢 BUY = Vétel\n🔴 SELL = Eladás\n🟡 WAIT = Várj\n\n"
            "70%+ = Erős jelzés\n60-70% = Közepes\n\n⚠️ Max $5/kereskedés",
            parse_mode="Markdown"
        )

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("signal", lambda u, c: send_signals(u.message, c)))
    app.add_handler(CallbackQueryHandler(button))
    print("✅ Bot fut!")
    app.run_polling()

if __name__ == "__main__":
    main()

import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")
    def log_message(self, format, *args):
        pass

def run_web():
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()

threading.Thread(target=run_web, daemon=True).start()
