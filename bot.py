import os
import time
import sqlite3
import requests

# Your Discord Webhook
DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1566561896583266385/UcO1lypDvEunsA9GPiIGL1usfpCGMPhNiDIQ2KnR8Xg0v-S1f1WDchKK699SK5ueLo7H"

DB_PATH = "jobs.db"

INCLUDE_KEYWORDS = [
    "data analyst", "data analytics", "data intern",
    "software engineer intern", "swe intern", "data entry",
    "python", "sql", "junior data", "micro-internship"
]

EXCLUDE_KEYWORDS = [
    "senior", "lead", "principal", "manager", "director",
    "phd", "master", "clearance required", "ts/sci"
]

GREENHOUSE_COMPANIES = [
    "amplify", "instacart", "datadog", "figma", "reddit",
    "discord", "stripe", "gitlab", "cloudflare", "affirm"
]

LEVER_COMPANIES = [
    "spotify", "palantir", "benchling", "coursera"
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
    title_lower = title.lower()
    if any(ex in title_lower for ex in EXCLUDE_KEYWORDS):
        return False
    return any(inc in title_lower for inc in INCLUDE_KEYWORDS)

def send_discord_alert(job):
    payload = {
        "content": "🚨 **New Matching Role Alert!**",
        "embeds": [{
            "title": f"{job['title']} — {job['company']}",
            "url": job["url"],
            "color": 3447003,
            "fields": [
                {"name": "Location", "value": job.get("location", "Remote"), "inline": True},
                {"name": "Source", "value": job.get("source", "Career Board"), "inline": True},
                {"name": "Apply Link", "value": f"[Click here to apply]({job['url']})", "inline": False}
            ],
            "footer": {"text": "Job Alert Bot"}
        }]
    }
    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        res.raise_for_status()
    except Exception as e:
        print(f"Failed to deliver Discord notification: {e}")

def scan_greenhouse():
    for company in GREENHOUSE_COMPANIES:
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
        try:
            res = requests.get(endpoint, timeout=10)
            if res.status_code != 200:
                continue
            for job in res.json().get("jobs", []):
                title = job.get("title", "")
                job_id = f"gh_{company}_{job.get('id')}"
                url = job.get("absolute_url")
                location = job.get("location", {}).get("name", "Remote")
                
                if is_relevant_role(title) and not is_job_seen(job_id):
                    mark_job_seen(job_id, title, company.capitalize(), url)
                    send_discord_alert({
                        "title": title,
                        "company": company.capitalize(),
                        "location": location,
                        "url": url,
                        "source": "Greenhouse"
                    })
        except Exception as e:
            print(f"Error querying Greenhouse ({company}): {e}")

def scan_lever():
    for company in LEVER_COMPANIES:
        endpoint = f"https://api.lever.co/v0/postings/{company}?mode=json"
        try:
            res = requests.get(endpoint, timeout=10)
            if res.status_code != 200:
                continue
            for job in res.json():
                title = job.get("text", "")
                job_id = f"lev_{company}_{job.get('id')}"
                url = job.get("hostedUrl")
                location = job.get("categories", {}).get("location", "Remote")

                if is_relevant_role(title) and not is_job_seen(job_id):
                    mark_job_seen(job_id, title, company.capitalize(), url)
                    send_discord_alert({
                        "title": title,
                        "company": company.capitalize(),
                        "location": location,
                        "url": url,
                        "source": "Lever"
                    })
        except Exception as e:
            print(f"Error querying Lever ({company}): {e}")

def run_scanner():
    print("Scanning active boards...")
    scan_greenhouse()
    scan_lever()
    print("Scan complete. Sleeping for 30 minutes.")

if __name__ == "__main__":
    init_db()
    # Test ping to verify your Discord webhook works
    requests.post(DISCORD_WEBHOOK_URL, json={"content": "✅ **Job Alert Bot is active and connected!**"})
    
    while True:
        run_scanner()
        time.sleep(1800)  # Check every 30 minutes
