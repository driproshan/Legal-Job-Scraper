import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import yaml
import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel
from google import genai
from dotenv import load_dotenv

# Load environment variables from keys.txt
load_dotenv("keys.txt")

class JobMatchDetails(BaseModel):
    is_match: bool
    company_name: str | None
    role_title: str | None
    location: str | None
    experience_required: str | None
    practice_areas: list[str] | None
    key_responsibilities: list[str] | None
    application_link: str | None
    hr_email: str | None
    reasoning: str | None

def load_config():
    with open("config.yaml", "r") as f:
        return yaml.safe_load(f)

def load_prompt():
    with open("criteria_prompt.txt", "r") as f:
        return f.read()

def fetch_job_links(hub_url, base_domain=""):
    """
    Looks for links on the hub_url that appear to be article pages (i.e. lengthier URLs)
    and point back to the same site.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(hub_url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        links = set()
        
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Simple heuristics for "article" links rather than category/tag links
            # Must be a long url or contain job-like terms, not ending in bare category structures
            if "job" in href.lower() or "vacancy" in href.lower() or "associate" in href.lower() or len(href.split("/")) > 4:
                # Exclude obvious non-article links
                if "/category/" in href or "/author/" in href or "/tag/" in href:
                    continue
                
                # Make link absolute
                if href.startswith("/"):
                    href = base_domain + href
                
                if href.startswith("http"):
                    links.add(href)
        return list(links)
    except Exception as e:
        print(f"Error fetching links from {hub_url}: {e}")
        return []

def extract_job_text(url):
    """
    Downloads the page and extracts visible text, discarding boilerplate navigation/footers.
    """
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove nav, header, footer
        for el in soup(['nav', 'header', 'footer', 'aside', 'script', 'style']):
            el.decompose()
            
        return soup.get_text(separator=' ', strip=True)
    except Exception as e:
        print(f"Error extracting text from {url}: {e}")
        return ""

def evaluate_job(text, prompt, url, llm_model, client):
    """
    Uses Gemini API to evaluate if the job meets the complex criteria.
    """
    if len(text.strip()) < 100:
        return None  # Probably an empty/failed scrape
    
    # We truncate text if it is excessively long, though Gemini handles large context well.
    safe_text = text[:15000] 
    
    combined_prompt = f"{prompt}\n\nHere is the scraped job posting text (from {url}):\n\n{safe_text}"
    
    try:
        response = client.models.generate_content(
            model=llm_model,
            contents=combined_prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": JobMatchDetails,
                "temperature": 0.1, # Keep it deterministic
            },
        )
        # Parse output
        match_data = JobMatchDetails.model_validate_json(response.text)
        return match_data
    except Exception as e:
        print(f"Error evaluating job from {url}: {e}")
        return None

def send_email_report(matched_jobs, config):
    """
    Sends an HTML formatted email containing the matched jobs.
    """
    sender = config['notification']['sender_email']
    receiver = config['notification']['target_email']
    password = os.getenv("EMAIL_PASSWORD")
    
    if not sender or not password or "your_" in sender:
        print("Skipping email notification: sender email or password not configured correctly.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"AI Legal Job Scraper - {len(matched_jobs)} New Matching Roles"
    msg["From"] = sender
    msg["To"] = receiver

    html_content = "<h2>Scraped Entry-Level Corporate Roles</h2><ul>"
    for job, url in matched_jobs:
        html_content += f"""
        <li style='margin-bottom: 20px;'>
            <strong>Role:</strong> {job.role_title or 'Unknown'} @ <strong>{job.company_name or 'Unknown'}</strong><br>
            <strong>Location:</strong> {job.location or 'Unknown'}<br>
            <strong>Practice Areas:</strong> {", ".join(job.practice_areas) if job.practice_areas else 'N/A'}<br>
            <strong>Link:</strong> <a href="{url}">{url}</a><br>
            <strong>HR Email:</strong> {job.hr_email or 'Not Provided'}<br>
            <strong>AI Note:</strong> <em>{job.reasoning or ''}</em>
        </li>
        """
    html_content += "</ul>"

    part = MIMEText(html_content, "html")
    msg.attach(part)

    try:
        # Connect to Gmail SMTP (adjust if using another provider)
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())
        server.quit()
        print("Email report sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")

def main():
    print("Loading config and prompt...")
    config = load_config()
    prompt = load_prompt()
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or "your_" in api_key:
        print("Missing or invalid GEMINI_API_KEY. Update keys.txt file.")
        return
        
    client = genai.Client(api_key=api_key)
    model_name = config['llm']['model']
    
    matched_jobs = []
    
    print("Starting Web Scrape...")
    for site in config['websites']:
        name = site['name']
        hub_url = site['url']
        
        base_domain = "/".join(hub_url.split("/")[:3]) # e.g. https://lawbhoomi.com
        
        print(f"  Scraping {name} ({hub_url})...")
        links = fetch_job_links(hub_url, base_domain)
        print(f"    Found {len(links)} potential job links.")
        
        # To avoid rate limits and taking too long in this run, we process up to 15 latest links per site.
        # In a robust cron job, you might want to track previously seen URLs in a SQLite DB or local JSON file.
        for link in links[:15]:
            print(f"    Evaluating: {link}")
            text = extract_job_text(link)
            
            result = evaluate_job(text, prompt, link, model_name, client)
            if result and result.is_match:
                print(f"      [MATCH] {result.role_title} @ {result.company_name}")
                matched_jobs.append((result, link))
            else:
                reason = result.reasoning if result else "Failed to parse/extract."
                print(f"      [SKIP] {reason}")

    print(f"\nCompleted! Found {len(matched_jobs)} matching roles.")
    if matched_jobs:
        send_email_report(matched_jobs, config)
    else:
        print("No matching jobs to email today.")

if __name__ == "__main__":
    main()
