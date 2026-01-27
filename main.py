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
    return any(norm(k) in t for k in kws or [])


def classify(title: str, summary: str, categories: dict) -> set[str]:
    hay = f"{title} {summary}"
    matched = set()
    for cat, rule in categories.items():
        if any_kw_in(hay, rule.get("include_any", [])):
            matched.add(cat)
    return matched


def is_romanian(title: str) -> bool:
    t = title.lower()
    if any(c in t for c in "ăâîșț"):
        return True
    return any(w in f" {t} " for w in [" și ", " în ", " la ", " pentru ", " din "])


def dedupe(items: list[dict], threshold: int):
    out = []
    for it in items:
        if not any(
            fuzz.token_set_ratio(norm(it["title"]), norm(o["title"])) >= threshold
            for o in out
        ):
            out.append(it)
    return out


def send(text: str):
    r = httpx.post(
        f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
        json={
            "chat_id": os.environ["TELEGRAM_CHAT_ID"],
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )
    r.raise_for_status()


def split(text: str):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > TELEGRAM_MAX:
            parts.append(cur)
            cur = line + "\n"
        else:
            cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


def main():
    cfg = load_config()

    exclude_any = cfg["filters"]["exclude_any"]
    categories = cfg["categories"]
    feeds = cfg["feeds"]

    selected = ["politics", "economy", "technology"]

    buckets = {
        "romania": {c: [] for c in selected},
        "world": {c: [] for c in selected},
    }

   def process(region, feed):
    for e in fetch(feed["url"], cfg["settings"]["items_per_feed"]):
        title = (e.get("title") or "").strip()
        summary = (e.get("summary") or "").strip()
        link = (e.get("link") or "").strip()

        hay = f"{title} {summary} {link}"

        if any_kw_in(hay, exclude_any):
            continue

        if region == "romania" and not is_romanian(title):
            continue

        matched = classify(title, summary, categories)
        matched &= set(selected)

        if not matched:
            continue

        item = {"title": title, "link": link, "source": feed["name"]}
        for cat in matched:
            buckets[region][cat].append(item)


    for f in feeds["romania"]:
        process("romania", f)

    for f in feeds["world"]:
        process("world", f)

    for region in buckets:
        for cat in buckets[region]:
            buckets[region][cat] = dedupe(
                buckets[region][cat],
                cfg["settings"]["dedupe_threshold"],
            )[: cfg["settings"]["max_items_per_section"]]

    today = datetime.now(BUCHAREST).strftime("%d %b %Y")
    msg = f"🗞️ <b>Daily Brief — {today}</b>\n\n"

    def render_region(region, title, emoji):
        nonlocal msg
        msg += f"{emoji} <b>{title}</b>\n"
        for cat, label in [
            ("politics", "🏛️ Politică"),
            ("economy", "📈 Economie"),
            ("technology", "🧠 Tehnologie & Inovație"),
        ]:
            items = buckets[region][cat]
            if not items:
                continue
            msg += f"• <b>{label}</b>\n"
            for it in items:
                msg += (
                    f"  - {escape(it['title'])} — "
                    f"<a href=\"{escape(it['link'])}\">Citește</a> "
                    f"<i>({escape(it['source'])})</i>\n"
                )
            msg += "\n"

    render_region("romania", "România", "🇷🇴")
    render_region("world", "Global", "🌍")

    for part in split(msg):
        send(part)


if __name__ == "__main__":
    main()
