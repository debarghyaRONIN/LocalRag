import re
import sqlite3
from typing import List, Dict, Any, Optional
from backend.app.core.config import settings
from backend.app.domain.models import ParentChunk


def sanitize_fts5_query(query: str) -> str:
    """
    Sanitize raw user query into a safe FTS5 query string.
    Extracts alphanumeric tokens and joins them with OR or prefix queries.
    Prevents FTS5 syntax errors caused by special characters like quotes, colons, or dashes.
    """
    # Extract alphanumeric words
    tokens = re.findall(r"\b\w+\b", query)
    if not tokens:
        return ""
    # Filter out single-character noise
    meaningful = [t for t in tokens if len(t) > 1]
    if not meaningful:
        meaningful = tokens
    # Build FTS5 query: match full words or prefix matches
    safe_terms = [f'"{t}"*' for t in meaningful[:15]]
    return " OR ".join(safe_terms)


class FTS5BM25Store:
    """
    High-performance, offline Full-Text BM25 Lexical Index backed by SQLite FTS5.
    Complements dense cosine vector search with exact keyword, part number,
    error code, and technical acronym matching.
    """

    _instance = None

    def __init__(self, db_path: Optional[str] = None):
        if db_path:
            self.db_path = db_path
        else:
            # Extract raw sqlite file path from DATABASE_URL
            raw_url = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
            self.db_path = raw_url

        self._ensure_table()

    @classmethod
    def get_instance(cls) -> "FTS5BM25Store":
        if cls._instance is None:
            cls._instance = FTS5BM25Store()
        return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_table(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS parent_chunks_fts USING fts5(
                    parent_id UNINDEXED,
                    doc_id UNINDEXED,
                    filename,
                    content,
                    clearance_level UNINDEXED,
                    tokenize='porter unicode61'
                );
            """)
            conn.commit()

    def upsert_fts_chunks(
        self,
        parent_chunks: List[ParentChunk],
        filename: str,
        clearance_level: int = 1,
    ):
        """
        Batch index parent chunks into FTS5 for BM25 keyword matching.
        """
        if not parent_chunks:
            return

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Insert each parent chunk
            records = [
                (
                    p.parent_id,
                    p.doc_id,
                    filename,
                    p.content,
                    int(clearance_level),
                )
                for p in parent_chunks
            ]
            cursor.executemany(
                """
                INSERT INTO parent_chunks_fts (parent_id, doc_id, filename, content, clearance_level)
                VALUES (?, ?, ?, ?, ?)
                """,
                records
            )
            conn.commit()

    def search_bm25(
        self,
        query: str,
        top_k: int = settings.RETRIEVAL_TOP_K,
        user_clearance: Optional[int] = None,
        doc_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute BM25 ranked full-text search using SQLite FTS5 bm25() function.
        Returns ranked list of hits: chunk/parent content, filename, and bm25_score.
        """
        safe_q = sanitize_fts5_query(query)
        if not safe_q:
            return []

        sql = """
            SELECT 
                parent_id,
                doc_id,
                filename,
                content,
                clearance_level,
                bm25(parent_chunks_fts) as bm25_rank
            FROM parent_chunks_fts
            WHERE parent_chunks_fts MATCH ?
        """
        params: List[Any] = [safe_q]

        if doc_id:
            sql += " AND doc_id = ?"
            params.append(doc_id)

        if user_clearance is not None:
            sql += " AND CAST(clearance_level AS INTEGER) <= ?"
            params.append(int(user_clearance))

        # SQLite FTS5 bm25() returns negative scores where lower (more negative) is better.
        # We order by bm25_rank ASC to get most relevant first.
        sql += " ORDER BY bm25_rank ASC LIMIT ?"
        params.append(top_k)

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()

                hits = []
                for row in rows:
                    raw_score = float(row["bm25_rank"])
                    # Normalize bm25 rank to positive score for RRF comparison
                    normalized_score = 1.0 / (1.0 + abs(raw_score))
                    hits.append({
                        "parent_id": row["parent_id"],
                        "doc_id": row["doc_id"],
                        "filename": row["filename"],
                        "content": row["content"],
                        "clearance_level": int(row["clearance_level"] or 1),
                        "bm25_score": normalized_score,
                    })
                return hits
        except Exception:
            # Fallback gracefully if FTS query syntax error
            return []

    def delete_by_doc(self, doc_id: str):
        """Purge document chunks from FTS5 index upon deletion."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM parent_chunks_fts WHERE doc_id = ?", (doc_id,))
                conn.commit()
        except Exception:
            pass

    def purge_all(self):
        """Purge all document chunks from FTS5 full-text index."""
        try:
            with self._get_connection() as conn:
                conn.execute("DELETE FROM parent_chunks_fts")
                conn.commit()
        except Exception:
            pass
