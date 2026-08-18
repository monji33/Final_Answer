import json
import re
import ssl
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from sqlalchemy import create_engine

# =========================================================
# 設定
# =========================================================

SEARCH_URLS = [
    # 浜松駅周辺
    "https://r.gnavi.co.jp/eki/0004611/rs/?r=1000",

    # 静岡駅周辺
    "https://r.gnavi.co.jp/eki/0004556/rs/?r=1000",

    # 掛川駅周辺
    "https://r.gnavi.co.jp/eki/0004477/rs/?r=1000",
]

DATABASE_URL = "mysql+pymysql://user:password@mysql:3306/ex2?charset=utf8mb4"
TABLE_NAME = "ex2_2"
TARGET_COUNT = 50
WAIT_SECONDS = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    )
}

COLUMNS = [
    "店舗名",
    "電話番号",
    "メールアドレス",
    "都道府県",
    "市区町村",
    "番地",
    "建物名",
    "URL",
    "SSL",
]

# ぐるなびの個別店舗URL
STORE_URL_PATTERN = re.compile(
    r"^https://r\.gnavi\.co\.jp/(?=[A-Za-z0-9]*\d)[A-Za-z0-9]+/$"
)

# メールアドレス
EMAIL_PATTERN = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)


# =========================================================
# HTTP取得
# =========================================================

def request_page(session, url, allow_redirects=True):
    """
    リクエスト前に3秒待機してページを取得する。
    """
    time.sleep(WAIT_SECONDS)

    response = session.get(
        url,
        headers=HEADERS,
        timeout=30,
        allow_redirects=allow_redirects,
    )

    response.raise_for_status()

    # 日本語の文字化け対策
    if response.encoding is None or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding

    return response


def get_soup(session, url):
    """
    URLからBeautifulSoupオブジェクトを作る。
    """
    response = request_page(session, url)

    return BeautifulSoup(
        response.text,
        "html.parser"
    )


# =========================================================
# 店舗URL取得
# =========================================================

def normalize_store_url(href, base_url):
    """
    相対URLを絶対URLに変換し、クエリ文字列を削除する。
    """
    absolute_url = urljoin(base_url, href)

    parsed = urlparse(absolute_url)

    clean_url = (
        f"{parsed.scheme}://"
        f"{parsed.netloc}"
        f"{parsed.path}"
    )

    if not clean_url.endswith("/"):
        clean_url += "/"

    return clean_url


def extract_store_urls(soup, page_url):
    """
    検索結果ページから個別店舗URLだけを取得する。
    """
    store_urls = []

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()

        if not href:
            continue

        clean_url = normalize_store_url(
            href,
            page_url
        )

        if STORE_URL_PATTERN.match(clean_url):
            if clean_url not in store_urls:
                store_urls.append(clean_url)

    return store_urls


def find_next_page_url(soup, current_url):
    """
    検索結果ページから次ページのURLを取得する。
    """

    # rel="next"がある場合
    next_link = soup.find(
        "a",
        attrs={"rel": lambda value: value and "next" in value}
    )

    if next_link and next_link.get("href"):
        return urljoin(
            current_url,
            next_link["href"]
        )

    # 「>」「次へ」などのリンクを探す
    next_text_candidates = {
        ">",
        "＞",
        "次へ",
        "次のページ",
    }

    for link in soup.find_all("a", href=True):
        text = link.get_text(
            " ",
            strip=True
        )

        aria_label = link.get(
            "aria-label",
            ""
        ).strip()

        title = link.get(
            "title",
            ""
        ).strip()

        if (
            text in next_text_candidates
            or "次へ" in aria_label
            or "次のページ" in aria_label
            or "次へ" in title
            or "次のページ" in title
        ):
            next_url = urljoin(
                current_url,
                link["href"]
            )

            if next_url != current_url:
                return next_url

    # URLやクラス名にnextが含まれるリンクを探す
    for link in soup.find_all("a", href=True):
        classes = " ".join(
            link.get("class", [])
        ).lower()

        href = link.get(
            "href",
            ""
        )

        if "next" in classes or "next" in href.lower():
            next_url = urljoin(
                current_url,
                href
            )

            if next_url != current_url:
                return next_url

    return ""


def collect_store_urls(session):
    """
    複数の検索結果ページから、
    重複しない店舗URLを50件集める。
    """
    store_urls = []

    for search_url in SEARCH_URLS:
        if len(store_urls) >= TARGET_COUNT:
            break

        print(f"一覧ページを取得中: {search_url}")

        try:
            soup = get_soup(session, search_url)

        except requests.RequestException as error:
            print(f"一覧ページ取得エラー: {error}")
            continue

        page_store_urls = extract_store_urls(
            soup,
            search_url
        )

        print(
            f"このページで見つかった店舗数: "
            f"{len(page_store_urls)}"
        )

        for store_url in page_store_urls:
            if store_url not in store_urls:
                store_urls.append(store_url)

            if len(store_urls) >= TARGET_COUNT:
                break

        print(
            f"現在の合計店舗URL数: "
            f"{len(store_urls)}"
        )

    
    return store_urls[:TARGET_COUNT]


