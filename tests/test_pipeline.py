from datetime import datetime, timedelta, timezone

from filters import apply_hard_filters, deduplicate
from models import Article
from ranking import rank_articles


def _art(title: str, url: str, hours: int = 3, pub: str = "Reuters", company: str = "JPMorgan Chase") -> Article:
    return Article(
        title=title,
        url=url,
        publication=pub,
        company=company,
        published_at=datetime.now(timezone.utc) - timedelta(hours=hours),
        snippet=title,
        relevance_score=8.0,
        executive_relevance=8.0,
    )


def test_excludes_share_price_and_conference():
    articles = [
        _art("Bank of America stock rises 3%", "https://ex.com/1", company="Bank of America"),
        _art("Citigroup executives speak at summit", "https://ex.com/2", company="Citigroup"),
        _art("JPMorgan expands AI investment", "https://ex.com/3"),
    ]
    kept = apply_hard_filters(
        articles,
        lookback_hours=24,
        exclude_keywords=["share price", "conference", "summit"],
    )
    assert len(kept) == 1
    assert "AI" in kept[0].title


def test_deduplicates_same_event():
    a1 = _art("JPMorgan expands generative AI platform", "https://reuters.com/a")
    a2 = _art("JPMorgan expands generative AI platform", "https://bloomberg.com/b", pub="Bloomberg")
    a2.relevance_score = 9.0
    a2.source_quality = 1.0
    unique = deduplicate([a1, a2])
    assert len(unique) == 1


def test_scheduler_next_run_is_in_future():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from scheduler import next_run_at, seconds_until

    tz = ZoneInfo("Asia/Kolkata")
    now = datetime(2026, 9, 5, 10, 0, tzinfo=tz)  # after 9 AM IST
    nxt = next_run_at(9, 0, "Asia/Kolkata", now=now)
    assert nxt.day == 6
    assert nxt.hour == 9
    assert seconds_until(nxt, now=now) > 0


def test_ranking_prefers_boosted_topics():
    ai = _art("BlackRock AI strategy update", "https://ex.com/ai", company="BlackRock", pub="Reuters")
    ai.category = "artificial intelligence"
    ai.relevance_score = 8.0
    ai.executive_relevance = 8.0

    reg = _art("HSBC regulation update", "https://ex.com/reg", company="HSBC", pub="CNBC")
    reg.category = "regulation"
    reg.relevance_score = 8.0
    reg.executive_relevance = 8.0

    ranked = rank_articles(
        [reg, ai],
        weights={"relevance": 0.55, "executive_relevance": 0.20, "source_quality": 0.10, "preference": 0.15},
        source_map={"Reuters": 1.0, "CNBC": 0.75, "default": 0.55},
        preference_fn=lambda a: 0.9 if "artificial intelligence" in (a.category or "") else 0.3,
    )
    assert ranked[0].company == "BlackRock"


def test_explicit_feedback_and_implicit_learning(tmp_path):
    from memory import PreferenceMemory

    mem = PreferenceMemory(tmp_path / "memory.db")
    before = mem.load_preferences()["artificial intelligence"]
    mem.apply_feedback("more", topic="artificial intelligence")
    after_explicit = mem.load_preferences()["artificial intelligence"]
    assert after_explicit > before

    story = _art(
        "JPMorgan artificial intelligence platform expansion",
        "https://ex.com/jpm-ai",
        company="JPMorgan Chase",
    )
    story.category = "artificial intelligence"
    story.synopsis = "Bank expands artificial intelligence tooling."
    mem.learn_from_brief([story], weight=0.05)
    after_implicit = mem.load_preferences()["artificial intelligence"]
    assert after_implicit > after_explicit
    assert mem.load_company_preferences().get("JPMorgan Chase", 0) > 0.5
