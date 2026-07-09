"""
Healthcare Resume Parser & Candidate Profile Generator (Deep 7-Year History Framework v4.3)
===================================================================================
"""
import streamlit as st
import anthropic
from fpdf import FPDF
import json
import pdfplumber
import pandas as pd
from thefuzz import process
from datetime import datetime
import re

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

if "parsed_payload" not in st.session_state:
    st.session_state["parsed_payload"] = None
if "final_highlights" not in st.session_state:
    st.session_state["final_highlights"] = ""

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
# 3. GLOBAL CONFIGURATIONS & THE BLUEPRINT TEMPLATE
# ---------------------------------------------------------
STATES_LIST = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "Compact RN"]
MODALITIES = ["RN", "LPN", "CNA", "LPT", "CLS", "SLP", "SLPA", "PT" "Echo Tech"]
CERTS_LIST = ["ACLS", "BLS", "PALS", "TNCC", "ENPC", "CEN", "CCRN", "AWHONN - Advanced", "AWHONN - Intermediate", "NRP", "C-EFM", "CIC", "CNE", "CNM", "CNOR", "COHN", "CPEN", "CPI", "MAB", "CRNFA", "CWCN", "CWON", "FNP", "NCSN", "OCN", "ONC", "WCC", "ARRT (MR)", "ARRT (R)", "ARDMS RVT", "ARDMS RDCS"]
EMR_LIST = ["Epic", "Cerner", "MEDITECH", "TruBridge / CPSI", "McKesson", "Allscripts / Altera", "MatrixCare", "PointClickCare", "Not Specified / Paper Charting"]

EXECUTIVE_CHECKLIST_TEMPLATE = (
    "- __ years of RN Experience\n"
    "- __ Years of (insert specialty) Experience\n"
    "- (Insert float units) Float Experience\n"
    "- Travel Experience\n"
    "- (Charge and Preceptor) Experience\n"
    "- (insert facility type exp) Trauma Facility Experience\n"
    "- (insert license details) License x__/__\n"
    "- ACLS x__/__, BLS x__/__\n"
    "- Bachelors Degree\n"
    "- (insert types of charting exp) Computer Charting Experience"
)

# UPGRADED SYSTEM PROMPT: Enforces a strict 7-year lookback mandate
SYSTEM_PROMPT = """You are an expert healthcare recruitment assistant. Your job is to extract data from a medical resume and format it into a highly structured JSON object.

CRITICAL JSON SANITIZATION RULES:
- Never use unescaped double quotes inside text strings. Always map clinical quotes or software settings using single quotes (e.g., 'ICU' or 'Epic').
- Never leave dangling commas at the end of lists or object keys.
- Output MUST be strictly a single raw JSON block. Do not wrap code blocks or write notes.

CRITICAL EXTRACTION INSTRUCTIONS:
1. STRICT 7-YEAR LOOKBACK MANDATE: You MUST extract every single professional position listed on the resume stretching back at least 7 years (to 2019) if present. Do not truncate the work history list early, do not skip older roles, and do not condense separate travel assignments into single items.
2. DO NOT extract or look for Licenses or Certifications in standalone sections. Completely ignore those blocks.
3. LOCATION IS MANDATORY: For every single entry in 'work_history', you MUST extract the City and the 2-letter State code where that hospital is located and put them in 'facility_city' and 'facility_state'. If you cannot find them, default to "US".
4. STRICT TITLE EXTRACTION RULE: Extract ONLY the official raw job position title (e.g., 'MRI Technologist', 'Registered Nurse', 'Staff Nurse') into the 'title' field. Do NOT append or include employment types, shifts, or statuses like 'Part-Time', 'Full-Time', or 'PRN' within the title text string itself.
5. NO AI GAP GENERATION: Do not attempt to compute, calculate, or insert any employment gaps or 'N/A' placeholder rows into the 'work_history' array. Extract ONLY the actual, real positions explicitly listed on the candidate's resume.
6. STRUCTURED DATE EXTRACTION: Convert the position start and end dates into a standard hidden sortable string format "YYYY-MM". 
   - If they started in August 2022, set 'start_date_structured' to '2022-08'.
   - If they are currently working there, set 'end_date_structured' to 'Present'. Otherwise, convert the end date to 'YYYY-MM' (e.g., '2025-11').
7. EXECUTIVE SUMMARY OF DUTIES (ELIMINATE FLUFF): Summarize their role into exactly 3 to 4 high-level, professional macro bullet points focusing on unit scope and accountabilities.

Your output must match this structural schema exactly:
{
  "name": "",
  "contact_info": "",
  "education": [
    {"degree": "", "institution": "", "location": "", "date": ""}
  ],
  "work_history": [
    {"title": "", "company": "", "facility_city": "", "facility_state": "", "dates": "", "start_date_structured": "", "end_date_structured": "", "specialty": "", "charting_system": "", "prn_shifts_per_month": "", "duties": []}
  ]
}"""

