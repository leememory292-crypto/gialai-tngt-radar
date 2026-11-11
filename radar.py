import json
import os
import re
import smtplib
import ssl
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import feedparser
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
HISTORY_FILE = BASE_DIR / "history.json"
VN_TZ = timezone(timedelta(hours=7))

# Các truy vấn Google News RSS tập trung vào Tai nạn giao thông tại Gia Lai
SEARCH_QUERIES = [
    '"tai nạn giao thông" "Gia Lai" when:2d',
    '"va chạm giao thông" "Gia Lai" when:2d',
    '"tai nạn" ("Pleiku" OR "An Khê" OR "Ayun Pa" OR "Chư Sê" OR "Đak Đoa" OR "Chư Prông") when:2d',
    '"tai nạn" ("Quốc lộ 19" OR "Quốc lộ 14" OR "Quốc lộ 25" OR "đèo Mang Yang" OR "đèo An Khê") "Gia Lai" when:2d',
]

# Từ khóa bắt buộc phải liên quan đến Gia Lai & tai nạn giao thông
LOCATION_KEYWORDS = [
    "gia lai", "pleiku", "an khê", "ayun pa", "chư păh", "ia grai",
    "đak đoa", "đắk đoa", "chư prông", "đức cơ", "chư sê", "chư pưh",
    "đak pơ", "đắk pơ", "kbang", "kông chro", "mang yang", "phú thiện",
    "ia pa", "krông pa", "đèo an khê", "đèo mang yang", "hồ tơ nưng"
]

ACCIDENT_KEYWORDS = [
    "tai nạn", "tngt", "va chạm", "lật xe", "tông", "đâm nhau",
    "thương vong", "tử vong", "cán tử vong", "mất lái", "hiện trường vụ"
]


def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "sent_urls" in data:
                return data
            if isinstance(data, list):
                return {"updated_at": None, "sent_urls": data}
        except Exception as exc:
            print(f"[WARN] Không đọc được history.json, khởi tạo mới: {exc}")
    return {"updated_at": None, "sent_urls": []}


def save_history(history: dict) -> None:
    # Giữ tối đa 500 link gần nhất để file gọn nhẹ
    history["sent_urls"] = history.get("sent_urls", [])[-500:]
    history["updated_at"] = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S %z")
    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def is_relevant_article(title: str, summary: str) -> bool:
    combined = f"{title} {summary}".lower()
    has_location = any(loc in combined for loc in LOCATION_KEYWORDS)
    has_accident = any(acc in combined for acc in ACCIDENT_KEYWORDS)
    return has_location and has_accident


def fetch_news(sent_urls: set) -> list[dict]:
    articles = []
    seen_in_run = set(sent_urls)
    seen_titles = set()

    for query in SEARCH_QUERIES:
        encoded_q = urllib.parse.quote(query)
        rss_url = f"https://news.google.com/rss/search?q={encoded_q}&hl=vi&gl=VN&ceid=VN:vi"
        print(f"[INFO] Đang quét RSS: {query}")
        feed = feedparser.parse(rss_url)

        for entry in feed.entries:
            link = entry.get("link", "").strip()
            title = entry.get("title", "").strip()
            summary = clean_html(entry.get("summary", ""))
            published = entry.get("published", "Mới cập nhật")
            source = ""
            if "source" in entry and isinstance(entry.source, dict):
                source = entry.source.get("title", "")

            if not link or link in seen_in_run:
                continue

            # Chuẩn hóa tiêu đề để tránh trùng tin từ cùng 1 bài báo
            norm_title = re.sub(r"\s*-\s*[^-]+$", "", title).strip().lower()
            if norm_title in seen_titles:
                continue

            if not is_relevant_article(title, summary):
                continue

            seen_in_run.add(link)
            seen_titles.add(norm_title)
            articles.append(
                {
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published": published,
                    "source": source or "Google News",
                }
            )

    return articles


