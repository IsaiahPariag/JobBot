cat << 'EOF' > run_once.py
import os
import sqlite3
from datetime import datetime, timezone
import requests

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1566561896583266385/UcO1lypDvEunsA9GPiIGL1usfpCGMPhNiDIQ2KnR8Xg0v-S1f1WDchKK699SK5ueLo7H"
DB_PATH = "jobs.db"

# Match roles
INCLUDE_KEYWORDS = [
    "data analyst", "data analytics", "data intern",
    "software engineer intern", "swe intern", "data entry",
    "python", "sql", "junior data", "micro-internship", "junior developer"
]

# Disqualifiers
EXCLUDE_KEYWORDS = [
    "senior", "lead", "principal", "manager", "director",
    "phd", "master", "clearance required", "ts/sci"
]

# Standard US & Global Tech Boards
GREENHOUSE_COMPANIES = [
    "amplify", "instacart", "datadog", "figma", "reddit",
    "discord", "stripe", "gitlab", "cloudflare", "affirm"
]

LEVER_COMPANIES = [
    "spotify", "palantir", "benchling", "coursera"
]

# Caribbean / Global allowed locations
ALLOWED_LOCATIONS = [
    "remote", "anywhere", "worldwide", "global",
    "caribbean", "trinidad", "jamaica", "barbados",
    "latin america", "latam", "americas"
]

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seen_jobs (
                job_id TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                url TEXT,
                date_found TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

def is_job_seen(job_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM seen_jobs WHERE job_id = ?", (job_id,))
        return cursor.fetchone() is not None

def mark_job_seen(job_id, title, company, url):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO seen_jobs (job_id, title, company, url) VALUES (?, ?, ?, ?)",
            (job_id, title, company, url)
        )
        conn.commit()

def is_relevant_role(title):
    t = title.lower()
    if any(ex in t for ex in EXCLUDE_KEYWORDS):
        return False
    return any(inc in t for inc in INCLUDE_KEYWORDS)

def is_valid_location(location_str):
    if not location_str:
        return True
    loc = location_str.lower()
    return any(target in loc for target in ALLOWED_LOCATIONS)

def format_timestamp(dt_val):
    try:
        if isinstance(dt_val, (int, float)):
            dt = datetime.fromtimestamp(dt_val / 1000, tz=timezone.utc)
            return dt.strftime("%b %d, %Y")
        elif isinstance(dt_val, str) and dt_val:
            dt = datetime.fromisoformat(dt_val.replace("Z", "+00:00"))
            return dt.strftime("%b %d, %Y")
    except Exception:
        pass
    return "Recently"

def send_alert(job):
    payload = {
        "content": "🚨 **New Matching Role Alert!**",
        "embeds": [{
            "title": f"{job['title']} — {job['company']}",
            "url": job["url"],
            "color": 3447003,
            "fields": [
                {"name": "Location", "value": job.get("location", "Remote (Worldwide)"), "inline": True},
                {"name": "Posted", "value": job.get("posted", "Recently"), "inline": True},
                {"name": "Source", "value": job.get("source", "Career Board"), "inline": True},
                {"name": "Apply Link", "value": f"[Click here to apply]({job['url']})", "inline": False}
            ],
            "footer": {"text": "Job Alert Bot • Global & Caribbean Scanner"}
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
    except Exception as e:
        print(f"Error posting alert: {e}")

def scan_greenhouse():
    for company in GREENHOUSE_COMPANIES:
        try:
            r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs", timeout=10)
            if r.status_code == 200:
                for j in r.json().get("jobs", []):
                    title = j.get("title", "")
                    loc = j.get("location", {}).get("name", "Remote")
                    jid = f"gh_{company}_{j.get('id')}"
                    if is_relevant_role(title) and is_valid_location(loc) and not is_job_seen(jid):
                        mark_job_seen(jid, title, company.capitalize(), j.get("absolute_url"))
                        send_alert({
                            "title": title,
                            "company": company.capitalize(),
                            "location": loc,
                            "url": j.get("absolute_url"),
                            "posted": format_timestamp(j.get("updated_at")),
                            "source": "Greenhouse"
                        })
        except Exception as e:
            print(f"Error Greenhouse {company}: {e}")

def scan_lever():
    for company in LEVER_COMPANIES:
        try:
            r = requests.get(f"https://api.lever.co/v0/postings/{company}?mode=json", timeout=10)
            if r.status_code == 200:
                for j in r.json():
                    title = j.get("text", "")
                    loc = j.get("categories", {}).get("location", "Remote")
                    jid = f"lev_{company}_{j.get('id')}"
                    if is_relevant_role(title) and is_valid_location(loc) and not is_job_seen(jid):
                        mark_job_seen(jid, title, company.capitalize(), j.get("hostedUrl"))
                        send_alert({
                            "title": title,
                            "company": company.capitalize(),
                            "location": loc,
                            "url": j.get("hostedUrl"),
                            "posted": format_timestamp(j.get("createdAt")),
                            "source": "Lever"
                        })
        except Exception as e:
            print(f"Error Lever {company}: {e}")

def scan_remotive_global():
    """Scrapes Remotive's public API for worldwide software development and data roles."""
    categories = ["software-dev", "data"]
    for cat in categories:
        endpoint = f"https://remotive.com/api/remote-jobs?category={cat}&limit=50"
        try:
            r = requests.get(endpoint, timeout=10)
            if r.status_code == 200:
                jobs = r.json().get("jobs", [])
                for j in jobs:
                    title = j.get("title", "")
                    loc = j.get("candidate_required_location", "Worldwide")
                    jid = f"remotive_{j.get('id')}"
                    
                    if is_relevant_role(title) and is_valid_location(loc) and not is_job_seen(jid):
                        mark_job_seen(jid, title, j.get("company_name"), j.get("url"))
                        send_alert({
                            "title": title,
                            "company": j.get("company_name", "Remote Company"),
                            "location": loc,
                            "url": j.get("url"),
                            "posted": format_timestamp(j.get("publication_date")),
                            "source": "Remotive (Global)"
                        })
        except Exception as e:
            print(f"Error Remotive {cat}: {e}")

def main():
    init_db()
    scan_greenhouse()
    scan_lever()
    scan_remotive_global()

if __name__ == "__main__":
    main()
EOF