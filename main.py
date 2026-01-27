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
