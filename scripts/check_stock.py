"""
카페24 상품 재고 모니터링 스크립트
- 옵션 없는 단일상품 전용 (페이지 소스의 stock_number 변수를 그대로 읽음)
- products.json에 등록된 상품들을 순회하며 재고를 조회
- 이전 상태(state.json)와 비교해서 변동 있으면 텔레그램 알림
"""

import json
import os
import re
import sys
import time
import requests

PRODUCTS_FILE = "products.json"
STATE_FILE = "state.json"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_stock(url):
    """상품 페이지 HTML에서 재고/옵션여부/상품명을 추출"""
    res = requests.get(url, headers=HEADERS, timeout=15)
    res.raise_for_status()
    html = res.text

    has_option_match = re.search(r"var\s+has_option\s*=\s*'([TF])'", html)
    stock_match = re.search(r"var\s+stock_number\s*=\s*'(\d+)'", html)
    name_match = re.search(r"var\s+product_name\s*=\s*'([^']*)'", html)

    return {
        "has_option": has_option_match.group(1) if has_option_match else None,
        "stock_number": int(stock_match.group(1)) if stock_match else None,
        "product_name": name_match.group(1) if name_match else None,
    }


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[경고] 텔레그램 토큰/채팅ID 미설정 - 알림 생략")
        print(message)
        return
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(api_url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    except Exception as e:
        print(f"[텔레그램 전송 실패] {e}")


def main():
    products = load_json(PRODUCTS_FILE, [])
    prev_state = load_json(STATE_FILE, {})
    new_state = {}

    if not products:
        print("products.json에 등록된 상품이 없습니다.")
        sys.exit(0)

    for product in products:
        name_hint = product.get("name", "")
        url = product["url"]

        try:
            info = fetch_stock(url)
        except Exception as e:
            print(f"[에러] {name_hint} 조회 실패: {e}")
            continue

        if info["has_option"] == "T":
            print(f"[알림] {name_hint} 는 옵션이 있는 상품이라 이 방식으로 재고 확인이 안 됩니다. (건너뜀)")
            continue

        stock = info["stock_number"]
        product_name = info["product_name"] or name_hint
        key = url

        print(f"{product_name}: 재고 {stock}")

        new_state[key] = {"stock": stock, "product_name": product_name}

        prev_stock = prev_state.get(key, {}).get("stock")

        # 최초 실행 -> 알림 없이 기록만
        if prev_stock is None:
            continue

        if stock != prev_stock:
            if prev_stock == 0 and stock and stock > 0:
                send_telegram(f"🟢 재입고!\n{product_name}\n재고: {stock}개\n{url}")
            elif stock == 0:
                send_telegram(f"🔴 품절\n{product_name}\n{url}")
            else:
                send_telegram(f"⚪ 재고 변동\n{product_name}\n{prev_stock}개 → {stock}개\n{url}")

        time.sleep(1)  # 요청 간 텀

    save_json(STATE_FILE, new_state)


if __name__ == "__main__":
    main()
