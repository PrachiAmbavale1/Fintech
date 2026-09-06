# FinTech Intelligence Agent

Daily fintech brief: last-24-hour news for watched banks/asset managers → ranked HTML email.

## Requirements

- Python 3.10+
- Groq API key (or OpenAI)
- Gmail OAuth (`credentials.json`) to send mail

## Setup (Windows)

```powershell
cd "C:\path\to\Fintech Project"
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in the project root:

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

- Multiple recipients: `EMAIL_TO=a@gmail.com,b@gmail.com`
- Put Google OAuth desktop credentials at `credentials.json`
- First real send creates `token.json` via browser login
- Do not commit `.env`, `credentials.json`, or `token.json`

Optional: edit companies/topics/timezone in `config.yaml`.

## Commands

```powershell
.\.venv\Scripts\activate

python main.py --run-now
python main.py --schedule
```

| Command | What it does |
| --- | --- |
| `--run-now` | Live last-24h brief abhi bhejo |
| `--schedule` | Har din 9:00 AM IST pe automatic (terminal open rakhna padega) |

`DRY_RUN=true` → writes `sample_email.html` and `data/runs/`.  
`DRY_RUN=false` → sends Gmail.

## macOS / Linux

```bash
cd /path/to/Fintech\ Project
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then create `.env` as above and use the same `python main.py` commands.

## Project layout

```
main.py            CLI
agent.py           pipeline
search.py          news search
filters.py         filters + dedupe
ranking.py         ranking
memory.py          preferences (SQLite)
email_out.py       HTML + Gmail
models.py          models
scheduler.py       local daily loop
calendar_tool.py   optional calendar
config.yaml        watchlist + settings
requirements.txt
data/
tests/
```
