#!/usr/bin/env python3
"""
GIA LAI TRAFFIC ACCIDENT RADAR (TNGT)
Automated Web Scraping & Google Groups Email Alert Pipeline
"""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import os
import re
import smtplib
import ssl
import sys
import unicodedata
import urllib.parse
import warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

# Configure UTF-8 output for Windows & Linux consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

warnings.simplefilter("ignore", InsecureRequestWarning)

# ==============================================================================
# 1. CORE OPERATIONAL PARAMETERS
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_FILE = BASE_DIR / "data" / "history.json"
MAX_HISTORY_URLS = 500
FRESHNESS_HOURS = 48
VN_TZ = timezone(timedelta(hours=7))

DEFAULT_SENDER = "leememory292@gmail.com"
DEFAULT_TARGET_EMAIL = "tngt@googlegroups.com"
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
}

# ==============================================================================
# 2. TARGET ROUTES & TWO-TIER FILTERING LOGIC
# ==============================================================================

# Tier 1: Incident Keywords (Từ khóa biến cố TNGT)
TIER1_INCIDENT_KEYWORDS: list[str] = [
    "tai nạn giao thông",
    "xảy ra tai nạn",
    "tai nạn",
    "tông nhau",
    "va chạm",
    "lật xe",
    "tử vong",
    "bị thương",
    "chết",
    "hiện trường",
    "xe máy đối đầu",
    "ô tô đâm",
]

# Tier 2A: Designated Routes (Tuyến đường bắt buộc theo dõi)
# Mapping canonical route label -> list of keyword variations
TIER2A_ROUTE_GROUPS: dict[str, list[str]] = {
    "QL19": ["ql19", "ql 19", "quốc lộ 19"],
    "QL19D": ["ql19d", "ql 19d", "quốc lộ 19d"],
    "Đường Hồ Chí Minh (QL14)": ["đường hồ chí minh", "ql14", "ql 14", "quốc lộ 14"],
    "Trường Sơn Đông": ["trường sơn đông"],
    "QL25": ["ql25", "ql 25", "quốc lộ 25"],
    "Đường tránh Pleiku": ["đường tránh pleiku", "tuyến tránh pleiku"],
    "Đường tránh Chư Sê": ["đường tránh chư sê", "tuyến tránh chư sê"],
    "ĐT662": ["đt662", "đt 662", "tỉnh lộ 662", "662b"],
    "ĐT663": ["đt663", "đt 663", "tỉnh lộ 663"],
    "ĐT664": ["đt664", "đt 664", "tỉnh lộ 664"],
    "ĐT665": ["đt665", "đt 665", "tỉnh lộ 665"],
    "ĐT666": ["đt666", "đt 666", "tỉnh lộ 666"],
    "ĐT667": ["đt667", "đt 667", "tỉnh lộ 667"],
    "ĐT668": ["đt668", "đt 668", "tỉnh lộ 668"],
    "ĐT670": ["đt670", "đt 670", "tỉnh lộ 670"],
}

# Flat list of all Tier 2A route keywords (matching specification)
TIER2A_ROUTES: list[str] = [
    "QL19", "QL 19", "Quốc lộ 19",
    "Đường Hồ Chí Minh", "QL14", "QL 14",
    "Trường Sơn Đông", "Trường Sơn đông",
    "QL25", "QL 25", "Quốc lộ 25",
    "QL19D", "QL 19D",
    "đường tránh Pleiku", "tuyến tránh Pleiku",
    "đường tránh Chư Sê", "tuyến tránh Chư Sê",
    "ĐT662", "ĐT 662", "662B", "662b",
    "ĐT663", "ĐT 663", "tỉnh lộ 663",
    "ĐT664", "ĐT 664", "tỉnh lộ 664",
    "ĐT665", "ĐT 665", "tỉnh lộ 665",
    "ĐT666", "ĐT 666", "tỉnh lộ 666",
    "ĐT667", "ĐT 667", "tỉnh lộ 667",
    "ĐT670", "ĐT 670", "tỉnh lộ 670",
    "ĐT668", "ĐT 668", "tỉnh lộ 668",
]

# Tier 2B: Local Gia Lai Locality Anchors
TIER2B_LOCALITIES: list[str] = [
    "Pleiku",
    "Chư Sê",
    "Chư Păh",
    "Đắk Đoa",
    "Đak Đoa",
    "Mang Yang",
    "An Khê",
    "Ia Grai",
    "Chư Prông",
    "Đức Cơ",
    "Kbang",
    "Kông Chro",
    "Krông Pa",
    "Ayun Pa",
    "Phú Thiện",
    "Ia Pa",
    "Chư Pưh",
    "Gia Lai",
]


@dataclass
class Article:
    title: str
    url: str
    source: str
    published_at: datetime | None = None
    published_str: str = ""
    snippet: str = ""
    matched_tier1: list[str] = field(default_factory=list)
    matched_routes: list[str] = field(default_factory=list)
    matched_localities: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)


# ==============================================================================
# 3. TEXT NORMALIZATION & TWO-TIER KEYWORD MATCHER
# ==============================================================================

