# Fintech Daily Brief

Python pipeline that pulls fintech news for a configured bank/asset-manager watchlist, keeps items from the last 24 hours, ranks them, and sends an HTML email brief.

Stack: search APIs + LLM classification/summarization (Groq or OpenAI) + Gmail API. Local schedule via CLI; production schedule via GitHub Actions cron (09:00 IST).

## Setup

```powershell
cd "C:\path\to\Fintech Project"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Add a `.env` in the project root:

```
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
EMAIL_TO=you@gmail.com
EMAIL_FROM=you@gmail.com
DRY_RUN=true
TAVILY_API_KEY=
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
```

`EMAIL_TO` accepts comma-separated addresses. Place Google OAuth desktop credentials as `credentials.json`; the first live send writes `token.json`. Keep `.env`, `credentials.json`, and `token.json` out of git.

Watchlist and timing live in `config.yaml` (`email_hour`, `timezone`, `lookback_hours`).

## Run

```powershell
.\.venv\Scripts\activate
python main.py --run-now      # one live brief now
python main.py --schedule     # wait for next 09:00 IST, then every day
```

With `DRY_RUN=true`, output is written to `sample_email.html` and `data/runs/`. Set `DRY_RUN=false` to send mail.

GitHub Actions workflow `.github/workflows/daily-brief.yml` runs the same job on a cron without keeping a machine online. Configure repo secrets for keys and Gmail JSON.

## Layout

- `main.py` – CLI
- `agent.py` – end-to-end run
- `search.py` – news retrieval
- `filters.py` – lookback, exclusions, dedupe
- `ranking.py` – scoring
- `memory.py` – preference store (SQLite)
- `email_out.py` – HTML + Gmail
- `scheduler.py` – local daily loop
- `config.yaml` – companies, topics, settings
- `tests/` – pipeline tests
