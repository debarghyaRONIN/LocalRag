import hashlib
from pathlib import Path


def compute_file_hash(file_path: Path) -> str:
    """
    Compute SHA-256 hash of a file for idempotent deduplication.
    """
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_content_hash(text: str) -> str:
    """
    Compute SHA-256 hash of a string content.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
