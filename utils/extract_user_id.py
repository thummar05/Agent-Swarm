from typing import Optional
import re

def extract_user_id_from_query(query: str) -> Optional[str]:
    """Extract user ID from the query if mentioned"""
    match = re.search(r'\buser\d+\b', query.lower())
    if match:
        return match.group(0)
    return None