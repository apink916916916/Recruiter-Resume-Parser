"""
Healthcare Resume Parser & Candidate Profile Generator
=======================================================
"""
import streamlit as st
import anthropic
from fpdf import FPDF
import json

# ---------------------------------------------------------
# 1. THE SECURITY GATEKEEPER (PASSWORD PROTECTION)
# ---------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    st.set_page_config(page_title="🔒 Internal Access", page_icon="🔒")
    st.title("🔒 Company Internal Tool Access")
    user_password = st.text_input("Please enter the recruiter access password:", type="password")
    
    # Validates against the Streamlit Advanced Settings Secrets Vault
    if user_password == st.secrets.get("ACCESS_PASSWORD", ""):
        st.session_state["authenticated"] = True
        st.rerun()
    elif user_password != "":
        st.error("❌ Incorrect password. Please try again.")
    st.stop()

# ---------------------------------------------------------
# 2. APP CONFIGURATION & CONSTANTS
# ---------------------------------------------------------
st.set_page_config(page_title="Healthcare Resume Parser", page_icon="🩺", layout="wide")

STATES_LIST = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "Compact RN"]
CERTS_LIST = ["ACLS", "BLS", "PALS", "TNCC", "ENPC", "CEN", "CCRN", "AWHONN - Advanced", "AWHONN - Intermediate", "C-EFM", "CIC", "CNE", "CNM", "CNOR", "COHN", "CPEN", "CPI", "MAB", "CRNFA", "CWCN", "CWON", "FNP", "NCSN", "OCN", "ONC", "WCC"]
MODALITIES = ["RN", "LPN", "CNA", "LPT", "CLS", "SLP", "SLPA", "PT", "LCSW", "LMFT"]

SYSTEM_PROMPT = """You are an expert healthcare recruitment assistant. Your job is to extract data from a medical resume and format it into a highly structured JSON object.

CRITICAL INSTRUCTIONS:
1. DO NOT extract or look for Licenses or Certifications. Completely ignore those sections of the resume.
2. TIMELINE AUDIT (JOINT COMMISSION COMPLIANCE): Audit the candidate's work history timeline over the past 7 years (back to 2019). The current date is May 14, 2026.
   - Calculate gaps between positions. If a gap of more than 30 days is detected, you MUST insert a placeholder entry into the 'work_history' array.
   - BUFFER RULE: If job A ends in Month X and job B starts in Month X or X+1, do NOT count it as a gap. Only flag missing full calendar months.
   - OVERLAP RULE: If jobs overlap or run concurrently, no gap exists.
   - If a gap is valid, insert this exact object:
     {
       "title": "Employment Gap / Personal Time",
       "company": "N/A",
       "dates": "MM/YYYY - MM/YYYY (or corresponding gap dates)",
       "duties": ["Timeline gap accounted for."]
     }
3. Sort all work history entries (including gaps) in reverse chronological order (newest first).

Your output must be raw JSON matching this structure exactly:
{
  "name": "",
  "contact_info": "",
  "summary": "",
  "education": [],
  "work_history": [
    {"title": "", "company": "", "dates": "", "duties": []}
  ]
}"""

# ---------------------------------------------------------
# 3. CUSTOM PDF GENERATION CLASS (FPDF RECOVERY IMPLEMENTED)
# ---------------------------------------------------------
class CustomPDF(FPDF):
    def header(self):
        # Graceful logo integration
        try:
            self.image('logo.png', x='C', w=45)
            self.ln(10)
        except:
            pass # Silently skip if logo.png is missing

    def footer(self):
        # Blank footer per compliance request (No system generated date printed)
        pass

    def _clean(self, text: str) -> str:
        """The Ultimate Scrubber - Completely eliminates FPDF Unicode crashes."""
        if not text:
            return ""
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

    def kv_row(self, label: str, value: str):
        self.set_font("Helvetica", "B", 10)
        self.cell(35, 6, self._clean(label) + ":")
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 6, self._clean(value))
        self.ln(1)

    def bullet(self, text: str):
        """Bulletproof margin containment rule preventing 0-horizontal space crash."""
        self.set_x(self.l_margin + 5)
        current_y = self.get_y()
        self.set_font("Helvetica", "", 10)
        self.cell(6, 6, "-")
        
        self.set_xy(self.l_margin + 11, current_y)
        self.multi_cell(0, 6, self._clean(text))
        self.set_y(self.get_y() + 1)

# ---------------------------------------------------------
# 4. CORE PIPELINE FUNCTIONS
# ---------------------------------------------------------
def call_anthropic(resume_text: str) -> dict:
    """Directly leverages secure vault to call Claude and parse raw text."""
    try:
        client = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Here is the full resume text to parse:\n\n{resume_text}"}],
        )
        # Parse the response text clean of Markdown syntax wrapper if present
        raw_content = message.content[0].text.strip()
        if raw_content.startswith("```json"):
            raw_content = raw_content.split("```json")[1].split("```")[0].strip()
        elif raw_content.startswith("```"):
            raw_content = raw_content.split("```")[1].split("```")[0].strip()
        return json.loads(raw_content)
    except Exception as e:
        st.error(f"Failed to connect or parse with Anthropic: {e}")
        return None

