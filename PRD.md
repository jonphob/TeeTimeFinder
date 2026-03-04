# Product Requirements Document: Tee Time Finder

## Overview

A Python script that monitors the St Annes Old Links Golf Club competition tee sheet
and sends an email alert when a tee time earlier than the user's cutoff time becomes
available. Runs on a Linux server via cron at regular intervals.

## Problem Statement

The user is a member who prefers early tee times. When entered into a Saturday
competition, they are sometimes allocated a late tee time. Currently they must manually
check the tee sheet repeatedly to see if an earlier slot has opened up (e.g. due to
another player withdrawing). This script automates that monitoring.

## Target Website

- Club site: https://www.stannesoldlinks.com/
- Member login: https://www.stannesoldlinks.com/login.php
- Competition tee sheet: https://www.stannesoldlinks.com/competition2.php?tab=details&compid=<COMPID>
- Competition list (AJAX): POST https://www.stannesoldlinks.com/competition2.php
- Platform: IntelligentGolf v10.1.2

## Functional Requirements

1. **Authentication**: Log in using member ID and PIN via session-based cookies.

2. **Competition Discovery**: Automatically find the next upcoming Saturday competition
   by querying the competition list AJAX endpoint. Extract the compid.

3. **Tee Sheet Parsing**: Fetch and parse the competition detail page to extract all
   tee times and the player names allocated to each slot.

4. **Analysis**:
    - Find the user's own tee time by matching `PLAYER_NAME` in the tee sheet.
    - If the user's tee time is at or after `CUTOFF_TIME` (default 10:00), look for
      tee time slots before `CUTOFF_TIME` that have at least one empty player position.

5. **Alert**: Send an email listing available early tee times if the condition is met.

6. **Deduplication**: Only send a new alert if the set of available early slots has
   changed since the last alert. State is stored in `last_alert.json`.

7. **Logging**: All runs produce clean timestamped log output suitable for cron.

## Non-Functional Requirements

- Runs on Linux server (Python 3.x)
- Scheduled via cron (e.g. every 5 minutes)
- Credentials stored in `.env` file (never committed to git)
- Handles errors gracefully (network failures, login failures, no comp found)
- Debug mode dumps raw HTML for selector inspection

## Configuration (.env)

| Variable    | Description                             | Example             |
| ----------- | --------------------------------------- | ------------------- |
| MEMBER_ID   | Member login ID                         | 12345               |
| MEMBER_PIN  | Member PIN                              | 9999                |
| PLAYER_NAME | Name as shown on tee sheet              | J Flitcroft         |
| CUTOFF_TIME | Alert if player's time is at/after this | 10:00               |
| SMTP_HOST   | SMTP server hostname                    | smtp.gmail.com      |
| SMTP_PORT   | SMTP port                               | 587                 |
| SMTP_USER   | SMTP login email                        | you@gmail.com       |
| SMTP_PASS   | SMTP password or app password           | xxxx xxxx xxxx xxxx |
| ALERT_TO    | Email address to receive alerts         | you@gmail.com       |

## CLI Flags

| Flag               | Purpose                                                         |
| ------------------ | --------------------------------------------------------------- |
| `--test-login`     | Test login only, print result, exit                             |
| `--find-comp`      | Find next Saturday comp, print compid, exit                     |
| `--parse-teesheet` | Parse tee sheet, print all rows, exit                           |
| `--analyse`        | Run analysis logic, print result, exit                          |
| `--test-email`     | Send a test email, print result, exit                           |
| `--debug`          | Save raw HTML to debug_output.html                              |
| (no flag)          | Full run: login → find comp → parse → analyse → alert if needed |

## Delivery Chunks

| Chunk | Name                  | Key Deliverables                        |
| ----- | --------------------- | --------------------------------------- |
| 1     | Scaffolding + Login   | requirements.txt, scraper.py login func |
| 2     | Competition Discovery | AJAX call, compid extraction            |
| 3     | Tee Sheet Parsing     | HTML parsing, structured tee time data  |
| 4     | Analysis + Dedup      | Time comparison, last_alert.json        |
| 5     | Email + End-to-End    | SMTP, full run, cron-ready              |

## Success Criteria (Overall)

1. Setting `CUTOFF_TIME=23:59` causes an email to be sent with available early slots.
2. Email contains accurate tee time information from the live tee sheet.
3. Running the script twice with no tee sheet changes sends only one email.
4. Full run completes in under 30 seconds on a standard Linux server.
5. Cron log output is clean and timestamped.
