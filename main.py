import os
import json
import urllib.parse
import urllib.request

API_KEY = os.environ["TWELVE_DATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

PAIRS = ["EUR/USD", "GBP/USD", "AUD/USD"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(url, data=data)
    urllib.request.urlopen(req, timeout=20)

def get_candles(pair):
    params = urllib.parse.urlencode({
        "symbol": pair,
        "interval": "5min",
        "outputsize": 50,
        "order": "asc",
        "apikey": API_KEY
    })

    url = "https://api.twelvedata.com/time_series?" + params

    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.loads(response.read())

    if "values" not in data:
        raise Exception(str(data))

    return [
        {
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
            "time": c["datetime"]
        }
        for c in data["values"]
    ]

def scan(pair, candles):
    if len(candles) < 25:
        return []

    # آخرین کندل ممکن است هنوز بسته نشده باشد.
    candles = candles[:-1]
    last = candles[-1]
    previous = candles[-21:-1]

    resistance = max(c["high"] for c in previous)
    support = min(c["low"] for c in previous)

    signals = []

    if last["close"] > resistance:
        signals.append("Bullish BOS")

    if last["close"] < support:
        signals.append("Bearish BOS")

    candle_range = last["high"] - last["low"]
    body = abs(last["close"] - last["open"])

    if candle_range > 0 and body / candle_range >= 0.75:
        direction = "Bullish" if last["close"] > last["open"] else "Bearish"
        signals.append(direction + " Displacement")

    recent = candles[-6:-1]
    average_range = sum(
        c["high"] - c["low"] for c in recent
    ) / len(recent)

    if average_range > 0 and candle_range < average_range * 0.5:
        signals.append("Possible Base")

    return signals, last["time"]

def main():
    for pair in PAIRS:
        try:
            candles = get_candles(pair)
            result = scan(pair, candles)

            if result:
                signals, candle_time = result

                if signals:
                    message = (
                        f"FOREX SCANNER\n"
                        f"Pair: {pair}\n"
                        f"Timeframe: M5\n"
                        f"Time: {candle_time}\n\n"
                        + "\n".join(signals)
                    )
                    send_telegram(message)

            print(pair, "checked")

        except Exception as error:
            print(pair, "ERROR:", error)

if __name__ == "__main__":
    main()
