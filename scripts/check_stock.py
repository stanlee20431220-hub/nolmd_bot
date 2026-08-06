import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

PRODUCT_URL = "https://nolmdshop.com/product/%EB%91%90%EC%82%B0%EB%B2%A0%EC%96%B4%EC%8A%A4-%ED%82%A4%EC%A6%88-%EC%9C%A0%EB%8B%88%ED%8F%BC%EC%9B%90%EC%A0%95/1615/category/30/display/1/"
HISTORY_FILE = "data/stock_history.json"


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def extract_stock(html):
    m = re.search(r"option_stock_data\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        raise RuntimeError("option_stock_data not found on page")
    data = json.loads(m.group(1))
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
    html = fetch_html(PRODUCT_URL)
    current = extract_stock(html)
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

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
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
