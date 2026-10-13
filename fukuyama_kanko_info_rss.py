import os
import re
import time
import hashlib
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urljoin, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup


SOURCE_URL = "https://www.fukuyama-kanko.com/information/"
OUTPUT_FILE = "fukuyama_kanko_info.xml"

JST = timezone(timedelta(hours=9))

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/154.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

DATE_PATTERN = re.compile(
    r"^(20\d{2})\.(\d{2})\.(\d{2})$"
)


def normalize_text(text):
    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def fetch_page(url):
    last_error = None

    for attempt in range(1, 4):
        try:
            print(
                f"取得 {attempt}/3:",
                url
            )

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=30
            )

            print(
                "HTTP:",
                response.status_code
            )

            response.raise_for_status()

            if len(response.content) < 3000:
                raise RuntimeError(
                    "HTMLが異常に短いため取得を中止します"
                )

            return response.content

        except Exception as e:
            last_error = e

            print(
                "取得失敗:",
                repr(e)
            )

            if attempt < 3:
                print(
                    "10秒待って再試行します"
                )

                time.sleep(10)

    raise RuntimeError(
        f"3回とも取得に失敗しました: {last_error}"
    )


def parse_date(text):
    text = normalize_text(text)

    match = DATE_PATTERN.fullmatch(
        text
    )

    if not match:
        return None

    return datetime(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        0,
        0,
        0,
        tzinfo=JST
    )


def canonicalize_link(href):
    link = urljoin(
        SOURCE_URL,
        href
    )

    parsed = urlparse(
        link
    )

    query = parse_qs(
        parsed.query
    )

    article_id = query.get(
        "id",
        [""]
    )[0]

    if (
        parsed.netloc == "www.fukuyama-kanko.com"
        and parsed.path == "/information/detail.php"
        and article_id.isdigit()
    ):
        return (
            "https://www.fukuyama-kanko.com"
            "/information/detail.php?id="
            + article_id
        )

    return link


def make_guid(link):
    parsed = urlparse(
        link
    )

    query = parse_qs(
        parsed.query
    )

    article_id = query.get(
        "id",
        [""]
    )[0]

    if article_id.isdigit():
        return (
            "fukuyama-kanko-information-"
            + article_id
        )

    return hashlib.sha256(
        (
            "fukuyama-kanko-information|"
            + link
        ).encode(
            "utf-8"
        )
    ).hexdigest()


