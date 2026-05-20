"""
Healthcare Resume Parser & Candidate Profile Generator (Enhanced Data Matrix)
=============================================================================
"""
import streamlit as st
import anthropic
from fpdf import FPDF
import json
import pdfplumber
import pandas as pd
from thefuzz import process

# ---------------------------------------------------------
# 1. APP CONFIGURATION & DATA INGESTION
# ---------------------------------------------------------
st.set_page_config(page_title="Healthcare Resume Parser", page_icon="🩺", layout="wide")

@st.cache_data
def load_hospital_intelligence():
    """Loads the compressed master hospital dataset into memory once."""
    try:
        return pd.read_parquet("master_hospitals.parquet")
    except Exception as e:
        st.error(f"Critical System Alert: Hospital intelligence layer failed to load: {e}")
        return None

HOSPITAL_DB = load_hospital_intelligence()

# ---------------------------------------------------------
# 2. THE SECURITY GATEKEEPER
# ---------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.title("🔒 Company Internal Tool Access")
    with st.form("secure_login_gate"):
        user_password = st.text_input("Please enter the recruiter access password:", type="password")
        submit_password = st.form_submit_button("Unlock Parser Engine")
        if submit_password:
            target_password = st.secrets.get("ACCESS_PASSWORD", "")
            if target_password == "":
                st.error("⚠️ System Configuration Error: ACCESS_PASSWORD is blank in Secrets vault.")
            elif user_password == target_password:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("❌ Incorrect password. Please try again.")
    st.stop()

# ---------------------------------------------------------
# 3. CONSTANTS & SYSTEM INSTRUCTIONS
# ---------------------------------------------------------
STATES_LIST = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "Compact RN"]
CERTS_LIST = ["ACLS", "BLS", "PALS", "TNCC", "ENPC", "CEN", "CCRN", "AWHONN - Advanced", "AWHONN - Intermediate", "C-EFM", "CIC", "CNE", "CNM", "CNOR", "COHN", "CPEN", "CPI", "MAB", "CRNFA", "CWCN", "CWON", "FNP", "NCSN", "OCN", "ONC", "WCC"]
MODALITIES = ["RN", "LPN", "CNA", "LPT", "CLS", "SLP", "SLPA", "PT"]

SYSTEM_PROMPT = """You are an expert healthcare recruitment assistant. Your job is to extract data from a medical resume and format it into a highly structured JSON object.

CRITICAL INSTRUCTIONS:
1. DO NOT extract or look for Licenses or Certifications. Completely ignore those sections of the resume.
2. LOCATION IS MANDATORY: For every single entry in 'work_history', you MUST identify the 2-letter state code where that hospital is located and put it in the 'facility_state' field. If you cannot find it, default to "US".
3. TIMELINE AUDIT (JOINT COMMISSION COMPLIANCE): Audit the candidate's work history timeline over the past 7 years (back to 2019). The current date is May 14, 2026.
   - Calculate gaps between positions. If a gap of more than 30 days is detected, you MUST insert a placeholder entry into the 'work_history' array.
   - BUFFER RULE: If job A ends in Month X and job B starts in Month X or X+1, do NOT count it as a gap.
   - If a gap is valid, insert this exact object:
     {
       "title": "Employment Gap / Personal Time",
       "company": "N/A",
       "facility_state": "N/A",
       "dates": "MM/YYYY - MM/YYYY",
       "duties": ["Timeline gap accounted for."]
     }
4. Sort all entries in reverse chronological order.

Your output must be raw JSON matching this structure exactly:
{
  "name": "",
  "contact_info": "",
  "summary": "",
  "education": [],
  "work_history": [
    {"title": "", "company": "", "facility_state": "", "dates": "", "duties": []}
  ]
}"""

