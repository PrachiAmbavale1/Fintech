# FinTech Intelligence Agent

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Make a `.env` file in the project root:

```
GROQ_API_KEY=
GROQ_MODEL=openai/gpt-oss-20b
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
EMAIL_TO=
EMAIL_FROM=
DRY_RUN=true
TAVILY_API_KEY=
GMAIL_CREDENTIALS_FILE=credentials.json
GMAIL_TOKEN_FILE=token.json
```

## Run

Open the project folder first:

```bash
cd "C:\Users\Prachi Ambavale\OneDrive\Desktop\Bank"
.venv\Scripts\activate
```

### Quick commands

```bash
# offline demo (sample articles; safest for review)
python main.py --run-now --demo

# live one-shot brief (needs network / optional API keys)
python main.py --run-now

# daily 9:00 AM IST loop — keep terminal open; stop with Ctrl+C
python main.py --schedule

# run once now, then wait for every following 9:00 AM
python main.py --schedule --run-now

# scheduled run using sample articles
python main.py --schedule --demo

# preference feedback
python main.py --feedback more --topic "artificial intelligence"
python main.py --feedback less --company "Bank of America"

# optional Google Calendar 9 AM reminder
python main.py --sync-calendar

# tests
pytest -q
```

### 9:00 AM morning brief

Config in `config.yaml` (already set):

- `email_hour: 9`
- `email_minute: 0`
- `timezone: Asia/Kolkata` (IST)

```bash
# leave running overnight for the daily 9 AM brief
python main.py --schedule

# test the brief right now (do not wait until morning)
python main.py --run-now --demo
# or live:
python main.py --run-now
```

Notes:

- `--schedule` alone waits until the **next 09:00 IST**, then runs every day.
- `--schedule --run-now` runs once immediately, then waits for each following 9 AM.
- Keep the terminal open while the scheduler is running. Stop with `Ctrl+C`.

### Output

- `sample_email.html`
- `data/runs/brief_YYYYMMDD_HHMMSS.html` (when `DRY_RUN=true`)

For real Gmail send: set `DRY_RUN=false`, add `credentials.json`, fill `EMAIL_TO` / `EMAIL_FROM`, then run again.

## Files

```
main.py              entry / CLI
agent.py             main pipeline
search.py            news search
filters.py           hard filters + dedupe
ranking.py           ranking
memory.py            sqlite preferences
email_out.py         html email + gmail send
models.py            data models
scheduler.py         daily schedule loop
calendar_tool.py     optional google calendar reminder
config.yaml          companies / topics / settings
requirements.txt     deps
sample_email.html    last brief html
data/sample_articles.json
tests/test_pipeline.py
```
