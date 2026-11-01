cat << 'EOF' > run_once.py
import os
import sqlite3
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1566561896583266385/UcO1lypDvEunsA9GPiIGL1usfpCGMPhNiDIQ2KnR8Xg0v-S1f1WDchKK699SK5ueLo7H"
DB_PATH = "jobs.db"

# Match student / early career / remote roles
INCLUDE_KEYWORDS = [
    # Data & Analytics
    "data analyst", "data analytics", "data intern", "junior data", "data entry",
    # Software & Web
    "software engineer intern", "swe intern", "junior developer", "junior software",
    "web developer", "frontend intern", "backend intern", "python",
    # QA & Support & Operations
    "qa tester", "qa intern", "quality assurance", "technical support",
    "tech support", "it support", "support specialist", "operations intern"
]

# Disqualifiers
EXCLUDE_KEYWORDS = [
    "senior", "lead", "principal", "manager", "director", "head of",
    "phd", "master", "clearance required", "ts/sci", "secret clearance"
]

# High-profile remote tech boards
GREENHOUSE_COMPANIES = [
    "amplify", "instacart", "datadog", "figma", "reddit",
    "discord", "stripe", "gitlab", "cloudflare", "affirm",
    "automattic", "canonical", "zapier", "webflow", "vercel", "supabase"
]

LEVER_COMPANIES = [
    "spotify", "palantir", "benchling", "coursera", "mozilla"
]

# Allowed locations (US, Caribbean, LatAm, and Worldwide Remote)
ALLOWED_LOCATIONS = [
    "remote", "anywhere", "worldwide", "global", "us", "united states",
    "caribbean", "trinidad", "jamaica", "barbados", "latin america", "latam", "americas"
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
                {"name": "Location", "value": job.get("location", "Remote"), "inline": True},
                {"name": "Posted", "value": job.get("posted", "Recently"), "inline": True},
                {"name": "Source", "value": job.get("source", "Career Board"), "inline": True},
                {"name": "Apply Link", "value": f"[Click here to apply]({job['url']})", "inline": False}
            ],
            "footer": {"text": "Job Alert Bot • Global, US & Caribbean"}
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
    categories = ["software-dev", "data", "qa", "customer-support"]
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

def scan_linkedin():
    search_queries = [
        "data analyst intern remote",
        "software engineer intern remote",
        "remote data entry",
        "junior developer remote"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for query in search_queries:
        formatted_query = query.replace(" ", "%20")
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={formatted_query}&location=Worldwide&f_TPR=r86400"
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code != 200:
                continue

            soup = BeautifulSoup(res.text, "html.parser")
            job_cards = soup.find_all("li")

            for card in job_cards:
                title_elem = card.find("h3", class_="base-search-card__title")
                company_elem = card.find("h4", class_="base-search-card__subtitle")
                link_elem = card.find("a", class_="base-card__full-link")
                loc_elem = card.find("span", class_="job-search-card__location")
                time_elem = card.find("time")

                if not (title_elem and company_elem and link_elem):
                    continue

                title = title_elem.text.strip()
                company = company_elem.text.strip()
                job_url = link_elem["href"].split("?")[0]
                job_id = f"li_{job_url.split('-')[-1]}"
                location = loc_elem.text.strip() if loc_elem else "Remote"
                posted = time_elem.text.strip() if time_elem else "Recently"

                if is_relevant_role(title) and is_valid_location(location) and not is_job_seen(job_id):
                    mark_job_seen(job_id, title, company, job_url)
                    send_alert({
                        "title": title,
                        "company": company,
                        "location": location,
                        "url": job_url,
                        "posted": posted,
                        "source": "LinkedIn"
                    })
        except Exception as e:
            print(f"Error LinkedIn ({query}): {e}")

def main():
    init_db()
    scan_greenhouse()
    scan_lever()
    scan_remotive_global()
    scan_linkedin()

if __name__ == "__main__":
    main()
EOF