def normalize_text(text: str) -> str:
    """Normalize Vietnamese text to NFC and collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def contains_keyword(normalized_lower_text: str, keyword: str) -> bool:
    """Check if keyword appears in text with word boundaries."""
    kw = unicodedata.normalize("NFC", keyword).lower().strip()
    if not kw:
        return False
    pattern = r"(?<![\w])" + re.escape(kw) + r"(?![\w])"
    return bool(re.search(pattern, normalized_lower_text))


def slugify_hashtag(label: str) -> str:
    """Convert Vietnamese route/locality name to ASCII hashtag (e.g. #DuongHoChiMinh, #QL19)."""
    special_map = {
        "Đường Hồ Chí Minh": "#DuongHoChiMinh",
        "Đường Hồ Chí Minh (QL14)": "#DuongHoChiMinh",
        "Trường Sơn Đông": "#TruongSonDong",
        "Trường Sơn đông": "#TruongSonDong",
        "đường tránh Pleiku": "#DuongTranhPleiku",
        "tuyến tránh Pleiku": "#TuyenTranhPleiku",
        "đường tránh Chư Sê": "#DuongTranhChuSe",
        "tuyến tránh Chư Sê": "#TuyenTranhChuSe",
    }
    if label in special_map:
        return special_map[label]

    text = label.replace("Đ", "D").replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    # Convert tỉnh lộ -> TinhLo or keep route prefixes (QL, DT) uppercase
    words = re.findall(r"[A-Za-z0-9]+", text)
    if not words:
        return "#TNGTGiaLai"
    formatted_words = []
    for w in words:
        if w.upper() in {"QL", "DT", "TNGT"} or any(c.isdigit() for c in w):
            formatted_words.append(w.upper())
        else:
            formatted_words.append(w.capitalize())
    return "#" + "".join(formatted_words)


# Generic Tier 1 keywords that also appear in non-traffic news (e.g. drowning, homicide)
GENERIC_TIER1_KEYWORDS = {"tử vong", "bị thương", "chết", "hiện trường"}

# Traffic/vehicle context anchors to disambiguate generic Tier 1 words when no Tier 2A route is present
TRAFFIC_CONTEXT_WORDS = [
    "giao thông", "xe máy", "ô tô", "xe tải", "xe khách", "xe đầu kéo",
    "xe ben", "xe con", "mô tô", "xe đạp", "xe công nông", "container",
    "rơ-moóc", "quốc lộ", "tỉnh lộ", "đèo", "cầu", "tài xế", "lái xe",
]


def evaluate_article_relevance(article: Article) -> bool:
    """
    Evaluate Two-Tier Intersection Criteria:
    [At least 1 Tier 1 Accident Keyword] AND ([At least 1 Tier 2A Route] OR [At least 1 Tier 2B Locality])
    """
    combined_raw = normalize_text(f"{article.title}. {article.snippet}")
    combined_lower = combined_raw.lower()

    matched_t1: list[str] = []
    for kw in TIER1_INCIDENT_KEYWORDS:
        if contains_keyword(combined_lower, kw):
            matched_t1.append(kw)

    matched_routes: list[str] = []
    for kw in TIER2A_ROUTES:
        if contains_keyword(combined_lower, kw):
            if kw.lower() not in [m.lower() for m in matched_routes]:
                matched_routes.append(kw)

    matched_locs: list[str] = []
    for kw in TIER2B_LOCALITIES:
        if contains_keyword(combined_lower, kw):
            if kw.lower() not in [m.lower() for m in matched_locs]:
                matched_locs.append(kw)

    article.matched_tier1 = matched_t1
    article.matched_routes = matched_routes
    article.matched_localities = matched_locs

    if not matched_t1 or not (matched_routes or matched_locs):
        return False

    # Disambiguate if ONLY generic Tier 1 words matched ("tử vong", "bị thương", "chết", "hiện trường")
    # without any explicit collision keyword or designated route
    has_explicit_collision = any(k not in GENERIC_TIER1_KEYWORDS for k in matched_t1)
    if not has_explicit_collision and not matched_routes:
        has_traffic_context = any(contains_keyword(combined_lower, vw) for vw in TRAFFIC_CONTEXT_WORDS)
        if not has_traffic_context:
            return False

    # If scraped from a national newspaper (baogiaothong.vn) and matched an inter-provincial highway
    # (like Đường Hồ Chí Minh / QL14 / QL19 / QL25) but NO Gia Lai locality is mentioned,
    # reject if the headline explicitly targets another province.
    if "baogiaothong.vn" in article.source and not matched_locs:
        other_provinces = [
            "lâm đồng", "đắk lắk", "đắk nông", "kon tum", "quảng ngãi",
            "quảng trị", "hà tĩnh", "nghệ an", "thanh hóa", "quảng bình",
            "đà nẵng", "hà nội", "tp.hcm", "đồng nai", "bình phước",
        ]
        title_lower = normalize_text(article.title).lower()
        if any(title_lower.startswith(p) or f"qua {p}" in title_lower or f"ở {p}" in title_lower for p in other_provinces):
            return False

    tags: list[str] = []
    for r in matched_routes:
        tag = slugify_hashtag(r)
        if tag not in tags:
            tags.append(tag)
    for loc in matched_locs:
        tag = slugify_hashtag(loc)
        if tag not in tags:
            tags.append(tag)
    if "#TNGTGiaLai" not in tags:
        tags.append("#TNGTGiaLai")
    article.hashtags = tags

    return True


# ==============================================================================
# 4. DATE PARSING & 48-HOUR FRESHNESS FILTER
# ==============================================================================

def parse_article_datetime(raw_str: str, url: str = "") -> datetime | None:
    """Parse various Vietnamese & RFC2822/ISO8601 date formats into timezone-aware VN datetime."""
    if raw_str:
        raw_str = raw_str.strip()
        # 1. RFC 2822 (RSS pubDate: 'Wed, 11 Nov 2026 15:44:42 +07:00')
        try:
            dt = email.utils.parsedate_to_datetime(raw_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TZ)
            return dt.astimezone(VN_TZ)
        except Exception:
            pass

        # 2. ISO 8601 ('2026-11-11T15:24:29+07:00' or '2026-11-11 15:24:29')
        try:
            iso_clean = raw_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_clean)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=VN_TZ)
            return dt.astimezone(VN_TZ)
        except Exception:
            pass

        # 3. Vietnamese dd/mm/yyyy hh:mm(:ss) (AM/PM)
        m_dt = re.search(
            r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})(?:\s+|,\s*|\s*-\s*)(\d{1,2}):(\d{2})(?::(\d{2}))?\s*(AM|PM)?",
            raw_str,
            re.IGNORECASE,
        )
        if m_dt:
            day, month, year = int(m_dt.group(1)), int(m_dt.group(2)), int(m_dt.group(3))
            hour, minute = int(m_dt.group(4)), int(m_dt.group(5))
            second = int(m_dt.group(6) or 0)
            ampm = (m_dt.group(7) or "").upper()
            if ampm == "PM" and hour < 12:
                hour += 12
            elif ampm == "AM" and hour == 12:
                hour = 0
            try:
                return datetime(year, month, day, hour, minute, second, tzinfo=VN_TZ)
            except ValueError:
                pass

        # 4. Date only dd/mm/yyyy or dd-mm-yyyy
        m_d = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", raw_str)
        if m_d:
            day, month, year = int(m_d.group(1)), int(m_d.group(2)), int(m_d.group(3))
            try:
                return datetime(year, month, day, 12, 0, 0, tzinfo=VN_TZ)
            except ValueError:
                pass

    # 5. Extract from URL patterns if present (e.g., baogiaothong -192YYMMDDHHMMSSxxx.htm or gialaitv dd-mm-yyyy)
    if url:
        m_bgt = re.search(r"-192(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})\d+\.htm", url)
        if m_bgt:
            yy, mm, dd, hh, mi, ss = (int(x) for x in m_bgt.groups())
            try:
                return datetime(2000 + yy, mm, dd, hh, mi, ss, tzinfo=VN_TZ)
            except ValueError:
                pass

        m_url_d = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})/?$", url)
        if m_url_d:
            dd, mm, yyyy = (int(x) for x in m_url_d.groups())
            try:
                return datetime(yyyy, mm, dd, 12, 0, 0, tzinfo=VN_TZ)
            except ValueError:
                pass

    return None