def build_pdf(data: dict, manual_licenses: list, manual_certs: list) -> bytes:
    """Combines AI parsed details with manual UI overlays into structured FPDF."""
    pdf = CustomPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Profile Summary Block
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 8, pdf._clean(data.get("name", "Candidate Profile")), ln=True, align="C")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 6, pdf._clean(data.get("contact_info", "")), ln=True, align="C")
    pdf.ln(6)
    
    if data.get("summary"):
        pdf.section_heading("Professional Summary")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 5, pdf._clean(data.get("summary")))
        pdf.ln(4)

    # Licenses Section (100% Controlled UI Override Mapping)
    pdf.section_heading("Verified Licenses")
    if manual_licenses:
        for lic in manual_licenses:
            pdf.bullet(f"{lic['modality']} - {lic['state']} - Exp: {lic['exp_date']}")
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "None Declared/Listed", ln=True)
    pdf.ln(4)

    # Certifications Section (100% Controlled UI Override Mapping)
    pdf.section_heading("Professional Certifications")
    if manual_certs:
        for cert in manual_certs:
            pdf.bullet(f"{cert['name']} - Exp: {cert['exp_date']}")
    else:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, "None Declared/Listed", ln=True)
    pdf.ln(4)

    # Work History & Compliance Section
    pdf.section_heading("Employment History (7-Year Compliance Audit)")
    for job in data.get("work_history", []):
        pdf.set_font("Helvetica", "B", 10)
        title_company = f"{job.get('title', 'N/A')} - {job.get('company', 'N/A')}"
        pdf.cell(140, 6, pdf._clean(title_company))
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 6, pdf._clean(job.get("dates", "N/A")), ln=True, align="R")
        pdf.ln(1)
        
        for duty in job.get("duties", []):
            pdf.bullet(duty)
        pdf.ln(2)

    # Education Block
    if data.get("education"):
        pdf.section_heading("Education Matrix")
        for edu in data.get("education", []):
            pdf.bullet(str(edu))
            
    return pdf.output()

# ---------------------------------------------------------
# 5. STREAMLIT INTERFACE / GRAPHICAL RUNTIME
# ---------------------------------------------------------
st.title("🩺 Healthcare Candidate Profile Generator")
st.write("Upload a messy resume to automatically audit history timelines, remove text artifacts, and map standardized credentials.")

col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("1. Source Document")
    uploaded_file = st.file_uploader("Upload candidate resume (Text format for processing)", type=["txt"])
    resume_raw_text = ""
    if uploaded_file:
        resume_raw_text = uploaded_file.read().decode("utf-8")
        st.success("Resume data successfully staged.")

with col2:
    st.subheader("2. Standardized Credentials Override")
    
    # Licenses Selection & Columnized Sub-loops
    selected_states = st.multiselect("Manually Add Active State Licenses / Compacts:", options=STATES_LIST)
    compiled_licenses = []
    if selected_states:
        st.info("Assign corresponding clinical designations and timeline boundaries:")
        for state in selected_states:
            c_mod, c_exp = st.columns([1, 1])
            with c_mod:
                mod = st.selectbox(f"Modality ({state}):", options=MODALITIES, key=f"mod_{state}")
            with c_exp:
                exp = st.text_input(f"Expiration Date ({state}):", placeholder="MM/YYYY or Permanent", key=f"exp_{state}")
            compiled_licenses.append({"state": state, "modality": mod, "exp_date": exp if exp else "Not Specified"})
            st.markdown("---")

    # Certifications Selection Matrix
    selected_certs = st.multiselect("Manually Add Professional Certifications:", options=CERTS_LIST)
    compiled_certs = []
    if selected_certs:
        st.info("Assign timeline boundaries for specialty validations:")
        for cert in selected_certs:
            exp_c = st.text_input(f"Expiration Date ({cert}):", placeholder="MM/YYYY or Active", key=f"cert_exp_{cert}")
            compiled_certs.append({"name": cert, "exp_date": exp_c if exp_c else "Active"})

# Execution Trigger
if st.button("Generate Stitched Compliance Profile", type="primary"):
    if not resume_raw_text:
        st.error("Action Blocked: Please upload a raw text resume source to initialize parser engine.")
    else:
        with st.spinner("Analyzing timelines and compiling client-ready profile..."):
            parsed_json = call_anthropic(resume_raw_text)
            
            if parsed_json:
                # Compile PDF using standard UI variables
                final_pdf = build_pdf(parsed_json, compiled_licenses, compiled_certs)
                
                st.balloons()
                st.success("Candidate Profile generated successfully!")
                
                st.download_button(
                    label="📥 Download Structured Candidate Profile (PDF)",
                    data=final_pdf,
                    file_name=f"Parsed_Profile_{parsed_json.get('name', 'Candidate')}.pdf",
                    mime="application/pdf"
                )
