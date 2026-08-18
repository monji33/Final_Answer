import json
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
from bs4 import BeautifulSoup

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


SEARCH_URLS = [
    # 浜松駅周辺・ラーメン
    (
        "https://r.gnavi.co.jp/eki/0004611/rs/"
        "?fw=%E3%83%A9%E3%83%BC%E3%83%A1%E3%83%B3&r=1000"
    ),

    # 静岡駅周辺・ラーメン
    (
        "https://r.gnavi.co.jp/eki/0004556/rs/"
        "?fw=%E3%83%A9%E3%83%BC%E3%83%A1%E3%83%B3&r=1000"
    ),

    # 掛川駅周辺・ラーメン
    (
        "https://r.gnavi.co.jp/eki/0004477/rs/"
        "?fw=%E3%83%A9%E3%83%BC%E3%83%A1%E3%83%B3&r=1000"
    ),
]


OUTPUT_FILE = "1-2.csv"
TARGET_COUNT = 50
WAIT_SECONDS = 3

COLUMNS = [
    "店舗名", "電話番号", "メールアドレス", "都道府県",
    "市区町村", "番地", "建物名", "URL", "SSL",
]

EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

STORE_URL_PATTERN = re.compile(
    r"^https://r\.gnavi\.co\.jp/"
    r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+/$"
)


def create_driver():
    options = Options()

    options.add_argument(f"user-agent={USER_AGENT}")
    options.add_argument("--window-size=1400,1000")
    options.add_argument(
        "--disable-blink-features=AutomationControlled"
    )

    service = Service("./chromedriver.exe")

    return webdriver.Chrome(
        service=service,
        options=options
    )


def normalize_store_url(href):
    """クエリ文字列を除き、店舗URLの形式を整える。"""
    absolute_url = urljoin(
    "https://r.gnavi.co.jp/",
    href
)
    
    parsed = urlparse(absolute_url)

    clean_url = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path}"
    )

    if not clean_url.endswith("/"):
        clean_url += "/"

    return clean_url


def collect_urls_on_current_page(driver):
    """現在表示中のページから店舗URLを取得する。"""
    store_urls = []

    links = driver.find_elements(By.TAG_NAME, "a")

    for link in links:
        href = link.get_attribute("href")

        if not href:
            continue

        clean_url = normalize_store_url(href)

        if STORE_URL_PATTERN.match(clean_url):
            if clean_url not in store_urls:
                store_urls.append(clean_url)

    return store_urls


def click_next_button(driver, next_page_number):
    """指定した次ページ番号のボタンをクリックする。"""

    driver.execute_script(
        "window.scrollTo(0, document.body.scrollHeight);"
    )

    time.sleep(WAIT_SECONDS)

    # 例：2ページ目なら p=2、3ページ目なら p=3
    selector = f"a[href*='p={next_page_number}']"

    try:
        next_button = WebDriverWait(
            driver,
            10
        ).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, selector)
            )
        )

        print(
            "次ページ候補:",
            next_button.get_attribute("href"),
            next_button.get_attribute("aria-label")
        )

        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});",
            next_button
        )

        time.sleep(1)

        driver.execute_script(
            "arguments[0].click();",
            next_button
        )

        return True

    except TimeoutException:
        print(
            f"{next_page_number}ページ目のボタンを"
            "見つけられませんでした。"
        )
        return False



def normalize_text(text):
    if not text:
        return ""
    text = text.replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def is_restaurant_data(item):
    if not isinstance(item, dict):
        return False
    item_type = item.get("@type", "")
    types = item_type if isinstance(item_type, list) else [item_type]
    return any(t in {"Restaurant", "LocalBusiness", "FoodEstablishment"} for t in types)


