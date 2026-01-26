import os
import yaml
import feedparser
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo

BUCHAREST = ZoneInfo("Europe/Bucharest")

# Telegram limit is ~4096 characters per message (safe buffer)
TELEGRAM_MAX = 3800


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch(feed_url, limit=7):
    feed = feedparser.parse(feed_url)

    # If the feed had a parsing error, feed.bozo is True and bozo_exception may exist
    if getattr(feed, "bozo", False):
        # We still might have entries, so we don't stop here
        pass

    entries = getattr(feed, "entries", []) or []
    return entries[:limit]


def safe_text(x: str) -> str:
    return (x or "").strip()


def send_telegram(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    r = httpx.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": False,  # show previews if Telegram wants
        },
        timeout=30,
    )
    r.raise_for_status()


def split_messages(big_text: str, max_len: int = TELEGRAM_MAX) -> list[str]:
    """
    Split by lines so we don't cut in the middle of an item.
    """
    lines = big_text.split("\n")
    parts = []
    current = ""

    for line in lines:
        # +1 for newline we add back
        if len(current) + len(line) + 1 > max_len:
            if current.strip():
                parts.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"

    if current.strip():
        parts.append(current.rstrip())

    return parts


def main():
    cfg = load_config()

    today = datetime.now(BUCHAREST).strftime("%d %b %Y")
    header = f"🗞️ Daily Brief — {today}\n"
    header += "====================\n\n"

    msg = header

    feeds = cfg.get("feeds", [])
    if not feeds:
        send_telegram("Config error: no feeds found in config.yaml")
        return

    for feed in feeds:
        name = feed.get("name", "Unknown source")
        url = feed.get("url", "")

        msg += f"• {name}\n"

        if not url:
            msg += "  - (feed url lipsă)\n\n"
            continue

        try:
            items = fetch(url, limit=7)
        except Exception as e:
            msg += f"  - (eroare la citire feed)\n"
            msg += f"    {type(e).__name__}\n\n"
            continue

        if not items:
            msg += "  - (nu am găsit articole în acest feed)\n\n"
            continue

        for e in items:
            title = safe_text(getattr(e, "title", ""))
            link = safe_text(getattr(e, "link", ""))

            if not title and not link:
                continue

            # Title line
            if title:
                msg += f"  - {title}\n"
            else:
                msg += "  - (fără titlu)\n"

            # Link line (this is clickable automatically in Telegram)
            if link:
                msg += f"    🔗 {link}\n"
            else:
                msg += "    🔗 (fără link)\n"

        msg += "\n"

    # If the message is too long, split into multiple Telegram messages
    parts = split_messages(msg, TELEGRAM_MAX)
    for i, part in enumerate(parts, start=1):
        # Add a small footer if multiple parts
        if len(parts) > 1:
            part = part + f"\n\n({i}/{len(parts)})"
        send_telegram(part)


if __name__ == "__main__":
    main()