# ---------------------------------------------------------
# 4. PYTHON CHRONOLOGY MATRIX (Deterministic Gap Calculator)
# ---------------------------------------------------------
def clean_and_balance_json(json_str):
    """Programmatically completes unclosed JSON objects caused by text stream truncation."""
    json_str = json_str.strip()
    json_str = re.sub(r',\s*([\]}])', r'\1', json_str)
    
    if json_str.endswith(','):
        json_str = json_str[:-1]
        
    if json_str.count('"') % 2 != 0:
        json_str += '"'
        
    open_brackets = json_str.count("[")
    close_brackets = json_str.count("]")
    open_braces = json_str.count("{")
    close_braces = json_str.count("}")
    
    if open_brackets > close_brackets:
        if open_braces > close_braces:
            json_str += "}"
            open_braces -= 1
        json_str += "]"
        
    if open_braces > json_str.count("}"):
        for _ in range(open_braces - json_str.count("}")):
            json_str += "}"
            
    return json_str

def calculate_deterministic_gaps(work_history_list):
    """Computes mathematically precise chronological gaps using exact datetimes."""
    jobs = [j for j in work_history_list if isinstance(j, dict) and j.get("company") != "N/A"]
    if not jobs:
        return work_history_list
        
    parsed_timeline = []
    current_runtime_date = datetime(2026, 5, 14)
    
    for j in jobs:
        start_str = str(j.get("start_date_structured", "")).strip()
        end_str = str(j.get("end_date_structured", "")).strip()
        
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m")
        except:
            start_dt = datetime(1900, 1, 1)
            
        if not end_str or "present" in end_str.lower() or "current" in end_str.lower():
            end_dt = current_runtime_date
        else:
            try:
                end_dt = datetime.strptime(end_str, "%Y-%m")
            except:
                end_dt = start_dt
                
        if end_dt < start_dt:
            end_dt = start_dt
                
        parsed_timeline.append({
            "job": j,
            "start": start_dt,
            "end": end_dt
        })
        
    parsed_timeline.sort(key=lambda x: x["start"])
    
    gaps = []
    if parsed_timeline:
        max_end_seen = parsed_timeline[0]["end"]
        
        for i in range(1, len(parsed_timeline)):
            next_start = parsed_timeline[i]["start"]
            
            if next_start > max_end_seen and (next_start - max_end_seen).days > 30:
                gap_start_display = max_end_seen.strftime("%m/%Y")
                gap_end_display = next_start.strftime("%m/%Y")
                
                gap_node = {
                    "title": "Employment Gap / Personal Time",
                    "company": "N/A",
                    "facility_city": "N/A",
                    "facility_state": "N/A",
                    "dates": f"{gap_start_display} - {gap_end_display}",
                    "start_date_structured": max_end_seen.strftime("%Y-%m"),
                    "end_date_structured": next_start.strftime("%Y-%m"),
                    "specialty": "N/A",
                    "charting_system": "N/A",
                    "prn_shifts_per_month": "N/A",
                    "duties": ["Timeline gap accounted for."]
                }
                gaps.append(gap_node)
                
            if parsed_timeline[i]["end"] > max_end_seen:
                max_end_seen = parsed_timeline[i]["end"]
                
    combined_history = jobs + gaps
    combined_history.sort(
        key=lambda x: x.get("start_date_structured", "1900-01") if x.get("start_date_structured") else "1900-01", 
        reverse=True
    )
    return combined_history


