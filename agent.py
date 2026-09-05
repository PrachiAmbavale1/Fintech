from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import yaml
from openai import OpenAI

from email_out import render_email, send_daily_brief
from filters import apply_hard_filters, deduplicate
from memory import PreferenceMemory
from models import Article, ClassificationResult, DailyBrief, StorySummary
from ranking import rank_articles
from search import search_news

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        config_path: str | Path = "config.yaml",
        memory: PreferenceMemory | None = None,
        use_sample: bool = False,
    ) -> None:
        self.config = self._load_config(config_path)
        self.settings = self.config["settings"]
        self.memory = memory or PreferenceMemory("data/memory.db")
        self.use_sample = use_sample
        self.client = None
        self.llm_disabled_reason: str | None = None
        self.provider, self.model, self.client = self._init_llm_client()
        if self.client:
            logger.info("LLM provider=%s model=%s", self.provider, self.model)

    @staticmethod
    def _init_llm_client() -> tuple[str, str, OpenAI | None]:
        groq_key = os.getenv("GROQ_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()

        # gsk key sometimes lands in OPENAI_API_KEY
        if not groq_key and openai_key.startswith("gsk_"):
            groq_key = openai_key
            openai_key = ""

        if groq_key.startswith("gsk_"):
            default_groq = "openai/gpt-oss-20b"
            model = os.getenv("GROQ_MODEL", default_groq).strip() or default_groq
            deprecated = {
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "llama-3.1-70b-versatile",
                "mixtral-8x7b-32768",
                "gemma2-9b-it",
            }
            if (
                model.startswith("gpt-4")
                or model.startswith("gpt-3")
                or model.startswith("o1")
                or model.startswith("o3")
                or model in deprecated
            ):
                model = default_groq
            client = OpenAI(
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
            )
            return "groq", model, client

        if openai_key and not openai_key.startswith("sk-your"):
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            return "openai", model, OpenAI(api_key=openai_key)

        return "none", "", None

    @staticmethod
    def _load_config(path: str | Path) -> dict[str, Any]:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def all_companies(self) -> list[str]:
        cos = self.config["companies"]
        return list(cos.get("banks", [])) + list(cos.get("asset_managers", []))

    def create_queries(
        self,
        preferences: dict[str, float],
        companies: list[str] | None = None,
        round_idx: int = 1,
    ) -> list[tuple[str, str]]:
        companies = companies or self.all_companies()
        include = list(self.config["topics"]["include"])
        boosted = [t for t, s in sorted(preferences.items(), key=lambda x: x[1], reverse=True) if s >= 0.6]
        focus_topics = (boosted or ["artificial intelligence", "acquisitions", "partnerships", "regulation"])[:4]

        if round_idx > 1:
            focus_topics = ["cybersecurity", "product launches", "leadership changes", "strategic investments"]

        max_q = int(self.settings.get("max_search_queries", 20))
        queries: list[tuple[str, str]] = []

        for company in companies:
            for topic in focus_topics:
                if len(queries) >= max_q:
                    break
                queries.append((f"{company} {topic} latest", company))
            if len(queries) >= max_q:
                break

        for topic in include:
            if len(queries) >= max_q:
                break
            if topic not in focus_topics:
                company = companies[len(queries) % len(companies)]
                queries.append((f"{company} {topic} news", company))

        return queries[:max_q]

    def gather_articles(self, queries: list[tuple[str, str]]) -> list[Article]:
        if self.use_sample:
            from search import load_sample_articles

            if getattr(self, "_demo_loaded", False):
                return []
            self._demo_loaded = True
            return load_sample_articles()

        articles: list[Article] = []
        for query, company in queries:
            try:
                results = search_news(query, company=company, use_sample=False)
                articles.extend(results)
            except Exception:
                logger.exception("Search failed for query=%s, continuing", query)
        return articles

    def _llm_available(self) -> bool:
        return self.client is not None and self.llm_disabled_reason is None

    def _disable_llm(self, reason: str) -> None:
        if self.llm_disabled_reason is None:
            self.llm_disabled_reason = reason
            logger.warning("LLM disabled for this run: %s", reason)

    def _is_fatal_llm_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        markers = (
            "insufficient_quota",
            "credit_balance_exhausted",
            "you have no credits remaining",
            "invalid_api_key",
            "incorrect api key",
            "authentication",
            "permission",
            "model_not_found",
            "does not exist",
            "404",
        )
        return any(m in text for m in markers)

    def _parse_json_content(self, content: str) -> dict:
        text = (content or "").strip()
        if not text:
            raise ValueError("Empty LLM content")

        # drop ```json fences if the model adds them
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise
            data = json.loads(text[start : end + 1])

        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object, got {type(data).__name__}")
        return data

    def _chat_json(self, system: str, user: str) -> dict:
        assert self.client is not None
        models_to_try = [self.model]
        if self.provider == "groq":
            for alt in ("openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.6-27b"):
                if alt not in models_to_try:
                    models_to_try.append(alt)

        last_exc: Exception | None = None
        for model_name in models_to_try:
            try:
                resp = self.client.chat.completions.create(
                    model=model_name,
                    temperature=0.1,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                if model_name != self.model:
                    logger.info("Switched Groq model to %s", model_name)
                    self.model = model_name
                message = resp.choices[0].message
                content = message.content
                if not content:
                    content = getattr(message, "reasoning", None) or "{}"
                return self._parse_json_content(content if isinstance(content, str) else json.dumps(content))
            except Exception as exc:
                last_exc = exc
                text = str(exc).lower()
                if "404" in text or "model_not_found" in text or "does not exist" in text:
                    logger.warning("Model unavailable (%s): %s", model_name, str(exc)[:120])
                    continue
                if self._is_fatal_llm_error(exc):
                    self._disable_llm(str(exc)[:180])
                raise

        assert last_exc is not None
        self._disable_llm(f"No working Groq model: {last_exc}"[:180])
        raise last_exc

    def classify_article(self, article: Article) -> Article:
        if not self._llm_available():
            return self._heuristic_classify(article)

        system = (
            "You are a fintech intelligence analyst for a busy bank/asset-management executive. "
            "Decide if an article is material company-specific news from the last day. "
            "EXCLUDE share-price moves, conferences/summits, and general market commentary. "
            "Return ONLY a JSON object with keys: "
            "include (boolean), score (0-10 number), category (string), "
            "strategic_importance (0-10), business_impact (0-10), "
            "executive_relevance (0-10), reason (string)."
        )
        user = json.dumps(
            {
                "title": article.title,
                "publication": article.publication,
                "company": article.company,
                "snippet": article.snippet,
                "url": article.url,
            }
        )
        try:
            raw = self._chat_json(system, user)
            if "score" not in raw and "relevance_score" in raw:
                raw["score"] = raw["relevance_score"]
            if "include" not in raw and "relevant" in raw:
                raw["include"] = raw["relevant"]
            result = ClassificationResult.model_validate(raw)
        except Exception as exc:
            if self._is_fatal_llm_error(exc):
                self._disable_llm(str(exc)[:180])
            logger.warning(
                "Classification failed for %s, using heuristic (%s)",
                article.title,
                str(exc)[:160],
            )
            return self._heuristic_classify(article)

        article.include = result.include
        article.relevance_score = result.score
        article.category = result.category
        article.strategic_score = result.strategic_importance
        article.business_impact_score = result.business_impact
        article.executive_relevance = result.executive_relevance
        article.classification_reason = result.reason
        if not result.include:
            article.excluded = True
            article.exclusion_reason = result.reason
        return article

    def _heuristic_classify(self, article: Article) -> Article:
        text = f"{article.title} {article.snippet or ''}".lower()
        exclude_hits = [
            "share price", "stock rises", "stock falls", "stock climbed",
            "conference", "summit", "market rally", "webinar",
        ]
        if any(x in text for x in exclude_hits):
            article.include = False
            article.excluded = True
            article.relevance_score = 2.0
            article.exclusion_reason = "Heuristic exclusion"
            article.category = "Excluded"
            return article

        topic_map = {
            "artificial intelligence": ["generative ai", " artificial intelligence", " ai ", "ai-", "ai-", " ai-assisted", "ai platform", "ai-assisted"],
            "acquisitions": ["acquisition", "acquire", "acquires", "acquired"],
            "mergers": ["merger", "merge with"],
            "partnerships": ["partnership", "partners with", "partner with"],
            "regulation": ["regulation", "regulator", "regulatory", "capital requirements"],
            "cybersecurity": ["cybersecurity", "cyber security", "cyber"],
            "product launches": ["launches", "launched", "unveil", "rolls out", "rollout"],
            "technology": ["cloud", "tokenization", "digital", "platform", "technology"],
            "strategic investments": ["strategic investment", "invests in", "investment into"],
            "leadership changes": ["appoint", "ceo", "cfo", "names new"],
            "operational developments": ["operational", "operations", "outage", "resilience"],
        }

        matched: list[str] = []
        score = 6.8
        for topic, needles in topic_map.items():
            if any(n in text for n in needles):
                matched.append(topic)
                score += 0.55

        score = min(score, 9.6)
        min_score = float(self.settings.get("min_relevance_score", 7))
        article.include = score >= min_score and bool(matched)
        article.relevance_score = score if matched else 5.0
        article.executive_relevance = article.relevance_score
        article.strategic_score = article.relevance_score
        article.business_impact_score = max(article.relevance_score - 0.5, 0)
        article.category = matched[0] if matched else "Other"
        article.classification_reason = (
            f"Heuristic classification (no LLM key); topics={matched}"
            if matched
            else "Heuristic: no strategic topic match"
        )
        if not article.include:
            article.excluded = True
            article.exclusion_reason = article.classification_reason
        return article

    def summarize_article(self, article: Article) -> Article:
        if article.synopsis and article.why_it_matters:
            return article

        if not self._llm_available():
            snippet = (article.snippet or article.title).strip()
            article.synopsis = snippet if snippet.endswith(".") else snippet + "."
            article.why_it_matters = (
                f"This is a material development for {article.company or 'the firm'} "
                "that executives should track for competitive and strategic context."
            )
            return article

        system = (
            "You write a daily fintech intelligence brief for a busy executive. "
            "Return JSON with keys synopsis and why_it_matters. "
            "Synopsis: factual 2-3 sentences; preserve numbers/orgs/dates; no speculation; do not repeat the headline. "
            "why_it_matters: one sentence."
        )
        user = json.dumps(
            {
                "title": article.title,
                "publication": article.publication,
                "company": article.company,
                "snippet": article.snippet,
            }
        )
        try:
            raw = self._chat_json(system, user)
            summary = StorySummary.model_validate(raw)
            article.synopsis = summary.synopsis
            article.why_it_matters = summary.why_it_matters
        except Exception as exc:
            if self._is_fatal_llm_error(exc):
                self._disable_llm(str(exc)[:180])
            logger.warning("Summarization failed for %s, using snippet", article.title)
            article.synopsis = article.snippet or article.title
            article.why_it_matters = "Material company-specific development for executive awareness."
        return article

    def build_watchlist(self, ranked: list[Article], top_n: int) -> list[str]:
        leftovers = ranked[top_n: top_n + 3]
        items = []
        for a in leftovers:
            label = a.category or "development"
            company = a.company or "Firm"
            items.append(f"{company} - {label}")
        return items

    def run(self) -> DailyBrief:
        preferences = self.memory.load_preferences()
        exclude_keywords = list(self.config["topics"]["exclude"])
        lookback = int(self.settings.get("lookback_hours", 24))
        min_score = float(self.settings.get("min_relevance_score", 7))
        max_articles = int(self.settings.get("max_articles", 7))
        min_target = int(self.settings.get("min_stories_target", 5))
        max_rounds = int(self.settings.get("max_search_rounds", 2))

        all_raw: list[Article] = []
        relevant: list[Article] = []
        round_used = 0

        for round_idx in range(1, max_rounds + 1):
            round_used = round_idx
            queries = self.create_queries(preferences, round_idx=round_idx)
            logger.info("Search round %s - %s queries", round_idx, len(queries))
            raw = self.gather_articles(queries)
            all_raw.extend(raw)

            filtered = apply_hard_filters(
                raw,
                lookback_hours=lookback,
                exclude_keywords=exclude_keywords,
            )

            classified: list[Article] = []
            for article in filtered:
                try:
                    classified.append(self.classify_article(article))
                except Exception:
                    logger.exception("Skipping broken article: %s", article.title)

            batch_relevant = [
                a for a in classified
                if a.include and (a.relevance_score or 0) >= min_score
            ]
            relevant.extend(batch_relevant)

            unique_so_far = deduplicate(relevant)
            if len(unique_so_far) >= min_target:
                break
            logger.info(
                "Coverage low (%s < %s), maybe another round",
                len(unique_so_far),
                min_target,
            )

        unique_events = deduplicate(relevant)
        fresh = [a for a in unique_events if not self.memory.was_seen(a.url)]
        if len(fresh) >= min(3, max_articles):
            unique_events = fresh

        ranked = rank_articles(
            unique_events,
            weights=self.config.get("ranking_weights", {}),
            source_map=self.config.get("source_quality", {}),
            preference_fn=lambda a: self.memory.preference_score_for(a, preferences),
        )

        top_stories = ranked[:max_articles]
        summarized: list[Article] = []
        for story in top_stories:
            try:
                summarized.append(self.summarize_article(story))
            except Exception:
                logger.exception("Summary failed, keeping story anyway")
                story.synopsis = story.snippet or story.title
                story.why_it_matters = "Included despite summarization failure."
                summarized.append(story)

        if not summarized:
            placeholder = Article(
                title="No material developments above threshold",
                url="https://example.com/fintech-intelligence",
                publication="System",
                synopsis=(
                    "The agent reviewed available sources for the last 24 hours and did not find "
                    "enough company-specific developments that cleared exclusion and relevance gates."
                ),
                why_it_matters="A quiet brief is preferable to padding with share-price or conference noise.",
                relevance_score=0,
                final_score=0,
            )
            summarized = [placeholder]

        watchlist = self.build_watchlist(ranked, max_articles)
        brief = render_email(
            summarized,
            timezone_name=self.settings.get("timezone", "Asia/Kolkata"),
            watchlist=watchlist,
        )
        brief.search_rounds = round_used
        brief.raw_count = len(all_raw)
        brief.relevant_count = len(relevant)

        dry_run = bool(self.settings.get("dry_run", True))
        if os.getenv("DRY_RUN") is not None:
            dry_run = os.getenv("DRY_RUN", "true").lower() in {"1", "true", "yes"}

        send_daily_brief(
            recipient=os.getenv("EMAIL_TO", "executive@example.com"),
            subject=brief.subject,
            html_body=brief.html_body,
            dry_run=dry_run,
        )

        self.memory.record_run(summarized, notes=f"rounds={round_used}; raw={len(all_raw)}")
        self.memory.learn_from_brief(summarized)
        return brief
