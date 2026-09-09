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

        # Windows without tzdata used to silently fall back to UTC and miss 09:00 IST.
        if name in {"Asia/Kolkata", "Asia/Calcutta"}:
            logger.warning("Timezone %s missing; using fixed UTC+05:30", name)
            return dt_timezone(timedelta(hours=5, minutes=30))
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


def todays_send_at(hour: int, minute: int, tz_name: str, now: datetime | None = None) -> datetime:
    """Today's clock time in tz (may already be in the past)."""
    tz = _zoneinfo(tz_name)
    now = now.astimezone(tz) if now else datetime.now(tz)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def seconds_until(target: datetime, now: datetime | None = None) -> float:
    tz = target.tzinfo
    now = now.astimezone(tz) if now else datetime.now(tz)  # type: ignore[arg-type]
    return max(0.0, (target - now).total_seconds())


def _sleep_until_deadline(deadline_monotonic: float) -> None:
    """Sleep until wall-clock deadline with finer steps near the end."""
    while True:
        remaining = deadline_monotonic - time.time()
        if remaining <= 0:
            return
        if remaining > 60:
            time.sleep(30.0)
        elif remaining > 5:
            time.sleep(1.0)
        else:
            time.sleep(min(0.25, remaining))


def wait_until_clock(
    hour: int,
    minute: int,
    tz_name: str,
    *,
    now: datetime | None = None,
) -> bool:
    """
    Block until today's hour:minute in tz_name.

    Returns True if we waited, False if the time already passed (send immediately).
    """
    target = todays_send_at(hour, minute, tz_name, now=now)
    wait_s = seconds_until(target, now=now)
    if wait_s <= 0:
        logger.info(
            "Scheduled send time %s already passed — sending now",
            target.isoformat(),
        )
        return False

    logger.info(
        "Holding send until %s (%.0f seconds / %.1f minutes)",
        target.isoformat(),
        wait_s,
        wait_s / 60.0,
    )
    _sleep_until_deadline(time.time() + wait_s)
    logger.info("Scheduled send time reached (%s)", target.isoformat())
    return True


def wait_for_config_send_time(config_path: str | Path = "config.yaml") -> bool:
    hour, minute, tz_name = load_schedule_settings(config_path)
    return wait_until_clock(hour, minute, tz_name)


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

        _sleep_until_deadline(time.time() + wait_s)

        logger.info("Scheduled time reached - running brief")
        _safe_run(job)


def _safe_run(job: Callable[[], None]) -> None:
    try:
        job()
    except Exception:
        logger.exception("Scheduled run failed - will try again tomorrow")
