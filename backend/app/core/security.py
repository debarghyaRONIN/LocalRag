import re


# Suspicious prompt injection heuristics
INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
    re.compile(r"system\s*prompt\s*reveal", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+in\s+developer\s+mode", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"<\s*script\s*>", re.IGNORECASE),
]


def sanitize_query(query: str, max_length: int = 1500) -> str:
    """
    Sanitize user queries to prevent prompt injection and abuse.
    """
    cleaned = query.strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    # Neutralize null bytes
    cleaned = cleaned.replace("\x00", "")

    return cleaned


def detect_prompt_injection(text: str) -> bool:
    """
    Check if the user input matches recognized prompt-injection signatures.
    """
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            return True
    return False
