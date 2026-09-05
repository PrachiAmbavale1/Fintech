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

```bash
# offline sample data
python main.py --run-now --demo

# live run
python main.py --run-now

# daily at 9:00 (config.yaml timezone)
python main.py --schedule

# feedback
python main.py --feedback more --topic "artificial intelligence"

# tests
pytest -q
```

Output:
- `sample_email.html`
- `data/runs/brief_*.html` (when `DRY_RUN=true`)

For real Gmail send: set `DRY_RUN=false`, add `credentials.json`, then run again.

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
