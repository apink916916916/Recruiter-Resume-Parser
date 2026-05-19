"""
Healthcare Resume Parser & Candidate Profile Generator
=======================================================
"""
import streamlit as st
import anthropic
from fpdf import FPDF
import json
import pdfplumber

# ---------------------------------------------------------
# 1. APP CONFIGURATION (CRITICAL: MUST BE THE ABSOLUTE FIRST ST COMMAND)
# ---------------------------------------------------------
st.set_page_config(page_title="Healthcare Resume Parser", page_icon="🩺", layout="wide")

# ---------------------------------------------------------
# 2. THE SECURITY GATEKEEPER (PASSWORD PROTECTION)
# ---------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
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
# 3. CONSTANTS
# ---------------------------------------------------------
STATES_LIST = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "Compact RN"]
CERTS_LIST = ["ACLS", "BLS", "PALS", "TNCC", "ENPC", "CEN", "CCRN", "AWHONN - Advanced", "AWHONN - Intermediate", "C-EFM", "CIC", "CNE", "CNM", "CNOR", "COHN", "CPEN", "CPI", "MAB", "CRNFA", "CWCN", "CWON", "FNP", "NCSN", "OCN", "ONC", "WCC"]
MODALITIES = ["RN", "LPN", "CNA", "LPT", "CLS", "SLP", "SLPA", "PT"]

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
# 4. CUSTOM PDF GENERATION CLASS (FPDF RECOVERY IMPLEMENTED)
# ---------------------------------------------------------
class CustomPDF(FPDF):
    def header(self):
        try:
            self.image('logo.png', x='C', w=45)
            self.ln(10)
        except:
            pass

    def footer(self):
        pass

    def _clean(self, text: str) -> str:
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

    def bullet(self, text: str):
        self.set_x(self.l_margin + 5)
        current_y = self.get_y()
        self.set_font("Helvetica", "", 10)
        self.cell(6, 6, "-")
        
        self.set_xy(self.l_margin + 11, current_y)
        self.multi_cell(0, 6, self._clean(text))
        self.set_y(self.get_y() + 1)
