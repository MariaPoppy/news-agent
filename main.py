import os
import re
import yaml
import feedparser
import httpx
from datetime import datetime
from zoneinfo import ZoneInfo
from html import escape
from rapidfuzz import fuzz

BUCHAREST = ZoneInfo("Europe/Bucharest")
TELEGRAM_MAX = 3800


def load_config():
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def fetch(feed_url, limit=15):
    feed = feedparser.parse(feed_url)
    return (getattr(feed, "entries", []) or [])[:limit]


def norm(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[^a-z0-9ăâîșț\- ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def any_kw_in(text: str, kws: list[str]) -> bool:
    t = norm(text)
    for k in kws or []:
        kk = norm(k)
        if kk and kk in t:
            return True
    return False


def classify(title: str, summary: str, categories: dict) -> set[str]:
    hay = f"{title} {summary}"
    matched = set()
    for cat, rule in (categories or {}).items():
        inc = rule.get("include_any", [])
        if inc and any_kw_in(hay, inc):
            matched.add(cat)
    return matched


def is_romanian(title: str) -> bool:
    t = (title or "").lower()
    if any(c in t for c in "ăâîșț"):
        return True
    ro_words = [" și ", " în ", " la ", " pentru ", " din ", " cu ", " pe ", " despre "]
    return any(w in f" {t} " for w in ro_words)


def dedupe(items: list[dict], threshold: int) -> list[dict]:
    out = []
    for it in items:
        nt = norm(it["title"])
        is_dup = False
        for o in out:
            if fuzz.token_set_ratio(nt, norm(o["title"])) >= threshold:
                is_dup = True
                break
        if not is_dup:
            out.append(it)
    return out


def send(text: str):
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


def split(text: str) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > TELEGRAM_MAX:
            if cur.strip():
                parts.append(cur.rstrip())
            cur = line + "\n"
        else:
            cur += line + "\n"
    if cur.strip():
        parts.append(cur.rstrip())
    return parts


def render_item(it: dict) -> str:
    title = escape(it.get("title") or "(fără titlu)")
    link = escape(it.get("link") or "")
    src = escape(it.get("source") or "")
    if link:
        return f'  - {title} — <a href="{link}">Citește</a> <i>({src})</i>'
    return f"  - {title} <i>({src})</i>"


def main():
    cfg = load_config()

    settings = cfg.get("settings", {})
    items_per_feed = int(settings.get("items_per_feed", 15))
    max_items_per_section = int(settings.get("max_items_per_section", 10))
    dedupe_threshold = int(settings.get("dedupe_threshold", 92))

    exclude_any = cfg.get("filters", {}).get("exclude_any", [])
    categories = cfg.get("categories", {})
    feeds = cfg.get("feeds", {})

    selected = ["politics", "economy", "technology"]

    buckets = {
        "romania": {c: [] for c in selected},
        "world": {c: [] for c in selected},
    }

    def process(region: str, feed: dict):
        src = str(feed.get("name", "Unknown")).strip()
        url = str(feed.get("url", "")).strip()
        if not url:
            return

        for e in fetch(url, limit=items_per_feed):
            title = (getattr(e, "title", "") or "").strip()
            summary = (getattr(e, "summary", "") or "").strip()
            link = (getattr(e, "link", "") or "").strip()

            hay = f"{title} {summary} {link}"

            # exclude deaths/violence etc.
            if exclude_any and any_kw_in(hay, exclude_any):
                continue

            # keep Romania clean (mostly RO)
            if region == "romania" and title and not is_romanian(title):
                continue

            matched = classify(title, summary, categories) & set(selected)
            if not matched:
                continue

            item = {"title": title, "link": link, "source": src}
            for cat in matched:
                buckets[region][cat].append(item)

    # collect
    for fd in feeds.get("romania", []):
        process("romania", fd)
    for fd in feeds.get("world", []):
        process("world", fd)

    # dedupe + cap
    for region in buckets:
        for cat in buckets[region]:
            buckets[region][cat] = dedupe(buckets[region][cat], dedupe_threshold)[:max_items_per_section]

    today = datetime.now(BUCHAREST).strftime("%d %b %Y")
    msg = f"🗞️ <b>Daily Brief — {escape(today)}</b>\n\n"

    def render_region(region_key: str, label: str, emoji: str):
        nonlocal msg
        msg += f"{emoji} <b>{escape(label)}</b>\n"

        any_region = False
        order = [
            ("politics", "🏛️ Politică"),
            ("economy", "📈 Economie"),
            ("technology", "🧠 Tehnologie & Inovație"),
        ]

        for cat, cat_label in order:
            items = buckets[region_key][cat]
            if not items:
                continue
            any_region = True
            msg += f"• <b>{escape(cat_label)}</b>\n"
            msg += "\n".join(render_item(it) for it in items)
            msg += "\n\n"

        if not any_region:
            msg += "• (nimic relevant după filtrare)\n\n"

    render_region("romania", "România", "🇷🇴")
    render_region("world", "Global", "🌍")

    for part in split(msg):
        send(part)


if __name__ == "__main__":
    main()
