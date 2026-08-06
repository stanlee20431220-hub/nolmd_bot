import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright

PRODUCT_URL = "https://nolmdshop.com/product/%EB%91%90%EC%82%B0%EB%B2%A0%EC%96%B4%EC%8A%A4-%ED%82%A4%EC%A6%88-%EC%9C%A0%EB%8B%88%ED%8F%BC%EC%9B%90%EC%A0%95/1615/category/30/display/1/"
HISTORY_FILE = "data/stock_history.json"


def fetch_stock_via_browser():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(PRODUCT_URL, wait_until="networkidle", timeout=60000)
        data = page.evaluate(
            "() => (typeof option_stock_data !== 'undefined') ? option_stock_data : null"
        )
        browser.close()

    if not data:
        return None
    if isinstance(data, str):
        data = json.loads(data)

    result = {}
    for _, v in data.items():
        result[v["option_value"]] = v["stock_number"]
    return result


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)


def load_previous():
    if not os.path.exists(HISTORY_FILE):
        return {}, {"history": []}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)
    if saved.get("history"):
        return saved["history"][-1]["stock"], saved
    return {}, saved


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    current = fetch_stock_via_browser()

    if current is None:
        print("option_stock_data NOT FOUND after rendering page with browser.")
        if token and chat_id:
            send_telegram(
                token,
                chat_id,
                "[\uc7ac\uace0 \ud655\uc778 \uc624\ub958] \ubaa9\ub85d\uc744 \uac00\uc838\uc624\uc9c0 \ubaa9\ud574\uc2f5\ub2c8\ub2e4",
            )
        sys.exit(1)

    prev_stock, saved = load_previous()

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")

    lines = [f"[\uc7ac\uace0 \ud655\uc778] {now}"]
    warnings = []
    for size, qty in current.items():
        diff = qty - prev_stock.get(size, qty)
        sign = "+" if diff > 0 else ""
        lines.append(f"- {size}: {qty}\uac1c ({sign}{diff})")
        if qty < 50:
            warnings.append(f"\u26a0\ufe0f {size}: {qty}\uac1c (50\uac1c \ubbf8\ub9cc)")

    message = "\n".join(lines)
    if warnings:
        message += "\n\n" + "\n".join(warnings)

    print(message)

    if token and chat_id:
        send_telegram(token, chat_id, message)
    else:
        print("Telegram credentials not set; skipping notification", file=sys.stderr)

    os.makedirs("data", exist_ok=True)
    saved.setdefault("history", []).append({"time": now, "stock": current})
    saved["history"] = saved["history"][-200:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
