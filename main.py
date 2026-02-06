import os
import re
import yaml
import feedparser
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from urllib.parse import urlsplit, urlunsplit

BUCHAREST = ZoneInfo("Europe/Bucharest")
TELEGRAM_LIMIT = 3900  # safe under 4096


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def normalize_text(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def contains_any(text: str, keywords: list[str]) -> bool:
    hay = normalize_text(text)
    for k in keywords or []:
        kk = normalize_text(k)
        if kk and kk in hay:
            return True
    return False


def canonical_link(url: str) -> str:
    """
    Normalize link to improve dedupe:
    - remove fragments
    - keep scheme+netloc+path+query (query kept because sometimes it identifies article)
    """
    if not url:
        return ""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def fetch_entries(feed_url: str, limit: int):
    feed = feedparser.parse(feed_url)
    return (getattr(feed, "entries", []) or [])[:limit]


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
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()


def build_message(date_str: str, ro_items: list[dict], world_items: list[dict]) -> str:
    msg = f"🗞️ <b>Daily Brief — {escape(date_str)}</b>\n\n"

    msg += "🇷🇴 <b>România</b>\n"
    if not ro_items:
        msg += "• (nimic relevant după filtrare)\n"
    else:
        for it in ro_items:
            title = escape(it["title"])
            link = escape(it["link"])
            src = escape(it["source"])
            msg += f'• {title} — <a href="{link}">Citește</a> <i>({src})</i>\n'

    msg += "\n🌍 <b>Global</b>\n"
    if not world_items:
        msg += "• (nimic relevant după filtrare)\n"
    else:
        for it in world_items:
            title = escape(it["title"])
            link = escape(it["link"])
            src = escape(it["source"])
            msg += f'• {title} — <a href="{link}">Citește</a> <i>({src})</i>\n'

    return msg.strip()


def main():
    cfg = load_config()

    settings = cfg.get("settings", {})
    scan_per_feed = int(settings.get("scan_per_feed", 25))
    romania_top = int(settings.get("romania_top", 10))
    world_top = int(settings.get("world_top", 10))
    max_total_items = int(settings.get("max_total_items", 18))

    exclude_any = cfg.get("filters", {}).get("exclude_any", [])

    feeds = cfg.get("feeds", {})
    ro_feeds = feeds.get("romania", [])
    world_feeds = feeds.get("world", [])

    # Collect + filter + dedupe
    seen_links = set()
    seen_titles = set()

    def collect(feed_defs: list[dict]) -> list[dict]:
        out = []
        for fd in feed_defs:
            name = str(fd.get("name", "Source")).strip()
            url = str(fd.get("url", "")).strip()
            if not url:
                continue

            for e in fetch_entries(url, scan_per_feed):
                title = (getattr(e, "title", "") or "").strip()
                link = canonical_link(getattr(e, "link", "") or "")
                summary = (getattr(e, "summary", "") or "").strip()

                if not title or not link:
                    continue

                hay = f"{title} {summary} {link}"

                # Exclude deaths/crime/etc.
                if contains_any(hay, exclude_any):
                    continue

                # Dedupe: link + normalized title
                nt = normalize_text(title)
                if link in seen_links or nt in seen_titles:
                    continue

                seen_links.add(link)
                seen_titles.add(nt)

                out.append({"title": title, "link": link, "source": name})
        return out

    ro_items = collect(ro_feeds)
    world_items = collect(world_feeds)

    # Limit per section + total (one message)
    ro_items = ro_items[:romania_top]
    world_items = world_items[:world_top]

    # Cap total items so message stays compact
    combined = ro_items + world_items
    if len(combined) > max_total_items:
        combined = combined[:max_total_items]
        ro_items = [x for x in combined if x in ro_items]
        world_items = [x for x in combined if x in world_items]

    date_str = datetime.now(BUCHAREST).strftime("%d %b %Y")
    msg = build_message(date_str, ro_items, world_items)

    # If still too long, shrink items until it fits (keeps one message)
    while len(msg) > TELEGRAM_LIMIT and (ro_items or world_items):
        # remove one from the bigger section
        if len(world_items) >= len(ro_items) and world_items:
            world_items = world_items[:-1]
        elif ro_items:
            ro_items = ro_items[:-1]
        msg = build_message(date_str, ro_items, world_items)

    send_telegram_html(msg)


if __name__ == "__main__":
    main()
