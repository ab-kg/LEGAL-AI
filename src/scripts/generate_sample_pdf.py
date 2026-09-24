import sys
import subprocess

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
except ImportError:
    print("reportlab not found. Installing...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "reportlab"])
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def main():
    pdf_filename = "sample_legal_contract.pdf"
    print(f"Generating {pdf_filename}...")
    
    doc = SimpleDocTemplate(pdf_filename, pagesize=letter,
                            rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
    
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=18,
        spaceAfter=20,
        alignment=1 # Center
    )
    
    section_style = ParagraphStyle(
        'SectionStyle',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=15,
        spaceAfter=10
    )
    
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        spaceAfter=10
    )
    
    story = []
    
    # Title
    story.append(Paragraph("<b>MASTER SERVICES AGREEMENT</b>", title_style))
    story.append(Spacer(1, 10))
    
    # Intro
    intro_text = (
        "This Master Services Agreement (the \"Agreement\") is entered into as of June 10, 2026 "
        "(the \"Effective Date\"), by and between <b>Acme Global Technologies LLC</b>, a Delaware limited "
        "liability company with its principal place of business at 100 Innovation Way, Wilmington, DE 19801 "
        "(\"Client\"), and <b>Apex Consulting Partners Group</b>, a California corporation with its principal "
        "place of business at 500 Silicon Valley Blvd, San Jose, CA 95110 (\"Service Provider\")."
    )
    story.append(Paragraph(intro_text, body_style))
    story.append(Spacer(1, 10))
    
    # Section 1
    story.append(Paragraph("<b>1. Term and Termination</b>", section_style))
    term_text = (
        "This Agreement shall commence on the Effective Date and shall continue for an initial term of "
        "one (1) year. Either Party may terminate this Agreement without cause upon giving at least "
        "<b>sixty (60) days</b> prior written notice to the other Party. Either Party may terminate this "
        "Agreement immediately for cause if the other Party commits a material breach of this Agreement and "
        "fails to cure such breach within fifteen (15) days of receiving written notice thereof."
    )
    story.append(Paragraph(term_text, body_style))
    story.append(Spacer(1, 10))
    
    # Section 2
    story.append(Paragraph("<b>2. Governing Law and Jurisdiction</b>", section_style))
    gov_text = (
        "This Agreement, and all claims or causes of action arising hereunder, shall be governed by, "
        "and construed in accordance with, the laws of the <b>State of Singapore</b>, without regard to "
        "principles of conflicts of law. The Parties hereby submit to the exclusive jurisdiction of the "
        "courts of Singapore for the resolution of any dispute arising out of or relating to this Agreement."
    )
    story.append(Paragraph(gov_text, body_style))
    story.append(Spacer(1, 10))
    
    # Section 3
    story.append(Paragraph("<b>3. Limitation of Liability</b>", section_style))
    liability_text = (
        "IN NO EVENT SHALL EITHER PARTY BE LIABLE FOR ANY INDIRECT, SPECIAL, INCIDENTAL, PUNITIVE, OR "
        "CONSEQUENTIAL DAMAGES ARISING OUT OF OR IN CONNECTION WITH THIS AGREEMENT. THE MAXIMUM AGGREGATE "
        "LIABILITY OF SERVICE PROVIDER FOR ANY AND ALL CLAIMS ARISING OUT OF THIS AGREEMENT SHALL NOT EXCEED "
        "THE AMOUNT OF <b>850,000 USD</b> (EIGHT HUNDRED AND FIFTY THOUSAND DOLLARS)."
    )
    story.append(Paragraph(liability_text, body_style))
    story.append(Spacer(1, 10))
    
    # Section 4
    story.append(Paragraph("<b>4. Confidentiality</b>", section_style))
    conf_text = (
        "During the Term of this Agreement, each Party may disclose to the other Party certain confidential "
        "business or technical information (\"Confidential Information\"). The receiving Party agrees to keep "
        "such information strictly confidential and use it solely for the purpose of performing its obligations "
        "under this Agreement. The obligations of confidentiality under this Section 4 shall survive the "
        "expiration or termination of this Agreement for a period of three (3) years."
    )
    story.append(Paragraph(conf_text, body_style))
    
    doc.build(story)
    print(f"Successfully generated {pdf_filename}!")

if __name__ == "__main__":
    main()
