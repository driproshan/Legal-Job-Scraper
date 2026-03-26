import streamlit as st
import time
from google import genai
from scraper import fetch_job_links, extract_job_text, evaluate_job, load_prompt

# Setup Page Configuration
st.set_page_config(page_title="Legal AI Scraper", page_icon="⚖️", layout="wide")

# Main Title and Description
st.title("⚖️ AI Legal Job Scraper Dashboard")
st.markdown("Automate your hunt for 0-3 PQE Transactional Corporate roles with this invisible AI Agent.")

# Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Settings")
    
    # Secure Password Input for API Key
    api_key = st.text_input("**Google Gemini API Key**", type="password", help="The robot needs its brain to evaluate the jobs!")
    
    st.markdown("---")
    st.subheader("Target Job Boards")
    scrape_lawbhoomi = st.checkbox("LawBhoomi", value=True)
    scrape_ltj = st.checkbox("Law Times Journal", value=True)
    scrape_bandb = st.checkbox("Bar and Bench", value=True)
    
    st.markdown("---")
    st.info("Your strict M&A/PE filtering criteria is permanently loaded from your `criteria_prompt.txt` file.")

# Massive Start Button
if st.button("🚀 Start Hunting For Jobs", use_container_width=True, type="primary"):
    if not api_key:
        st.error("❌ Please enter your Google Gemini API Key in the sidebar first!")
        st.stop()
        
    client = genai.Client(api_key=api_key)
    prompt = load_prompt()
    
    websites = []
    if scrape_lawbhoomi: websites.append({"name": "LawBhoomi", "url": "https://lawbhoomi.com/category/job-updates/"})
    if scrape_ltj: websites.append({"name": "Law Times Journal", "url": "https://lawtimesjournal.in/jobs/"})
    if scrape_bandb: websites.append({"name": "Bar and Bench", "url": "https://www.barandbench.com/legal-jobs"})
    
    if not websites:
        st.warning("Please select at least one website to scrape in the sidebar.")
        st.stop()
        
    matched_jobs = []
    
    # Pretty UI Elements for Loading State
    status_text = st.empty()
    progress_bar = st.progress(0.0)
    
    for idx, site in enumerate(websites):
        name = site['name']
        hub_url = site['url']
        base_domain = "/".join(hub_url.split("/")[:3])
        
        status_text.info(f"⏳ **Current Target:** Reading all recent posts from {name}...")
        links = fetch_job_links(hub_url, base_domain)
        
        # Take up to 10 latest links per site so the dashboard doesn't time out on the free cloud
        target_links = links[:10]
        
        for link_idx, link in enumerate(target_links):
            # Math to calculate the overall progress bar beautifully
            current_progress = (idx / len(websites)) + ((link_idx / len(target_links)) * (1 / len(websites)))
            progress_bar.progress(current_progress)
            
            text = extract_job_text(link)
            result = evaluate_job(text, prompt, link, "gemini-2.5-flash", client)
            
            if result and result.is_match:
                matched_jobs.append((result, link))
                
    # Finish line
    progress_bar.progress(1.0)
    status_text.success(f"✅ Scanning Complete! Found {len(matched_jobs)} matching M&A/Corporate roles.")
    
    st.markdown("---")
    
    # Beautiful display of the AI-Matched Jobs
    if matched_jobs:
        st.subheader("🎯 Your Exclusive Matches")
        
        # We process matches into nice looking cards using columns
        for job, url in matched_jobs:
            with st.container():
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.markdown(f"### 💼 {job.role_title or 'Legal Role'}")
                    st.markdown(f"**🏢 Company/Firm:** {job.company_name or 'Not Disclosed'}")
                    st.markdown(f"**📍 Location:** {job.location or 'Not Specified'}")
                    st.markdown(f"**📑 Practice Tags:** {', '.join(job.practice_areas) if job.practice_areas else 'General Corporate'}")
                    st.markdown(f"**🤖 AI Insight:** _{job.reasoning or 'This role passed the strict 0-3 PQE and Transactional requirements.'}_")
                
                with col2:
                    st.link_button("📑 View Original Post", url, use_container_width=True)
                    if job.hr_email:
                        st.markdown(f"✉️ **Apply:** `{job.hr_email}`")
                        
                st.divider() # Line separator between jobs
    else:
        st.header("🛌 Nothing new today.")
        st.info("No jobs matching your extremely strict criteria were posted recently. Check back tomorrow!")
