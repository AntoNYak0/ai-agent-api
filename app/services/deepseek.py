import asyncio
import logging
import re
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger("deepseek")


class DeepSeekError(Exception):
    """Raised when DeepSeek API is unavailable after all retries."""
    pass


# Prompt injection patterns — blocked in user input
_INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions?|prompts?|messages?)",
    r"forget\s+(all\s+)?(previous|prior|system)\s+(instructions?|prompts?)",
    r"you\s+are\s+now\s+(a\s+)?(different|new)\s+(ai|assistant|model)",
    r"system\s+prompt\s*(:|\n|is|was)",
    r"<\|im_start\|>",
    r"<\|im_end\|>",
    r"\[INST\]",
    r"\[/INST\]",
    r"\[SYSTEM\]",
    r"\[/SYSTEM\]",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)


def _sanitize(text: str) -> str:
    """Flag obvious prompt injection in user input."""
    if _INJECTION_RE.search(text):
        logger.warning("Prompt injection blocked in user input (len=%d)", len(text))
        raise DeepSeekError("Input contains blocked patterns")
    return text

client = AsyncOpenAI(
    base_url=settings.deepseek_base_url,
    api_key=settings.deepseek_api_key,
)

MAX_RETRIES = 3
RETRY_DELAYS = [1.0, 2.0, 4.0]


async def deepseek_completion(
    system_prompt: str,
    user_content: str,
    context_window: str | None = None,
    json_mode: bool = False,
) -> tuple[str, int]:
    # Sanitize user input against prompt injection
    _sanitize(user_content)
    if context_window:
        _sanitize(context_window)

    messages = [{"role": "system", "content": system_prompt}]

    if context_window:
        messages.append({"role": "user", "content": context_window})

    messages.append({"role": "user", "content": user_content})

    kwargs = {
        "model": settings.deepseek_model,
        "messages": messages,
        "max_tokens": 8192,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0
            return text, tokens
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    f"DeepSeek attempt {attempt + 1} failed: {e}. Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"DeepSeek failed after {MAX_RETRIES} attempts: {e}")
                raise DeepSeekError(f"DeepSeek API unavailable after {MAX_RETRIES} retries") from e


async def deepseek_completion_stream(
    system_prompt: str,
    user_content: str,
    context_window: str | None = None,
    json_mode: bool = False,
):
    """Stream DeepSeek response chunk by chunk. Yields text fragments."""
    import warnings
    _sanitize(user_content)
    if context_window:
        _sanitize(context_window)

    messages = [{"role": "system", "content": system_prompt}]

    if context_window:
        messages.append({"role": "user", "content": context_window})

    messages.append({"role": "user", "content": user_content})

    kwargs = {
        "model": settings.deepseek_model,
        "messages": messages,
        "max_tokens": 8192,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES):
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            return
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    f"DeepSeek stream attempt {attempt + 1} failed: {e}. Retrying in {delay}s..."
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"DeepSeek stream failed after {MAX_RETRIES} attempts: {e}")
                raise DeepSeekError(f"DeepSeek API unavailable after {MAX_RETRIES} retries") from e