def get_last_page(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    pages = [1]

    for a in soup.find_all(
        "a",
        href=True
    ):
        href = a.get(
            "href",
            ""
        )

        match = re.search(
            r"[?&]page=(\d+)",
            href
        )

        if not match:
            continue

        try:
            page = int(
                match.group(1)
            )

            if page >= 1:
                pages.append(
                    page
                )

        except ValueError:
            continue

    return max(
        pages
    )


def extract_article(a):
    href = normalize_text(
        a.get(
            "href",
            ""
        )
    )

    if not href:
        return None

    link = canonicalize_link(
        href
    )

    parsed = urlparse(
        link
    )

    if (
        parsed.netloc != "www.fukuyama-kanko.com"
        or parsed.path != "/information/detail.php"
    ):
        return None

    query = parse_qs(
        parsed.query
    )

    article_id = query.get(
        "id",
        [""]
    )[0]

    if not article_id.isdigit():
        return None

    dl = a.find(
        "dl"
    )

    if dl is None:
        return None

    date_span = dl.select_one(
        "dt span.date"
    )

    tag_span = dl.select_one(
        "dt span.tag"
    )

    title_dd = dl.find(
        "dd"
    )

    if date_span is None:
        return None

    if title_dd is None:
        return None

    date_text = normalize_text(
        date_span.get_text(
            " ",
            strip=True
        )
    )

    dt = parse_date(
        date_text
    )

    if dt is None:
        return None

    title = normalize_text(
        title_dd.get_text(
            " ",
            strip=True
        )
    )

    if not title:
        return None

    category = ""

    if tag_span is not None:
        category = normalize_text(
            tag_span.get_text(
                " ",
                strip=True
            )
        )

    description_parts = []

    if category:
        description_parts.append(
            "カテゴリー: "
            + category
        )

    description_parts.append(
        "掲載日: "
        + dt.strftime(
            "%Y.%m.%d"
        )
    )

    return {
        "title": title,
        "link": link,
        "guid": make_guid(
            link
        ),
        "description": " / ".join(
            description_parts
        ),
        "pubDate": format_datetime(
            dt
        ),
        "_datetime": dt,
        "_article_id": int(
            article_id
        ),
    }


def parse_articles(html):
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    info_list = soup.find(
        "div",
        class_="info_list"
    )

    if info_list is None:
        raise RuntimeError(
            "div.info_list が見つかりません"
        )

    article_links = info_list.select(
        "a.disp_b"
    )

    print(
        "記事候補:",
        len(article_links)
    )

    items = []
    seen = set()

    for a in article_links:
        item = extract_article(
            a
        )

        if item is None:
            continue

        guid = item[
            "guid"
        ]

        if guid in seen:
            continue

        seen.add(
            guid
        )

        items.append(
            item
        )

    return items


def load_existing_items():
    items = {}

    if not os.path.exists(
        OUTPUT_FILE
    ):
        print(
            "既存RSS件数: 0"
        )

        return items

    try:
        tree = ET.parse(
            OUTPUT_FILE
        )

        root = tree.getroot()

        for item in root.findall(
            "./channel/item"
        ):
            guid = normalize_text(
                item.findtext(
                    "guid"
                )
            )

            if not guid:
                continue

            pub_date = normalize_text(
                item.findtext(
                    "pubDate"
                )
            )

            try:
                dt = parsedate_to_datetime(
                    pub_date
                )

                if dt.tzinfo is None:
                    dt = dt.replace(
                        tzinfo=JST
                    )

            except Exception:
                dt = datetime.min.replace(
                    tzinfo=timezone.utc
                )

            link = (
                item.findtext(
                    "link"
                )
                or ""
            )

            article_id = 0

            try:
                parsed = urlparse(
                    link
                )

                query = parse_qs(
                    parsed.query
                )

                value = query.get(
                    "id",
                    ["0"]
                )[0]

                if value.isdigit():
                    article_id = int(
                        value
                    )

            except Exception:
                article_id = 0

            items[guid] = {
                "title": (
                    item.findtext(
                        "title"
                    )
                    or ""
                ),
                "link": link,
                "guid": guid,
                "description": (
                    item.findtext(
                        "description"
                    )
                    or ""
                ),
                "pubDate": pub_date,
                "_datetime": dt,
                "_article_id": article_id,
            }

        print(
            "既存RSS件数:",
            len(items)
        )

    except Exception as e:
        print(
            "既存RSS読み込み失敗:",
            repr(e)
        )

    return items


def build_rss(items):
    rss = ET.Element(
        "rss",
        {
            "version": "2.0"
        }
    )

    channel = ET.SubElement(
        rss,
        "channel"
    )

    ET.SubElement(
        channel,
        "title"
    ).text = (
        "福山観光コンベンション協会 新着情報"
    )

    ET.SubElement(
        channel,
        "link"
    ).text = SOURCE_URL

    ET.SubElement(
        channel,
        "description"
    ).text = (
        "福山観光コンベンション協会公式サイト"
        "「新着情報」の全カテゴリーを配信する非公式RSS"
    )

    ET.SubElement(
        channel,
        "language"
    ).text = "ja"

    ET.SubElement(
        channel,
        "lastBuildDate"
    ).text = format_datetime(
        datetime.now(
            timezone.utc
        )
    )

    for data in items:
        item = ET.SubElement(
            channel,
            "item"
        )

        ET.SubElement(
            item,
            "title"
        ).text = data[
            "title"
        ]

        ET.SubElement(
            item,
            "link"
        ).text = data[
            "link"
        ]

        guid = ET.SubElement(
            item,
            "guid",
            {
                "isPermaLink": "false"
            }
        )

        guid.text = data[
            "guid"
        ]

        ET.SubElement(
            item,
            "description"
        ).text = data[
            "description"
        ]

        ET.SubElement(
            item,
            "pubDate"
        ).text = data[
            "pubDate"
        ]

    tree = ET.ElementTree(
        rss
    )

    ET.indent(
        tree,
        space="  "
    )

    tree.write(
        OUTPUT_FILE,
        encoding="utf-8",
        xml_declaration=True
    )


def main():
    print(
        "=" * 70
    )

    print(
        "福山観光コンベンション協会 新着情報 RSS"
    )

    print(
        "=" * 70
    )

    existing = load_existing_items()

    try:
        first_html = fetch_page(
            SOURCE_URL
        )

        last_page = get_last_page(
            first_html
        )

        print(
            "検出ページ数:",
            last_page
        )

        if last_page < 1:
            raise RuntimeError(
                "ページ数を取得できませんでした"
            )

        if last_page > 100:
            raise RuntimeError(
                "ページ数が異常なため更新を中止します"
            )

        current_items = []
        seen_current = set()

        for page in range(
            1,
            last_page + 1
        ):
            if page == 1:
                html = first_html

            else:
                page_url = (
                    SOURCE_URL
                    + "?page="
                    + str(page)
                )

                html = fetch_page(
                    page_url
                )

            page_items = parse_articles(
                html
            )

            print(
                f"ページ{page}:",
                len(page_items),
                "件"
            )

            if (
                page == 1
                and len(page_items) < 10
            ):
                raise RuntimeError(
                    "1ページ目の記事取得数が"
                    "異常に少ないため更新を中止します"
                )

            for item in page_items:
                guid = item[
                    "guid"
                ]

                if guid in seen_current:
                    continue

                seen_current.add(
                    guid
                )

                current_items.append(
                    item
                )

        print(
            "今回取得記事数:",
            len(current_items)
        )

        if len(current_items) < 20:
            raise RuntimeError(
                "記事取得数が20件未満のため"
                "更新を中止します"
            )

        merged = dict(
            existing
        )

        new_count = 0

        for item in current_items:
            guid = item[
                "guid"
            ]

            if guid not in merged:
                new_count += 1

            merged[
                guid
            ] = item

        items = list(
            merged.values()
        )

        items.sort(
            key=lambda x: (
                x["_datetime"],
                x["_article_id"]
            ),
            reverse=True
        )

        print(
            "今回の新規記事:",
            new_count,
            "件"
        )

        print(
            "RSS保存件数:",
            len(items)
        )

        print()
        print(
            "上位20件"
        )

        for number, item in enumerate(
            items[:20],
            start=1
        ):
            print(
                f"{number:2}. "
                f"{item['pubDate']} | "
                f"{item['title']} | "
                f"{item['link']}"
            )

        build_rss(
            items
        )

        print()
        print(
            "RSS作成成功"
        )

        print(
            "保存先:",
            os.path.abspath(
                OUTPUT_FILE
            )
        )

    except Exception as e:
        print()
        print(
            "エラー:",
            repr(e)
        )

        print(
            "既存RSSは変更しません"
        )

        raise


if __name__ == "__main__":
    main()