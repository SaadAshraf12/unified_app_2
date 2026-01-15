"""
CV Parser Module - Extract text and basic info from PDF/DOCX files
"""
import re
from typing import Dict, Optional
import pdfplumber
from docx import Document


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from PDF file."""
    try:
        text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        return text.strip()
    except Exception as e:
        print(f"Error extracting PDF text: {e}")
        return ""


def extract_text_from_docx(file_path: str) -> str:
    """Extract text from DOCX file."""
    try:
        doc = Document(file_path)
        text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        return text.strip()
    except Exception as e:
        print(f"Error extracting DOCX text: {e}")
        return ""


def extract_text_from_cv(file_path: str) -> str:
    """Extract text from CV file based on extension."""
    if file_path.lower().endswith('.pdf'):
        return extract_text_from_pdf(file_path)
    elif file_path.lower().endswith(('.docx', '.doc')):
        return extract_text_from_docx(file_path)
    else:
        return ""


def extract_email(text: str) -> Optional[str]:
    """Extract email address from text."""
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
    matches = re.findall(email_pattern, text)
    return matches[0] if matches else None


def extract_phone(text: str) -> Optional[str]:
    """Extract phone number from text."""
    # Matches various phone formats
    phone_pattern = r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'
    matches = re.findall(phone_pattern, text)
    return matches[0] if matches else None


def extract_linkedin(text: str) -> Optional[str]:
    """Extract LinkedIn URL from text."""
    linkedin_pattern = r'(?:https?://)?(?:www\.)?linkedin\.com/in/[\w-]+'
    matches = re.findall(linkedin_pattern, text, re.IGNORECASE)
    return matches[0] if matches else None


def extract_name(text: str) -> Optional[str]:
    """
    Extract candidate name from CV text.
    Heuristic: Usually the first non-empty line or first few words.
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if lines:
        # Return first line as name (common CV format)
        first_line = lines[0]
        # Remove common titles
        first_line = re.sub(r'^(Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+', '', first_line, flags=re.IGNORECASE)
        # If first line is too long, take first 3-5 words
        words = first_line.split()
        if len(words) > 5:
            return ' '.join(words[:3])
        return first_line
    return None


def parse_cv_basic_info(cv_text: str) -> Dict[str, Optional[str]]:
    """
    Extract basic information from CV text using regex patterns.
    Returns a dictionary with name, email, phone, and LinkedIn.
    """
    return {
        'name': extract_name(cv_text),
        'email': extract_email(cv_text),
        'phone': extract_phone(cv_text),
        'linkedin_url': extract_linkedin(cv_text)
    }
