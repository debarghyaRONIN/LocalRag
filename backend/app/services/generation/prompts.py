from typing import List
from backend.app.domain.models import SearchCandidate

SYSTEM_RAG_PROMPT = """You are a highly capable, articulate, and thoughtful sovereign AI assistant running locally with zero data egress. You answer questions thoroughly, accurately, and naturally based on the user's uploaded local documents.

Instructions for your response:
1. Direct, Conversational Synthesis: Synthesize the facts into a polished, natural, and comprehensive response. Do not output raw XML tags, chunk numbers, or internal debug markers.
2. Grounding & Citations: Ground your statements strictly in the facts present in the provided <context> blocks. Append citations like [1] or [2] to reference the source documents.
3. Resumes, Profiles & Technical Docs: When answering questions about a person, resume, or document, provide a well-structured summary organized with clear markdown headings (e.g. Education, Technical Skills, Experience, Projects, Contact Details).
4. Honesty & Accuracy: Answer as thoroughly as the provided context permits. If specific information is not mentioned in the context, simply state that it is not covered in the document rather than hallucinating.
5. Formatting: Use clean, professional markdown with headings, bullet points, and bold emphasis.
"""


def format_rag_context(candidates: List[SearchCandidate]) -> str:
    """
    Format retrieved parent-child chunks into indexed XML context blocks for the LLM.
    Uses stitched sibling context if available to provide complete contiguous document flow.
    """
    if not candidates:
        return "No relevant local documents found."

    context_blocks = []
    for idx, cand in enumerate(candidates, start=1):
        content_to_use = cand.stitched_context or cand.parent_content or cand.content
        block = (
            f"<source id=\"{idx}\" file=\"{cand.filename}\" page=\"{cand.page_number}\">\n"
            f"{content_to_use}\n"
            f"</source>"
        )
        context_blocks.append(block)

    return "\n\n".join(context_blocks)


def build_rag_messages(query: str, candidates: List[SearchCandidate], chat_history: List[dict] = None) -> List[dict]:
    """
    Construct chat completion messages array with system prompt, context, history, and user query.
    """
    context_str = format_rag_context(candidates)

    messages = [
        {"role": "system", "content": SYSTEM_RAG_PROMPT}
    ]

    # Include recent chat history if available
    if chat_history:
        for msg in chat_history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    user_content = (
        f"<context>\n"
        f"{context_str}\n"
        f"</context>\n\n"
        f"Question: {query}"
    )

    messages.append({"role": "user", "content": user_content})
    return messages

