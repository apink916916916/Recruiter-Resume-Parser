"""
Healthcare Resume Parser & Candidate Profile Generator
=======================================================
A Streamlit app that:
  1. Accepts a resume PDF upload
  2. Extracts raw text via pdfplumber
  3. Sends text to the Anthropic API for structured JSON extraction
     (name, specialty, contact, work history, education)
  4. Combines the structured data with manual highlights, licenses, and
     certifications entered by the recruiter in the UI
  5. Renders a clean, formatted PDF using FPDF and serves it as a download
"""

import json
import io
import re
from datetime import datetime

import streamlit as st
import pdfplumber
import anthropic
from fpdf import FPDF

# ─────────────────────────────────────────────
# CREDENTIAL OPTION LISTS  (manual override)
# Extend these lists freely as your team needs.
# ─────────────────────────────────────────────

CERT_OPTIONS = [
    "ACLS", "BLS", "PALS", "TNCC", "ENPC", "CEN", "CCRN",
    "AWHONN - Advanced", "AWHONN - Intermediate", "C-EFM", "CIC", "CNE",
    "CNM", "CNOR", "COHN", "CPEN", "CPI", "MAB", "CRNFA", "CWCN",
    "CWON", "FNP", "NCSN", "NMTCB", "OCN", "ONC", "WCC",
]

LICENSE_OPTIONS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI",
    "WY", "Compact RN",
]

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Healthcare Candidate Profile Generator",
    page_icon="🏥",
    layout="wide",
)

