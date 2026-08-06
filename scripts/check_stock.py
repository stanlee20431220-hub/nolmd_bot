import json
import os
import re
import sys
import time
import urllib.parse
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
PRODUCT_URL_RE = re.compile(r"/product/([^/]+/\d+)/")
EXCLUDE_KEYWORDS = ["마킹키트"]

def is_excluded(url):
    decoded = urllib.parse.unquote(url)
    return any(kw in decoded for kw in EXCLUDE_KEYWORDS)

def collect_product_links(page):
    links = set()
    page.mouse.move(700, 450)
    for url in CATEGORY_URLS:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(1500)

        last_count = -1
        rounds_without_growth = 0
        for _ in range(200):
            hrefs = page.eval_on_selector_all(
                'a[href*="/product/"]', "els => els.map(e => e.href)"
            )
            for h in hrefs:
                h = h.split("?")[0]
                m = PRODUCT_URL_RE.search(h)
                if not m:
                    continue
                canonical = f"https://nolmdshop.com/product/{m.group(1)}/"
                if is_excluded(canonical):
                    continue
                links.add(canonical)

            current_count = len(links)
            if current_count > last_count:
                last_count = current_count
                rounds_without_growth = 0
            else:
                rounds_without_growth += 1

            if rounds_without_growth >= 10:
                break

            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(600)

        print(f"  - {url}: {len(links)}개 누적 (카테고리별 진행)")
    return sorted(links)

def get_stock_for_product(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    data = page.evaluate(
        "() => (typeof option_stock_data !== 'undefined') ? option_stock_data : null"
    )
    raw_price = page.evaluate(
        "() => (typeof product_price !== 'undefined') ? product_price : null"
    )
    name = None
    try:
        title = page.title()
        name = title.split(" - ")[0].strip()
    except Exception:
        pass

    price = None
    if raw_price is not None:
        try:
            price = int(str(raw_price).replace(",", "").strip())
        except Exception:
            price = None

    if not data:
        return None, name, price
    if isinstance(data, str):
        data = json.loads(data)

    result = {}
    for _, v in data.items():
        result[v["option_value"]] = v["stock_number"]
    return result, name, price

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

def fmt_won(v):
    return f"{v:,}원"

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    prev_products = load_previous()
    current_products = {}

    change_blocks = []
    price_change_lines = []
    soldout_lines = []
    warning_lines = []
    error_lines = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})

        product_urls = collect_product_links(page)
        print(f"Found {len(product_urls)} products across categories (마킹키트 제외)")

        for url in product_urls:
            try:
                stock, name, price = get_stock_for_product(page, url)
            except Exception as e:
                error_lines.append(f"{url}: {e}")
                continue

            if stock is None:
                continue

            name = name or url
            current_products[url] = {"name": name, "price": price, "stock": stock}

            prev_entry = prev_products.get(url, {})
            prev_stock = prev_entry.get("stock", {})
            prev_price = prev_entry.get("price")

            option_lines = []
            for size, qty in stock.items():
                diff = qty - prev_stock.get(size, qty)
                if diff != 0:
                    sign = "+" if diff > 0 else ""
                    option_lines.append(f"  - {size}: {qty}개 ({sign}{diff})")

                if qty == 0:
                    soldout_lines.append(f"{name} - {size}")
                elif qty < LOW_STOCK_THRESHOLD:
                    warning_lines.append(f"⚠️ {name} - {size}: {qty}개")

            if option_lines:
                price_str = f" ({fmt_won(price)})" if price is not None else ""
                change_blocks.append(f"■ {name}{price_str}\n" + "\n".join(option_lines))

            if price is not None and prev_price is not None and price != prev_price:
                price_change_lines.append(
                    f"{name}: {fmt_won(prev_price)} → {fmt_won(price)}"
                )

            time.sleep(0.4)

        browser.close()

    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")

    header = (
        f"[전상품 재고 확인] {now}\n"
        f"확인된 상품: {len(current_products)}개"
    )

    messages = [header]
    if change_blocks:
        messages.append("[재고 변동]\n\n" + "\n\n".join(change_blocks))
    if price_change_lines:
        messages.append("[가격 변동]\n" + "\n".join(price_change_lines))
    if soldout_lines:
        messages.append("[품절 상품]\n" + "\n".join(soldout_lines))
    if warning_lines:
        messages.append("[50개 미만 재고 경고]\n" + "\n".join(warning_lines))
    if error_lines:
        messages.append("[오류]\n" + "\n".join(error_lines))

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
