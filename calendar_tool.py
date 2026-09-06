from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def _zoneinfo(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        from datetime import timezone as dt_timezone

        return dt_timezone.utc


def ensure_daily_brief_event(config_path: str | Path = "config.yaml") -> str | None:
    token_file = os.getenv("GMAIL_TOKEN_FILE", "token.json")
    creds_file = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
    if not Path(creds_file).exists():
        logger.info("Calendar sync skipped - credentials.json missing")
        return None

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        logger.info("Calendar sync skipped - Google API libs not installed")
        return None

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    settings = cfg.get("settings", {})
    hour = int(settings.get("email_hour", 9))
    minute = int(settings.get("email_minute", 0))
    tz_name = str(settings.get("timezone", "Asia/Kolkata"))

    scopes = [
        "https://www.googleapis.com/auth/gmail.send",
        CALENDAR_SCOPE,
    ]

    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, scopes)

    if creds and creds.valid and not creds.has_scopes([CALENDAR_SCOPE]):
        logger.info("Calendar sync skipped - token has Gmail only")
        return None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                logger.info("Calendar sync skipped - token refresh failed")
                return None
        else:
            logger.info("Calendar sync skipped - no calendar token")
            return None

    service = build("calendar", "v3", credentials=creds)
    tz = _zoneinfo(tz_name)
    start = datetime.now(tz).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if start < datetime.now(tz):
        start = start + timedelta(days=1)
    end = start + timedelta(minutes=15)

    existing = (
        service.events()
        .list(
            calendarId="primary",
            privateExtendedProperty=["fintech_agent=daily_brief"],
            maxResults=1,
            singleEvents=False,
        )
        .execute()
        .get("items", [])
    )

    body = {
        "summary": "FinTech Intelligence Brief",
        "description": "Daily fintech brief reminder.",
        "start": {"dateTime": start.isoformat(), "timeZone": tz_name},
        "end": {"dateTime": end.isoformat(), "timeZone": tz_name},
        "recurrence": ["RRULE:FREQ=DAILY"],
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": 5}]},
        "extendedProperties": {"private": {"fintech_agent": "daily_brief"}},
    }

    if existing:
        event_id = existing[0]["id"]
        updated = (
            service.events()
            .patch(calendarId="primary", eventId=event_id, body=body)
            .execute()
        )
        logger.info("Updated calendar event id=%s", updated.get("id"))
        return updated.get("id")

    created = service.events().insert(calendarId="primary", body=body).execute()
    logger.info("Created calendar event id=%s", created.get("id"))
    return created.get("id")