# ─────────────────────────────────────────────
# CUSTOM CSS  – clean, clinical aesthetic
# ─────────────────────────────────────────────
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=DM+Serif+Display&display=swap');

    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

    /* Page background */
    .stApp { background: #f4f6f9; }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #0d2137;
        color: #e8edf2;
    }
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stMarkdown p {
        color: #b8c8d8 !important;
    }

    /* Hero header */
    .hero-header {
        background: linear-gradient(135deg, #0d2137 0%, #1a4a6e 60%, #1e6fa0 100%);
        border-radius: 12px;
        padding: 2rem 2.5rem;
        margin-bottom: 1.5rem;
        color: white;
    }
    .hero-header h1 {
        font-family: 'DM Serif Display', serif;
        font-size: 2rem;
        margin: 0 0 0.4rem 0;
        letter-spacing: -0.5px;
    }
    .hero-header p { margin: 0; opacity: 0.75; font-size: 0.95rem; }

    /* Card panels */
    .card {
        background: white;
        border-radius: 10px;
        padding: 1.5rem;
        box-shadow: 0 1px 6px rgba(0,0,0,.07);
        margin-bottom: 1.2rem;
    }
    .card-title {
        font-weight: 600;
        font-size: 0.78rem;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        color: #1a4a6e;
        margin-bottom: 0.8rem;
        border-bottom: 2px solid #e8f0f7;
        padding-bottom: 0.5rem;
    }

    /* Result table rows */
    .result-row {
        display: flex;
        justify-content: space-between;
        padding: 0.35rem 0;
        border-bottom: 1px solid #f0f4f8;
        font-size: 0.9rem;
    }
    .result-label { color: #6b7f95; font-weight: 500; min-width: 160px; }
    .result-value { color: #1a2b3c; font-weight: 400; text-align: right; }

    /* Status badges */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.5px;
    }
    .badge-blue  { background: #dbeafe; color: #1d4ed8; }
    .badge-green { background: #dcfce7; color: #15803d; }
    .badge-amber { background: #fef3c7; color: #b45309; }

    /* Primary button override */
    div.stButton > button {
        background: linear-gradient(135deg, #1a4a6e, #1e6fa0);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 0.55rem 1.6rem;
        font-size: 0.95rem;
        transition: opacity 0.2s;
    }
    div.stButton > button:hover { opacity: 0.87; }

    /* Download button */
    div.stDownloadButton > button {
        background: #15803d;
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        padding: 0.55rem 1.6rem;
    }
    div.stDownloadButton > button:hover { opacity: 0.87; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# HERO HEADER
# ─────────────────────────────────────────────
st.markdown(
    """
    <div class="hero-header">
        <h1>🏥 Healthcare Candidate Profile Generator</h1>
        <p>Upload a resume PDF → AI extracts structured data → Download a polished candidate profile</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────
# SIDEBAR – API key input
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Configuration")
    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        placeholder="sk-ant-...",
        help="Your key is used only for this session and never stored.",
    )
    st.markdown("---")
    st.markdown(
        """
        **How it works**
        1. Paste your Anthropic API key above
        2. Upload a candidate PDF resume
        3. Optionally add recruiter highlights
        4. Click **Generate** → download the PDF
        """
    )
    st.markdown("---")
    st.caption("Powered by Claude 3 Sonnet + pdfplumber + FPDF")

# ─────────────────────────────────────────────
# MAIN LAYOUT  –  two columns
# ─────────────────────────────────────────────
col_left, col_right = st.columns([1, 1], gap="large")

# ── LEFT COLUMN: inputs ──────────────────────
with col_left:
    st.markdown('<div class="card-title">📄 Resume Upload</div>', unsafe_allow_html=True)
    uploaded_file = st.file_uploader(
        "Drop a PDF resume here",
        type=["pdf"],
        help="Multi-page resumes are fully supported.",
        label_visibility="collapsed",
    )

    st.markdown("")
    st.markdown('<div class="card-title">✏️ Recruiter Highlights</div>', unsafe_allow_html=True)
    highlights = st.text_area(
        "Candidate Highlights",
        height=150,
        placeholder=(
            "e.g.\n"
            "• 8 years ICU experience across Level I trauma centers\n"
            "• Open to travel – 13-week contracts preferred\n"
            "• Currently on assignment in Phoenix, AZ\n"
            "• Excellent references available on request"
        ),
        label_visibility="collapsed",
    )

    # ── Manual Certifications Override ───────────────────────────────────────
    st.markdown("")
    st.markdown('<div class="card-title">➕ Manually Add Certifications</div>', unsafe_allow_html=True)
    selected_certs = st.multiselect(
        "Select certifications to add",
        options=CERT_OPTIONS,
        placeholder="Choose one or more certifications…",
        label_visibility="collapsed",
    )
    # Render one expiration date input per selected cert, keyed by cert name
    manual_cert_expirations = {}
    if selected_certs:
        st.caption("Enter expiration date for each selected certification:")
        for cert_name in selected_certs:
            exp_val = st.text_input(
                f"Exp. date — {cert_name}",
                placeholder="MM/YYYY",
                key=f"cert_exp_{cert_name}",
            )
            manual_cert_expirations[cert_name] = exp_val.strip()

    # ── Manual Licenses Override ──────────────────────────────────────────────
    st.markdown("")
    st.markdown('<div class="card-title">➕ Manually Add Licenses</div>', unsafe_allow_html=True)
    selected_licenses = st.multiselect(
        "Select licenses to add",
        options=LICENSE_OPTIONS,
        placeholder="Choose one or more licenses…",
        label_visibility="collapsed",
    )
    # Render modality selectbox + expiration date input side-by-side for each license
    manual_license_data = {}  # {lic_name: {"modality": str, "expiration": str}}
    if selected_licenses:
        st.caption("Set modality and expiration date for each selected license:")
        for lic_name in selected_licenses:
            col_mod, col_exp = st.columns([1, 1])
            with col_mod:
                modality = st.selectbox(
                    f"Modality — {lic_name}",
                    options=["RN", "LPN", "CNA", "LPT", "CLS", "SLP", "SLPA", "PT", "NMT", "LMFT", "LCSW"],
                    key=f"lic_mod_{lic_name}",
                    label_visibility="visible",
                )
            with col_exp:
                exp_val = st.text_input(
                    f"Expiration — {lic_name}",
                    placeholder="MM/YYYY",
                    key=f"lic_exp_{lic_name}",
                    label_visibility="visible",
                )
            manual_license_data[lic_name] = {
                "modality": modality,
                "expiration": exp_val.strip(),
            }

    st.markdown("")
    generate_btn = st.button("🚀 Generate Stitched PDF", use_container_width=True)

# ── RIGHT COLUMN: results / preview ──────────
with col_right:
    st.markdown('<div class="card-title">📋 Extracted Profile Preview</div>', unsafe_allow_html=True)
    preview_placeholder = st.empty()
    preview_placeholder.info("Upload a resume and click **Generate** to see the extracted profile here.")

# ─────────────────────────────────────────────
# HELPER: Extract text from PDF using pdfplumber
# ─────────────────────────────────────────────

def extract_pdf_text(file_bytes: bytes) -> str:
    """Open the PDF from bytes and concatenate text from every page."""
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
    return "\n".join(text_parts)


# ─────────────────────────────────────────────
# HELPER: Call Anthropic API for structured extraction
# ─────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert healthcare recruiting assistant.
Your task is to parse a resume and return a STRICTLY valid JSON object — no markdown, no backticks, no commentary.
Return ONLY the JSON object below, replacing placeholder values.

IMPORTANT: Do NOT extract or include licenses or certifications — those fields are managed
separately and must be completely omitted from your response.

{
  "candidate_name": "Full Name",
  "specialty": "e.g. ICU RN / Travel Nurse",
  "phone": "xxx-xxx-xxxx or N/A",
  "email": "email@domain.com or N/A",
  "work_history": [
    {
      "job_title": "Staff RN - ICU",
      "company": "General Hospital",
      "location": "Chicago, IL",
      "dates": "03/2021 - Present",
      "duties": [
        "Managed care for critically ill patients in a 24-bed ICU",
        "Performed rapid response assessments and code blue interventions"
      ]
    }
  ],
  "education": [
    {"degree": "BSN", "institution": "University Name", "year": "2015"}
  ]
}

Rules:
- Scan the ENTIRE document — dense summary paragraphs, tables, sidebars, and bulleted lists.
- Do NOT include a "licenses" or "certifications" key anywhere in your response.
- For work_history, capture every position listed. Include all duty/responsibility bullet points
  under each role as an array of strings in "duties". If no duties are listed, use [].

TIMELINE AUDIT — perform this after extracting all positions:

FIXED REFERENCE DATES:
  - TODAY = May 14, 2026. Use this exact date for all calculations. Do not infer any other date.
  - WINDOW START = May 2019 (exactly 7 years before today).
  - Ignore any role whose end date falls entirely before May 2019.

STEP-BY-STEP PROCEDURE:

Step 1 — Normalise all dates.
  Convert every start/end date to (YYYY, MM) integer tuples so all comparisons are on the
  same scale. If a role lists "Present" or is the current job, treat its end as (2026, 05).
  If only a year is given (e.g. "2021"), assume January of that year for start dates and
  December for end dates.

Step 2 — Sort ascending.
  Sort all positions that overlap the audit window by start date, oldest first.

Step 3 — Apply the "next-month buffer" rule (CRITICAL — this prevents false positives).
  Two adjacent positions have NO gap if:
    end_month of role A  >=  start_month of role B  - 1
  In plain English: if role A ends in month X and role B starts in month X or X+1,
  treat them as contiguous. Only flag a gap when at least one full calendar month is
  completely unaccounted for between the two roles.
  Example — NOT a gap:  Role A ends Jan 2023, Role B starts Feb 2023  (adjacent months)
  Example — NOT a gap:  Role A ends Jan 2023, Role B starts Jan 2023  (same month / overlap)
  Example — IS a gap:   Role A ends Jan 2023, Role B starts Mar 2023  (Feb 2023 is missing)

Step 4 — Overlap / concurrent jobs.
  If two roles overlap (role B starts before role A ends), treat them as contiguous.
  Never insert a gap between overlapping or concurrent positions.

Step 5 — Check the window opening.
  Apply the same buffer rule between WINDOW START (May 2019) and the earliest position's
  start date. If the candidate's first position in the window starts in May 2019 or
  June 2019, no opening gap exists.

Step 6 — Check the window closing.
  Apply the same buffer rule between the most recent position's end date and TODAY
  (May 2026). If the candidate is currently employed ("Present"), there is no closing gap.

Step 7 — Insert placeholders only for confirmed gaps.
  For each confirmed gap, insert EXACTLY this shape:
        {
          "job_title": "Employment Gap / Personal Time",
          "company": "N/A",
          "location": "",
          "dates": "<gap start MM/YYYY> - <gap end MM/YYYY>",
          "duties": ["Timeline gap accounted for."]
        }

Step 8 — Verify before outputting.
  Mentally walk the final timeline from May 2019 to May 2026.
  Every month should be covered by either a real role or a gap placeholder.
  If the total tenure of all roles plus the duration of all gap placeholders equals
  approximately 84 months (7 years), the audit is correct. If not, re-check your work.

Step 9 — Final sort.
  Sort the COMPLETE work_history array (real roles + placeholders) in REVERSE
  chronological order (most recent first) before writing the JSON output.

- If a field is missing, use null for scalar values or [] for arrays.
- Return ONLY the JSON. No extra text.
"""

def call_anthropic(api_key: str, resume_text: str) -> dict:
    """Send resume text to Claude and return the parsed JSON dict."""
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,  # Increased to handle work history with duty bullets
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Here is the full resume text to parse:\n\n{resume_text}",
            }
        ],
    )
    raw = message.content[0].text.strip()
    # Strip any accidental markdown fences the model may have added
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


# ─────────────────────────────────────────────
# HELPER: Generate PDF with FPDF
# ─────────────────────────────────────────────

class CandidatePDF(FPDF):
    """Custom FPDF subclass with shared header/footer styling."""

    BRAND_DARK  = (13,  33,  55)    # #0d2137
    BRAND_MID   = (26,  74, 110)    # #1a4a6e
    BRAND_LIGHT = (30, 111, 160)    # #1e6fa0
    TEXT_DARK   = (26,  43,  60)    # #1a2b3c
    TEXT_MID    = (80, 100, 120)
    RULE_COLOR  = (210, 220, 230)

    def header(self):
        # Thin brand-colored top bar
        self.set_fill_color(*self.BRAND_DARK)
        self.rect(0, 0, 210, 8, "F")
        self.ln(12)

    def footer(self):
        pass  # No footer text — keeps the PDF clean and timeless

    def section_heading(self, title: str):
        """Render a styled section heading with a colored underline rule."""
        self.ln(4)
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*self.BRAND_MID)
        self.cell(0, 8, title.upper(), ln=True)
        # Underline rule
        self.set_draw_color(*self.BRAND_LIGHT)
        self.set_line_width(0.5)
        self.line(self.get_x(), self.get_y(), self.get_x() + 190, self.get_y())
        self.ln(3)

    @staticmethod
    def _clean(text: str) -> str:
        """Sanitise Unicode chars that crash Helvetica / Latin-1 encoding."""
        return (
            str(text)
            .replace("\u2013", "-")   # en dash
            .replace("\u2014", "-")   # em dash
            .replace("\u2018", "'")   # left single quote
            .replace("\u2019", "'")   # right single quote / apostrophe
            .replace("\u201c", '"')   # left double quote
            .replace("\u201d", '"')   # right double quote
            .replace("\u2022", "-")   # bullet
        )

    def kv_row(self, label: str, value: str):
        """Render a label/value pair on the same line."""
        if not value or value in ("null", "N/A"):
            return
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*self.TEXT_MID)
        self.cell(45, 6, self._clean(label) + ":", ln=False)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*self.TEXT_DARK)
        self.multi_cell(0, 6, self._clean(value))

    def bullet(self, text: str):
        # Force the cursor to an indented left margin
        self.set_x(self.l_margin + 5)
        current_y = self.get_y()
        
        # Draw a safe, standard keyboard hyphen
        self.cell(6, 6, "-")
        
        # 1. Convert to string and handle basic replacements
        clean_text = str(text).replace("–", "-").replace("—", "-").replace("’", "'").replace("“", '"').replace("”", '"').replace("•", "-")
        
        # 2. Handle non-breaking spaces and special quotes
        clean_text = clean_text.replace('\xa0', ' ').replace('\u2013', '-').replace('\u2014', '-')
        
        # 3. THE SAFETY NET: Force everything into a format PDF can read
        # Any "illegal" characters will be replaced with ? so the app doesn't crash
        clean_text = clean_text.encode('cp1252', 'replace').decode('cp1252')
        
        # Lock the cursor safely past the hyphen to draw the actual text
        self.set_xy(self.l_margin + 11, current_y)
        self.multi_cell(0, 6, clean_text)
        
        # Add a tiny bit of padding before the next bullet
        self.set_y(self.get_y() + 1)

    def light_rule(self):
        self.set_draw_color(*self.RULE_COLOR)
        self.set_line_width(0.2)
        self.line(self.get_x(), self.get_y(), self.get_x() + 190, self.get_y())
        self.ln(2)


def build_pdf(data: dict, highlights: str) -> bytes:
    """
    Assemble the candidate profile PDF.

    Layout order:
      1. Logo (if logo.png is present)
      2. Name & Contact Info  — centered at the very top
      3. Candidate Highlights — recruiter notes
      4. Work History         — reverse-chronological roles with duty bullets
      5. Education
      6. Certifications       — built exclusively from manual UI selections
      7. Licenses             — built exclusively from manual UI selections
    """
    pdf = CandidatePDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_margins(10, 14, 10)

    # ── 0. COMPANY LOGO (centred, graceful fallback if file is missing) ─────────
    try:
        logo_w = 50                                          # printed width in mm
        page_w = pdf.w - pdf.l_margin - pdf.r_margin        # usable page width
        logo_x = pdf.l_margin + (page_w - logo_w) / 2      # centre horizontally
        pdf.image("logo.png", x=logo_x, w=logo_w)
        pdf.ln(3)                                            # gap between logo and name
    except Exception:
        pass                                                 # logo.png not found — skip silently

    # ── 1. NAME & CONTACT BLOCK (perfectly centred) ───────────────────────────
    name     = CandidatePDF._clean(data.get("candidate_name") or "Unknown Candidate")
    specialty = CandidatePDF._clean(data.get("specialty") or "")
    phone    = CandidatePDF._clean(data.get("phone") or "")
    email    = CandidatePDF._clean(data.get("email") or "")

    # Candidate name — large, bold, centred
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(*CandidatePDF.BRAND_DARK)
    pdf.cell(0, 11, name, ln=True, align="C")

    # Specialty sub-title — centred in brand blue
    if specialty:
        pdf.set_font("Helvetica", "I", 11)
        pdf.set_text_color(*CandidatePDF.BRAND_LIGHT)
        pdf.cell(0, 6, specialty, ln=True, align="C")

    # Contact line (Phone  |  Email) — centred, smaller
    contact_parts = [p for p in [phone, email] if p and p.lower() not in ("n/a", "null")]
    if contact_parts:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*CandidatePDF.TEXT_MID)
        pdf.cell(0, 6, "  |  ".join(contact_parts), ln=True, align="C")

    # Decorative rule beneath the header block
    pdf.ln(2)
    pdf.set_draw_color(*CandidatePDF.BRAND_DARK)
    pdf.set_line_width(1.0)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(4)

    # ── 2. CANDIDATE HIGHLIGHTS ───────────────────────────────────────────────
    if highlights and highlights.strip():
        pdf.section_heading("Candidate Highlights")
        for line in highlights.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            # Strip any bullet chars the recruiter may have typed themselves
            clean = stripped.lstrip("*+-\u2022\u2013\u2014 ").strip()
            if clean:
                pdf.bullet(clean)
        pdf.ln(1)

    # ── 3. WORK HISTORY ───────────────────────────────────────────────────────
    work_history = data.get("work_history") or []
    if work_history:
        pdf.section_heading("Work History")
        for job in work_history:
            # Job title line — bold
            title    = CandidatePDF._clean(job.get("job_title") or "")
            company  = CandidatePDF._clean(job.get("company")   or "")
            location = CandidatePDF._clean(job.get("location")  or "")
            dates    = CandidatePDF._clean(job.get("dates")     or "")

            if title:
                pdf.set_font("Helvetica", "B", 9)
                pdf.set_text_color(*CandidatePDF.BRAND_MID)
                pdf.cell(0, 6, title, ln=True)

            # Company / location / dates on one line in muted colour
            meta_parts = [p for p in [company, location, dates] if p]
            if meta_parts:
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(*CandidatePDF.TEXT_MID)
                # Indent slightly to sit under the title
                pdf.cell(4, 5, "", ln=False)
                pdf.cell(0, 5, "  -  ".join(meta_parts), ln=True)

            # Duty bullets — indented under the role
            duties = job.get("duties") or []
            for duty in duties:
                duty_clean = CandidatePDF._clean(duty)
                if duty_clean.strip():
                    pdf.set_font("Helvetica", "", 9)
                    pdf.set_text_color(*CandidatePDF.TEXT_DARK)
                    # set_x pins the left edge so multi_cell wraps within the
                    # same indented column instead of snapping back to margin.
                    pdf.set_x(pdf.l_margin + 5)
                    pdf.cell(5, 6, "-", ln=False)
                    pdf.multi_cell(0, 6, duty_clean)

            pdf.ln(2)  # breathing room between roles

    # ── 4. EDUCATION ──────────────────────────────────────────────────────────
    education = data.get("education") or []
    if education:
        pdf.section_heading("Education")
        for edu in education:
            parts = []
            if edu.get("degree"):      parts.append(CandidatePDF._clean(edu["degree"]))
            if edu.get("institution"): parts.append(CandidatePDF._clean(edu["institution"]))
            if edu.get("year"):        parts.append(f'({CandidatePDF._clean(edu["year"])})')
            if parts:
                pdf.bullet("  ".join(parts))
        pdf.ln(1)

    # ── 5. CERTIFICATIONS ─────────────────────────────────────────────────────
    certs = data.get("certifications") or []
    if certs:
        pdf.section_heading("Certifications")
        for cert in certs:
            cert_name = CandidatePDF._clean(cert.get("name") or "")
            exp_str   = CandidatePDF._clean(cert.get("expiration") or "")
            line      = cert_name + (f"  -  Exp: {exp_str}" if exp_str else "")
            pdf.bullet(line)
        pdf.ln(1)

    # ── 6. LICENSES ───────────────────────────────────────────────────────────
    licenses = data.get("licenses") or []
    if licenses:
        pdf.section_heading("Licenses")
        # Format: "Modality - State - Exp: Date"  e.g. "RN - CA - Exp: 12/2025"
        for lic in licenses:
            modality = CandidatePDF._clean(lic.get("modality") or "")
            state    = CandidatePDF._clean(lic.get("state")    or "")
            exp      = CandidatePDF._clean(lic.get("expiration") or "")
            parts    = [p for p in [modality, state] if p]
            line     = " - ".join(parts)
            if exp:
                line += f" - Exp: {exp}"
            if line.strip():
                pdf.bullet(line)
        pdf.ln(1)

    return bytes(pdf.output())


# ─────────────────────────────────────────────
# MAIN LOGIC: wired to the Generate button
# ─────────────────────────────────────────────

if generate_btn:
    # ── Validation ────────────────────────────
    if not api_key:
        st.error("⚠️  Please enter your Anthropic API key in the sidebar.")
        st.stop()
    if not uploaded_file:
        st.error("⚠️  Please upload a PDF resume.")
        st.stop()

    # ── Step 1: Extract PDF text ──────────────
    with st.spinner("📄  Extracting text from PDF…"):
        file_bytes = uploaded_file.read()
        resume_text = extract_pdf_text(file_bytes)

    if not resume_text.strip():
        st.error("Could not extract any text from the uploaded PDF. Please try a text-based (non-scanned) PDF.")
        st.stop()

    # ── Step 2: Call Anthropic API ────────────
    with st.spinner("🤖  Asking Claude to parse and deduplicate credentials…"):
        try:
            structured_data = call_anthropic(api_key, resume_text)
        except json.JSONDecodeError as exc:
            st.error(f"Claude returned non-JSON output. Details: {exc}")
            st.stop()
        except Exception as exc:
            st.error(f"Anthropic API error: {exc}")
            st.stop()

    # ── Step 2b: Build licenses & certifications exclusively from manual UI ─────
    # The AI prompt no longer extracts these fields. We build both lists entirely
    # from what the recruiter selected in the multiselect dropdowns.

    # Certifications — each selected cert name + its expiration text input
    structured_data["certifications"] = [
        {"name": cert_name, "expiration": exp or None}
        for cert_name, exp in manual_cert_expirations.items()
        if cert_name.strip()
    ]

    # Licenses — LICENSE_OPTIONS are bare state codes ("TX") or "Compact RN".
    # Each entry now also carries the recruiter-selected modality (RN, LPN, CNA, LPT, CLS, SLP, SLPA, PT, NMT, LMFT, LCSW).
    manual_licenses = []
    for lic_name, lic_info in manual_license_data.items():
        modality = lic_info.get("modality") or "RN"
        exp      = lic_info.get("expiration") or None
        if lic_name == "Compact RN":
            state = "Compact RN"
        else:
            state = lic_name   # 2-letter abbreviation, e.g. "TX"
        manual_licenses.append(
            {"modality": modality, "state": state, "expiration": exp}
        )
    structured_data["licenses"] = manual_licenses

    # ── Step 3: Render preview ─────────────────
    with preview_placeholder.container():
        def _badge(txt, color="blue"):
            return f'<span class="badge badge-{color}">{txt}</span>'

        html = '<div class="card">'
        html += f'<div class="card-title">👤 {structured_data.get("candidate_name","—")}</div>'
        if structured_data.get("specialty"):
            html += f'<p style="color:#1e6fa0;font-weight:500;margin-bottom:8px">{structured_data["specialty"]}</p>'

        def row(label, val):
            if val and val != "null":
                return f'<div class="result-row"><span class="result-label">{label}</span><span class="result-value">{val}</span></div>'
            return ""

        html += row("📞 Phone", structured_data.get("phone"))
        html += row("✉️ Email", structured_data.get("email"))
        html += "</div>"  # close overview card

        # Work History card
        work_history = structured_data.get("work_history") or []
        if work_history:
            html += '<div class="card"><div class="card-title">💼 Work History</div>'
            for job in work_history:
                title   = job.get("job_title", "")
                company = job.get("company", "")
                loc     = job.get("location", "")
                dates   = job.get("dates", "")
                meta    = "  -  ".join(p for p in [company, loc, dates] if p)
                html += f'<div style="margin-bottom:10px">'
                html += f'<div style="font-weight:600;color:#1a2b3c;font-size:0.9rem">{title}</div>'
                if meta:
                    html += f'<div style="color:#6b7f95;font-size:0.8rem;margin-bottom:4px">{meta}</div>'
                duties = job.get("duties") or []
                for duty in duties:
                    html += f'<div style="font-size:0.85rem;color:#344a5e;padding-left:10px">- {duty}</div>'
                html += "</div>"
            html += "</div>"

        # Licenses card — format matches PDF: "Modality - State - Exp: Date"
        licenses = structured_data.get("licenses") or []
        if licenses:
            html += '<div class="card"><div class="card-title">🪪 Licenses</div>'
            for lic in licenses:
                modality = lic.get("modality") or ""
                state    = lic.get("state")    or ""
                exp      = lic.get("expiration") or ""
                parts    = [p for p in [modality, state] if p]
                label    = " - ".join(parts)
                exp_str  = f"Exp: {exp}" if exp else ""
                html += (
                    f'<div class="result-row">'
                    f'<span class="result-label">{label}</span>'
                    f'<span class="result-value">{exp_str}</span>'
                    f'</div>'
                )
            html += "</div>"

        # Certs card
        certs = structured_data.get("certifications") or []
        if certs:
            html += '<div class="card"><div class="card-title">📋 Certifications</div>'
            for cert in certs:
                exp    = f'Exp: {cert["expiration"]}' if cert.get("expiration") else ""
                html += (
                    f'<div class="result-row">'
                    f'<span class="result-label">{cert.get("name","")}</span>'
                    f'<span class="result-value">{exp}</span>'
                    f'</div>'
                )
            html += "</div>"

        # Education card
        education = structured_data.get("education") or []
        if education:
            html += '<div class="card"><div class="card-title">🎓 Education</div>'
            for edu in education:
                label = "  ".join(p for p in [edu.get("degree",""), edu.get("institution",""), edu.get("year","")] if p)
                html += f'<div class="result-row"><span class="result-label">{label}</span></div>'
            html += "</div>"

        st.markdown(html, unsafe_allow_html=True)

    # ── Step 4: Build PDF ─────────────────────
    with st.spinner("📝  Generating PDF…"):
        pdf_bytes = build_pdf(structured_data, highlights)

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", structured_data.get("candidate_name") or "candidate")
    filename = f"{safe_name}_profile.pdf"

    st.success("✅  Profile generated successfully!")
    st.download_button(
        label="⬇️  Download Candidate Profile PDF",
        data=pdf_bytes,
        file_name=filename,
        mime="application/pdf",
        use_container_width=True,
    )