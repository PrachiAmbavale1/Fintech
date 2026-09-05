from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Article(BaseModel):
    title: str
    url: str
    publication: str = "Unknown"
    published_at: Optional[datetime] = None

    company: Optional[str] = None
    snippet: Optional[str] = None
    query_used: Optional[str] = None

    category: Optional[str] = None
    include: Optional[bool] = None
    relevance_score: Optional[float] = None
    strategic_score: Optional[float] = None
    business_impact_score: Optional[float] = None
    executive_relevance: Optional[float] = None
    classification_reason: Optional[str] = None

    preference_score: float = 0.5
    source_quality: float = 0.55
    final_score: Optional[float] = None

    synopsis: Optional[str] = None
    why_it_matters: Optional[str] = None

    excluded: bool = False
    exclusion_reason: Optional[str] = None
    event_hash: Optional[str] = None


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "include", "relevant"}
    return False


def _as_score(v: Any, default: float = 5.0) -> float:
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    # some models give 0-100
    if x > 10:
        x = x / 10.0
    return max(0.0, min(10.0, x))


class ClassificationResult(BaseModel):
    include: bool = False
    score: float = Field(default=5.0)
    category: str = "Other"
    strategic_importance: float = Field(default=5.0)
    business_impact: float = Field(default=5.0)
    executive_relevance: float = Field(default=5.0)
    reason: str = ""

    @field_validator("include", mode="before")
    @classmethod
    def coerce_include(cls, v: Any) -> bool:
        return _as_bool(v)

    @field_validator(
        "score",
        "strategic_importance",
        "business_impact",
        "executive_relevance",
        mode="before",
    )
    @classmethod
    def coerce_scores(cls, v: Any) -> float:
        return _as_score(v)

    @field_validator("category", "reason", mode="before")
    @classmethod
    def coerce_str(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        return str(v)


class StorySummary(BaseModel):
    synopsis: str
    why_it_matters: str

    @field_validator("synopsis", "why_it_matters", mode="before")
    @classmethod
    def coerce_text(cls, v: Any) -> str:
        if v is None:
            return ""
        if isinstance(v, list):
            return " ".join(str(x) for x in v)
        return str(v).strip()


class DailyBrief(BaseModel):
    generated_at: datetime
    timezone: str
    stories: list[Article]
    watchlist: list[str] = Field(default_factory=list)
    subject: str = ""
    html_body: str = ""
    search_rounds: int = 1
    raw_count: int = 0
    relevant_count: int = 0
