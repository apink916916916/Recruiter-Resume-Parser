"""
Healthcare Resume Parser & Candidate Profile Generator (Checklist Scribe Engine)
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

if "parsed_payload" not in st.session_state:
    st.session_state["parsed_payload"] = None

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
CERTS_LIST = ["ACLS", "BLS", "PALS", "TNCC", "ENPC", "CEN", "CCRN", "AWHONN - Advanced", "AWHONN - Intermediate", "C-EFM", "CIC", "CNE", "CNM", "CNOR", "COHN", "CPEN", "CPI", "MAB", "CRNFA", "CWCN", "CWON", "FNP", "NCSN", "OCN", "ONC", "WCC"]
MODALITIES = ["RN", "LPN", "CNA", "LPT", "CLS", "SLP", "SLPA", "PT"]
EMR_LIST = ["Epic", "Oracle Cerner", "MEDITECH", "TruBridge / CPSI", "McKesson", "Allscripts / Altera", "MatrixCare", "PointClickCare", "Not Specified / Paper Charting"]

# The Exact Standardized Checklist Matrix
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

SYSTEM_PROMPT = """You are an expert healthcare recruitment assistant. Your job is to extract data from a medical resume and format it into a highly structured JSON object.

CRITICAL INSTRUCTIONS:
1. DO NOT extract or look for Licenses or Certifications in standalone sections. Completely ignore those blocks.
2. LOCATION IS MANDATORY: For every single entry in 'work_history', you MUST extract the City and the 2-letter State code where that hospital is located and put them in 'facility_city' and 'facility_state'. If you cannot find them, default to "US".
3. TIMELINE SORT AUDIT: For every job, extract the exact start date and convert it into a standard hidden sortable string format "YYYY-MM" inside the 'start_date_structured' field. If they started in August 2022, output '2022-08'.
4. TIMELINE AUDIT (GAPS): Audit the candidate's work history timeline over the past 7 years (back to 2019). The current date is May 14, 2026. If a gap of more than 30 days is detected, you MUST insert a placeholder entry object with title "Employment Gap / Personal Time" and company "N/A".
5. EXECUTIVE SUMMARY OF DUTIES (ELIMINATE FLUFF): Summarize their role into exactly 3 to 4 high-level, professional macro bullet points.
6. ADVANCED CLINICAL EXTRACTION (SPECIALTY & CHARTING):
   - For every position, attempt to isolate their clinical specialty area (e.g., ICU, ER, OR, MedSurg, Labor & Delivery). If the resume only states 'Registered Nurse' with no context, set the 'specialty' field to a blank string "".
   - Scan the resume's text or technical bullets for any mention of the EMR/charting system used at that facility (e.g., Epic, Cerner, Meditech). If discovered, place it in the 'charting_system' field. If not found, leave it as a blank string "".
7. RECRUITER CHECKLIST MERGE: The user will pass an initial checklist draft. Look at what information the recruiter has already plugged into it. Review the raw resume text to find metrics that fill any remaining blanks (like '__' or placeholder text). Return a fully populated 10-line array under 'suggested_highlights'. Maintain the exact structure of the 10 core lines.