def find_restaurant_json(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if is_restaurant_data(item):
                return item
            if isinstance(item, dict):
                for graph_item in item.get("@graph", []):
                    if is_restaurant_data(graph_item):
                        return graph_item
    return {}


def split_street_address(street_address):
    street_address = normalize_text(street_address)
    if not street_address:
        return "", ""
    match = re.match(
        r"^(.+?\d+(?:[-ー‐−－]\d+)*(?:番地?|号)?)(.*)$",
        street_address,
    )
    if not match:
        return street_address, ""
    return match.group(1).strip(), match.group(2).strip()


def extract_email(soup):
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if href.lower().startswith("mailto:"):
            email = href[7:].split("?")[0].strip()
            if EMAIL_PATTERN.fullmatch(email):
                return email
    match = EMAIL_PATTERN.search(soup.get_text(" ", strip=True))
    return match.group(0) if match else ""


def is_external_url(url):
    if not url.startswith(("http://", "https://")):
        return False
    domain = urlparse(url).netloc.lower()
    excluded = ("gnavi.co.jp", "gnst.jp", "rakuten.co.jp", "facebook.com",
                "twitter.com", "x.com", "instagram.com", "youtube.com", "google.com")
    return not any(value in domain for value in excluded)


def resolve_final_url(driver, url):
    if not url:
        return ""
    original = driver.current_window_handle
    try:
        driver.switch_to.new_window("tab")
        time.sleep(WAIT_SECONDS)
        driver.get(url)
        time.sleep(WAIT_SECONDS)
        return driver.current_url
    except Exception:
        return ""
    finally:
        if len(driver.window_handles) > 1:
            driver.close()
        driver.switch_to.window(original)


def extract_official_url(driver, soup, store_url):
    keywords = ("オフィシャルページ", "お店のホームページ", "公式ホームページ", "公式サイト", "ホームページ")
    for link in soup.find_all("a", href=True):
        text = link.get_text(" ", strip=True)
        if not any(keyword in text for keyword in keywords):
            continue
        final_url = resolve_final_url(driver, urljoin(store_url, link["href"]))
        if final_url and is_external_url(final_url):
            return final_url
    return ""


def check_ssl(url):
    if not url or urlparse(url).scheme.lower() != "https":
        return False
    host = urlparse(url).hostname
    if not host:
        return False
    try:
        context = ssl.create_default_context()
        with socket.create_connection((host, 443), timeout=15) as raw_socket:
            with context.wrap_socket(raw_socket, server_hostname=host) as secure_socket:
                return bool(secure_socket.getpeercert())
    except (ssl.SSLError, OSError, TimeoutError):
        return False


def get_store_information(driver, store_url):
    time.sleep(WAIT_SECONDS)
    driver.get(store_url)
    time.sleep(WAIT_SECONDS)
    soup = BeautifulSoup(driver.page_source, "html.parser")
    data = find_restaurant_json(soup)
    address = data.get("address", {})
    if not isinstance(address, dict):
        address = {}
    block, building = split_street_address(address.get("streetAddress", ""))
    official_url = extract_official_url(driver, soup, store_url)
    return {
        "店舗名": normalize_text(data.get("name", "")),
        "電話番号": normalize_text(data.get("telephone", "")),
        "メールアドレス": extract_email(soup),
        "都道府県": normalize_text(address.get("addressRegion", "")),
        "市区町村": normalize_text(address.get("addressLocality", "")),
        "番地": block,
        "建物名": building,
        "URL": official_url,
        "SSL": check_ssl(official_url),
    }

def main():
    driver = create_driver()
    store_urls = []

    try:
        for search_number, search_url in enumerate(SEARCH_URLS, start=1):
            if len(store_urls) >= TARGET_COUNT:
                break

            print(f"\n検索条件{search_number}を開始します。")
            time.sleep(WAIT_SECONDS)
            driver.get(search_url)
            time.sleep(WAIT_SECONDS)
            page_number = 1

            while len(store_urls) < TARGET_COUNT:
                print(f"{page_number}ページ目を確認中")
                for store_url in collect_urls_on_current_page(driver):
                    if store_url not in store_urls:
                        store_urls.append(store_url)
                    if len(store_urls) >= TARGET_COUNT:
                        break

                print(f"現在の店舗URL数: {len(store_urls)}")
                if len(store_urls) >= TARGET_COUNT:
                    break

                old_url = driver.current_url
                next_page_number = page_number + 1
                if not click_next_button(driver, next_page_number):
                    print("この検索条件の最終ページです。")
                    break

                time.sleep(WAIT_SECONDS)
                try:
                    WebDriverWait(driver, 15).until(lambda browser: browser.current_url != old_url)
                except TimeoutException:
                    print("ページ移動を確認できませんでした。")
                    break
                page_number += 1

        print(f"\n取得した店舗URL数: {len(store_urls)}")
        records = []

        for index, store_url in enumerate(store_urls[:TARGET_COUNT], start=1):
            print(f"{index}/{len(store_urls[:TARGET_COUNT])}件目を取得中: {store_url}")
            try:
                record = get_store_information(driver, store_url)
                records.append(record)
                print(f"取得成功: {record['店舗名']}")
            except Exception as error:
                print(f"解析エラー: {error}")
                records.append({column: (False if column == "SSL" else "") for column in COLUMNS})

        dataframe = pd.DataFrame(records, columns=COLUMNS).head(TARGET_COUNT)
        dataframe.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
        print(f"\n{OUTPUT_FILE}を保存しました。")
        print(f"保存レコード数: {len(dataframe)}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()