def is_within_freshness_window(dt: datetime | None, hours: int = FRESHNESS_HOURS) -> bool:
    """Return True if article datetime is within the last `hours` hours (or if datetime cannot be determined)."""
    if dt is None:
        return True
    now = datetime.now(VN_TZ)
    cutoff = now - timedelta(hours=hours)
    return dt >= cutoff


# ==============================================================================
# 5. STATE MANAGEMENT (`data/history.json`)
# ==============================================================================

def load_history() -> dict:
    """Load `data/history.json` or initialize if not exists."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not HISTORY_FILE.exists():
        initial = {"scraped_urls": [], "last_run": ""}
        save_history(initial)
        return initial

    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"scraped_urls": [], "last_run": ""}
        if "scraped_urls" not in data or not isinstance(data["scraped_urls"], list):
            data["scraped_urls"] = []
        if "last_run" not in data:
            data["last_run"] = ""
        return data
    except Exception as exc:
        print(f"[WARN] Could not parse {HISTORY_FILE}, re-initializing: {exc}")
        return {"scraped_urls": [], "last_run": ""}


def save_history(history: dict) -> None:
    """Save `data/history.json` with max 500 recent URLs."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    urls = history.get("scraped_urls", [])
    # Deduplicate while preserving order, then cap at MAX_HISTORY_URLS
    deduped = list(dict.fromkeys(urls))[-MAX_HISTORY_URLS:]
    history["scraped_urls"] = deduped
    history["last_run"] = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S %z")
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


# ==============================================================================
# 6. MULTI-SOURCE WEB SCRAPING PIPELINE
# ==============================================================================

