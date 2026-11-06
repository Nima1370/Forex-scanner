import os
import json
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

API_KEY = os.environ["TWELVE_DATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PAIRS = ["AUD/USD", "GBP/USD"]
TIMEFRAMES = ["5min", "15min"]


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(url, data=data)
    urllib.request.urlopen(req, timeout=20)


def get_candles(pair, interval):
    params = urllib.parse.urlencode({
        "symbol": pair,
        "interval": interval,
        "outputsize": 60,
        "timezone": "UTC",
        "apikey": API_KEY
    })

    url = "https://api.twelvedata.com/time_series?" + params

    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.loads(response.read())

    if "values" not in data:
        raise Exception(str(data))

    candles = []
    for c in reversed(data["values"]):
        candles.append({
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "time": c["datetime"]
        })

    return candles


def in_trading_session(candle_time):
    dt = datetime.strptime(candle_time, "%Y-%m-%d %H:%M:%S")
    dt = dt.replace(tzinfo=ZoneInfo("UTC"))

    london = dt.astimezone(ZoneInfo("Europe/London"))
    new_york = dt.astimezone(ZoneInfo("America/New_York"))

    london_open = 8 <= london.hour < 17
    new_york_open = 8 <= new_york.hour < 17

    return london_open or new_york_open


def scan(candles):
    if len(candles) < 15:
        return None

    # آخرین کندل برای بررسی ورود قیمت به FVG
    current = candles[-1]
    history = candles[:-1]

    # جست‌وجوی حرکت شارپ و FVG در کندل‌های اخیر
    for i in range(len(history) - 2, max(2, len(history) - 12), -1):
        impulse = history[i]

        candle_range = impulse["high"] - impulse["low"]
        body = abs(impulse["close"] - impulse["open"])

        if candle_range <= 0:
            continue

        if body / candle_range < 0.70:
            continue

        direction = (
            "BUY" if impulse["close"] > impulse["open"]
            else "SELL"
        )

        previous = history[i - 1]
        following = history[i + 1]

        # تشکیل FVG صعودی
        if direction == "BUY":
            if following["low"] <= previous["high"]:
                continue

            zone_low = previous["high"]
            zone_high = following["low"]

        # تشکیل FVG نزولی
        else:
            if following["high"] >= previous["low"]:
                continue

            zone_low = following["high"]
            zone_high = previous["low"]

        # بررسی برگشت قیمت به محدوده FVG
        touched = (
            current["low"] <= zone_high
            and current["high"] >= zone_low
        )

        if not touched:
            continue

        # بررسی وجود OB یا Base پیش از حرکت شارپ
        setup = None

        if direction == "BUY":
            for c in history[max(0, i - 4):i]:
                if c["close"] < c["open"]:
                    setup = "Bullish Order Block"
                    break
        else:
            for c in history[max(0, i - 4):i]:
                if c["close"] > c["open"]:
                    setup = "Bearish Order Block"
                    break

        if setup is None:
            base = history[max(0, i - 4):i]

            if len(base) >= 2:
                avg_range = sum(
                    c["high"] - c["low"] for c in base
                ) / len(base)

                if avg_range > 0 and candle_range > avg_range * 1.5:
                    setup = "Base"

        if setup is None:
            continue

        return {
            "direction": direction,
            "setup": setup,
            "low": zone_low,
            "high": zone_high,
            "time": current["time"]
        }

    return None


def main():
    for pair in PAIRS:
        for timeframe in TIMEFRAMES:
            try:
                candles = get_candles(pair, timeframe)

                signal = scan(candles)

                if not signal:
                    continue

                if not in_trading_session(signal["time"]):
                    continue

                message = (
                    "FOREX SCANNER\n\n"
                    f"Pair: {pair}\n"
                    f"Timeframe: {timeframe}\n"
                    f"Signal: {signal['direction']}\n"
                    f"Setup: {signal['setup']}\n"
                    f"FVG: {signal['low']} - {signal['high']}\n"
                    f"Time: {signal['time']} UTC\n\n"
                    "Price returned to FVG"
                )

                send_telegram(message)
                print("Signal sent:", pair, timeframe)

            except Exception as error:
                print(pair, timeframe, "ERROR:", error)


if __name__ == "__main__":
    main()
