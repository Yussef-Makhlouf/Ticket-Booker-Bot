import re

def validate_seat_numbers(text: str) -> list[int]:
    """Validaes and extracts seat numbers from a comma-separated string."""
    try:
        return [int(x.strip()) for x in text.split(',')]
    except ValueError:
        return []

def validate_webook_url(url: str) -> bool:
    """Validates if the URL is a Webook event URL."""
    return url.startswith("https://webook.com")
