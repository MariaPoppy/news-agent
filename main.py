import os
import yaml
import feedparser
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

BUCHAREST = ZoneInfo("Europe/Bucharest")

def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def fetch(feed_url, limit=5):
    feed = feedparser.parse(feed_url)
    return feed.entries[:limit]

def send_telegram(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = httpx.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()

def main():
    cfg = load_config()
    msg = f"🗞️ Daily Brief — {datetime.now(BUCHAREST):%d %b %Y}\n\n"

    for feed in cfg["feeds"]:
        msg += f"• {feed['name']}\n"
        for e in fetch(feed["url"], limit=5):
            link = getattr(e, "link", "").strip()
title = getattr(e, "title", "").strip()

if title:
    msg += f"  - {title}\n"
    if link:
        msg += f"    🔗 {link}\n"

        msg += "\n"

    send_telegram(msg)

if __name__ == "__main__":
    main()