def clean_html_snippet(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return normalize_text(soup.get_text(" ", strip=True))


def enrich_article_from_detail_page(article: Article) -> None:
    """Fetch article detail page to fill missing snippet or publish time."""
    try:
        resp = requests.get(
            article.url,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
            verify=False,
        )
        if resp.status_code != 200:
            return
        soup = BeautifulSoup(resp.text, "html.parser")

        # 1. Extract snippet from meta description / sapo / first paragraphs
        if len(article.snippet) < 40:
            meta_desc = (
                soup.find("meta", attrs={"property": "og:description"})
                or soup.find("meta", attrs={"name": "description"})
            )
            desc_text = ""
            if meta_desc and meta_desc.get("content"):
                desc_text = normalize_text(meta_desc["content"])

            # Also grab first 2 content paragraphs to catch route names mentioned in body lead
            body_paras = []
            for p in soup.select(
                ".cms-body p, .detail-content p, .entry-content p, #news-bodyhtml p, article p, p"
            ):
                pt = normalize_text(p.get_text(" ", strip=True))
                if len(pt) > 50 and not pt.lower().startswith("xem thêm"):
                    body_paras.append(pt)
                if len(body_paras) >= 2:
                    break

            combined_snippet = " ".join(filter(None, [desc_text] + body_paras[:2]))
            if combined_snippet:
                article.snippet = combined_snippet[:650]

        # 2. Extract published datetime if missing
        if article.published_at is None:
            meta_time = (
                soup.find("meta", attrs={"property": "article:published_time"})
                or soup.find("meta", attrs={"name": "pubdate"})
                or soup.find("time")
            )
            raw_time = ""
            if meta_time:
                raw_time = meta_time.get("content") or meta_time.get("datetime") or meta_time.get_text(strip=True)
            if not raw_time:
                # Look for common date elements
                for sel in [".cms-date", ".detail-time", ".post-date", ".date", ".time"]:
                    el = soup.select_one(sel)
                    if el:
                        raw_time = el.get_text(" ", strip=True)
                        break

            dt = parse_article_datetime(raw_time, article.url)
            if dt:
                article.published_at = dt
                article.published_str = dt.strftime("%H:%M - %d/%m/%Y")
    except Exception as exc:
        print(f"[WARN] Detail fetch failed for {article.url}: {exc}")


def scrape_baogialai() -> list[Article]:
    """
    Source 1: Báo Gia Lai điện tử (baogialai.com.vn)
    - RSS feeds: Pháp luật, An ninh trật tự, Thời sự, Xã hội
    - HTML Category fallback: /phap-luat/, /an-ninh-trat-tu/
    """
    source_name = "Báo Gia Lai điện tử (baogialai.com.vn)"
    articles: list[Article] = []
    seen_urls: set[str] = set()

    rss_urls = [
        "https://baogialai.com.vn/rss/phap-luat.rss",
        "https://baogialai.com.vn/rss/an-ninh-trat-tu.rss",
        "https://baogialai.com.vn/rss/thoi-su.rss",
        "https://baogialai.com.vn/rss/xa-hoi.rss",
    ]

    for rss_url in rss_urls:
        try:
            print(f"[SCRAPE] {source_name} -> {rss_url}")
            resp = requests.get(rss_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = normalize_text(item.findtext("title") or "")
                link = (item.findtext("link") or "").strip()
                pub_raw = (item.findtext("pubDate") or "").strip()
                desc_raw = item.findtext("description") or ""
                snippet = clean_html_snippet(desc_raw)

                if not title or not link or link in seen_urls:
                    continue

                dt = parse_article_datetime(pub_raw, link)
                if not is_within_freshness_window(dt):
                    continue

                seen_urls.add(link)
                articles.append(
                    Article(
                        title=title,
                        url=link,
                        source=source_name,
                        published_at=dt,
                        published_str=dt.strftime("%H:%M - %d/%m/%Y") if dt else pub_raw,
                        snippet=snippet,
                    )
                )
        except Exception as exc:
            print(f"[ERROR] Failed scraping {rss_url}: {exc}")

    html_urls = [
        "https://baogialai.com.vn/phap-luat/",
        "https://baogialai.com.vn/",
    ]
    for html_url in html_urls:
        try:
            print(f"[SCRAPE] {source_name} HTML -> {html_url}")
            resp = requests.get(html_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for story in soup.select(".story, article, .box-category-item"):
                a_tag = story.find("a", href=True)
                if not a_tag:
                    continue
                link = urllib.parse.urljoin("https://baogialai.com.vn", a_tag["href"].strip())
                title_el = story.select_one(".story__heading, h2, h3, .cms-link") or a_tag
                title = normalize_text(title_el.get_text(" ", strip=True))
                if len(title) < 15 or link in seen_urls or not link.endswith(".html"):
                    continue

                summary_el = story.select_one(".story__summary, .sapo, p")
                snippet = normalize_text(summary_el.get_text(" ", strip=True)) if summary_el else ""
                time_el = story.select_one("time, .story__time, .time")
                time_raw = time_el.get("datetime") or time_el.get_text(" ", strip=True) if time_el else ""
                dt = parse_article_datetime(time_raw, link)
                if not is_within_freshness_window(dt):
                    continue

                seen_urls.add(link)
                articles.append(
                    Article(
                        title=title,
                        url=link,
                        source=source_name,
                        published_at=dt,
                        published_str=dt.strftime("%H:%M - %d/%m/%Y") if dt else "Mới cập nhật",
                        snippet=snippet,
                    )
                )
        except Exception as exc:
            print(f"[ERROR] Failed scraping {html_url}: {exc}")

    return articles


def scrape_congan_gialai() -> list[Article]:
    """
    Source 2: Cổng thông tin Công an tỉnh Gia Lai (congan.gialai.gov.vn)
    - Chuyên mục: An toàn giao thông, ANTT trong tỉnh, Lực lượng CSGT, Thông báo
    """
    source_name = "Cổng TTĐT Công an tỉnh Gia Lai (congan.gialai.gov.vn)"
    articles: list[Article] = []
    seen_urls: set[str] = set()

    category_urls = [
        "https://congan.gialai.gov.vn/vi/news/an-toan-giao-thong/",
        "https://congan.gialai.gov.vn/vi/news/antt-trong-tinh/",
        "https://congan.gialai.gov.vn/vi/news/luc-luong-canh-sat-giao-thong/",
        "https://congan.gialai.gov.vn/vi/news/cong-tac-cuu-nan-cuu-ho/",
        "https://congan.gialai.gov.vn/vi/news/thong-bao/",
    ]

    for cat_url in category_urls:
        try:
            print(f"[SCRAPE] {source_name} -> {cat_url}")
            resp = requests.get(cat_url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if "/vi/news/" not in href or not href.endswith(".html"):
                    continue
                link = urllib.parse.urljoin("https://congan.gialai.gov.vn", href)
                if link in seen_urls:
                    continue

                title = normalize_text(a_tag.get_text(" ", strip=True))
                if len(title) < 20:
                    continue

                # Inspect parent container for date & snippet
                container = a_tag.find_parent(["div", "li", "article"])
                container_text = normalize_text(container.get_text(" ", strip=True)) if container else title
                dt = parse_article_datetime(container_text, link)
                if not is_within_freshness_window(dt):
                    continue

                # Clean title date suffix like "(05/09/2026)"
                clean_title = re.sub(r"\s*\(\d{1,2}/\d{1,2}/\d{4}\)\s*$", "", title).strip()
                snippet = container_text.replace(title, "").strip()

                seen_urls.add(link)
                articles.append(
                    Article(
                        title=clean_title,
                        url=link,
                        source=source_name,
                        published_at=dt,
                        published_str=dt.strftime("%H:%M - %d/%m/%Y") if dt else "Mới cập nhật",
                        snippet=snippet[:500],
                    )
                )
        except Exception as exc:
            print(f"[ERROR] Failed scraping {cat_url}: {exc}")

    return articles


def scrape_gialaitv() -> list[Article]:
    """
    Source 3: Đài PT-TH Gia Lai (gialaitv.vn)
    - Chuyên mục: An ninh trật tự, An toàn giao thông, Trang chủ Thời sự
    """
    source_name = "Đài PT-TH Gia Lai (gialaitv.vn)"
    articles: list[Article] = []
    seen_urls: set[str] = set()

    urls = [
        "https://gialaitv.vn/category/chuyen-muc/an-ninh-trat-tu/",
        "https://gialaitv.vn/category/chuyen-muc/an-toan-giao-thong/",
        "https://gialaitv.vn/",
    ]

    gtv_headers = {**HEADERS, "Referer": "https://gialaitv.vn/"}

    for url in urls:
        try:
            print(f"[SCRAPE] {source_name} -> {url}")
            resp = requests.get(url, headers=gtv_headers, timeout=REQUEST_TIMEOUT, verify=False)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                if not href.startswith("https://gialaitv.vn/"):
                    continue
                if any(skip in href for skip in ["/category/", "/tag/", "/author/", "/page/", "wp-content"]):
                    continue
                if href.rstrip("/") == "https://gialaitv.vn":
                    continue

                title = normalize_text(a_tag.get_text(" ", strip=True))
                if len(title) < 20 or href in seen_urls:
                    continue

                container = a_tag.find_parent(["article", "div", "li"])
                container_text = normalize_text(container.get_text(" ", strip=True)) if container else ""
                dt = parse_article_datetime(f"{title} {container_text}", href)
                if not is_within_freshness_window(dt):
                    continue

                snippet = container_text.replace(title, "").strip()
                seen_urls.add(href)
                articles.append(
                    Article(
                        title=title,
                        url=href,
                        source=source_name,
                        published_at=dt,
                        published_str=dt.strftime("%H:%M - %d/%m/%Y") if dt else "Mới cập nhật",
                        snippet=snippet[:500],
                    )
                )
        except Exception as exc:
            print(f"[ERROR] Failed scraping {url}: {exc}")

    return articles


def scrape_baogiaothong() -> list[Article]:
    """
    Source 4: Báo Giao thông (baogiaothong.vn / baoxaydung.vn)
    - Chuyên mục: An toàn giao thông, Giao thông 24h, ATGT địa phương, An ninh hình sự
    """
    source_name = "Báo Giao thông (baogiaothong.vn)"
    articles: list[Article] = []
    seen_urls: set[str] = set()

    urls = [
        "https://www.baogiaothong.vn/an-toan-giao-thong.htm",
        "https://www.baogiaothong.vn/an-toan-giao-thong/giao-thong-24h.htm",
        "https://www.baogiaothong.vn/an-toan-giao-thong/atgt-dia-phuong.htm",
        "https://www.baogiaothong.vn/phap-luat/an-ninh-hinh-su.htm",
    ]

    for url in urls:
        try:
            print(f"[SCRAPE] {source_name} -> {url}")
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT, verify=False)
            resp.raise_for_status()
            base_domain = f"{urllib.parse.urlsplit(resp.url).scheme}://{urllib.parse.urlsplit(resp.url).netloc}"
            soup = BeautifulSoup(resp.text, "html.parser")

            for item in soup.select(".box-category-item, article, .story"):
                a_tag = item.select_one("a.box-category-link-title, h2 a, h3 a, a[href$='.htm']")
                if not a_tag or not a_tag.get("href"):
                    continue
                href = a_tag["href"].strip()
                if not re.search(r"-\d{10,}\.htm$", href):
                    continue

                link = urllib.parse.urljoin(base_domain, href)
                if link in seen_urls:
                    continue

                title = normalize_text(a_tag.get("title") or a_tag.get_text(" ", strip=True))
                if len(title) < 20:
                    continue

                sapo_el = item.select_one(".box-category-sapo, .sapo, p")
                snippet = normalize_text(sapo_el.get_text(" ", strip=True)) if sapo_el else ""

                time_el = item.select_one(".box-category-time, time")
                time_raw = (time_el.get("title") or time_el.get("datetime") or time_el.get_text(" ", strip=True)) if time_el else ""
                dt = parse_article_datetime(time_raw, link)
                if not is_within_freshness_window(dt):
                    continue

                seen_urls.add(link)
                articles.append(
                    Article(
                        title=title,
                        url=link,
                        source=source_name,
                        published_at=dt,
                        published_str=dt.strftime("%H:%M - %d/%m/%Y") if dt else "Mới cập nhật",
                        snippet=snippet,
                    )
                )
        except Exception as exc:
            print(f"[ERROR] Failed scraping {url}: {exc}")

    return articles


def collect_all_articles() -> list[Article]:
    """Run all 4 source scrapers with isolated error handling."""
    scrapers = [
        scrape_baogialai,
        scrape_congan_gialai,
        scrape_gialaitv,
        scrape_baogiaothong,
    ]
    all_articles: list[Article] = []
    seen_urls: set[str] = set()

    for scraper_fn in scrapers:
        try:
            items = scraper_fn()
            for item in items:
                if item.url not in seen_urls:
                    seen_urls.add(item.url)
                    all_articles.append(item)
        except Exception as exc:
            print(f"[ERROR] Unexpected error in {scraper_fn.__name__}: {exc}")

    return all_articles


# ==============================================================================
# 7. EMAIL FORMATTING & DISPATCH VIA GMAIL SMTP
# ==============================================================================

def highlight_keywords_html(text: str, keywords: Iterable[str]) -> str:
    """Highlight matched keywords inside the snippet HTML."""
    escaped = html.escape(text or "Không có đoạn trích dẫn chi tiết.")
    for kw in sorted(set(keywords), key=len, reverse=True):
        if not kw:
            continue
        pattern = re.compile(r"(?<![\w])(" + re.escape(html.escape(kw)) + r")(?![\w])", re.IGNORECASE)
        escaped = pattern.sub(
            r'<mark style="background:#ffeb3b;color:#b71c1c;font-weight:bold;padding:1px 4px;border-radius:3px;">\1</mark>',
            escaped,
        )
    return escaped


def build_alert_email(article: Article) -> tuple[str, str]:
    """
    Build Subject & HTML Body according to Section 4.5 Specification:
    Subject: [TNGT GIA LAI] - <Tuyến đường / Địa bàn phát hiện> - <Tiêu đề bài báo>
    """
    detected_locations = article.matched_routes + article.matched_localities
    primary_locus = ", ".join(detected_locations[:3]) if detected_locations else "Gia Lai"
    subject = f"[TNGT GIA LAI] - {primary_locus} - {article.title}"

    all_matched_kws = article.matched_tier1 + article.matched_routes + article.matched_localities
    highlighted_snippet = highlight_keywords_html(article.snippet or article.title, all_matched_kws)

    tags_html = " ".join(
        f'<span style="display:inline-block;background:#e3f2fd;color:#0d47a1;border:1px solid #90caf9;'
        f'font-weight:bold;font-size:14px;padding:4px 10px;border-radius:14px;margin:3px 4px 3px 0;">{html.escape(tag)}</span>'
        for tag in article.hashtags
    )

    pub_display = html.escape(article.published_str or datetime.now(VN_TZ).strftime("%H:%M - %d/%m/%Y"))
    routes_display = html.escape(", ".join(article.matched_routes) if article.matched_routes else "Đường nội tỉnh / Chưa nêu tên tuyến")
    localities_display = html.escape(", ".join(article.matched_localities) if article.matched_localities else "Gia Lai")
    incidents_display = html.escape(", ".join(article.matched_tier1))

    html_body = f"""<!DOCTYPE html>
<html lang="vi">
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:18px;background-color:#f0f2f5;font-family:Arial,Helvetica,sans-serif;color:#111111;">
  <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;border:2px solid #c62828;box-shadow:0 4px 12px rgba(0,0,0,0.08);">
    <div style="background:#b71c1c;color:#ffffff;padding:20px 24px;">
      <div style="font-size:13px;font-weight:bold;letter-spacing:1px;text-transform:uppercase;color:#ffcdd2;margin-bottom:4px;">
        HỆ THỐNG CẢNH BÁO SỚM TNGT GIA LAI
      </div>
      <h1 style="margin:0;font-size:22px;line-height:1.35;">
        🚨 {html.escape(article.title)}
      </h1>
    </div>

    <div style="padding:22px 24px;">
      <table style="width:100%;border-collapse:collapse;margin-bottom:18px;font-size:16px;">
        <tr>
          <td style="padding:8px 0;color:#555555;width:165px;font-weight:bold;">📰 Nguồn báo chí:</td>
          <td style="padding:8px 0;color:#111111;font-weight:bold;">{html.escape(article.source)}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#555555;font-weight:bold;">🕒 Thời gian đăng:</td>
          <td style="padding:8px 0;color:#111111;">{pub_display}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#555555;font-weight:bold;">🛣️ Tuyến đường:</td>
          <td style="padding:8px 0;color:#b71c1c;font-weight:bold;">{routes_display}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#555555;font-weight:bold;">📍 Địa bàn:</td>
          <td style="padding:8px 0;color:#111111;font-weight:bold;">{localities_display}</td>
        </tr>
        <tr>
          <td style="padding:8px 0;color:#555555;font-weight:bold;">⚠️ Từ khóa biến cố:</td>
          <td style="padding:8px 0;color:#d32f2f;font-weight:bold;">{incidents_display}</td>
        </tr>
      </table>

      <div style="background:#fff8e1;border-left:6px solid #f57f17;padding:16px;border-radius:6px;margin-bottom:20px;">
        <div style="font-size:14px;font-weight:bold;color:#e65100;margin-bottom:6px;text-transform:uppercase;">
          Trích dẫn hiện trường &amp; từ khóa phát hiện:
        </div>
        <div style="font-size:17px;line-height:1.6;color:#212121;">
          “{highlighted_snippet}”
        </div>
      </div>

      <div style="margin-bottom:22px;">
        <div style="font-size:14px;font-weight:bold;color:#555555;margin-bottom:6px;">Tag phân loại:</div>
        {tags_html}
      </div>

      <div style="text-align:center;margin:24px 0 8px 0;">
        <a href="{html.escape(article.url)}" target="_blank"
           style="display:inline-block;background:#c62828;color:#ffffff;text-decoration:none;font-size:17px;font-weight:bold;padding:14px 28px;border-radius:8px;">
          👉 XEM BÀI BÁO GỐC TẠI ĐÂY
        </a>
      </div>
    </div>

    <div style="background:#eceff1;padding:14px 24px;font-size:13px;color:#455a64;text-align:center;border-top:1px solid #cfd8dc;">
      Gia Lai Traffic Accident Radar • Tự động gửi tới <strong>tngt@googlegroups.com</strong>
    </div>
  </div>
</body>
</html>"""
    return subject, html_body


def send_smtp_email(subject: str, html_body: str, sender: str, password: str, recipient: str) -> None:
    """Send HTML email via smtp.gmail.com (supports Port 587 TLS and Port 465 SSL)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Gia Lai TNGT Radar <{sender}>"
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    recipients = [r.strip() for r in recipient.split(",") if r.strip()]
    context = ssl.create_default_context()

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
    except Exception as tls_exc:
        print(f"[WARN] Port 587 STARTTLS failed ({tls_exc}), retrying with Port 465 SSL...")
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=20) as server:
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())

    print(f"[EMAIL SENT] To: {recipient} | Subject: {subject}")


# ==============================================================================
# 8. MOCK DATA SUITE FOR LOCAL VERIFICATION
# ==============================================================================

def run_mock_verification() -> int:
    """Verify Two-Tier keyword filtering precision against synthetic test cases."""
    print("=" * 72)
    print("RUNNING TWO-TIER FILTERING VERIFICATION SUITE (MOCK DATA)")
    print("=" * 72)

    test_cases = [
        (
            Article(
                title="Gia Lai: Xe tải va chạm xe máy trên QL19 đoạn qua huyện Đak Đoa, 1 người tử vong",
                url="https://baogialai.com.vn/mock-ql19-dak-doa-post1001.html",
                source="Báo Gia Lai điện tử (baogialai.com.vn)",
                published_str="14:30 - 11/11/2026",
                snippet="Vụ tai nạn giao thông nghiêm trọng xảy ra trên tuyến Quốc lộ 19 thuộc địa bàn huyện Đak Đoa khiến 1 người tử vong tại chỗ.",
            ),
            True,
            "Should MATCH (Tier 1: va chạm, tai nạn giao thông, tử vong + Tier 2A: QL19, Quốc lộ 19 + Tier 2B: Gia Lai, Đak Đoa)",
        ),
        (
            Article(
                title="Lật xe chở nông sản trên đường Trường Sơn Đông qua thị xã Ayun Pa",
                url="https://congan.gialai.gov.vn/vi/news/an-toan-giao-thong/mock-tsd-1002.html",
                source="Cổng TTĐT Công an tỉnh Gia Lai (congan.gialai.gov.vn)",
                published_str="10:15 - 11/11/2026",
                snippet="Tại hiện trường trên tuyến Trường Sơn Đông và ĐT662, lực lượng CSGT đã kịp thời hỗ trợ tài xế bị thương.",
            ),
            True,
            "Should MATCH (Tier 1: lật xe, hiện trường, bị thương + Tier 2A: Trường Sơn Đông, ĐT662 + Tier 2B: Ayun Pa)",
        ),
        (
            Article(
                title="Hai xe máy đối đầu trên tỉnh lộ 664 qua huyện Ia Grai",
                url="https://gialaitv.vn/mock-dt664-ia-grai/",
                source="Đài PT-TH Gia Lai (gialaitv.vn)",
                published_str="08:00 - 11/11/2026",
                snippet="Vụ xe máy đối đầu trên ĐT 664 làm 2 người bị thương nặng phải đưa đi cấp cứu tại Pleiku.",
            ),
            True,
            "Should MATCH (Tier 1: xe máy đối đầu, bị thương + Tier 2A: tỉnh lộ 664, ĐT 664 + Tier 2B: Ia Grai, Pleiku)",
        ),
        (
            Article(
                title="Gia Lai: Hội nghị tổng kết công tác bảo đảm trật tự an toàn giao thông năm 2026",
                url="https://baogialai.com.vn/mock-hoi-nghi-post1003.html",
                source="Báo Gia Lai điện tử (baogialai.com.vn)",
                published_str="09:00 - 11/11/2026",
                snippet="Sáng 11/11 tại TP. Pleiku, Ban ATGT tỉnh Gia Lai tổ chức hội nghị triển khai kế hoạch tuần tra trên QL19 và đường Hồ Chí Minh.",
            ),
            False,
            "Should REJECT (Has Tier 2A/2B QL19, Pleiku, Gia Lai, but NO Tier 1 accident incident keyword)",
        ),
        (
            Article(
                title="TP.HCM: Xe máy tông rơ-moóc đỗ bên đường, nữ sinh lớp 12 tử vong",
                url="https://www.baogiaothong.vn/mock-tphcm-192261111150000123.htm",
                source="Báo Giao thông (baogiaothong.vn)",
                published_str="15:00 - 11/11/2026",
                snippet="Vụ tai nạn xảy ra tại TP.HCM khiến 1 người tử vong tại hiện trường.",
            ),
            False,
            "Should REJECT (Has Tier 1 tai nạn, tử vong, hiện trường, but NO Tier 2A/2B Gia Lai route or locality)",
        ),
    ]

    passed = 0
    for idx, (art, expected, desc) in enumerate(test_cases, 1):
        actual = evaluate_article_relevance(art)
        status = "PASS" if actual == expected else "FAIL"
        if actual == expected:
            passed += 1
        print(f"[TEST #{idx}] {status}: {desc}")
        print(f"   Title: {art.title}")
        if actual:
            subj, _ = build_alert_email(art)
            print(f"   Generated Subject: {subj}")
            print(f"   Generated Tags:    {' '.join(art.hashtags)}")

    print("-" * 72)
    print(f"Mock Verification Result: {passed}/{len(test_cases)} tests passed.")
    return 0 if passed == len(test_cases) else 1


# ==============================================================================
# 9. MAIN PIPELINE ENTRYPOINT
# ==============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(description="Gia Lai Traffic Accident Radar Scraper")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and filter without sending email or modifying history")
    parser.add_argument("--mock-test", action="store_true", help="Run unit tests with mock data to verify Two-Tier filtering")
    parser.add_argument("--send-test-alert", action="store_true", help="Send a test alert email to verify SMTP -> Google Groups delivery")
    args = parser.parse_args()

    if args.mock_test:
        return run_mock_verification()

    sender = os.environ.get("GMAIL_USER", DEFAULT_SENDER).strip() or DEFAULT_SENDER
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    target_email = os.environ.get("TARGET_EMAIL", DEFAULT_TARGET_EMAIL).strip() or DEFAULT_TARGET_EMAIL

    if args.send_test_alert:
        if not password:
            print("[ERROR] Missing GMAIL_APP_PASSWORD environment variable.")
            return 1
        sample_article = Article(
            title="[KIỂM TRA HỆ THỐNG] Xác nhận kết nối Radar TNGT Gia Lai tới Google Groups",
            url="https://baogialai.com.vn/phap-luat/",
            source="Hệ thống Gia Lai TNGT Radar (GitHub Actions)",
            published_at=datetime.now(VN_TZ),
            published_str=datetime.now(VN_TZ).strftime("%H:%M - %d/%m/%Y"),
            snippet=(
                "Đây là bản tin kiểm tra tự động nhằm xác nhận luồng gửi cảnh báo Tai nạn giao thông "
                "trên các tuyến QL19, Đường Hồ Chí Minh (QL14), Trường Sơn Đông, QL25, ĐT664 tại Gia Lai "
                "về địa chỉ tngt@googlegroups.com hoạt động thông suốt."
            ),
        )
        evaluate_article_relevance(sample_article)
        subj, body = build_alert_email(sample_article)
        send_smtp_email(subj, body, sender, password, target_email)
        return 0

    history = load_history()
    scraped_urls_set = set(history.get("scraped_urls", []))
    print(f"[INIT] Loaded {len(scraped_urls_set)} previously alerted URLs from {HISTORY_FILE}")

    candidates = collect_all_articles()
    print(f"[SCRAPE] Collected {len(candidates)} candidate articles (published within {FRESHNESS_HOURS}h)")

    matched_articles: list[Article] = []

    for article in candidates:
        if article.url in scraped_urls_set:
            continue

        # First pass check on title + listing snippet
        is_match = evaluate_article_relevance(article)

        # If title/snippet has Tier 1 incident OR mentions a route/locality, fetch detail page
        # so we don't miss route names or incident keywords located in the article sapo/lead!
        if not is_match:
            lower_combined = normalize_text(f"{article.title} {article.snippet}").lower()
            has_any_t1 = any(contains_keyword(lower_combined, kw) for kw in TIER1_INCIDENT_KEYWORDS)
            has_any_route = any(contains_keyword(lower_combined, kw) for kw in TIER2A_ROUTES)
            if has_any_t1 or has_any_route:
                enrich_article_from_detail_page(article)
                if not is_within_freshness_window(article.published_at):
                    continue
                is_match = evaluate_article_relevance(article)
        else:
            # Enrich matched article to ensure full snippet and accurate timestamp in email
            enrich_article_from_detail_page(article)
            if not is_within_freshness_window(article.published_at):
                continue
            evaluate_article_relevance(article)

        if is_match:
            matched_articles.append(article)

    print(f"[FILTER] Found {len(matched_articles)} new matching TNGT Gia Lai articles.")

    if args.dry_run:
        for idx, art in enumerate(matched_articles, 1):
            subj, _ = build_alert_email(art)
            print(f"  [{idx}] {subj}")
            print(f"      URL:  {art.url}")
            print(f"      Tags: {' '.join(art.hashtags)}")
        print("[DRY-RUN] Completed without sending email or updating history.json.")
        return 0

    event_name = os.environ.get("GITHUB_EVENT_NAME", "")

    if matched_articles:
        if not password:
            raise RuntimeError("Missing GMAIL_APP_PASSWORD environment variable! Check GitHub Secrets.")

        for art in matched_articles:
            subj, html_body = build_alert_email(art)
            send_smtp_email(subj, html_body, sender, password, target_email)
            history["scraped_urls"].append(art.url)

        save_history(history)
        print(f"[STATE] Updated {HISTORY_FILE} with {len(matched_articles)} new URLs.")
    else:
        print("[INFO] No new TNGT articles matching Two-Tier criteria in the last 48 hours.")
        # When triggered manually via workflow_dispatch, send a verification alert so the operator
        # can confirm end-to-end delivery to tngt@googlegroups.com immediately.
        if event_name == "workflow_dispatch" and password:
            print("[WORKFLOW_DISPATCH] Sending manual test verification alert to TARGET_EMAIL...")
            test_art = Article(
                title="Kiểm tra luồng cảnh báo TNGT Gia Lai (Không có vụ TNGT mới trong 48h qua)",
                url="https://baogialai.com.vn/phap-luat/",
                source="Hệ thống Gia Lai TNGT Radar (workflow_dispatch)",
                published_at=datetime.now(VN_TZ),
                published_str=datetime.now(VN_TZ).strftime("%H:%M - %d/%m/%Y"),
                snippet=(
                    "Hệ thống đã quét 4 nguồn báo (Báo Gia Lai, Công an tỉnh Gia Lai, Đài PT-TH Gia Lai, "
                    "Báo Giao thông) trên các tuyến QL19, Đường Hồ Chí Minh (QL14), Trường Sơn Đông, QL25, "
                    "QL19D và các tuyến ĐT662-ĐT670 tại Gia Lai. Hiện chưa có tin tai nạn giao thông mới chưa gửi."
                ),
            )
            evaluate_article_relevance(test_art)
            subj, html_body = build_alert_email(test_art)
            send_smtp_email(subj, html_body, sender, password, target_email)

        save_history(history)

    return 0


if __name__ == "__main__":
    sys.exit(main())
