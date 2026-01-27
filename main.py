import os
import re
import yaml
import feedparser
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape

BUCHAREST = ZoneInfo("Europe/Bucharest")
TELEGRAM_MAX = 3800  # sub limita de 4096


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch(feed_url, limit=10):
    feed = feedparser.parse(feed_url)
    return (getattr(feed, "entries", None) or [])[:limit]


def norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"\s+", " ", text).strip()
    return text


def any_kw_in(text: str, kws: list[str]) -> bool:
    t = norm(text)
    for k in kws or []:
        kk = norm(k)
        if kk and kk in t:
            return True
    return False


def split_messages(big_text: str, max_len: int = TELEGRAM_MAX) -> list[str]:
    lines = big_text.split("\n")
    parts, current = [], ""
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
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()


def classify(title: str, summary: str, categories: dict) -> list[str]:
    hay = f"{title} {summary} {link}"
    matched = []
    for cat, rule in (categories or {}).items():
        include_any = rule.get("include_any", [])
        if include_any and any_kw_in(hay, include_any):
            matched.append(cat)
    return matched


def main():
    cfg = load_config()

    settings = cfg.get("settings", {})
    items_per_feed = int(settings.get("items_per_feed", 10))
    max_items_per_cat = int(settings.get("max_items_per_category", 12))

    exclude_any = cfg.get("filters", {}).get("exclude_any", [])
    categories = cfg.get("categories", {})
    feeds = cfg.get("feeds", [])

    # Ce categorii vrei azi: setabil din GitHub Actions env CATEGORIES
    # Exemple:
    #   CATEGORIES="politics,economy"
    #   CATEGORIES="economy"
    #   CATEGORIES="politics,economy,science_health"
    selected_env = (os.environ.get("CATEGORIES", "politics,economy") or "").strip().lower()
    selected = [x.strip() for x in selected_env.split(",") if x.strip()]

    # bucket pe categorii
    bucket = {cat: [] for cat in selected}

    for feed in feeds:
        feed_name = str(feed.get("name", "Unknown source")).strip()
        feed_url = str(feed.get("url", "")).strip()
        if not feed_url:
            continue

        try:
            entries = fetch(feed_url, limit=items_per_feed)
        except Exception:
            continue

        for e in entries:
            title = (getattr(e, "title", "") or "").strip()
            link = (getattr(e, "link", "") or "").strip()
            summary = (getattr(e, "summary", "") or "").strip()

            if not title and not link:
                continue

            hay = f"{title} {summary} {link}"

            # 1) EXCLUDE: crime/droguri/etc.
            if exclude_any and any_kw_in(hay, exclude_any):
                continue

            # 2) INCLUDE: doar ce intră în categoriile alese
            matched = classify(title, summary, categories)
            matched = [m for m in matched if m in selected]
            if not matched:
                continue

            safe_title = escape(title) if title else "(fără titlu)"
            safe_feed = escape(feed_name)
            safe_link = escape(link)

            if link:
                line = f'  - {safe_title} — <a href="{safe_link}">Citește</a> <i>({safe_feed})</i>'
            else:
                line = f"  - {safe_title} <i>({safe_feed})</i>"

            # un articol poate intra în mai multe categorii
            for cat in matched:
                bucket[cat].append(line)

    today = datetime.now(BUCHAREST).strftime("%d %b %Y")
    msg = f"🗞️ <b>Daily Brief — {escape(today)}</b>\n"
    msg += f"<i>Categorii: {escape(', '.join(selected))}</i>\n\n"

    pretty = {
        "politics": "🏛️ Politică",
        "economy": "📈 Economie",
        "science_health": "🧬 Știință & Sănătate",
    }

    any_content = False
    for cat in selected:
        items = bucket.get(cat, [])
        if not items:
            continue
        any_content = True
        msg += f"• <b>{escape(pretty.get(cat, cat))}</b>\n"
        msg += "\n".join(items[:max_items_per_cat])
        msg += "\n\n"

    if not any_content:
        msg += "Nu am găsit articole potrivite (după filtrare)."

    for part in split_messages(msg):
        send_telegram_html(part)


if __name__ == "__main__":
    main()
