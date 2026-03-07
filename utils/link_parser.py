import re

def extract_event_id(url: str) -> str:
    r"""
    Extracts the event ID from a Webook URL using regex: r'events/[^/]+-(\d+)$'
    """
    match = re.search(r'events/[^/]+-(\d+)(?:/|$|\?)', url)
    if match:
        return match.group(1)
    
    # Try an alternative matching for standard query params if needed
    match = re.search(r'id=(\d+)', url)
    if match:
         return match.group(1)
         
    return None

def determine_event_type(url: str) -> str:
    """
    Simple heuristic to guess event type from URL or name.
    """
    url_lower = url.lower()
    if 'match' in url_lower or 'football' in url_lower or 'roshn' in url_lower or 'spl' in url_lower:
        return 'match'
    return 'general'
