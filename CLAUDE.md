# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TeetimeFinder is a Python scraper that monitors the St Annes Old Links Golf Club competition tee sheet and sends email alerts when early tee times become available. It authenticates via member ID/PIN, finds the next Saturday competition, parses the tee sheet HTML, and emails when slots before `CUTOFF_TIME` open up.

Target site runs IntelligentGolf v10.1.2 at `https://www.stannesoldlinks.com`.

## Running

```bash
# Install dependencies
pip install -r requirements.txt

# Full run (login → find comp → parse → analyse → alert if needed)
python scraper.py

# Individual steps for debugging
python scraper.py --test-login
python scraper.py --find-comp
python scraper.py --parse-teesheet [--debug]
python scraper.py --analyse [--debug]
python scraper.py --test-email

# --debug saves raw HTML to debug_output.html for selector inspection
```

## Configuration

All config via `.env` file (see `.env.example`). Key variables: `MEMBER_ID`, `MEMBER_PIN`, `PLAYER_NAME`, `CUTOFF_TIME`, SMTP settings (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`), `ALERT_TO`.

## Architecture

Single-file application (`scraper.py`) with this pipeline:

1. **Login** — Session-based auth, collects hidden form fields + submits credentials
2. **Competition Discovery** — Scrapes future competitions list, filters for Saturdays, returns nearest
3. **Tee Sheet Parsing** — Parses `startsheettable` HTML table; extracts time slots and player names (empty slots = empty strings)
4. **Analysis** — Finds player's time, checks if after cutoff, identifies available early slots
5. **Deduplication** — Compares current slots against `last_alert.json` to avoid repeat emails
6. **Email Alert** — SMTP with STARTTLS
7. **Prometheus Metrics** — Writes textfile metrics to `/var/lib/prometheus/node-exporter/teetime.prom`

## Deployment

Runs on a Linux server via systemd timer (`teetime.service` + `teetime.timer`) every 5 minutes. Deploy path: `/srv/apps/teetime_scraper` with a `.venv` virtualenv.

## Dependencies

`requests`, `beautifulsoup4`, `python-dotenv` (Python 3.10+ for `X | Y` type union syntax).