def build_email_html(articles: list[dict], is_test_run: bool = False) -> tuple[str, str]:
    now_str = datetime.now(VN_TZ).strftime("%H:%M - %d/%m/%Y")

    if articles:
        subject = f"[CẢNH BÁO TNGT GIA LAI] Phát hiện {len(articles)} tin mới ({now_str})"
        cards_html = ""
        for idx, item in enumerate(articles, 1):
            cards_html += f"""
            <div style="background:#ffffff;border:2px solid #d32f2f;border-left:8px solid #d32f2f;border-radius:8px;padding:16px;margin-bottom:16px;">
                <div style="font-size:14px;color:#b71c1c;font-weight:bold;margin-bottom:6px;">
                    #{idx} • {item['source']} • {item['published']}
                </div>
                <div style="font-size:19px;font-weight:bold;color:#111111;line-height:1.4;margin-bottom:10px;">
                    {item['title']}
                </div>
                <div style="font-size:16px;color:#333333;line-height:1.5;margin-bottom:14px;">
                    {item['summary']}
                </div>
                <a href="{item['link']}" target="_blank"
                   style="display:inline-block;background:#d32f2f;color:#ffffff;text-decoration:none;font-weight:bold;font-size:16px;padding:10px 18px;border-radius:6px;">
                    Xem chi tiết bài báo &rarr;
                </a>
            </div>
            """
    else:
        subject = f"[RADAR TNGT GIA LAI] Kiểm tra hệ thống thành công ({now_str})"
        cards_html = """
        <div style="background:#e8f5e9;border:2px solid #2e7d32;border-radius:8px;padding:18px;margin-bottom:16px;color:#1b5e20;font-size:17px;line-height:1.6;">
            <strong>Hệ thống Gia Lai TNGT Radar đang hoạt động tốt!</strong><br>
            Hiện tại chưa phát hiện bản tin tai nạn giao thông mới nào tại Gia Lai chưa được gửi.
            Luồng gửi email qua GitHub Actions và Gmail SMTP đã được xác nhận thông suốt.
        </div>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html lang="vi">
    <head><meta charset="utf-8"></head>
    <body style="margin:0;padding:16px;background:#f4f6f8;font-family:Arial,Helvetica,sans-serif;">
        <div style="max-width:680px;margin:0 auto;background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #cfd8dc;">
            <div style="background:#b71c1c;color:#ffffff;padding:20px 24px;">
                <h1 style="margin:0;font-size:22px;line-height:1.3;">🚨 RADAR TAI NẠN GIAO THÔNG GIA LAI</h1>
                <p style="margin:6px 0 0 0;font-size:15px;opacity:0.95;">Thời gian quét: {now_str} (Giờ Việt Nam)</p>
            </div>
            <div style="padding:20px 24px;">
                {cards_html}
            </div>
            <div style="background:#eceff1;padding:14px 24px;font-size:14px;color:#455a64;text-align:center;">
                Hệ thống tự động Gia Lai TNGT Radar • Chạy trên GitHub Actions
            </div>
        </div>
    </body>
    </html>
    """
    return subject, html_body


def send_email(subject: str, html_body: str) -> None:
    gmail_user = os.environ.get("GMAIL_USER", "").strip()
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    recipient = os.environ.get("GMAIL_RECEIVER", gmail_user).strip() or gmail_user

    if not gmail_user or not gmail_password:
        raise RuntimeError(
            "Thiếu biến môi trường GMAIL_USER hoặc GMAIL_APP_PASSWORD! "
            "Hãy kiểm tra lại cấu hình GitHub Secrets."
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Gia Lai TNGT Radar <{gmail_user}>"
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, [r.strip() for r in recipient.split(",") if r.strip()], msg.as_string())

    print(f"[SUCCESS] Đã gửi email tới {recipient}: {subject}")


def main() -> None:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    force_test_email = os.environ.get("FORCE_TEST_EMAIL", "false").lower() == "true"
    is_manual_dispatch = event_name == "workflow_dispatch" or force_test_email

    history = load_history()
    sent_urls = set(history.get("sent_urls", []))

    new_articles = fetch_news(sent_urls)
    print(f"[INFO] Số tin mới phát hiện: {len(new_articles)}")

    if new_articles:
        subject, html_body = build_email_html(new_articles, is_test_run=is_manual_dispatch)
        send_email(subject, html_body)
        for item in new_articles:
            history["sent_urls"].append(item["link"])
        save_history(history)
    elif is_manual_dispatch:
        print("[INFO] Chạy thử nghiệm thủ công (workflow_dispatch): Gửi email xác nhận luồng hoạt động.")
        subject, html_body = build_email_html([], is_test_run=True)
        send_email(subject, html_body)
        save_history(history)
    else:
        print("[INFO] Không có tin TNGT mới. Không gửi email.")


if __name__ == "__main__":
    main()
