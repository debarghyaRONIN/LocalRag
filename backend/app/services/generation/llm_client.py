import json
from typing import AsyncGenerator, List, Dict, Any, Optional
import httpx
from backend.app.core.config import settings


class VLLMClient:
    """
    Dedicated high-performance client for self-hosted vLLM inference engine.
    Utilizes vLLM's PagedAttention continuous-batching local inference API.
    Maintains a persistent connection pool to eliminate socket recreation latency.
    """

    def __init__(
        self,
        base_url: str = settings.VLLM_BASE_URL,
        api_key: str = settings.VLLM_API_KEY,
        model: str = settings.VLLM_MODEL,
        temperature: float = settings.VLLM_TEMPERATURE,
        max_tokens: int = settings.VLLM_MAX_TOKENS,
        timeout: float = settings.VLLM_TIMEOUT_SECONDS,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def get_client(self) -> httpx.AsyncClient:
        """Get or initialize the persistent pooled async HTTP client."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=30.0)
            self._client = httpx.AsyncClient(timeout=self.timeout, limits=limits)
        return self._client

    async def aclose(self) -> None:
        """Gracefully close the persistent connection pool."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def check_readiness(self) -> Dict[str, Any]:
        """
        Verify that the local vLLM or Ollama instance is online and accepting requests.
        Returns model metadata and status.
        """
        try:
            client = self.get_client()
            res = await client.get(f"{self.base_url}/models", timeout=2.0)
            if res.status_code == 200:
                data = res.json()
                models = [m.get("id") for m in data.get("data", [])]
                return {
                    "online": True,
                    "active_models": models,
                    "primary_model": models[0] if models else self.model,
                }
        except Exception:
            pass

        # Probe Ollama directly
        try:
            client = self.get_client()
            res = await client.get("http://localhost:11434/api/tags", timeout=2.0)
            if res.status_code == 200:
                models = [m.get("name") for m in res.json().get("models", []) if m.get("name")]
                primary = models[0] if models else self.model
                return {
                    "online": True,
                    "active_models": models,
                    "primary_model": primary,
                }
        except Exception:
            pass

        return {"online": False, "active_models": [], "primary_model": self.model}

    async def get_available_models(self) -> List[str]:
        """List all detected local models from Ollama and vLLM."""
        models: List[str] = []
        try:
            client = self.get_client()
            res = await client.get("http://localhost:11434/api/tags", timeout=2.0)
            if res.status_code == 200:
                for m in res.json().get("models", []):
                    if m.get("name") and m.get("name") not in models:
                        models.append(m.get("name"))
        except Exception:
            pass

        try:
            client = self.get_client()
            res = await client.get(f"{self.base_url}/models", timeout=2.0)
            if res.status_code == 200:
                for m in res.json().get("data", []):
                    if m.get("id") and m.get("id") not in models:
                        models.append(m.get("id"))
        except Exception:
            pass

        return models

    async def _resolve_ollama_model(self) -> Optional[str]:
        """Dynamically detect installed models in local Ollama instance."""
        try:
            client = self.get_client()
            res = await client.get("http://localhost:11434/api/tags", timeout=1.5)
            if res.status_code == 200:
                models = res.json().get("models", [])
                names = [m.get("name") for m in models if m.get("name")]
                if not names:
                    return None
                for pref in ["llama3.2", "qwen2.5", "llama3", "gemma", "mistral", "phi"]:
                    for n in names:
                        if pref in n.lower():
                            return n
                return names[0]
        except Exception:
            pass
        return None

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completions token-by-token directly from vLLM.
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "top_p": kwargs.get("top_p", 0.95),
            "stream": True,
        }

        url = f"{self.base_url}/chat/completions"

        try:
            client = self.get_client()
            async with client.stream("POST", url, headers=headers, json=payload) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    err_text = error_body.decode("utf-8", errors="replace")
                    yield f"\n\n[vLLM Server Error ({response.status_code})]: {err_text}"
                    return

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue

                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk_json = json.loads(data_str)
                        delta = chunk_json.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
        except httpx.ConnectError:
            # Automatic fallback probe to local Ollama runtime if vLLM port is unavailable
            ollama_url = "http://localhost:11434/v1"
            if self.base_url != ollama_url:
                try:
                    ollama_model = await self._resolve_ollama_model()
                    if ollama_model:
                        ollama_payload = {
                            "model": ollama_model,
                            "messages": messages,
                            "temperature": kwargs.get("temperature", self.temperature),
                            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
                            "stream": True,
                        }
                        client = self.get_client()
                        async with client.stream("POST", f"{ollama_url}/chat/completions", headers=headers, json=ollama_payload, timeout=30.0) as o_res:
                            if o_res.status_code == 200:
                                async for o_line in o_res.aiter_lines():
                                    o_line = o_line.strip()
                                    if not o_line or not o_line.startswith("data:"):
                                        continue
                                    d_str = o_line[5:].strip()
                                    if d_str == "[DONE]":
                                        break
                                    try:
                                        c_json = json.loads(d_str)
                                        c_content = c_json.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                        if c_content:
                                            yield c_content
                                    except Exception:
                                        continue
                                return
                except Exception:
                    pass

            # Built-in Sovereign Passage Synthesis Fallback when external LLM daemons are offline
            fallback_text = self._synthesize_local_fallback(messages)
            import asyncio
            # Stream words with slight delay for realistic, smooth UI rendering
            words = fallback_text.split(" ")
            for i, w in enumerate(words):
                yield w + (" " if i < len(words) - 1 else "")
                if i % 4 == 0:
                    await asyncio.sleep(0.01)
        except Exception as e:
            yield f"\n\n[vLLM Inference Error]: {str(e)}"

    def _synthesize_local_fallback(self, messages: List[Dict[str, str]]) -> str:
        """
        Extractive sovereign synthesis from retrieved parent-child passages.
        Executes purely locally without requiring Docker or an external LLM daemon.
        """
        user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
                break

        import re
        if "<context>" in user_msg and "</context>" in user_msg:
            sources = re.findall(
                r'<source id="(\d+)" file="([^"]*)" page="([^"]*)">\s*(.*?)\s*</source>',
                user_msg,
                re.DOTALL,
            )
            q_match = re.search(r"Question:\s*(.*)", user_msg, re.DOTALL)
            question = q_match.group(1).strip() if q_match else "your query"

            if sources:
                lines = [
                    f"### Sovereign Knowledge Extraction for: *\"{question}\"*\n\n",
                    "Based on verified passages retrieved from your local knowledge corpus:\n\n",
                ]
                for s_id, s_file, s_page, s_content in sources[:3]:
                    clean_chunk = s_content.strip()
                    if len(clean_chunk) > 400:
                        clean_chunk = clean_chunk[:400] + "..."
                    lines.append(f"**[{s_id}] {s_file} (Page {s_page})**:\n> \"{clean_chunk}\"\n\n")

                lines.append(
                    "\n---\n*Sovereign Direct Extraction Mode: Grounded directly on your verified corpus with zero data egress. "
                    "For neural conversational reasoning on Windows without Docker, start Ollama with `ollama run qwen2.5:3b`.*"
                )
                return "".join(lines)
            else:
                return (
                    f"The provided local documents do not contain sufficient information to answer: *\"{question}\"*.\n\n"
                    "Please upload relevant documents into your Knowledge Corpus, or launch Ollama (`ollama run qwen2.5:3b`) for general conversational reasoning."
                )
        else:
            clean_prompt = user_msg.strip()
            return (
                f"**Sealed Sovereign Enclave is running locally.**\n\n"
                f"Query received: *\"{clean_prompt}\"*\n\n"
                "To enable conversational reasoning on Windows without Docker:\n"
                "1. Download and start [Ollama](https://ollama.com/) on your Windows machine.\n"
                "2. Run in a terminal: `ollama run qwen2.5:3b`\n\n"
                "Sealed will automatically connect to Ollama on `http://localhost:11434` with zero configuration."
            )

    async def complete_chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any
    ) -> str:
        """
        Non-streaming chat completion from vLLM.
        """
        tokens = []
        async for token in self.stream_chat(messages, **kwargs):
            tokens.append(token)
        return "".join(tokens)

    async def generate(
        self,
        prompt_or_messages: Any,
        **kwargs: Any
    ) -> str:
        """Universal text generation accepting either string prompt or messages list."""
        if isinstance(prompt_or_messages, str):
            messages = [{"role": "user", "content": prompt_or_messages}]
        else:
            messages = list(prompt_or_messages)
        return await self.complete_chat(messages, **kwargs)


# Alias for backward compatibility
LLMClient = VLLMClient
