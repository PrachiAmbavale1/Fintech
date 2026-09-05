from __future__ import annotations

from datetime import datetime, timezone

from models import Article


def source_quality_score(publication: str, source_map: dict) -> float:
    if not publication:
        return float(source_map.get("default", 0.55))
    for name, score in source_map.items():
        if name == "default":
            continue
        if name.lower() in publication.lower():
            return float(score)
    return float(source_map.get("default", 0.55))


def recency_boost(article: Article, now: datetime | None = None) -> float:
    if not article.published_at:
        return 0.5
    now = now or datetime.now(timezone.utc)
    pub = article.published_at
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now - pub).total_seconds() / 3600.0)
    return max(0.0, 1.0 - (age_hours / 24.0))


def rank_articles(
    articles: list[Article],
    *,
    weights: dict,
    source_map: dict,
    preference_fn,
) -> list[Article]:
    wr = float(weights.get("relevance", 0.55))
    we = float(weights.get("executive_relevance", 0.20))
    ws = float(weights.get("source_quality", 0.10))
    wp = float(weights.get("preference", 0.15))

    for a in articles:
        a.source_quality = source_quality_score(a.publication, source_map)
        a.preference_score = float(preference_fn(a))
        relevance = (a.relevance_score or 0.0) / 10.0
        exec_rel = (a.executive_relevance or a.relevance_score or 0.0) / 10.0
        src = 0.7 * a.source_quality + 0.3 * recency_boost(a)

        a.final_score = (
            wr * relevance
            + we * exec_rel
            + ws * src
            + wp * a.preference_score
        ) * 10.0

    return sorted(articles, key=lambda x: x.final_score or 0.0, reverse=True)