# ---------------------------------------------------------
# 4. CUSTOM DATABASE ENRICHMENT ENGINE
# ---------------------------------------------------------
def enrich_work_history(work_history_list):
    """Intercepts extracted history and matches it against your master parquet database."""
    if HOSPITAL_DB is None:
        return work_history_list
        
    enriched_list = []
    for job in work_history_list:
        company_name = job.get("company", "")
        state_filter = str(job.get("facility_state", "")).strip().upper()
        
        if company_name == "N/A" or "Gap" in job.get("title", ""):
            enriched_list.append(job)
            continue
            
        state_db = HOSPITAL_DB[HOSPITAL_DB['State'].str.upper() == state_filter] if state_filter in HOSPITAL_DB['State'].str.upper().values else HOSPITAL_DB
        
        if not state_db.empty:
            hospital_names = state_db['Hospital Name'].tolist()
            best_match, score = process.extractOne(company_name, hospital_names) if hospital_names else (None, 0)
            
            if score > 82:
                match_row = state_db[state_db['Hospital Name'] == best_match].iloc[0]
                job["enriched_metrics"] = {
                    "beds": str(match_row.get("Bed Count", "Not Listed")),
                    "trauma": str(match_row.get("Trauma Status", "Not Listed")),
                    "magnet": str(match_row.get("Magnet Status", "No")),
                    "teaching": str(match_row.get("Teaching Status", "Non-Teaching"))
                }
                job["company"] = best_match
                
        enriched_list.append(job)
    return enriched_list

# ---------------------------------------------------------
# 5. CUSTOM PDF GENERATION CLASS
# ---------------------------------------------------------
class CustomPDF(FPDF):
    def header(self):
        try:
            self.image('logo.png', x='C', w=45)
            self.ln(10)
        except:
            pass

    def _clean(self, text: str) -> str:
        if not text: return ""
        clean_text = str(text).replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"').replace("•", "-")
        clean_text = clean_text.replace('\xa0', ' ').replace('\u2013', '-').replace('\u2014', '-')
        return clean_text.encode('cp1252', 'replace').decode('cp1252')

    def section_heading(self, label: str):
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(40, 40, 40)
        self.cell(0, 8, self._clean(label), ln=True)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), 210 - self.r_margin, self.get_y())
        self.ln(4)

    def bullet(self, text: str):
        self.set_x(self.l_margin + 5)
        current_y = self.get_y()
        self.set_font("Helvetica", "", 10)
        self.cell(6, 6, "-")
        self.set_xy(self.l_margin + 11, current_y)
        self.multi_cell(0, 6, self._clean(text))
        self.set_y(self.get_y() + 1)

