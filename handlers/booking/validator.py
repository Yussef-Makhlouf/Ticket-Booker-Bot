"""
Input validation for booking flow.
"""
import re
from typing import Optional


class Validator:
    """Validates user input for the booking flow."""

    @staticmethod
    def validate_url(url: str) -> bool:
        """Validate Webook.com URL."""
        return bool(url and url.startswith("https://webook.com"))

    @staticmethod
    def validate_ticket_count(text: str) -> Optional[int]:
        """Validate and extract ticket count (1-10)."""
        try:
            # Support Arabic digits
            text = text.strip()
            for ar, en in zip("٠١٢٣٤٥٦٧٨٩", "0123456789"):
                text = text.replace(ar, en)
            count = int(text)
            if 1 <= count <= 10:
                return count
        except (ValueError, TypeError):
            pass
        return None

    @staticmethod
    def validate_section(section: str) -> bool:
        """Validate section name (e.g., D9, A1, VIP)."""
        if not section:
            return False
        section = section.strip().upper()
        if len(section) > 10:
            return False
        # Allow alphanumeric + some special chars
        return bool(re.match(r'^[A-Z0-9\-_]+$', section))

    @staticmethod
    def validate_email(email: str) -> bool:
        """Basic email validation."""
        return bool(re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email))

    @staticmethod
    def validate_seat_numbers(text: str) -> list:
        """Parse comma-separated seat numbers."""
        try:
            return [int(x.strip()) for x in text.split(",") if x.strip()]
        except ValueError:
            return []