def enrich_work_history(work_history_list):
    """Intercepts extracted history and matches it against your master hospital database."""
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
            
            if score >= 90:
                match_row = state_db[state_db['Hospital Name'] == best_match].iloc[0]
                job["enriched_metrics"] = {
                    "beds": str(match_row.get("Bed Count", "Not Listed")),
                    "trauma": str(match_row.get("Trauma Status", "Not Listed/None")),
                    "magnet": str(match_row.get("Magnet Status", "No")),
                    "teaching": str(match_row.get("Teaching Status", "Non-Teaching")),
                    "city": str(match_row.get("City", "")).strip(),
                    "state": str(match_row.get("State", "")).strip().upper()
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
        self.set_x(self.l_margin)
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5, f" - {self._clean(text)}")
        self.set_y(self.get_y() + 0.5)

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

    # Standard Highlights Section
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

    # Employment History Section
    pdf.section_heading("Employment History")
    for job in data.get("work_history", []):
        pdf.set_font("Helvetica", "B", 10)
        
        job_title = str(job.get('title', 'N/A'))
        is_gap_entry = "gap" in job_title.lower() or job.get("company") == "N/A"
        
        if is_gap_entry:
            geo_string = ""
        else:
            metrics = job.get("enriched_metrics")
            if metrics and metrics.get("city") and metrics.get("state"):
                geo_string = f"{metrics['city']}, {metrics['state']}"
            else:
                city_val = str(job.get("facility_city", "")).strip()
                state_val = str(job.get("facility_state", "")).strip()
                if city_val and state_val and city_val != "N/A" and state_val != "N/A":
                    geo_string = f"{city_val}, {state_val}"
                elif state_val and state_val != "N/A" and state_val != "US":
                    geo_string = state_val
                else:
                    geo_string = ""

        specialty_val = str(job.get('specialty', '')).strip()
        if specialty_val and specialty_val.lower() != "not specified" and not is_gap_entry:
            if specialty_val.lower() not in job_title.lower():
                job_title = f"{job_title} ({specialty_val})"

        title_company = f"{job_title} - {job.get('company', 'N/A')}"
        if geo_string:
            title_company += f" ({geo_string})"
            
        pdf.multi_cell(0, 5, pdf._clean(title_company))
        pdf.set_x(pdf.l_margin)
        
        pdf.set_font("Helvetica", "BI", 9)
        pdf.set_text_color(100, 110, 120)
        
        ribbon_parts = [f"Dates: {job.get('dates', 'N/A')}"]
        
        prn_vol = job.get("prn_shifts_per_month", "Full-Time")
        if prn_vol and prn_vol != "Full-Time" and prn_vol != "N/A":
            ribbon_parts.append(f"Employment Type: {prn_vol}")
            
        charting_val = job.get("charting_system", "")
        if charting_val and charting_val.lower() != "not specified" and charting_val != "N/A":
            ribbon_parts.append(f"EMR: {charting_val}")
        
        if not is_gap_entry and metrics:
            is_trauma = any(lvl in str(metrics.get("trauma", "")).upper() for lvl in ["LEVEL I", "LEVEL II", "LEVEL III", "LEVEL IV"])
            is_magnet = metrics.get("magnet") == "Yes"
            is_teaching = "Teaching" in metrics.get("teaching", "") and "Non-Teaching" not in metrics.get("teaching", "")
            
            if is_trauma or is_magnet or is_teaching:
                ribbon_parts.append(f"Beds: {metrics['beds']}")
                if is_trauma: 
                    ribbon_parts.append(f"Trauma: {metrics['trauma']}")
                if is_magnet: 
                    ribbon_parts.append("Magnet Facility")
                if is_teaching: 
                    ribbon_parts.append("Teaching Hospital")
            
        metadata_ribbon = "  •  ".join(ribbon_parts)
        pdf.cell(0, 5, pdf._clean(metadata_ribbon), ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.ln(1)
        
        for duty in job.get("duties", []): pdf.bullet(duty)
        pdf.ln(2)

    # Education Section
    if data.get("education"):
        pdf.section_heading("Education")
        for edu in data.get("education", []):
            if isinstance(edu, dict):
                degree = str(edu.get("degree", "Degree Not Listed")).strip()
                if "aas in nursing" in degree.lower() or "associate" in degree.lower():
                    degree = "ADN"
                elif "bachelor" in degree.lower():
                    degree = "BSN"
                
                date = str(edu.get("date", "")).strip()
                institution = str(edu.get("institution", "")).strip()
                location = str(edu.get("location", "")).strip()
                
                edu_parts = []
                if degree and date: 
                    edu_parts.append(f"{degree}, {date}")
                elif degree: 
                    edu_parts.append(degree)
                
                if institution: 
                    edu_parts.append(institution)
                if location: 
                    edu_parts.append(location)
                    
                line_text = " - ".join(edu_parts)
            else:
                line_text = str(edu)
                
            pdf.bullet(line_text)
            
    return bytes(pdf.output())

# ---------------------------------------------------------
# 7. INTERFACE DESIGNS & WORKFLOW ENGINE
# ---------------------------------------------------------
st.title("🩺 Healthcare Candidate Profile Generator")

if st.session_state["parsed_payload"] is None:
    st.write("Upload a candidate's resume to parse details, cross-reference facility statuses, and unlock interactive customization fields.")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("1. Source Document & Executive Checklist Scribe")
        uploaded_file = st.file_uploader("Upload candidate resume (PDF or TXT):", type=["txt", "pdf"])
        
        manual_highlights = st.text_area(
            "Candidate Highlights Template (Fill this out directly to print to the top of the PDF):",
            value=EXECUTIVE_CHECKLIST_TEMPLATE,
            height=240
        )
        
    with col2:
        st.subheader("2. Initial Standardized Override Credentials")
        selected_states = st.multiselect("Manually Add Active State Licenses / Compacts:", options=STATES_LIST)
        
        if selected_states:
            for state in selected_states:
                c_mod, c_exp = st.columns([1, 1])
                with c_mod: 
                    st.selectbox(f"Modality ({state}):", options=MODALITIES, key=f"initial_mod_{state}")
                with c_exp: 
                    st.text_input(f"Expiration Date ({state}):", placeholder="MM/YYYY", key=f"initial_exp_{state}")
                st.markdown("---")

        selected_certs = st.multiselect("Manually Add Professional Certifications:", options=CERTS_LIST)
        if selected_certs:
            for cert in selected_certs:
                st.text_input(f"Expiration Date ({cert}):", placeholder="MM/YYYY or Active", key=f"initial_cert_exp_{cert}")

    if st.button("Parse & Extract Resume Data", type="primary"):
        if not uploaded_file:
            st.error("Action Blocked: Please upload a resume file to initialize the tracking sequence.")
        else:
            with st.spinner("Extracting timeline records and formatting code frameworks..."):
                if uploaded_file.name.endswith(".pdf"):
                    with pdfplumber.open(uploaded_file) as pdf:
                        resume_text = "".join([page.extract_text() for page in pdf.pages if page.extract_text()])
                else:
                    resume_text = uploaded_file.read().decode("utf-8")
                
                resume_text = resume_text.replace("•", "-").replace("·", "-").replace("\xa0", " ")
                
                client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
                
                try:
                    # ENHANCEMENT 1: Capped lookahead ceiling expanded to 8,000 max output tokens
                    message = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=8000,
                        system=SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": f"Parse:\n\n{resume_text}"}],
                    )
                    raw_content = message.content[0].text.strip()
                except anthropic.InternalServerError:
                    st.error("⚠️ Anthropic Server Error (500): Anthropic's processing servers are currently overloaded. Please click the primary execution button once more to retry.")
                    st.stop()
                except Exception as e:
                    st.error(f"⚠️ Unexpected Network Handoff Exception: {e}")
                    st.stop()
                
                start_idx = raw_content.find("{")
                end_idx = raw_content.rfind("}")
                
                if start_idx != -1 and end_idx != -1:
                    clean_json_string = raw_content[start_idx:end_idx+1]
                    
                    if not clean_json_string.endswith("}") and not clean_json_string.endswith("]"):
                        last_complete_brace = clean_json_string.rfind("}")
                        if last_complete_brace != -1:
                            clean_json_string = clean_json_string[:last_complete_brace + 1]
                    
                    clean_json_string = re.sub(r',\s*([\]}])', r'\1', clean_json_string)
                    if clean_json_string.count("[") > clean_json_string.count("]"):
                        clean_json_string += "]"
                    if clean_json_string.count("{") > clean_json_string.count("}"):
                        clean_json_string += "}"
                    
                    try:
                        parsed_data = json.loads(clean_json_string)
                    except json.JSONDecodeError:
                        st.error("⚠️ AI Formatting Exception: The engine returned corrupted data arrays. Please click the parse button again to generate a clean pass.")
                        st.text_area("System Diagnostic Log (Raw Output Window):", value=raw_content, height=250)
                        st.stop()
                else:
                    st.error("❌ Transmission Failure: The AI failed to respond with a structured data framework.")
                    st.stop()
                
                if parsed_data:
                    history_nodes = parsed_data.get("work_history", [])
                    if not history_nodes or len(history_nodes) == 0:
                        st.error("⚠️ Parser Warning: No chronological work records could be detected in this document text.")
                        st.stop()
                        
                    enriched_nodes = enrich_work_history(history_nodes)
                    parsed_data["work_history"] = calculate_deterministic_gaps(enriched_nodes)
                    
                    final_compiled_licenses = []
                    if selected_states:
                        for state in selected_states:
                            state_modality = st.session_state.get(f"initial_mod_{state}", "RN")
                            state_expiration = st.session_state.get(f"initial_exp_{state}", "").strip()
                            final_compiled_licenses.append({
                                "state": state,
                                "modality": state_modality,
                                "exp_date": state_expiration if state_expiration else "Active"
                            })

                    final_compiled_certs = []
                    if selected_certs:
                        for cert in selected_certs:
                            cert_expiration = st.session_state.get(f"initial_cert_exp_{cert}", "").strip()
                            final_compiled_certs.append({
                                "name": cert,
                                "exp_date": cert_expiration if cert_expiration else "Active"
                            })
                    
                    st.session_state["parsed_payload"] = parsed_data
                    st.session_state["final_highlights"] = manual_highlights  
                    st.session_state["manual_states_compiled"] = final_compiled_licenses
                    st.session_state["manual_certs_compiled"] = final_compiled_certs
                    st.rerun()

