from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import yaml

logger = logging.getLogger(__name__)


def _zoneinfo(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        from datetime import timezone as dt_timezone

        logger.warning("Timezone %s missing, using UTC", name)
        return dt_timezone.utc


def load_schedule_settings(config_path: str | Path = "config.yaml") -> tuple[int, int, str]:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    settings = cfg.get("settings", {})
    hour = int(settings.get("email_hour", 9))
    minute = int(settings.get("email_minute", 0))
    tz_name = str(settings.get("timezone", "Asia/Kolkata"))
    return hour, minute, tz_name


def next_run_at(hour: int, minute: int, tz_name: str, now: datetime | None = None) -> datetime:
    tz = _zoneinfo(tz_name)
    now = now.astimezone(tz) if now else datetime.now(tz)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return target


def seconds_until(target: datetime, now: datetime | None = None) -> float:
    tz = target.tzinfo
    now = now.astimezone(tz) if now else datetime.now(tz)  # type: ignore[arg-type]
    return max(0.0, (target - now).total_seconds())


def run_daily_scheduler(
    job: Callable[[], None],
    *,
    config_path: str | Path = "config.yaml",
    run_immediately: bool = False,
) -> None:
    hour, minute, tz_name = load_schedule_settings(config_path)
    logger.info("Scheduler started - daily at %02d:%02d %s", hour, minute, tz_name)

    if run_immediately:
        logger.info("Running once before waiting for next slot")
        _safe_run(job)

    while True:
        target = next_run_at(hour, minute, tz_name)
        wait_s = seconds_until(target)
        logger.info(
            "Next run at %s (in %.0f seconds / %.1f hours)",
            target.isoformat(),
            wait_s,
            wait_s / 3600.0,
        )

        # sleep in small chunks so Ctrl+C works
        deadline = time.time() + wait_s
        while time.time() < deadline:
            remaining = deadline - time.time()
            time.sleep(min(30.0, max(0.5, remaining)))

        logger.info("Scheduled time reached - running brief")
        _safe_run(job)


def _safe_run(job: Callable[[], None]) -> None:
    try:
        job()
    except Exception:
        logger.exception("Scheduled run failed - will try again tomorrow")
