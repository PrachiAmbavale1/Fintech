from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx
from dateutil import parser as date_parser
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from models import Article

logger = logging.getLogger(__name__)


SAMPLE_PATH = Path(__file__).parent / "data" / "sample_articles.json"


class SearchError(Exception):
    pass


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = date_parser.parse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def normalize_result(
    *,
    title: str,
    url: str,
    publication: str = "Unknown",
    published_at: Optional[datetime] = None,
    snippet: Optional[str] = None,
    company: Optional[str] = None,
    query_used: Optional[str] = None,
) -> Article:
    return Article(
        title=title.strip(),
        url=url.strip(),
        publication=publication.strip() or "Unknown",
        published_at=published_at,
        snippet=(snippet or "").strip() or None,
        company=company,
        query_used=query_used,
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError, SearchError)),
)
def _tavily_search(query: str, api_key: str) -> list[Article]:
    payload = {
        "api_key": api_key,
        "query": query,
        "topic": "news",
        "search_depth": "basic",
        "max_results": 5,
        "days": 1,
    }
    with httpx.Client(timeout=20.0) as client:
        resp = client.post("https://api.tavily.com/search", json=payload)
        if resp.status_code in {401, 403}:
            raise httpx.HTTPStatusError("Auth failed", request=resp.request, response=resp)
        if resp.status_code >= 500:
            raise SearchError(f"Tavily server error: {resp.status_code}")
        if resp.status_code >= 400:
            raise ValueError(f"Tavily bad request: {resp.status_code} {resp.text[:200]}")
        data = resp.json()

    articles: list[Article] = []
    for item in data.get("results", []):
        articles.append(
            normalize_result(
                title=item.get("title") or "Untitled",
                url=item.get("url") or "",
                publication=_guess_publication(item.get("url", "")),
                published_at=_parse_date(item.get("published_date")),
                snippet=item.get("content"),
                query_used=query,
            )
        )
    return articles


def _duckduckgo_search(query: str) -> list[Article]:
    try:
        from duckduckgo_search import DDGS
    except ImportError as exc:
        raise SearchError("duckduckgo-search not installed") from exc

    articles: list[Article] = []
    with DDGS() as ddgs:
        results = list(ddgs.news(query, max_results=5, timelimit="d"))
    for item in results:
        articles.append(
            normalize_result(
                title=item.get("title") or "Untitled",
                url=item.get("url") or item.get("link") or "",
                publication=item.get("source") or _guess_publication(item.get("url", "")),
                published_at=_parse_date(item.get("date")),
                snippet=item.get("body") or item.get("excerpt"),
                query_used=query,
            )
        )
    return articles


def _guess_publication(url: str) -> str:
    host = (url or "").lower()
    mapping = {
        "reuters.com": "Reuters",
        "bloomberg.com": "Bloomberg",
        "ft.com": "Financial Times",
        "wsj.com": "Wall Street Journal",
        "cnbc.com": "CNBC",
        "forbes.com": "Forbes",
        "bbc.com": "BBC",
        "nytimes.com": "New York Times",
    }
    for needle, name in mapping.items():
        if needle in host:
            return name
    return "Unknown"


def load_sample_articles(company_hint: Optional[str] = None) -> list[Article]:
    if not SAMPLE_PATH.exists():
        return _builtin_samples()
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    articles: list[Article] = []
    for item in data:
        published = now - timedelta(hours=int(item.get("hours_ago", 6)))
        art = normalize_result(
            title=item["title"],
            url=item["url"],
            publication=item.get("publication", "Unknown"),
            published_at=published,
            snippet=item.get("snippet"),
            company=item.get("company"),
            query_used=item.get("query"),
        )
        if company_hint and art.company and company_hint.lower() not in art.company.lower():
            if company_hint.lower() not in art.title.lower():
                continue
        articles.append(art)
    return articles or _builtin_samples()


def _builtin_samples() -> list[Article]:
    now = datetime.now(timezone.utc)
    samples = [
        (
            "JPMorgan expands generative AI platform for institutional clients",
            "https://www.reuters.com/sample/jpmorgan-ai-platform",
            "Reuters",
            "JPMorgan Chase",
            "JPMorgan said it is scaling an internal generative AI platform to support research and client workflows.",
        ),
        (
            "BlackRock launches digital tokenization fund for alternative assets",
            "https://www.ft.com/sample/blackrock-tokenization",
            "Financial Times",
            "BlackRock",
            "BlackRock unveiled a new vehicle focused on tokenized private-market assets for institutional investors.",
        ),
        (
            "HSBC faces new digital banking capital requirements in UK",
            "https://www.bloomberg.com/sample/hsbc-regulation",
            "Bloomberg",
            "HSBC",
            "UK regulators proposed updated capital and operational resilience rules affecting large digital banking units.",
        ),
        (
            "Goldman Sachs partners with fintech on real-time treasury tooling",
            "https://www.cnbc.com/sample/gs-partnership",
            "CNBC",
            "Goldman Sachs",
            "Goldman Sachs announced a partnership to modernize corporate treasury cash-management workflows.",
        ),
        (
            "Morgan Stanley invests in cybersecurity startup for wealth platforms",
            "https://www.wsj.com/sample/ms-cyber",
            "Wall Street Journal",
            "Morgan Stanley",
            "Morgan Stanley led a strategic investment into a cybersecurity firm protecting advisor and client portals.",
        ),
        (
            "Bank of America stock rises 3% on strong trading day",
            "https://www.example.com/sample/bofa-stock",
            "MarketWire",
            "Bank of America",
            "Shares of Bank of America climbed after a broad market rally.",
        ),
        (
            "Citigroup executives to speak at fintech summit in London",
            "https://www.example.com/sample/citi-conference",
            "EventDaily",
            "Citigroup",
            "Citigroup leaders are scheduled to appear on a conference panel about payments innovation.",
        ),
    ]
    out: list[Article] = []
    for i, (title, url, pub, company, snippet) in enumerate(samples):
        out.append(
            normalize_result(
                title=title,
                url=url,
                publication=pub,
                published_at=now - timedelta(hours=3 + i),
                snippet=snippet,
                company=company,
            )
        )
    return out


def search_news(
    query: str,
    *,
    company: Optional[str] = None,
    use_sample: bool = False,
) -> list[Article]:
    if use_sample:
        return load_sample_articles(company_hint=company)

    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if tavily_key:
        try:
            results = _tavily_search(query, tavily_key)
            for a in results:
                a.company = company
            return results
        except httpx.HTTPStatusError:
            logger.error("Tavily authentication failed — not retrying")
            raise
        except ValueError as exc:
            logger.error("Tavily bad request: %s", exc)
            raise
        except Exception as exc:
            logger.warning("Tavily search failed for '%s': %s", query, exc)

    try:
        results = _duckduckgo_search(query)
        for a in results:
            if company:
                a.company = company
        if results:
            return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed for '%s': %s", query, exc)

    logger.warning("Falling back to sample articles for query: %s", query)
    return load_sample_articles(company_hint=company)