# =========================================================
# JSON-LD解析
# =========================================================

def is_restaurant_data(item):
    """
    JSON-LDのデータが店舗情報か判定する。
    """
    if not isinstance(item, dict):
        return False

    item_type = item.get("@type", "")

    if isinstance(item_type, list):
        types = item_type
    else:
        types = [item_type]

    target_types = {
        "Restaurant",
        "LocalBusiness",
        "FoodEstablishment",
    }

    return any(
        item_type in target_types
        for item_type in types
    )


def find_restaurant_json(soup):
    """
    application/ld+jsonから店舗データを取得する。
    """
    scripts = soup.find_all(
        "script",
        type="application/ld+json"
    )

    for script in scripts:
        raw_json = script.string

        if not raw_json:
            raw_json = script.get_text(
                strip=True
            )

        if not raw_json:
            continue

        try:
            json_data = json.loads(raw_json)

        except (
            json.JSONDecodeError,
            TypeError
        ):
            continue

        if isinstance(json_data, list):
            items = json_data
        else:
            items = [json_data]

        for item in items:
            if is_restaurant_data(item):
                return item

            if isinstance(item, dict):
                graph_items = item.get(
                    "@graph",
                    []
                )

                if isinstance(graph_items, list):
                    for graph_item in graph_items:
                        if is_restaurant_data(
                            graph_item
                        ):
                            return graph_item

    return {}


# =========================================================
# 住所処理
# =========================================================