else:
    payload = st.session_state["parsed_payload"]
    
    st.info("🎉 Step 1 Complete: Resume data structured successfully. Refine candidate metrics below before generating the final file.")
    
    if st.button("⬅️ Clear & Upload New Resume"):
        st.session_state["parsed_payload"] = None
        st.rerun()
        
    st.markdown("---")
    
    st.subheader("🏥 Verification Step 1: Custom Workplace Specialty & Charting Adjustments")
    st.write("Review each separate extracted chronological work record. Assign or correct specialties and EMR charting values below:")
    
    updated_history = []
    for i, job in enumerate(payload.get("work_history", [])):
        company_display = f"{job.get('title', 'N/A')} - {job.get('company', 'N/A')} ({job.get('dates', 'N/A')})"
        
        if job.get("company") == "N/A":
            updated_history.append(job)
            continue
            
        with st.expander(f"📍 WORKPLACE LAYER {i+1}: {company_display}", expanded=True):
            col_spec, col_emr, col_shifts = st.columns([1, 1, 1])
            
            with col_spec:
                existing_specialty = job.get("specialty", "").strip()
                spec_input = st.text_input(
                    f"Assigned Specialty:", 
                    value=existing_specialty if existing_specialty else "Not Specified",
                    key=f"spec_widget_{i}"
                )
                job["specialty"] = spec_input
                
            with col_emr:
                existing_emr = job.get("charting_system", "").strip()
                default_index = 8
                if existing_emr:
                    for idx, vendor in enumerate(EMR_LIST):
                        if vendor.lower() in existing_emr.lower() or existing_emr.lower() in vendor.lower():
                            default_index = idx
                            break
                
                emr_selection = st.selectbox(
                    f"Facility EMR System:",
                    options=EMR_LIST,
                    index=default_index,
                    key=f"emr_widget_{i}"
                )
                job["charting_system"] = emr_selection
                
            with col_shifts:
                existing_shifts = job.get("prn_shifts_per_month", "Full-Time")
                shifts_selection = st.text_input(
                    f"Employment Type / PRN Shifts:",
                    value=existing_shifts,
                    key=f"shifts_widget_{i}"
                )
                job["prn_shifts_per_month"] = shifts_selection
                
        updated_history.append(job)
    
    st.session_state["parsed_payload"]["work_history"] = updated_history
    
    st.markdown("---")
    st.subheader("🚀 Verification Step 2: Compile Document")
    
    if st.button("Compile & Download Enriched Profile (PDF)", type="primary"):
        with st.spinner("Stitching final presentation layers onto document canvas..."):
            
            compiled_licenses = st.session_state.get("manual_states_compiled", [])
            compiled_certs = st.session_state.get("manual_certs_compiled", [])
                    
            final_pdf = build_pdf(
                st.session_state["parsed_payload"], 
                compiled_licenses, 
                compiled_certs, 
                st.session_state["final_highlights"]
            )
            
            st.balloons()
            st.success("Candidate Profile generated successfully!")
            
            st.download_button(
                label="📥 Download Final Structured Candidate Profile (PDF)",
                data=final_pdf,
                file_name=f"Final_Enriched_Profile_{st.session_state['parsed_payload'].get('name', 'Candidate')}.pdf",
                mime="application/pdf"
            )