Your output must be raw JSON matching this structure exactly:
{
  "name": "",
  "contact_info": "",
  "suggested_highlights": [],
  "education": [
    {"degree": "", "institution": "", "location": "", "date": ""}
  ],
  "work_history": [
    {"title": "", "company": "", "facility_city": "", "facility_state": "", "dates": "", "start_date_structured": "", "specialty": "", "charting_system": "", "prn_shifts_per_month": "Full-Time", "duties": []}
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

    # Recruiter Checklist Section
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
        
        metrics = job.get("enriched_metrics")
        if metrics and metrics.get("city") and metrics.get("state"):
            geo_string = f"{metrics['city']}, {metrics['state']}"
        else:
            city_val = str(job.get("facility_city", "")).strip()
            state_val = str(job.get("facility_state", "")).strip()
            if city_val and state_val and city_val != "N/A" and state_val != "N/A":
                geo_string = f"{city_val}, {state_val}"
            elif state_val and state_val != "N/A":
                geo_string = state_val
            else:
                geo_string = ""

        job_title = str(job.get('title', 'N/A'))
        specialty_val = str(job.get('specialty', '')).strip()
        if specialty_val and specialty_val.lower() != "not specified":
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
        if prn_vol and prn_vol != "Full-Time":
            ribbon_parts.append(f"Volume: {prn_vol}")
            
        charting_val = job.get("charting_system", "")
        if charting_val and charting_val.lower() != "not specified":
            ribbon_parts.append(f"EMR: {charting_val}")
        
        if metrics:
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
        
        # PREloaded checklist configuration node
        manual_highlights = st.text_area(
            "Candidate Highlights Template (Edit directly or let the parser fill remaining blanks):",
            value=EXECUTIVE_CHECKLIST_TEMPLATE,
            height=240
        )
        
    with col2:
        st.subheader("2. Initial Standardized Override Credentials")
        selected_states = st.multiselect("Manually Add Active State Licenses / Compacts:", options=STATES_LIST)
        selected_certs = st.multiselect("Manually Add Professional Certifications:", options=CERTS_LIST)

    if st.button("Parse & Extract Resume Data", type="primary"):
        if not uploaded_file:
            st.error("Action Blocked: Please upload a resume file to initialize the tracking sequence.")
        else:
            with st.spinner("Extracting timeline records and combining scorecard profiles..."):
                if uploaded_file.name.endswith(".pdf"):
                    with pdfplumber.open(uploaded_file) as pdf:
                        resume_text = "".join([page.extract_text() for page in pdf.pages if page.extract_text()])
                else:
                    resume_text = uploaded_file.read().decode("utf-8")
                
                # Forward both the resume and the exact state of the checklist area box to Claude
                client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
                message = client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=4000,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": f"Recruiter Checklist State:\n{manual_highlights}\n\nResume Text:\n{resume_text}"}],
                )
                
                raw_content = message.content[0].text.strip()
                if "```json" in raw_content:
                    raw_content = raw_content.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_content:
                    raw_content = raw_content.split("```")[1].split("```")[0].strip()
                
                parsed_data = json.loads(raw_content)
                
                if parsed_data:
                    parsed_data["work_history"] = enrich_work_history(parsed_data.get("work_history", []))
                    
                    parsed_data["work_history"].sort(
                        key=lambda x: x.get("start_date_structured", "1900-01") if x.get("start_date_structured") else "1900-01", 
                        reverse=True
                    )
                    
                    st.session_state["parsed_payload"] = parsed_data
                    st.session_state["active_highlights_draft"] = "\n".join(parsed_data.get("suggested_highlights", []))
                    st.session_state["manual_states"] = selected_states
                    st.session_state["manual_certs"] = selected_certs
                    st.rerun()

else:
    payload = st.session_state["parsed_payload"]
    
    st.info("🎉 Step 1 Complete: Resume data structured successfully. Refine candidate metrics below before generating the final file.")
    
    if st.button("⬅️ Clear & Upload New Resume"):
        st.session_state["parsed_payload"] = None
        st.rerun()
        
    st.markdown("---")
    
    st.subheader("📋 Verification Step 1: Candidate Highlights Executive Checklist Preview")
    st.write("Review or adjust the final populated scorecard list before printing:")
    edited_highlights = st.text_area("Active Document Highlights Board:", value=st.session_state["active_highlights_draft"], height=240)
    
    st.markdown("---")
    st.subheader("🏥 Verification Step 2: Custom Workplace Specialty & Charting Adjustments")
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
                    f"PRN Shifts/Mo (If Per Diem):",
                    value=existing_shifts,
                    key=f"shifts_widget_{i}"
                )
                job["prn_shifts_per_month"] = shifts_selection
                
        updated_history.append(job)
    
    st.session_state["parsed_payload"]["work_history"] = updated_history
    
    st.markdown("---")
    st.subheader("🚀 Verification Step 3: Compile Document")
    
    if st.button("Compile & Download Enriched Profile (PDF)", type="primary"):
        with st.spinner("Stitching final presentation layers onto document canvas..."):
            
            final_states = st.session_state["manual_states"]
            final_certs = st.session_state["manual_certs"]
            
            compiled_licenses = []
            if final_states:
                for state in final_states:
                    compiled_licenses.append({
                        "state": state,
                        "modality": "RN",
                        "exp_date": "Active"
                    })
            compiled_certs = []
            if final_certs:
                for cert in final_certs:
                    compiled_certs.append({
                        "name": cert,
                        "exp_date": "Active"
                    })
                    
            final_pdf = build_pdf(
                st.session_state["parsed_payload"], 
                compiled_licenses, 
                compiled_certs, 
                edited_highlights
            )
            
            st.balloons()
            st.success("Candidate Profile generated successfully!")
            
            st.download_button(
                label="📥 Download Final Structured Candidate Profile (PDF)",
                data=final_pdf,
                file_name=f"Final_Enriched_Profile_{st.session_state['parsed_payload'].get('name', 'Candidate')}.pdf",
                mime="application/pdf"
            )
