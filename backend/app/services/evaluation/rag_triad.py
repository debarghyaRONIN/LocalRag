"""
Sovereign RAG Triad Offline Evaluation Metrics.

Computes the three fundamental pillars of RAG quality offline without external cloud APIs:
1. Context Relevance: Are the retrieved chunks relevant to the user query?
2. Faithfulness (Groundedness): Is the generated answer strictly grounded in the retrieved context?
3. Answer Relevance: Does the generated answer directly address the user query?

Scores are normalized between 0.0 and 1.0.
"""

from typing import List, Any, Union, Dict, Optional
import math
import re
import numpy as np


STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it",
    "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my",
    "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or",
    "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same",
    "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll",
    "they're", "they've", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's", "where",
    "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with",
    "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
    "your", "yours", "yourself", "yourselves"
}


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric words."""
    if not text:
        return []
    return [w.lower() for w in re.findall(r"\b[a-zA-Z0-9_\-']+\b", text)]


def _content_words(text: str) -> List[str]:
    """Extract non-stop content words."""
    return [w for w in _tokenize(text) if w not in STOP_WORDS and len(w) > 1]


def _split_sentences(text: str) -> List[str]:
    """Split text into sentences or clause units."""
    if not text:
        return []
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    sentences = [s.strip() for s in raw_sentences if s and len(s.strip()) > 3]
    if not sentences and text.strip():
        sentences = [text.strip()]
    return sentences


def _normalize_chunks(retrieved_chunks: Any) -> List[str]:
    """Normalize input chunks to a list of plain strings."""
    if not retrieved_chunks:
        return []
    if isinstance(retrieved_chunks, str):
        return [retrieved_chunks.strip()] if retrieved_chunks.strip() else []

    normalized: List[str] = []
    for item in retrieved_chunks:
        if isinstance(item, str):
            text = item.strip()
        elif isinstance(item, dict):
            text = str(item.get("content", item.get("text", ""))).strip()
        elif hasattr(item, "content"):
            text = str(getattr(item, "content", "")).strip()
        elif hasattr(item, "text"):
            text = str(getattr(item, "text", "")).strip()
        else:
            text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _sigmoid(x: float) -> float:
    """Stable sigmoid activation mapping logit to [0, 1]."""
    if x >= 15.0:
        return 1.0
    if x <= -15.0:
        return 0.0
    return 1.0 / (1.0 + math.exp(-x))


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    a = np.array(vec1, dtype=float)
    b = np.array(vec2, dtype=float)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    dot = float(np.dot(a, b) / (norm_a * norm_b))
    return max(0.0, min(1.0, dot))


def _lexical_overlap(query_text: str, target_text: str) -> float:
    """Fraction of query content words present in target text."""
    q_words = set(_content_words(query_text))
    if not q_words:
        return 1.0 if not query_text.strip() else 0.5
    t_words = set(_content_words(target_text))
    if not t_words:
        return 0.0
    intersection = q_words.intersection(t_words)
    return len(intersection) / len(q_words)


def _get_embedding_engine():
    """Lazily load the embedding engine if available."""
    try:
        from backend.app.services.retrieval.embeddings import EmbeddingEngine
        return EmbeddingEngine.get_instance()
    except Exception:
        return None


def _get_reranker_engine():
    """Lazily load the cross-encoder reranker engine if available."""
    try:
        from backend.app.services.retrieval.reranker import RerankerEngine
        return RerankerEngine.get_instance()
    except Exception:
        return None


def evaluate_context_relevance(
    query: str,
    retrieved_chunks: Union[List[str], List[Any], str]
) -> float:
    """
    Evaluates Context Relevance (0.0 to 1.0).
    Measures the degree to which retrieved chunks contain relevant information
    to the query without extraneous noise.

    Returns float in range [0.0, 1.0].
    """
    if not query or not str(query).strip():
        return 0.0

    chunks = _normalize_chunks(retrieved_chunks)
    if not chunks:
        return 0.0

    query_str = str(query).strip()
    reranker = _get_reranker_engine()
    embedder = _get_embedding_engine()

    chunk_scores: List[float] = []

    # 1. Try Cross-Encoder Reranker if available
    rerank_scores: Optional[List[float]] = None
    if reranker is not None:
        try:
            raw_scores = reranker.rerank(query_str, chunks)
            rerank_scores = [_sigmoid(float(s)) for s in raw_scores]
        except Exception:
            rerank_scores = None

    # 2. Dense Embeddings Cosine Similarity
    dense_scores: Optional[List[float]] = None
    if embedder is not None:
        try:
            q_emb = embedder.embed_query(query_str)
            c_embs = embedder.embed_texts(chunks)
            dense_scores = [_cosine_similarity(q_emb, c) for c in c_embs]
        except Exception:
            dense_scores = None

    for idx, chunk in enumerate(chunks):
        lex = _lexical_overlap(query_str, chunk)

        if rerank_scores is not None and dense_scores is not None:
            r_s = rerank_scores[idx]
            d_s = dense_scores[idx]
            score = 0.55 * r_s + 0.35 * d_s + 0.10 * lex
        elif rerank_scores is not None:
            score = 0.80 * rerank_scores[idx] + 0.20 * lex
        elif dense_scores is not None:
            score = 0.70 * dense_scores[idx] + 0.30 * lex
        else:
            # Fallback lexical overlap with Jaccard smoothing
            score = lex

        chunk_scores.append(max(0.0, min(1.0, score)))

    if not chunk_scores:
        return 0.0

    # Aggregate: top chunk relevance heavily weighted, penalized by irrelevant noise chunks
    max_score = max(chunk_scores)
    mean_score = sum(chunk_scores) / len(chunk_scores)
    overall_rel = 0.70 * max_score + 0.30 * mean_score

    return round(float(max(0.0, min(1.0, overall_rel))), 4)


def evaluate_faithfulness(
    answer: str,
    retrieved_chunks: Union[List[str], List[Any], str]
) -> float:
    """
    Evaluates Faithfulness / Groundedness (0.0 to 1.0).
    Measures whether statements/claims in the answer are supported by the retrieved context.

    Returns float in range [0.0, 1.0].
    """
    if not answer or not str(answer).strip():
        return 0.0

    chunks = _normalize_chunks(retrieved_chunks)
    if not chunks:
        return 0.0

    ans_str = str(answer).strip()
    sentences = _split_sentences(ans_str)
    if not sentences:
        return 0.0

    combined_context = " ".join(chunks)
    context_words = set(_content_words(combined_context))

    reranker = _get_reranker_engine()
    embedder = _get_embedding_engine()

    sentence_scores: List[float] = []

    for sentence in sentences:
        s_words = set(_content_words(sentence))
        if not s_words:
            sentence_scores.append(1.0)
            continue

        # Lexical support: proportion of content words grounded in context
        overlap_count = len(s_words.intersection(context_words))
        lex_coverage = overlap_count / len(s_words)

        # Cross-encoder semantic grounding against top matching chunk
        sem_score = 0.0
        if reranker is not None:
            try:
                # Pair sentence with each chunk or full context
                scores = reranker.rerank(sentence, chunks[:5])
                best_logit = max(scores) if scores else -10.0
                sem_score = _sigmoid(float(best_logit))
            except Exception:
                sem_score = 0.0

        if sem_score == 0.0 and embedder is not None:
            try:
                s_emb = embedder.embed_query(sentence)
                c_embs = embedder.embed_texts(chunks[:5])
                best_sim = max([_cosine_similarity(s_emb, c) for c in c_embs]) if c_embs else 0.0
                sem_score = best_sim
            except Exception:
                sem_score = 0.0

        if sem_score > 0.0:
            # Weighted blend of semantic entailment and strict lexical grounding
            sent_groundedness = 0.50 * sem_score + 0.50 * lex_coverage
            if lex_coverage < 0.25:
                # Strong hallucination penalty if key tokens do not exist in retrieved sources
                sent_groundedness *= (lex_coverage * 2.0)
        else:
            sent_groundedness = lex_coverage

        sentence_scores.append(max(0.0, min(1.0, sent_groundedness)))

    if not sentence_scores:
        return 0.0

    faithfulness = sum(sentence_scores) / len(sentence_scores)
    return round(float(max(0.0, min(1.0, faithfulness))), 4)


def evaluate_groundedness(
    answer: str,
    retrieved_chunks: Union[List[str], List[Any], str]
) -> float:
    """Alias for evaluate_faithfulness."""
    return evaluate_faithfulness(answer, retrieved_chunks)


def evaluate_answer_relevance(query: str, answer: str) -> float:
    """
    Evaluates Answer Relevance (0.0 to 1.0).
    Measures how directly and adequately the answer addresses the user's prompt/query.

    Returns float in range [0.0, 1.0].
    """
    if not query or not str(query).strip():
        return 0.0
    if not answer or not str(answer).strip():
        return 0.0

    q_str = str(query).strip()
    a_str = str(answer).strip()

    reranker = _get_reranker_engine()
    embedder = _get_embedding_engine()

    lex = _lexical_overlap(q_str, a_str)

    rerank_prob: Optional[float] = None
    if reranker is not None:
        try:
            scores = reranker.rerank(q_str, [a_str])
            if scores:
                rerank_prob = _sigmoid(float(scores[0]))
        except Exception:
            rerank_prob = None

    dense_sim: Optional[float] = None
    if embedder is not None:
        try:
            q_emb = embedder.embed_query(q_str)
            a_emb = embedder.embed_query(a_str)
            dense_sim = _cosine_similarity(q_emb, a_emb)
        except Exception:
            dense_sim = None

    if rerank_prob is not None and dense_sim is not None:
        score = 0.60 * rerank_prob + 0.30 * dense_sim + 0.10 * lex
    elif rerank_prob is not None:
        score = 0.80 * rerank_prob + 0.20 * lex
    elif dense_sim is not None:
        score = 0.70 * dense_sim + 0.30 * lex
    else:
        score = lex

    return round(float(max(0.0, min(1.0, score))), 4)


def evaluate_rag_triad(
    query: str,
    retrieved_chunks: Union[List[str], List[Any], str],
    answer: str
) -> Dict[str, float]:
    """
    Compute comprehensive RAG Triad offline evaluation metrics.
    """
    c_rel = evaluate_context_relevance(query, retrieved_chunks)
    faith = evaluate_faithfulness(answer, retrieved_chunks)
    a_rel = evaluate_answer_relevance(query, answer)
    overall = round((c_rel + faith + a_rel) / 3.0, 4)

    return {
        "context_relevance": c_rel,
        "faithfulness": faith,
        "groundedness": faith,
        "answer_relevance": a_rel,
        "overall_score": overall,
    }

