from pathlib import Path
from backend.app.services.ingestion.hasher import compute_file_hash, compute_content_hash


def test_compute_content_hash():
    text1 = "Local RAG on RTX 3060"
    text2 = "Local RAG on RTX 3060"
    text3 = "Different text"

    hash1 = compute_content_hash(text1)
    hash2 = compute_content_hash(text2)
    hash3 = compute_content_hash(text3)

    assert hash1 == hash2
    assert hash1 != hash3
    assert len(hash1) == 64  # SHA-256 hex length


def test_compute_file_hash(tmp_path: Path):
    test_file = tmp_path / "sample.txt"
    test_file.write_text("Test content for hashing", encoding="utf-8")

    hash_val = compute_file_hash(test_file)
    assert len(hash_val) == 64

    # Idempotent
    assert compute_file_hash(test_file) == hash_val

