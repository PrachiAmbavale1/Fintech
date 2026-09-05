from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models import Article


DEFAULT_TOPIC_SCORES = {
    "artificial intelligence": 0.7,
    "acquisitions": 0.65,
    "mergers": 0.65,
    "partnerships": 0.6,
    "regulation": 0.55,
    "cybersecurity": 0.6,
    "product launches": 0.55,
    "technology": 0.6,
    "digital banking": 0.6,
    "strategic investments": 0.6,
    "leadership changes": 0.5,
    "operational developments": 0.5,
}


class PreferenceMemory:
    def __init__(self, db_path: str | Path = "data/memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS preferences (
                    topic TEXT PRIMARY KEY,
                    score REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS company_preferences (
                    company TEXT PRIMARY KEY,
                    score REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS story_history (
                    url TEXT PRIMARY KEY,
                    title TEXT,
                    event_hash TEXT,
                    company TEXT,
                    category TEXT,
                    seen_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal TEXT NOT NULL,
                    topic TEXT,
                    company TEXT,
                    weight REAL NOT NULL,
                    note TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_at TEXT NOT NULL,
                    story_count INTEGER,
                    notes TEXT
                );
                """
            )
            count = conn.execute("SELECT COUNT(*) AS c FROM preferences").fetchone()["c"]
            if count == 0:
                now = datetime.now(timezone.utc).isoformat()
                conn.executemany(
                    "INSERT INTO preferences(topic, score, updated_at) VALUES (?, ?, ?)",
                    [(t, s, now) for t, s in DEFAULT_TOPIC_SCORES.items()],
                )

    def load_preferences(self) -> dict[str, float]:
        with self._connect() as conn:
            rows = conn.execute("SELECT topic, score FROM preferences").fetchall()
        return {r["topic"]: float(r["score"]) for r in rows}

    def load_company_preferences(self) -> dict[str, float]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT company, score FROM company_preferences"
            ).fetchall()
        return {r["company"]: float(r["score"]) for r in rows}

    def set_topic_score(self, topic: str, score: float) -> None:
        score = max(0.0, min(1.0, score))
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences(topic, score, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(topic) DO UPDATE SET
                    score=excluded.score,
                    updated_at=excluded.updated_at
                """,
                (topic.lower(), score, now),
            )

    def apply_feedback(self, signal: str, topic: Optional[str] = None, company: Optional[str] = None, note: str = "") -> None:
        signal = signal.strip().lower()
        if signal in {"more", "up", "boost", "like"}:
            weight = 0.15
        elif signal in {"less", "down", "reduce", "dislike"}:
            weight = -0.2
        elif signal in {"neutral", "ok"}:
            weight = 0.0
        else:
            weight = 0.1

        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback(signal, topic, company, weight, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (signal, topic, company, weight, note, now),
            )

            if topic:
                row = conn.execute(
                    "SELECT score FROM preferences WHERE topic = ?",
                    (topic.lower(),),
                ).fetchone()
                current = float(row["score"]) if row else 0.5
                new_score = max(0.0, min(1.0, current + weight))
                conn.execute(
                    """
                    INSERT INTO preferences(topic, score, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(topic) DO UPDATE SET
                        score=excluded.score,
                        updated_at=excluded.updated_at
                    """,
                    (topic.lower(), new_score, now),
                )

            if company:
                row = conn.execute(
                    "SELECT score FROM company_preferences WHERE company = ?",
                    (company,),
                ).fetchone()
                current = float(row["score"]) if row else 0.5
                new_score = max(0.0, min(1.0, current + weight))
                conn.execute(
                    """
                    INSERT INTO company_preferences(company, score, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(company) DO UPDATE SET
                        score=excluded.score,
                        updated_at=excluded.updated_at
                    """,
                    (company, new_score, now),
                )

    def preference_score_for(self, article: Article, topic_prefs: dict[str, float] | None = None) -> float:
        topic_prefs = topic_prefs or self.load_preferences()
        company_prefs = self.load_company_preferences()

        category = (article.category or "").lower()
        best = 0.5
        for topic, score in topic_prefs.items():
            if topic in category or topic in (article.title or "").lower():
                best = max(best, score)

        if article.company and article.company in company_prefs:
            best = 0.6 * best + 0.4 * company_prefs[article.company]

        return best

    def was_seen(self, url: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM story_history WHERE url = ?",
                (url.rstrip("/").lower(),),
            ).fetchone()
        return row is not None

    def record_run(self, stories: list[Article], notes: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO runs(run_at, story_count, notes) VALUES (?, ?, ?)",
                (now, len(stories), notes),
            )
            for s in stories:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO story_history(url, title, event_hash, company, category, seen_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        s.url.rstrip("/").lower(),
                        s.title,
                        s.event_hash,
                        s.company,
                        s.category,
                        now,
                    ),
                )

    def learn_from_brief(self, stories: list[Article], *, weight: float = 0.03) -> None:
        # small bump for topics that made the brief
        if not stories:
            return
        now = datetime.now(timezone.utc).isoformat()
        topic_keys = list(DEFAULT_TOPIC_SCORES.keys())
        with self._connect() as conn:
            for story in stories:
                if (story.publication or "").lower() == "system":
                    continue
                haystack = " ".join(
                    filter(
                        None,
                        [
                            story.category,
                            story.title,
                            story.synopsis,
                            story.query_used,
                        ],
                    )
                ).lower()
                for topic in topic_keys:
                    if topic not in haystack:
                        continue
                    row = conn.execute(
                        "SELECT score FROM preferences WHERE topic = ?",
                        (topic,),
                    ).fetchone()
                    current = float(row["score"]) if row else float(DEFAULT_TOPIC_SCORES.get(topic, 0.5))
                    new_score = max(0.0, min(1.0, current + weight))
                    conn.execute(
                        """
                        INSERT INTO preferences(topic, score, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(topic) DO UPDATE SET
                            score=excluded.score,
                            updated_at=excluded.updated_at
                        """,
                        (topic, new_score, now),
                    )
                    conn.execute(
                        """
                        INSERT INTO feedback(signal, topic, company, weight, note, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        ("implicit", topic, story.company, weight, "selected for brief", now),
                    )
                if story.company:
                    row = conn.execute(
                        "SELECT score FROM company_preferences WHERE company = ?",
                        (story.company,),
                    ).fetchone()
                    current = float(row["score"]) if row else 0.5
                    new_score = max(0.0, min(1.0, current + weight))
                    conn.execute(
                        """
                        INSERT INTO company_preferences(company, score, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(company) DO UPDATE SET
                            score=excluded.score,
                            updated_at=excluded.updated_at
                        """,
                        (story.company, new_score, now),
                    )

    def boosted_topics(self, limit: int = 3) -> list[str]:
        prefs = self.load_preferences()
        ranked = sorted(prefs.items(), key=lambda x: x[1], reverse=True)
        return [t for t, score in ranked if score >= 0.6][:limit]
