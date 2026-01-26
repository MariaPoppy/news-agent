import os
import yaml
import feedparser
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape

BUCHAREST = ZoneInfo("Europe/Bucharest")
TELEGRAM_MAX = 3800  # buffer under Telegram 4096


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch(feed_url, limit=7):
    feed = feedparser.parse(feed_url)
    entries = getattr(feed, "entries", []) or []
    return entries[:limit]


def split_messages(big_text: str, max_len: int = TELEGRAM_MAX) -> list[str]:
    lines = big_text.split("\n")
    parts = []
    current = ""

    for line in lines:
        if len(current) + len(line) + 1 > max_len:
            if current.strip():
                parts.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"

    if current.strip():
        parts.append(current.rstrip())

    return parts


def send_telegram_html(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    r = httpx.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,  # keep message compact
        },
        timeout=30,
    )
    r.raise_for_status()


def main():
    cfg = load_config()
    feeds = cfg.get("feeds", [])
    if not feeds:
        send_telegram_html("Config error: nu există <b>feeds</b> în config.yaml")
        return

    today = datetime.now(BUCHAREST).strftime("%d %b %Y")
    msg = f"🗞️ <b>Daily Brief — {escape(today)}</b>\n\n"

    for feed in feeds:
        name = escape(str(feed.get("name", "Unknown source")))
        url = str(feed.get("url", "")).strip()

        msg += f"• <b>{name}</b>\n"

        if not url:
            msg += "  - (feed url lipsă)\n\n"
            continue

        try:
            items = fetch(url, limit=7)
        except Exception:
            msg += "  - (eroare la citirea feed-ului)\n\n"
            continue

        if not items:
            msg += "  - (nu am găsit articole)\n\n"
            continue

        for e in items:
            title = (getattr(e, "title", "") or "").strip()
            link = (getattr(e, "link", "") or "").strip()

            if not title and not link:
                continue

            safe_title = escape(title) if title else "(fără titlu)"
            safe_link = escape(link)

            # "Citește" = text clickabil (în loc de URL-ul lung)
            if link:
                msg += f'  - {safe_title} — <a href="{safe_link}">Citește</a>\n'
            else:
                msg += f"  - {safe_title}\n"

        msg += "\n"

    parts = split_messages(msg, TELEGRAM_MAX)
    for part in parts:
        send_telegram_html(part)


if __name__ == "__main__":
    main()
