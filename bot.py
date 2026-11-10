import os
import re
import sqlite3
import time
from datetime import datetime, timezone
import requests

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1566561896583266385/UcO1lypDvEunsA9GPiIGL1usfpCGMPhNiDIQ2KnR8Xg0v-S1f1WDchKK699SK5ueLo7H"
DB_PATH = "jobs.db"

# 1. Target Roles (Must match at least one)
TARGET_TITLE_PATTERNS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\bco-?op\b",
    r"\bearly career\b",
    r"\buniversity\b",
    r"\bstudent\b",
    r"\bundergrad\b",
    r"\bmicro-internship\b",
    r"\bjuniordata\b",
    r"\bjuniorengineer\b",
    r"\bdata entry\b",
    r"\bdata analyst intern\b",
    r"\bswe intern\b",
    r"\bsoftware engineering intern\b",
]

# 2. Senior / Ineligible Exclusion Patterns
SENIOR_TITLE_EXCLUSIONS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
    r"\blead\b",
    r"\bprincipal\b",
    r"\bstaff\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bvp\b",
    r"\bhead of\b",
    r"\bphd\b",
    r"\bmaster\b",
    r"\bclearance required\b",
    r"\bts/sci\b",
    r"\bii\b",
    r"\biii\b",
    r"\biv\b",
    r"\bintermediate\b",
]

# 3. Explicit Remote Keywords (Must match at least one in location/title)
REMOTE_PATTERNS = [
    r"\bremote\b",
    r"\bwork from home\b",
    r"\bwfh\b",
    r"\bvirtual\b",
    r"\banywhere\b",
    r"\bus remote\b",
    r"\bremote - us\b",
    r"\bunited states \(remote\)\b",
]

# 4. Ineligible Region Restrictions
NON_US_RESTRICTIONS = [
    r"\buk\b",
    r"\bunited kingdom\b",
    r"\bpoland\b",
    r"\bcanada\b",
    r"\bemea\b",
    r"\bapac\b",
    r"\bgermany\b",
    r"\bindia\b",
    r"\blatam\b",
    r"\baustralia\b",
]

GREENHOUSE_COMPANIES = [
    "amplify",
    "instacart",
    "datadog",
    "figma",
    "reddit",
    "discord",
    "stripe",
    "gitlab",
    "cloudflare",
    "affirm",
]

LEVER_COMPANIES = ["spotify", "palantir", "benchling", "coursera"]


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
        "INSERT OR IGNORE INTO seen_jobs (job_id, title, company, url) VALUES"
        " (?, ?, ?, ?)",
        (job_id, title, company, url),
    )
    conn.commit()


def is_qualifying_remote_role(title: str, location: str) -> bool:
  title_lower = title.lower()
  loc_lower = location.lower()
  combined_meta = f"{title_lower} {loc_lower}"

  # Step 1: Reject any senior titles or high-level roman numerals
  if any(re.search(pat, title_lower) for pat in SENIOR_TITLE_EXCLUSIONS):
    return False

  # Step 2: Must be an intern, student, or early-career title
  if not any(re.search(pat, title_lower) for pat in TARGET_TITLE_PATTERNS):
    return False

  # Step 3: Enforce strict Remote qualification
  if not any(re.search(pat, combined_meta) for pat in REMOTE_PATTERNS):
    return False

  # Step 4: Discard remote roles restricted to non-US jurisdictions (unless US is also stated)
  if any(re.search(pat, loc_lower) for pat in NON_US_RESTRICTIONS):
    if not re.search(r"\b(us|usa|united states|americas)\b", loc_lower):
      return False

  return True


def format_timestamp(dt_str_or_epoch):
  try:
    if isinstance(dt_str_or_epoch, (int, float)):
      dt = datetime.fromtimestamp(dt_str_or_epoch / 1000, tz=timezone.utc)
      return dt.strftime("%b %d, %Y")
    elif isinstance(dt_str_or_epoch, str) and dt_str_or_epoch:
      clean_str = dt_str_or_epoch.replace("Z", "+00:00")
      dt = datetime.fromisoformat(clean_str)
      return dt.strftime("%b %d, %Y")
  except Exception:
    pass
  return "Recently Posted"


def send_discord_alert(job):
  payload = {
      "content": "🚨 **New Matching Remote Role Alert!**",
      "embeds": [{
          "title": f"{job['title']} — {job['company']}",
          "url": job["url"],
          "color": 3447003,
          "fields": [
              {
                  "name": "Location",
                  "value": f"🌐 {job.get('location', 'Remote')}",
                  "inline": True,
              },
              {
                  "name": "Posted",
                  "value": job.get("posted", "Recently"),
                  "inline": True,
              },
              {
                  "name": "Source",
                  "value": job.get("source", "Career Board"),
                  "inline": True,
              },
              {
                  "name": "Apply Link",
                  "value": f"[Click here to apply]({job['url']})",
                  "inline": False,
              },
          ],
          "footer": {"text": "Remote Early-Career Bot"},
      }],
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
        posted_raw = job.get("updated_at")

        if is_qualifying_remote_role(
            title, location
        ) and not is_job_seen(job_id):
          mark_job_seen(job_id, title, company.capitalize(), url)
          send_discord_alert({
              "title": title,
              "company": company.capitalize(),
              "location": location,
              "url": url,
              "posted": format_timestamp(posted_raw),
              "source": "Greenhouse",
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
        posted_raw = job.get("createdAt")

        if is_qualifying_remote_role(
            title, location
        ) and not is_job_seen(job_id):
          mark_job_seen(job_id, title, company.capitalize(), url)
          send_discord_alert({
              "title": title,
              "company": company.capitalize(),
              "location": location,
              "url": url,
              "posted": format_timestamp(posted_raw),
              "source": "Lever",
          })
    except Exception as e:
      print(f"Error querying Lever ({company}): {e}")


def run_scanner():
  print("Scanning active boards for remote student & intern roles...")
  scan_greenhouse()
  scan_lever()
  print("Scan complete. Sleeping for 30 minutes.")


if __name__ == "__main__":
  init_db()
  while True:
    run_scanner()
    time.sleep(1800)
