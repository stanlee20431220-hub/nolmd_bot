import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright

CATEGORY_URLS = [
    "https://nolmdshop.com/category/%EB%91%90%EC%82%B0%EB%B2%A0%EC%96%B4%EC%8A%A4/30/",
    "https://nolmdshop.com/category/LG%ED%8A%B8%EC%9C%88%EC%8A%A4/31/",
    "https://nolmdshop.com/category/%ED%82%A4%EC%9B%80%ED%9E%88%EC%96%B4%EB%A1%9C%EC%A6%88/29/",
]

HISTORY_FILE = "data/stock_history.json"
LOW_STOCK_THRESHOLD = 50
PRODUCT_URL_RE = re.compile(r"/product/[^/]+/\d+/category/\d+/display/\d+/")


def collect_product_links(page):
    links = set()
    for url in CATEGORY_URLS:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        hrefs = page.eval_on_selector_all(
            'a[href*="/product/"]', "els => els.map(e => e.href)"
        )
        for h in hrefs:
            h = h.split("?")[0]
            if PRODUCT_URL_RE.search(h):
                links.add(h)
    return sorted(links)


def get_stock_for_product(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    data = page.evaluate(
        "() => (typeof option_stock_data !== 'undefined') ? option_stock_data : null"
    )
    name = None
    try:
        title = page.title()
        name = title.split(" - ")[0].strip()
    except Exception:
        pass

    if not data:
        return None, name
    if isinstance(data, str):
        data = json.loads(data)

    result = {}
    for _, v in data.items():
        result[v["option_value"]] = v["stock_number"]
    return result, name


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15)


def send_telegram_chunked(token, chat_id, text, limit=3500):
    if len(text) <= limit:
        send_telegram(token, chat_id, text)
        return
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > limit:
            send_telegram(token, chat_id, chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        send_telegram(token, chat_id, chunk)


def load_previous():
    if not os.path.exists(HISTORY_FILE):
        return {}
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)
    return saved.get("products", {})


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    prev_products = load_previous()
    current_products = {}
    change_lines = []
    warning_lines = []
    error_lines = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        product_urls = collect_product_links(page)
        print(f"Found {len(product_urls)} products across categories")

        for url in product_urls:
            try:
                stock, name = get_stock_for_product(page, url)
            except Exception as e:
                error_lines.append(f"{url}: {e}")
                continue

            if stock is None:
                continue

            name = name or url
            current_products[url] = {"name": name, "stock": stock}

            prev_stock = prev_products.get(url, {}).get("stock", {})
            for size, qty in stock.items():
                diff = qty - prev_stock.get(size, qty)
                if diff != 0:
                    sign = "+" if diff > 0 else ""
                    change_lines.append(f"{name} - {size}: {qty}\uac1c ({sign}{diff})")
                if qty < LOW_STOCK_THRESHOLD:
                    warning_lines.append(f"\u26a0\ufe0f {name} - {size}: {qty}\uac1c")

            time.sleep(0.4)

        browser.close()

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")

    header = (
        f"[\uc804\uc0c1\ud488 \uc7ac\uace0 \ud655\uc778] {now}\n"
        f"\ud655\uc778\ub41c \uc0c1\ud488: {len(current_products)}\uac1c"
    )

    messages = [header]
    if change_lines:
        messages.append("[\uc7ac\uace0 \ubcc0\ub3d9]\n" + "\n".join(change_lines))
    if warning_lines:
        messages.append("[50\uac1c \ubbf8\ub9cc \uc7ac\uace0 \uacbd\uace0]\n" + "\n".join(warning_lines))
    if error_lines:
        messages.append("[\uc624\ub958]\n" + "\n".join(error_lines))

    full_message = "\n\n".join(messages)
    print(full_message)

    if token and chat_id:
        send_telegram_chunked(token, chat_id, full_message)
    else:
        print("Telegram credentials not set; skipping notification", file=sys.stderr)

    os.makedirs("data", exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"last_checked": now, "products": current_products},
            f,
            ensure_ascii=False,
            indent=2,
        )


if __name__ == "__main__":
    main()