def normalize_address_text(text):
    """
    全角スペースや改行を整理する。
    """
    if not text:
        return ""

    text = text.replace(
        "\u3000",
        " "
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


def split_street_address(street_address):
    """
    streetAddressを番地と建物名に分割する。

    例：
    砂山町322-6一兆ビル2F
    ↓
    番地：砂山町322-6
    建物名：一兆ビル2F
    """
    street_address = normalize_address_text(
        street_address
    )

    if not street_address:
        return "", ""

    pattern = re.compile(
        r"^(.+?"
        r"\d+"
        r"(?:[-ー‐−－]\d+)*"
        r"(?:番地?|号)?)"
        r"(.*)$"
    )

    match = pattern.match(
        street_address
    )

    if match:
        block_number = match.group(
            1
        ).strip()

        building_name = match.group(
            2
        ).strip()

        return block_number, building_name

    return street_address, ""


# =========================================================
# メールアドレス取得
# =========================================================

def extract_email(soup):
    """
    HTML内に直接記載されたメールアドレスを取得する。
    無ければ空欄。
    """
    # mailtoリンクを優先
    for link in soup.find_all(
        "a",
        href=True
    ):
        href = link.get(
            "href",
            ""
        ).strip()

        if href.lower().startswith(
            "mailto:"
        ):
            email = href[7:].split(
                "?"
            )[0].strip()

            if EMAIL_PATTERN.fullmatch(
                email
            ):
                return email

    # HTML全体から検索
    html_text = soup.get_text(
        " ",
        strip=True
    )

    match = EMAIL_PATTERN.search(
        html_text
    )

    if match:
        return match.group(0)

    return ""


# =========================================================
# 公式ホームページ取得
# =========================================================

def is_external_url(url):
    """
    ぐるなび以外の外部URLか判定する。
    """
    if not url.startswith(
        ("http://", "https://")
    ):
        return False

    domain = urlparse(
        url
    ).netloc.lower()

    excluded_domains = (
        "gnavi.co.jp",
        "gnst.jp",
        "rakuten.co.jp",
        "facebook.com",
        "twitter.com",
        "x.com",
        "instagram.com",
        "youtube.com",
        "google.com",
    )

    return not any(
        excluded in domain
        for excluded in excluded_domains
    )


def resolve_final_url(session, url):
    """
    実際にアクセスし、リダイレクト後のURLを取得する。
    """
    if not url:
        return ""

    try:
        response = request_page(
            session,
            url,
            allow_redirects=True
        )

        return response.url

    except requests.RequestException:
        return ""


def extract_official_url(session, soup):
    """
    「オフィシャルページ」
    「お店のホームページ」などのURLを取得する。
    """
    keywords = (
        "オフィシャルページ",
        "お店のホームページ",
        "公式ホームページ",
        "公式サイト",
        "ホームページ",
    )

    # まずリンク文字から探す
    for link in soup.find_all(
        "a",
        href=True
    ):
        link_text = link.get_text(
            " ",
            strip=True
        )

        href = link.get(
            "href",
            ""
        ).strip()

        if not any(
            keyword in link_text
            for keyword in keywords
        ):
            continue

        absolute_url = urljoin(
        "https://r.gnavi.co.jp/",
        href
        )
        

        # ぐるなびのリダイレクトリンクの場合でも
        # requestsで最終URLを取得する
        final_url = resolve_final_url(
            session,
            absolute_url
        )

        if (
            final_url
            and is_external_url(final_url)
        ):
            return final_url

    # 「店舗情報」テーブル付近から外部リンクを探す
    labels = soup.find_all(
        string=re.compile(
            r"オフィシャル|"
            r"ホームページ|"
            r"公式サイト"
        )
    )

    for label in labels:
        parent = label.parent

        if parent is None:
            continue

        container = parent.find_parent(
            ["tr", "dl", "div", "li"]
        )

        if container is None:
            continue

        link = container.find(
            "a",
            href=True
        )

        if link is None:
            continue

        absolute_url = urljoin(
        "https://r.gnavi.co.jp/",
        link["href"]
        )
    

        final_url = resolve_final_url(
            session,
            absolute_url
        )

        if (
            final_url
            and is_external_url(final_url)
        ):
            return final_url

    return ""


# =========================================================
# SSL判定
# =========================================================

def check_ssl(url):
    """
    URLのSSL証明書の有無を判定する。

    httpsで証明書検証が成功した場合はTrue。
    それ以外はFalse。
    """
    if not url:
        return False

    parsed = urlparse(url)

    if parsed.scheme.lower() != "https":
        return False

    hostname = parsed.hostname

    if not hostname:
        return False

    port = parsed.port or 443

    try:
        context = ssl.create_default_context()

        with context.wrap_socket(
            __import__("socket").socket(),
            server_hostname=hostname
        ) as secure_socket:

            secure_socket.settimeout(15)

            secure_socket.connect(
                (hostname, port)
            )

            certificate = (
                secure_socket.getpeercert()
            )

            return bool(certificate)

    except (
        ssl.SSLError,
        OSError,
        TimeoutError
    ):
        return False


# =========================================================
# 1店舗分の情報取得
# =========================================================

def get_store_information(
    session,
    store_url
):
    """
    1店舗分の情報を取得する。
    """
    soup = get_soup(
        session,
        store_url
    )

    restaurant_data = find_restaurant_json(
        soup
    )

    address = restaurant_data.get(
        "address",
        {}
    )

    if not isinstance(
        address,
        dict
    ):
        address = {}

    store_name = normalize_address_text(
        restaurant_data.get(
            "name",
            ""
        )
    )

    telephone = normalize_address_text(
        restaurant_data.get(
            "telephone",
            ""
        )
    )

    prefecture = normalize_address_text(
        address.get(
            "addressRegion",
            ""
        )
    )

    city = normalize_address_text(
        address.get(
            "addressLocality",
            ""
        )
    )

    street_address = normalize_address_text(
        address.get(
            "streetAddress",
            ""
        )
    )

    block_number, building_name = (
        split_street_address(
            street_address
        )
    )

    email = extract_email(
        soup
    )

    official_url = extract_official_url(
        session,
        soup
    )

    ssl_result = check_ssl(
        official_url
    )

    return {
        "店舗名": store_name,
        "電話番号": telephone,
        "メールアドレス": email,
        "都道府県": prefecture,
        "市区町村": city,
        "番地": block_number,
        "建物名": building_name,
        "URL": official_url,
        "SSL": ssl_result,
    }


# =========================================================
# メイン処理
# =========================================================

def main():
    session = requests.Session()
    session.headers.update(HEADERS)

    print(
        "店舗URLを収集します。"
    )

    store_urls = collect_store_urls(
        session
    )

    print(
        f"取得した店舗URL数: {len(store_urls)}"
    )

    if len(store_urls) < TARGET_COUNT:
        print(
            "警告：50店舗分のURLを取得できませんでした。"
        )

    records = []

    for index, store_url in enumerate(
        store_urls,
        start=1
    ):
        print(
            f"{index}/{len(store_urls)}件目を取得中: "
            f"{store_url}"
        )

        try:
            store_information = (
                get_store_information(
                    session,
                    store_url
                )
            )

            records.append(
                store_information
            )

            print(
                f"取得成功: "
                f"{store_information['店舗名']}"
            )

        except requests.RequestException as error:
            print(
                f"通信エラー: {error}"
            )

            records.append({
                "店舗名": "",
                "電話番号": "",
                "メールアドレス": "",
                "都道府県": "",
                "市区町村": "",
                "番地": "",
                "建物名": "",
                "URL": "",
                "SSL": False,
            })

        except Exception as error:
            print(
                f"解析エラー: {error}"
            )

            records.append({
                "店舗名": "",
                "電話番号": "",
                "メールアドレス": "",
                "都道府県": "",
                "市区町村": "",
                "番地": "",
                "建物名": "",
                "URL": "",
                "SSL": False,
            })

    dataframe = pd.DataFrame(
        records,
        columns=COLUMNS
    )

    # 最大50件
    dataframe = dataframe.head(
        TARGET_COUNT
    )

engine = create_engine(DATABASE_URL)

dataframe.to_sql(
    TABLE_NAME,
    con=engine,
    if_exists="replace",
    index=False
)

print()
print(
    f"MySQLの{TABLE_NAME}テーブルに保存しました。"
)
print(
    f"保存レコード数: {len(dataframe)}"
)

if __name__ == "__main__":
    main()