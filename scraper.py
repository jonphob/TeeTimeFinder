#!/usr/bin/env python3
"""
TeetimeFinder - Monitor St Annes Old Links competition tee sheet
and alert when an early tee time becomes available.
"""

import argparse
import json
import logging
import os
import re
import smtplib
import sys
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

MEMBER_ID = os.getenv("MEMBER_ID")
MEMBER_PIN = os.getenv("MEMBER_PIN")
PLAYER_NAME = os.getenv("PLAYER_NAME")
CUTOFF_TIME = os.getenv("CUTOFF_TIME", "10:00")
ACTIVE_START = os.getenv("ACTIVE_START", "06:00")
ACTIVE_END   = os.getenv("ACTIVE_END",   "23:00")
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
ALERT_TO = os.getenv("ALERT_TO")

BASE_URL = "https://www.stannesoldlinks.com"
LOGIN_URL = f"{BASE_URL}/member_login"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def login() -> requests.Session:
    """Authenticate with the club website and return an authenticated session."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; TeetimeFinder/1.0)"
    })

    log.info("Fetching login page...")
    resp = session.get(LOGIN_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    # Collect all hidden form fields
    form = soup.find("form")
    payload = {}
    if form:
        for hidden in form.find_all("input", type="hidden"):
            name = hidden.get("name")
            value = hidden.get("value", "")
            if name:
                payload[name] = value

    payload["memberid"] = MEMBER_ID
    payload["pin"] = MEMBER_PIN

    log.info("Submitting login credentials...")
    resp = session.post(LOGIN_URL, data=payload, timeout=30)
    resp.raise_for_status()

    # Check if login succeeded: the login form should no longer be present
    soup_after = BeautifulSoup(resp.text, "html.parser")
    pin_input = soup_after.find("input", {"name": "pin"})

    if pin_input is not None:
        raise RuntimeError("Login failed: PIN input field still present after login attempt")

    log.info("Login successful.")
    return session


# ---------------------------------------------------------------------------
# Competition Discovery
# ---------------------------------------------------------------------------

COMP_LIST_URL = f"{BASE_URL}/competition2.php?time=future"


def parse_comp_date(date_str: str) -> date | None:
    """Parse a date string like 'Saturday  7th March' into a date object."""
    # Strip ordinal suffixes: 1st, 2nd, 3rd, 4th..31st
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str.strip())
    for fmt in ("%A %d %B", "%A  %d %B"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            today = date.today()
            # Try current year first; if in the past use next year
            candidate = parsed.replace(year=today.year).date()
            if candidate < today:
                candidate = parsed.replace(year=today.year + 1).date()
            return candidate
        except ValueError:
            continue
    return None


def find_next_saturday_comp(session: requests.Session) -> dict | None:
    """Find the next upcoming Saturday competition. Returns dict or None."""
    import re as _re

    log.info("Fetching upcoming competitions list...")
    resp = session.get(COMP_LIST_URL, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table")
    if not table:
        log.warning("No competitions table found on future comps page.")
        return None

    saturday_comps = []
    for row in table.find_all("tr"):
        name_td = row.find("td", class_="comp-name-td")
        if not name_td:
            continue
        date_div = name_td.find("div", class_="comp-date")
        name_div = name_td.find("div", class_="comp-name")
        if not date_div or not name_div:
            continue

        date_text = date_div.get_text(strip=True)
        if "Saturday" not in date_text:
            continue

        comp_date = parse_comp_date(date_text)
        if comp_date is None:
            log.warning(f"Could not parse date: {date_text!r}")
            continue

        link = name_div.find("a", href=_re.compile(r"compid="))
        if not link:
            continue

        compid_match = _re.search(r"compid=(\d+)", link["href"])
        if not compid_match:
            continue

        compid = compid_match.group(1)
        name = link.get_text(strip=True)

        saturday_comps.append({"compid": compid, "name": name, "date": comp_date})

    if not saturday_comps:
        return None

    # Sort by date and return the nearest upcoming one
    saturday_comps.sort(key=lambda x: x["date"])
    return saturday_comps[0]


# ---------------------------------------------------------------------------
# Tee Sheet Parsing
# ---------------------------------------------------------------------------

STARTSHEET_URL = f"{BASE_URL}/competition.php?go=startsheet&compid={{compid}}"


def parse_teesheet(session: requests.Session, compid: str, debug: bool = False) -> list[dict]:
    """
    Fetch and parse the competition start sheet.
    Returns list of dicts: [{time: '08:00', players: ['A Smith', '', 'B Jones', '']}]
    Empty player slots are represented as empty strings.
    """
    url = STARTSHEET_URL.format(compid=compid)
    log.info(f"Fetching start sheet for compid={compid}...")
    resp = session.get(url, timeout=30)
    resp.raise_for_status()

    if debug:
        with open("debug_output.html", "w", encoding="utf-8") as f:
            f.write(resp.text)
        log.info("Raw HTML saved to debug_output.html")

    soup = BeautifulSoup(resp.text, "html.parser")
    table = soup.find("table", class_="startsheettable")
    if not table:
        log.warning("No startsheettable found on start sheet page.")
        return []

    tee_times = []
    for row in table.find_all("tr"):
        time_td = row.find("td", class_="startsheet_time")
        if not time_td:
            continue  # header or non-data row

        time_str = time_td.get_text(strip=True)

        players = []
        for slot_td in row.find_all("td", class_="slot"):
            # Remove the handicap span and course name italic
            for tag in slot_td.find_all(["span", "i"]):
                tag.decompose()
            name = slot_td.get_text(strip=True).replace("\xa0", "").strip()
            players.append(name)

        tee_times.append({"time": time_str, "players": players})

    log.info(f"Parsed {len(tee_times)} tee time rows.")
    return tee_times


# ---------------------------------------------------------------------------
# Analysis + Deduplication
# ---------------------------------------------------------------------------

LAST_ALERT_FILE = "last_alert.json"


def parse_time(time_str: str):
    """Parse HH:MM string to datetime.time."""
    return datetime.strptime(time_str, "%H:%M").time()


def analyse(tee_times: list[dict]) -> dict:
    """
    Analyse the tee sheet.
    Returns a dict:
      {
        player_time: str | None,       # e.g. '12:10', or None if not found
        player_not_entered: bool,
        alert_needed: bool,
        available_early_slots: [{'time': str, 'empty_slots': int}]
      }
    """
    cutoff = parse_time(CUTOFF_TIME)
    player_name_lower = PLAYER_NAME.lower()

    player_time = None
    for row in tee_times:
        for name in row["players"]:
            if name and player_name_lower in name.lower():
                player_time = row["time"]
                break
        if player_time:
            break

    if player_time is None:
        log.info(f"Player '{PLAYER_NAME}' not found on tee sheet.")
        return {
            "player_time": None,
            "player_not_entered": True,
            "alert_needed": False,
            "available_early_slots": [],
        }

    player_t = parse_time(player_time)
    log.info(f"Player '{PLAYER_NAME}' found at {player_time} (cutoff {CUTOFF_TIME})")

    if player_t < cutoff:
        log.info("Player already has an early tee time — no alert needed.")
        return {
            "player_time": player_time,
            "player_not_entered": False,
            "alert_needed": False,
            "available_early_slots": [],
        }

    # Player is at or after cutoff — find early slots with vacancies
    available_early_slots = []
    for row in tee_times:
        try:
            row_t = parse_time(row["time"])
        except ValueError:
            continue  # skip header or non-time rows
        if row_t >= cutoff:
            continue
        empty_count = sum(1 for p in row["players"] if not p)
        if empty_count > 0:
            available_early_slots.append({"time": row["time"], "empty_slots": empty_count})

    alert_needed = len(available_early_slots) > 0
    if alert_needed:
        log.info(f"Alert needed: {len(available_early_slots)} early slot(s) available.")
    else:
        log.info("Player is late but no early slots currently available.")

    return {
        "player_time": player_time,
        "player_not_entered": False,
        "alert_needed": alert_needed,
        "available_early_slots": available_early_slots,
    }


def load_last_alert() -> list:
    """Load previously alerted slots from last_alert.json."""
    if not os.path.exists(LAST_ALERT_FILE):
        return []
    try:
        with open(LAST_ALERT_FILE) as f:
            return json.load(f).get("available_early_slots", [])
    except (json.JSONDecodeError, KeyError):
        return []


def save_last_alert(result: dict) -> None:
    """Persist current alert state to last_alert.json."""
    with open(LAST_ALERT_FILE, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "player_time": result["player_time"],
            "available_early_slots": result["available_early_slots"],
        }, f, indent=2)


def slots_changed(current: list, previous: list) -> bool:
    """Return True if the available early slots have changed."""
    current_times = sorted(s["time"] for s in current)
    previous_times = sorted(s["time"] for s in previous)
    return current_times != previous_times


# ---------------------------------------------------------------------------
# Prometheus Metrics
# ---------------------------------------------------------------------------

PROM_FILE = "/var/lib/prometheus/node-exporter/teetime.prom"


def write_metrics(result: dict, alert_sent: bool, run_success: bool) -> None:
    """Write Prometheus textfile metrics after each run."""
    ts = int(datetime.now().timestamp())

    player_time_minutes = -1
    if result.get("player_time"):
        h, m = result["player_time"].split(":")
        player_time_minutes = int(h) * 60 + int(m)

    early_slots = len(result.get("available_early_slots", []))

    lines = [
        "# HELP teetime_last_run_timestamp_seconds Unix timestamp of last scraper run",
        "# TYPE teetime_last_run_timestamp_seconds gauge",
        f"teetime_last_run_timestamp_seconds {ts}",
        "# HELP teetime_run_success 1 if last run completed without error",
        "# TYPE teetime_run_success gauge",
        f"teetime_run_success {1 if run_success else 0}",
        "# HELP teetime_player_found 1 if player was found on the tee sheet",
        "# TYPE teetime_player_found gauge",
        f"teetime_player_found {0 if result.get('player_not_entered') else 1}",
        "# HELP teetime_player_time_minutes Player tee time in minutes since midnight (-1 if not found)",
        "# TYPE teetime_player_time_minutes gauge",
        f"teetime_player_time_minutes {player_time_minutes}",
        "# HELP teetime_early_slots_available Number of available slots before cutoff time",
        "# TYPE teetime_early_slots_available gauge",
        f"teetime_early_slots_available {early_slots}",
        "# HELP teetime_alert_sent 1 if an alert email was sent this run",
        "# TYPE teetime_alert_sent gauge",
        f"teetime_alert_sent {1 if alert_sent else 0}",
    ]

    try:
        with open(PROM_FILE, "w") as f:
            f.write("\n".join(lines) + "\n")
        log.info(f"Metrics written to {PROM_FILE}")
    except OSError as e:
        log.warning(f"Could not write metrics file: {e}")


# ---------------------------------------------------------------------------
# Email Alert
# ---------------------------------------------------------------------------


def send_daily_digest(comp: dict | None, result: dict) -> None:
    """Send a daily status/heartbeat email confirming the system is running."""
    now = datetime.now()
    subject = f"TeetimeFinder daily digest — {now.strftime('%a %d %b %Y')}"

    lines = ["TeetimeFinder is running normally.", ""]

    if comp is None:
        lines.append("Next competition: no upcoming Saturday competition found.")
    else:
        lines.append(f"Next competition: {comp['name']} — {comp['date'].strftime('%A %d %B %Y')}")
        if result.get("player_not_entered"):
            lines.append(f"Status: '{PLAYER_NAME}' not yet on the tee sheet.")
        else:
            lines.append(f"Your tee time: {result['player_time']}  (cutoff: {CUTOFF_TIME})")
            if result["alert_needed"]:
                lines.append(f"Early slots available before {CUTOFF_TIME}:")
                for slot in result["available_early_slots"]:
                    lines.append(f"  {slot['time']}  ({slot['empty_slots']} empty place(s))")
            else:
                lines.append("No early slots currently available — nothing to move to yet.")

    lines += ["", "— TeetimeFinder"]

    body = "\n".join(lines)
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_TO

    log.info(f"Sending daily digest to {ALERT_TO}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_USER, [ALERT_TO], msg.as_string())
    log.info("Daily digest sent.")


def send_alert_email(comp: dict, result: dict) -> None:
    """Send an email alert listing available early tee times."""
    slots = result["available_early_slots"]
    subject = f"Early tee time available — {comp['name']} ({comp['date'].strftime('%d %b')})"

    lines = [
        f"Hi Jon,",
        f"",
        f"An early tee time has become available for:",
        f"  {comp['name']} — {comp['date'].strftime('%A %d %B %Y')}",
        f"",
        f"Your current tee time: {result['player_time']}",
        f"Cutoff time:           {CUTOFF_TIME}",
        f"",
        f"Available slots before {CUTOFF_TIME}:",
    ]
    for slot in slots:
        lines.append(f"  {slot['time']}  ({slot['empty_slots']} empty place(s))")
    lines += [
        f"",
        f"Book at: https://www.stannesoldlinks.com/competition.php?go=startsheet&compid={comp['compid']}",
        f"",
        f"— TeetimeFinder",
    ]

    body = "\n".join(lines)
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = ALERT_TO

    log.info(f"Sending alert email to {ALERT_TO}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(SMTP_USER, SMTP_PASS)
        smtp.sendmail(SMTP_USER, [ALERT_TO], msg.as_string())
    log.info("Email sent.")


# ---------------------------------------------------------------------------
# Active hours
# ---------------------------------------------------------------------------


def is_within_active_hours() -> bool:
    """Return True if current local time falls within [ACTIVE_START, ACTIVE_END)."""
    fmt = "%H:%M"
    default_start, default_end = "06:00", "23:00"
    try:
        start = datetime.strptime(ACTIVE_START, fmt).time()
    except ValueError:
        log.warning(f"Invalid ACTIVE_START '{ACTIVE_START}', using default {default_start}")
        start = datetime.strptime(default_start, fmt).time()
    try:
        end = datetime.strptime(ACTIVE_END, fmt).time()
    except ValueError:
        log.warning(f"Invalid ACTIVE_END '{ACTIVE_END}', using default {default_end}")
        end = datetime.strptime(default_end, fmt).time()
    now = datetime.now().time()
    if start <= end:
        return start <= now < end
    # Cross-midnight window (e.g. 22:00–06:00)
    return now >= start or now < end


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="TeetimeFinder")
    parser.add_argument("--test-login", action="store_true", help="Test login only")
    parser.add_argument("--find-comp", action="store_true", help="Find next Saturday competition")
    parser.add_argument("--parse-teesheet", action="store_true", help="Parse competition tee sheet")
    parser.add_argument("--analyse", action="store_true", help="Analyse tee sheet for early slots")
    parser.add_argument("--test-email", action="store_true", help="Send a test email")
    parser.add_argument("--daily-digest", action="store_true", help="Send daily status/heartbeat email")
    parser.add_argument("--debug", action="store_true", help="Save raw HTML to debug_output.html")
    args = parser.parse_args()

    if args.test_login:
        try:
            login()
            print("Login successful")
            sys.exit(0)
        except Exception as exc:
            print(f"Login failed: {exc}")
            sys.exit(1)

    if args.find_comp:
        try:
            session = login()
            comp = find_next_saturday_comp(session)
            if comp:
                print(f"Competition: {comp['name']}")
                print(f"Date:        {comp['date'].strftime('%A %d %B %Y')}")
                print(f"CompID:      {comp['compid']}")
            else:
                print("No upcoming Saturday competition found")
            sys.exit(0)
        except Exception as exc:
            log.error(f"Error finding competition: {exc}")
            sys.exit(1)

    if args.parse_teesheet:
        try:
            session = login()
            comp = find_next_saturday_comp(session)
            if not comp:
                print("No upcoming Saturday competition found")
                sys.exit(0)
            tee_times = parse_teesheet(session, comp["compid"], debug=args.debug)
            if not tee_times:
                print("No tee time rows parsed.")
                sys.exit(1)
            print(f"\nStart sheet: {comp['name']} — {comp['date'].strftime('%A %d %B %Y')}")
            print(f"{'Time':<8} {'Players'}")
            print("-" * 70)
            for row in tee_times:
                players_str = " | ".join(f"{p if p else '(empty)'}" for p in row["players"])
                print(f"{row['time']:<8} {players_str}")
            sys.exit(0)
        except Exception as exc:
            log.error(f"Error parsing tee sheet: {exc}")
            sys.exit(1)

    if args.analyse:
        try:
            session = login()
            comp = find_next_saturday_comp(session)
            if not comp:
                print("No upcoming Saturday competition found")
                sys.exit(0)
            tee_times = parse_teesheet(session, comp["compid"], debug=args.debug)
            result = analyse(tee_times)

            print(f"\nAnalysis: {comp['name']} — {comp['date'].strftime('%A %d %B %Y')}")
            if result["player_not_entered"]:
                print(f"Status: '{PLAYER_NAME}' not found on tee sheet (not yet entered?)")
            else:
                print(f"Your tee time: {result['player_time']}  (cutoff: {CUTOFF_TIME})")
                if result["alert_needed"]:
                    print("Early slots available BEFORE cutoff:")
                    for slot in result["available_early_slots"]:
                        print(f"  {slot['time']}  ({slot['empty_slots']} empty place(s))")
                else:
                    print("No early slots currently available.")

            previous = load_last_alert()
            changed = slots_changed(result["available_early_slots"], previous)
            save_last_alert(result)
            print(f"\nSlots changed since last run: {changed}")
            sys.exit(0)
        except Exception as exc:
            log.error(f"Error during analysis: {exc}")
            sys.exit(1)

    if args.test_email:
        try:
            session = login()
            comp = find_next_saturday_comp(session)
            if not comp:
                comp = {"name": "Test Competition", "date": date.today(), "compid": "00000"}
            test_result = {
                "player_time": "12:10",
                "available_early_slots": [
                    {"time": "08:30", "empty_slots": 2},
                    {"time": "09:00", "empty_slots": 1},
                ],
            }
            send_alert_email(comp, test_result)
            print("Email sent")
            sys.exit(0)
        except Exception as exc:
            log.error(f"Failed to send email: {exc}")
            sys.exit(1)

    if args.daily_digest:
        try:
            session = login()
            comp = find_next_saturday_comp(session)
            digest_result = {"player_not_entered": True, "alert_needed": False, "available_early_slots": []}
            if comp:
                tee_times = parse_teesheet(session, comp["compid"], debug=args.debug)
                if tee_times:
                    digest_result = analyse(tee_times)
            send_daily_digest(comp, digest_result)
            print("Daily digest sent")
            sys.exit(0)
        except Exception as exc:
            log.error(f"Failed to send daily digest: {exc}")
            sys.exit(1)

    # Full run
    result = {"player_not_entered": True, "alert_needed": False, "available_early_slots": []}
    alert_sent = False

    if not any(vars(args).values()) and not is_within_active_hours():
        log.info("Skipped due to time window")
        write_metrics(result, alert_sent, run_success=True)
        sys.exit(0)

    try:
        session = login()

        comp = find_next_saturday_comp(session)
        if not comp:
            log.info("No upcoming Saturday competition found — nothing to do.")
            write_metrics(result, alert_sent, run_success=True)
            sys.exit(0)

        tee_times = parse_teesheet(session, comp["compid"], debug=args.debug)
        if not tee_times:
            log.warning("Could not parse tee sheet — aborting.")
            write_metrics(result, alert_sent, run_success=False)
            sys.exit(1)

        result = analyse(tee_times)

        if result["player_not_entered"]:
            log.info(f"'{PLAYER_NAME}' not on tee sheet yet — no action.")
            write_metrics(result, alert_sent, run_success=True)
            sys.exit(0)

        if not result["alert_needed"]:
            log.info("No alert needed.")
            save_last_alert(result)
            write_metrics(result, alert_sent, run_success=True)
            sys.exit(0)

        previous = load_last_alert()
        if not slots_changed(result["available_early_slots"], previous):
            log.info("Early slots unchanged since last alert — skipping email.")
            write_metrics(result, alert_sent, run_success=True)
            sys.exit(0)

        send_alert_email(comp, result)
        alert_sent = True
        save_last_alert(result)
        write_metrics(result, alert_sent, run_success=True)
        sys.exit(0)

    except Exception as exc:
        log.error(f"Unexpected error: {exc}")
        write_metrics(result, alert_sent, run_success=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
