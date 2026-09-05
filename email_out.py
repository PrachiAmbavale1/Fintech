from __future__ import annotations

import base64
import logging
import os
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from datetime import timezone as dt_timezone

from jinja2 import Template

from models import Article, DailyBrief

logger = logging.getLogger(__name__)


def _zoneinfo(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        logger.warning("Timezone %s missing, using UTC", name)
        return dt_timezone.utc

EMAIL_TEMPLATE = Template(
    """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>FinTech Intelligence Brief</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Georgia,'Times New Roman',serif;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f4f6f8;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="background:#ffffff;border:1px solid #e5e7eb;">
          <tr>
            <td style="padding:28px 32px 12px 32px;border-bottom:2px solid #0f2744;">
              <div style="font-size:12px;letter-spacing:0.12em;color:#6b7280;text-transform:uppercase;">Daily Brief</div>
              <h1 style="margin:8px 0 4px 0;font-size:26px;color:#0f2744;">FinTech Intelligence Brief</h1>
              <div style="color:#4b5563;font-size:14px;">{{ date_str }} · Last 24 hours · {{ story_count }} material developments</div>
            </td>
          </tr>

          {% for story in stories %}
          <tr>
            <td style="padding:24px 32px;border-bottom:1px solid #eef2f7;">
              <div style="font-size:12px;color:#6b7280;margin-bottom:6px;">{{ loop.index }}. {{ story.publication }}{% if story.company %} · {{ story.company }}{% endif %}</div>
              <h2 style="margin:0 0 10px 0;font-size:18px;line-height:1.35;color:#111827;">{{ story.title }}</h2>
              <p style="margin:0 0 10px 0;font-size:15px;line-height:1.55;color:#374151;">{{ story.synopsis }}</p>
              <p style="margin:0 0 12px 0;font-size:14px;line-height:1.5;color:#1f2937;">
                <strong style="color:#0f2744;">Why it matters:</strong> {{ story.why_it_matters }}
              </p>
              <a href="{{ story.url }}" style="color:#0b5fff;font-size:14px;text-decoration:none;">Read full story →</a>
            </td>
          </tr>
          {% endfor %}

          {% if watchlist %}
          <tr>
            <td style="padding:22px 32px;background:#f8fafc;">
              <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#6b7280;margin-bottom:8px;">Watchlist</div>
              <ul style="margin:0;padding-left:18px;color:#374151;font-size:14px;line-height:1.6;">
                {% for item in watchlist %}
                <li>{{ item }}</li>
                {% endfor %}
              </ul>
            </td>
          </tr>
          {% endif %}
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
""".strip()
)


def render_email(
    stories: list[Article],
    *,
    timezone_name: str = "Asia/Kolkata",
    watchlist: list[str] | None = None,
    generated_at: datetime | None = None,
) -> DailyBrief:
    tz = _zoneinfo(timezone_name)
    generated_at = generated_at or datetime.now(tz)
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=tz)
    else:
        generated_at = generated_at.astimezone(tz)

    date_str = generated_at.strftime("%B %d, %Y")
    html = EMAIL_TEMPLATE.render(
        date_str=date_str,
        story_count=len(stories),
        stories=stories,
        watchlist=watchlist or [],
    )
    subject = f"FinTech Intelligence Brief — {date_str} ({len(stories)} developments)"
    return DailyBrief(
        generated_at=generated_at,
        timezone=timezone_name,
        stories=stories,
        watchlist=watchlist or [],
        subject=subject,
        html_body=html,
    )


def send_daily_brief(
    recipient: str,
    subject: str,
    html_body: str,
    *,
    dry_run: bool = True,
    output_dir: str | Path = "data/runs",
) -> str:
    if dry_run or os.getenv("DRY_RUN", "true").lower() in {"1", "true", "yes"}:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = out / f"brief_{stamp}.html"
        path.write_text(html_body, encoding="utf-8")
        Path("sample_email.html").write_text(html_body, encoding="utf-8")
        logger.info("DRY_RUN: wrote email to %s", path)
        return str(path)

    return _send_gmail(recipient, subject, html_body)


def _send_gmail(recipient: str, subject: str, html_body: str) -> str:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/gmail.send"]
    creds_file = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
    token_file = os.getenv("GMAIL_TOKEN_FILE", "token.json")

    creds = None
    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, scopes)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(creds_file).exists():
                raise FileNotFoundError(
                    f"Missing {creds_file}. Enable Gmail API and download OAuth client credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, scopes)
            print("\n=== Gmail auth ===")
            print("1) Open the browser URL")
            print("2) Login with EMAIL_FROM")
            print("3) Allow access, then come back here\n")
            creds = flow.run_local_server(port=0, open_browser=True, prompt="consent")
        Path(token_file).write_text(creds.to_json(), encoding="utf-8")

    service = build("gmail", "v1", credentials=creds)
    message = MIMEText(html_body, "html")
    message["to"] = recipient
    message["from"] = os.getenv("EMAIL_FROM", recipient)
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    logger.info("Gmail sent message id=%s", sent.get("id"))
    return sent.get("id", "")