# ---------------------------------------------------------
# 6. PROFILE STITCHING SYSTEM
# ---------------------------------------------------------
def build_pdf(data: dict, manual_licenses: list, manual_certs: list, highlights: str) -> bytes:
    pdf = CustomPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Profile Header Block
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, pdf._clean(data.get("name", "Candidate Profile")), ln=True, align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 6, pdf._clean(data.get("contact_info", "")), ln=True, align="C")
    pdf.ln(6)
    
    # Summary Block
    if data.get("summary"):
        pdf.section_heading("Professional Summary")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, pdf._clean(data.get("summary")))
        pdf.ln(4)

    # Recruiter Notes Section
    if highlights.strip():
        pdf.section_heading("Candidate Highlights")
        for line in highlights.split("\n"):
            if line.strip(): pdf.bullet(line.strip())
        pdf.ln(4)

    # Verified Licenses Section
    pdf.section_heading("Verified Licenses")
    if manual_licenses:
        for lic in manual_licenses: 
            pdf.bullet(f"{lic['modality']} - {lic['state']} - Exp: {lic['exp_date']}")
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "None Declared/Listed", ln=True)
    pdf.ln(4)

    # Professional Certifications Section
    pdf.section_heading("Professional Certifications")
    if manual_certs:
        for cert in manual_certs: 
            pdf.bullet(f"{cert['name']} - Exp: {cert['exp_date']}")
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "None Declared/Listed", ln=True)
    pdf.ln(4)

    # Work History Section
    pdf.section_heading("Employment History (7-Year Compliance Audit)")
    for job in data.get("work_history", []):
        pdf.set_font("Helvetica", "B", 10)
        title_company = f"{job.get('title', 'N/A')} - {job.get('company', 'N/A')}"
        if job.get("facility_state") and job.get("facility_state") != "N/A":
            title_company += f" ({job.get('facility_state')})"
            
        pdf.cell(140, 6, pdf._clean(title_company))
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, pdf._clean(job.get("dates", "N/A")), ln=True, align="R")
        
        metrics = job.get("enriched_metrics")
        if metrics:
            pdf.set_font("Helvetica", "BI", 9)
            pdf.set_text_color(100, 110, 120)
            facility_badge = f" [Metrics -> Beds: {metrics['beds']} | Trauma: {metrics['trauma']} | Magnet: {metrics['magnet']} | {metrics['teaching']}]"
            pdf.cell(0, 5, pdf._clean(facility_badge), ln=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
        else:
            pdf.ln(1)
        
        for duty in job.get("duties", []): pdf.bullet(duty)
        pdf.ln(2)

    # Education Block
    if data.get("education"):
        pdf.section_heading("Education Matrix")
        for edu in data.get("education", []): pdf.bullet(str(edu))
            
    return bytes(pdf.output())

# ---------------------------------------------------------
# 7. STREAMLIT INTERFACE / GRAPHICAL RUNTIME
# ---------------------------------------------------------
st.title("🩺 Healthcare Candidate Profile Generator")
st.write("Upload a candidate's resume to audit employment timelines, clean text artifacts, and instantly enrich facility metrics.")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Source Document & Notes")
    uploaded_file = st.file_uploader("Upload candidate resume:", type=["txt", "pdf"])
    
    resume_raw_text = ""
    if uploaded_file:
        if uploaded_file.name.endswith(".pdf"):
            with pdfplumber.open(uploaded_file) as pdf:
                resume_raw_text = "".join([page.extract_text() for page in pdf.pages if page.extract_text()])
        else:
            resume_raw_text = uploaded_file.read().decode("utf-8")
        st.success("Resume data loaded successfully.")
        
    manual_highlights = st.text_area(
        "Candidate Highlights / Recruiter Notes:",
        placeholder="Enter key talking points or highlights (one per line)...",
        height=150
    )

with col2:
    st.subheader("2. Standardized Credentials Override")
    selected_states = st.multiselect("Manually Add Active State Licenses / Compacts:", options=STATES_LIST)
    
    if selected_states:
        for state in selected_states:
            c_mod, c_exp = st.columns([1, 1])
            with c_mod: 
                st.selectbox(f"Modality ({state}):", options=MODALITIES, key=f"mod_{state}")
            with c_exp: 
                st.text_input(f"Expiration Date ({state}):", placeholder="MM/YYYY", key=f"exp_{state}")
            st.markdown("---")

    selected_certs = st.multiselect("Manually Add Professional Certifications:", options=CERTS_LIST)
    if selected_certs:
        for cert in selected_certs:
            st.text_input(f"Expiration Date ({cert}):", placeholder="MM/YYYY or Active", key=f"cert_exp_{cert}")

# Execution Trigger
if st.button("Generate Stitched Compliance Profile", type="primary"):
    if not resume_raw_text:
        st.error("Action Blocked: Please upload a resume file to initialize the parser engine.")
    else:
        with st.spinner("Analyzing timelines and indexing institutional intelligence..."):
            try:
                final_compiled_licenses = []
                if selected_states:
                    for state in selected_states:
                        state_modality = st.session_state.get(f"mod_{state}", "RN")
                        state_expiration = st.session_state.get(f"exp_{state}", "").strip()
                        final_compiled_licenses.append({
                            "state": state,
                            "modality": state_modality,
                            "exp_date": state_expiration if state_expiration else "Not Specified"
                        })

                final_compiled_certs = []
                if selected_certs:
                    for cert in selected_certs:
                        cert_expiration = st.session_state.get(f"cert_exp_{cert}", "").strip()
                        final_compiled_certs.append({
                            "name": cert,
                            "exp_date": cert_expiration if cert_expiration else "Active"
                        })

                client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
                message = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": f"Parse:\n\n{resume_raw_text}"}],
                )
                
                raw_content = message.content[0].text.strip()
                
                if raw_content.startswith("```json"):
                    raw_content = raw_content.split("```json")[1].split("```")[0].strip()
                elif raw_content.startswith("```"):
                    raw_content = raw_content.split("```")[1].split("```")[0].strip()
                
                parsed_data = json.loads(raw_content)
                
                if parsed_data:
                    parsed_data["work_history"] = enrich_work_history(parsed_data.get("work_history", []))
                    
                    final_pdf = build_pdf(parsed_data, final_compiled_licenses, final_compiled_certs, manual_highlights)
                    
                    st.balloons()
                    st.success("Candidate Profile generated successfully with integrated hospital metrics!")
                    
                    st.download_button(
                        label="📥 Download Structured Candidate Profile (PDF)",
                        data=final_pdf,
                        file_name=f"Enriched_Profile_{parsed_data.get('name', 'Candidate')}.pdf",
                        mime="application/pdf"
                    )
            except Exception as e:
                st.error(f"Engine Exception Caught: {e}")
