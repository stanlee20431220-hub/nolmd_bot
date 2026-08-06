import json
import os
import re
import sys
import urllib.request
import urllib.error
from http.cookiejar import CookieJar
from datetime import datetime, timezone, timedelta

HOME_URL = "https://nolmdshop.com/"
PRODUCT_URL = "https://nolmdshop.com/product/%EB%91%90%EC%82%B0%EB%B2%A0%EC%96%B4%EC%8A%A4-%ED%82%A4%EC%A6%88-%EC%9C%A0%EB%8B%88%ED%8F%BC%EC%9B%90%EC%A0%95/1615/category/30/display/1/"
HISTORY_FILE = "data/stock_history.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "identity",
    "Connection": "keep-alive",
}


def build_opener():
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar)), jar


def fetch(opener, url, referer=None):
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="ignore")


def extract_stock(html):
    m = re.search(r"option_stock_data\s*=\s*(\{.*?\});", html, re.S)
    if not m:
        return None
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
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    opener, jar = build_opener()

    # Step 1: visit homepage first to receive session cookies, like a real browser would.
    home_status, _ = fetch(opener, HOME_URL)
    print(f"Home page status: {home_status}, cookies received: {len(jar)}")

    # Step 2: visit product page with the session cookies now attached.
    status, html = fetch(opener, PRODUCT_URL, referer=HOME_URL)
    print(f"Product page status: {status}, length: {len(html)}")

    current = extract_stock(html)

    if current is None:
        # Retry once more in case one extra hop is needed to fully establish the session.
        status2, html2 = fetch(opener, PRODUCT_URL, referer=PRODUCT_URL)
        print(f"Retry status: {status2}, length: {len(html2)}")
        current = extract_stock(html2)

    if current is None:
        snippet = html[:500].replace("\n", " ")
        print("option_stock_data NOT FOUND. Response snippet:")
        print(snippet)
        if token and chat_id:
            send_telegram(
                token,
                chat_id,
                "[\uc7ac\uace0 \ud655\uc778 \uc624\ub958] \uc0c1\ud488 \ud398\uc774\uc9c0\uc5d0\uc11c \uc7ac\uace0 \ub370\uc774\ud0a4\ub298 \ubaa8\ub976 \uc74c",
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
