from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable
from urllib.parse import urlparse

from models import Article


EXCLUSION_PATTERNS = [
    r"\bshare\s+price\b",
    r"\bstock\s+(price|movement|rises?|falls?|surges?|drops?|plunges?)\b",
    r"\bmarket\s+(rally|sell[- ]?off|commentary|outlook)\b",
    r"\bearnings\s+(beat|miss|estimate)\b",
    r"\b(conference|summit|webinar|panel\s+discussion)\b",
    r"\bindex\s+(rises?|falls?|hits?)\b",
    r"\bS&P\s*500\b.*\b(up|down|rises?|falls?)\b",
]


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def has_valid_url(article: Article) -> bool:
    try:
        parsed = urlparse(article.url)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    except Exception:
        return False


def is_within_lookback(
    article: Article,
    lookback_hours: int,
    now: datetime | None = None,
) -> bool:
    if article.published_at is None:
        return True
    now = _aware(now or datetime.now(timezone.utc))
    cutoff = now - timedelta(hours=lookback_hours)
    return _aware(article.published_at) >= cutoff


def is_obvious_exclusion(article: Article, exclude_keywords: Iterable[str]) -> tuple[bool, str]:
    text = f"{article.title} {article.snippet or ''}".lower()

    for kw in exclude_keywords:
        if kw.lower() in text:
            return True, f"Excluded keyword: {kw}"

    for pattern in EXCLUSION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True, f"Matched exclusion pattern: {pattern}"

    return False, ""


def apply_hard_filters(
    articles: list[Article],
    *,
    lookback_hours: int,
    exclude_keywords: list[str],
    now: datetime | None = None,
) -> list[Article]:
    kept: list[Article] = []

    for article in articles:
        if not has_valid_url(article):
            article.excluded = True
            article.exclusion_reason = "Invalid URL"
            continue

        if not is_within_lookback(article, lookback_hours, now=now):
            article.excluded = True
            article.exclusion_reason = f"Older than {lookback_hours}h"
            continue

        excluded, reason = is_obvious_exclusion(article, exclude_keywords)
        if excluded:
            article.excluded = True
            article.exclusion_reason = reason
            continue

        kept.append(article)

    return kept


def normalize_title(title: str) -> str:
    t = title.lower().strip()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def event_key(article: Article) -> str:
    title = normalize_title(article.title)
    tokens = [t for t in title.split() if len(t) > 3][:8]
    company = (article.company or "").lower().strip()
    return f"{company}|{' '.join(tokens)}"


def deduplicate(articles: list[Article]) -> list[Article]:
    by_url: dict[str, Article] = {}
    for a in articles:
        key = a.url.rstrip("/").lower()
        prev = by_url.get(key)
        if prev is None or _strength(a) > _strength(prev):
            by_url[key] = a

    unique_urls = list(by_url.values())

    clusters: dict[str, Article] = {}
    for a in unique_urls:
        key = event_key(a)
        a.event_hash = key
        prev = clusters.get(key)
        if prev is None or _strength(a) > _strength(prev):
            clusters[key] = a

    return list(clusters.values())


def _strength(a: Article) -> float:
    rel = a.relevance_score or 0.0
    src = a.source_quality or 0.55
    return rel * 0.8 + src * 2.0
