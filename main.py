import os
import json
import base64
import urllib.parse
import urllib.request
import urllib.error

from datetime import datetime
from zoneinfo import ZoneInfo


API_KEY = os.environ["TWELVE_DATA_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
GITHUB_REPOSITORY = os.environ["GITHUB_REPOSITORY"]
GITHUB_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

PAIRS = ["GBP/USD", "AUD/USD"]
TIMEFRAME = "15min"

STATE_FILE = "scanner_state.json"


def request_json(url, data=None, headers=None):
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers or {},
        method="POST" if data else "GET"
    )

    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request_json(url, data)


def load_state():
    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
        f"/contents/{STATE_FILE}?ref={GITHUB_BRANCH}"
    )

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    try:
        result = request_json(url, headers=headers)

        content = base64.b64decode(
            result["content"]
        ).decode()

        return json.loads(content), result["sha"]

    except urllib.error.HTTPError as error:
        if error.code == 404:
            return {}, None
        raise


def save_state(state, sha):
    url = (
        f"https://api.github.com/repos/{GITHUB_REPOSITORY}"
        f"/contents/{STATE_FILE}"
    )

    content = base64.b64encode(
        json.dumps(state, ensure_ascii=False).encode()
    ).decode()

    payload = {
        "message": "Update forex scanner state",
        "content": content,
        "branch": GITHUB_BRANCH
    }

    if sha:
        payload["sha"] = sha

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json"
    }

    data = json.dumps(payload).encode()

    request_json(url, data, headers)


def get_candles(pair):
    params = urllib.parse.urlencode({
        "symbol": pair,
        "interval": TIMEFRAME,
        "outputsize": 60,
        "timezone": "UTC",
        "apikey": API_KEY
    })

    url = (
        "https://api.twelvedata.com/time_series?"
        + params
    )

    data = request_json(url)

    if "values" not in data:
        raise RuntimeError(str(data))

    candles = []

    for candle in reversed(data["values"]):
        candles.append({
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
            "time": candle["datetime"]
        })

    return candles


def get_session(candle_time):
    dt = datetime.strptime(
        candle_time,
        "%Y-%m-%d %H:%M:%S"
    ).replace(tzinfo=ZoneInfo("UTC"))

    london = dt.astimezone(
        ZoneInfo("Europe/London")
    )

    new_york = dt.astimezone(
        ZoneInfo("America/New_York")
    )

    if 8 <= london.hour < 17:
        return "London"

    if 8 <= new_york.hour < 17:
        return "New York"

    return None


def scan(candles):
    if len(candles) < 30:
        return None

    # حذف کندل در حال تشکیل
    closed = candles[:-1]

    if len(closed) < 25:
        return None

    # سه کندل تشکیل‌دهنده FVG
    a, b, c = closed[-3:]

    # دو کندل قدرتمند متوالی
    first = b
    second = c

    # پنج کندل قبل از تشکیل FVG
    base = closed[-8:-3]

    # میانگین محدوده کندل‌های قدیمی‌تر
    reference = closed[-25:-8]

    if len(reference) < 10:
        return None

    average_range = sum(
        x["high"] - x["low"]
        for x in reference
    ) / len(reference)

    if average_range <= 0:
        return None

    def strong(candle):
        candle_range = candle["high"] - candle["low"]

        if candle_range <= 0:
            return False

        body = abs(
            candle["close"] - candle["open"]
        )

        return (
            body / candle_range >= 0.65
            and candle_range >= average_range * 1.20
        )

    bullish = (
        first["close"] > first["open"]
        and second["close"] > second["open"]
        and strong(first)
        and strong(second)
    )

    bearish = (
        first["close"] < first["open"]
        and second["close"] < second["open"]
        and strong(first)
        and strong(second)
    )

    if not bullish and not bearish:
        return None

    base_high = max(x["high"] for x in base)
    base_low = min(x["low"] for x in base)
    base_range = base_high - base_low

    # Base فشرده
    is_base = (
        base_range <= average_range * 3.5
        and sum(
            1 for x in base
            if x["high"] - x["low"] <= average_range
        ) >= 3
    )

    if bullish:
        direction = "BUY"

        # FVG صعودی
        if c["low"] <= a["high"]:
            return None

        fvg_low = a["high"]
        fvg_high = c["low"]

        # آخرین کندل نزولی قبل از حرکت
        is_ob = any(
            x["close"] < x["open"]
            for x in base
        )

        # حرکت باید از محدوده بیس عبور کرده باشد
        breakout = c["close"] > base_high

    else:
        direction = "SELL"

        # FVG نزولی
        if c["high"] >= a["low"]:
            return None

        fvg_low = c["high"]
        fvg_high = a["low"]

        is_ob = any(
            x["close"] > x["open"]
            for x in base
        )

        breakout = c["close"] < base_low

    if not breakout:
        return None

    if not is_base and not is_ob:
        return None

    setup = "Base + Order Block" if is_base and is_ob else (
        "Base" if is_base else "Order Block"
    )

    return {
        "direction": direction,
        "setup": setup,
        "fvg_low": fvg_low,
        "fvg_high": fvg_high,
        "time": c["time"]
    }


def main():
    state, state_sha = load_state()
    updated = False

    for pair in PAIRS:
        try:
            candles = get_candles(pair)
            signal = scan(candles)

            if signal is None:
                print(pair, "No setup")
                continue

            session = get_session(signal["time"])

            if session is None:
                print(pair, "Outside trading sessions")
                continue

            signal_id = (
                f"{pair}|{TIMEFRAME}|"
                f"{signal['time']}|{signal['direction']}"
            )

            if state.get(pair) == signal_id:
                print(pair, "Duplicate signal ignored")
                continue

            message = (
                "🔥 NEW FOREX SETUP 🔥\n\n"
                f"Pair: {pair}\n"
                "Timeframe: M15\n"
                f"Direction: {signal['direction']}\n"
                f"Setup: {signal['setup']}\n"
                "Pattern: 2 Strong Candles + FVG\n"
                f"FVG Low: {signal['fvg_low']}\n"
                f"FVG High: {signal['fvg_high']}\n"
                f"Session: {session}\n"
                f"Time: {signal['time']} UTC\n\n"
                "FVG formed. No retest required."
            )

            send_telegram(message)

            state[pair] = signal_id
            updated = True

            print(pair, "Telegram alert sent")

        except Exception as error:
            print(pair, "ERROR:", str(error))

    if updated:
        save_state(state, state_sha)


if __name__ == "__main__":
    main()
