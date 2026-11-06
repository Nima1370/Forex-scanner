import requests
import datetime

# ======= تنظیمات =======
TELEGRAM_TOKEN = "<TOKEN>"
TELEGRAM_CHAT_ID = "<CHAT_ID>"
TWELVEDATA_API_KEY = "<TWELVEDATA_API_KEY>"
SYMBOLS = ["AUD/USD", "GBP/USD"]
TIMEFRAMES = ["5min", "15min"]
# =======================

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print("Telegram error:", e)

def get_klines(symbol, interval):
    url = (f"https://api.twelvedata.com/time_series?"
           f"symbol={symbol}&interval={interval}&outputsize=150&apikey={TWELVEDATA_API_KEY}")
    r = requests.get(url, timeout=15).json()
    if "values" not in r:
        print(f"Error {symbol} {interval}: {r.get('message', r)}")
        return []
    return r["values"][::-1]  # ترتیب زمانی صعودی

def calc_atr(candles, period=14):
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i]["high"])
        l = float(candles[i]["low"])
        pc = float(candles[i-1]["close"])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    return sum(trs[-period:]) / period

def is_small_body(candle, atr, factor=0.4):
    body = abs(float(candle["close"]) - float(candle["open"]))
    return body < atr * factor

def is_sharp_body(candle, atr, factor=1.5):
    body = abs(float(candle["close"]) - float(candle["open"]))
    return body > atr * factor

def find_base(candles, atr, start_idx, min_len=2, max_len=5):
    """پیدا کردن Base: چند کندل کوچک متوالی در یک محدوده باریک"""
    for length in range(max_len, min_len - 1, -1):
        if start_idx - length < 0:
            continue
        block = candles[start_idx - length:start_idx]
        if all(is_small_body(c, atr) for c in block):
            highs = [float(c["high"]) for c in block]
            lows = [float(c["low"]) for c in block]
            base_high, base_low = max(highs), min(lows)
            range_size = base_high - base_low
            if range_size < atr * 1.2:  # محدوده باریک
                return {
                    "high": base_high,
                    "low": base_low,
                    "start": start_idx - length,
                    "end": start_idx - 1
                }
    return None

def is_fresh_ob(candles, ob_high, ob_low, ob_end_idx, direction):
    """بررسی اینکه قیمت بعد از OB بهش برنگشته"""
    for c in candles[ob_end_idx + 1:]:
        h = float(c["high"])
        l = float(c["low"])
        if direction == "Bullish":
            # OB نزولی (آخرین کندل نزولی) - قیمت نباید بهش برگشته باشه
            if l <= ob_high:
                return False
        else:
            if h >= ob_low:
                return False
    return True

def detect_signal(symbol, interval):
    candles = get_klines(symbol, interval)
    if len(candles) < 40:
        return None

    atr = calc_atr(candles, 14)
    if atr == 0:
        return None

    # بررسی ۲۰ کندل آخر
    for i in range(len(candles) - 20, len(candles) - 3):
        ob_candle = candles[i]
        ob_high = float(ob_candle["high"])
        ob_low = float(ob_candle["low"])
        ob_open = float(ob_candle["open"])
        ob_close = float(ob_candle["close"])
        ob_is_bearish = ob_close < ob_open
        ob_is_bullish = ob_close > ob_open

        # بررسی Base قبل از OB
        base = find_base(candles, atr, i)
        if not base:
            continue

        # بررسی حرکت شارپ بعد از OB
        for j in range(i + 1, min(i + 4, len(candles))):
            nxt = candles[j]
            if not is_sharp_body(nxt, atr, 1.5):
                continue
            nxt_high = float(nxt["high"])
            nxt_low = float(nxt["low"])
            nxt_close = float(nxt["close"])
            nxt_open = float(nxt["open"])

            # ===== شارپ صعودی: کندل OB نزولی + شکست بالا =====
            if ob_is_bearish and nxt_close > nxt_open and nxt_high > ob_high:
                if is_fresh_ob(candles, ob_high, ob_low, j, "Bullish"):
                    return {
                        "type": "Bullish",
                        "symbol": symbol,
                        "tf": interval,
                        "ob_high": ob_high,
                        "ob_low": ob_low,
                        "base_high": base["high"],
                        "base_low": base["low"],
                        "sharp_close": nxt_close,
                        "atr": atr
                    }

            # ===== شارپ نزولی: کندل OB صعودی + شکست پایین =====
            if ob_is_bullish and nxt_close < nxt_open and nxt_low < ob_low:
                if is_fresh_ob(candles, ob_high, ob_low, j, "Bearish"):
                    return {
                        "type": "Bearish",
                        "symbol": symbol,
                        "tf": interval,
                        "ob_high": ob_high,
                        "ob_low": ob_low,
                        "base_high": base["high"],
                        "base_low": base["low"],
                        "sharp_close": nxt_close,
                        "atr": atr
                    }
    return None

def main():
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            result = detect_signal(symbol, tf)
            if result:
                tf_label = "5 دقیقه" if tf == "5min" else "15 دقیقه"
                emoji = "🟢" if result["type"] == "Bullish" else "🔴"
                text = (
                    f"{emoji} *{result['type']} OB + Sharp Move*\n\n"
                    f"📊 نماد: `{result['symbol']}`\n"
                    f"⏱ تایم‌فریم: `{tf_label}`\n"
                    f"📈 نوع OB: `{result['type']}`\n\n"
                    f"🔺 سقف OB: `{result['ob_high']:.5f}`\n"
                    f"🔻 کف OB: `{result['ob_low']:.5f}`\n"
                    f"📦 سقف Base: `{result['base_high']:.5f}`\n"
                    f"📦 کف Base: `{result['base_low']:.5f}`\n"
                    f"💰 قیمت شارپ: `{result['sharp_close']:.5f}`\n"
                    f"📏 ATR: `{result['atr']:.5f}`\n\n"
                    f"✅ OB تازه (Fresh) شناسایی شد"
                )
                send_telegram(text)
                print(f"Signal sent: {symbol} {tf} {result['type']}")

if __name__ == "__main__":
    main()
