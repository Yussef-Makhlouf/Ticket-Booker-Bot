"""
Arabic text processing and RTL formatting helpers.
"""
import re
from typing import Optional

# Arabic-English digit mapping
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
EN_DIGITS = "0123456789"


def to_arabic_digits(text: str) -> str:
    """Convert Western digits to Arabic/Hindi digits."""
    for en, ar in zip(EN_DIGITS, AR_DIGITS):
        text = text.replace(en, ar)
    return text


def to_english_digits(text: str) -> str:
    """Convert Arabic/Hindi digits to Western digits."""
    for ar, en in zip(AR_DIGITS, EN_DIGITS):
        text = text.replace(ar, en)
    return text


def format_price_ar(price: int) -> str:
    """Format price in Arabic style: ١٥٠ ريال"""
    return f"{to_arabic_digits(str(price))} ريال"


def format_number_ar(number: int) -> str:
    """Format a number with Arabic digits."""
    return to_arabic_digits(f"{number:,}")


def clean_arabic_text(text: str) -> str:
    """Clean and normalize Arabic text."""
    if not text:
        return ""
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    # Remove zero-width characters
    text = re.sub(r'[\u200b\u200c\u200d\u200e\u200f\ufeff]', '', text)
    return text


def extract_arabic_section(text: str) -> Optional[str]:
    """Extract section identifier from mixed Arabic/English text."""
    text = text.strip()
    # Try section patterns: D9, A1, VIP, etc.
    match = re.search(r'([A-Za-z]+\d*|\d+[A-Za-z]*)', text)
    if match:
        return match.group(1).upper()
    return text.upper() if len(text) <= 8 else None


ARABIC_MONTHS = {
    "يناير": "01", "فبراير": "02", "مارس": "03",
    "أبريل": "04", "مايو": "05", "يونيو": "06",
    "يوليو": "07", "أغسطس": "08", "سبتمبر": "09",
    "أكتوبر": "10", "نوفمبر": "11", "ديسمبر": "12"
}


def parse_arabic_date(text: str) -> Optional[str]:
    """Try to extract a date from Arabic text."""
    text = to_english_digits(text)

    # Pattern: ١٤ مارس ٢٠٢٥ or 14 مارس 2025
    for month_ar, month_num in ARABIC_MONTHS.items():
        pattern = rf'(\d{{1,2}})\s+{month_ar}\s+(\d{{4}})'
        match = re.search(pattern, text)
        if match:
            return f"{match.group(2)}-{month_num}-{match.group(1).zfill(2)}"

    # Pattern: 2025-03-14 or 14/03/2025
    iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', text)
    if iso_match:
        return iso_match.group(0)

    slash_match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', text)
    if slash_match:
        return f"{slash_match.group(3)}-{slash_match.group(2).zfill(2)}-{slash_match.group(1).zfill(2)}"

    return None
