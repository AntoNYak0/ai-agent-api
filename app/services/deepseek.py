import asyncio
import logging
import re
import time
from collections import deque
from openai import AsyncOpenAI
from app.config import settings

logger = logging.getLogger("deepseek")

# ── Injection attempt rate tracking ─────────────────────────────────

_injection_attempts: deque = deque()  # timestamps of recent injection attempts
_MAX_INJECTION_ATTEMPTS = 20           # max attempts before escalating
_INJECTION_WINDOW_SEC = 60             # sliding window
_INJECTION_ESCALATE_THRESHOLD = 10     # within window → critical alert
_injection_blocks_total: int = 0       # cumulative blocks since restart


def get_injection_stats() -> dict:
    """Export prompt injection statistics for monitoring."""
    return {
        "blocks_total": _injection_blocks_total,
        "recent_attempts": len(_injection_attempts),
        "window_seconds": _INJECTION_WINDOW_SEC,
        "escalation_threshold": _INJECTION_ESCALATE_THRESHOLD,
        "max_threshold": _MAX_INJECTION_ATTEMPTS,
        "patterns_count": len(_INJECTION_PATTERNS),
    }


class DeepSeekError(Exception):
    """Raised when DeepSeek API is unavailable after all retries."""
    pass


# ── Context window compression ────────────────────────────────────
# DeepSeek V4 has 1M token context. At 80% (800K tokens) we compress.

MAX_CONTEXT_TOKENS = 1_000_000
COMPRESSION_THRESHOLD = 0.80  # 80% → 800K tokens
COMPRESSION_TARGET = 0.60     # Compress to 60% → 600K tokens


def _estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for English, ~3 for code.
    Returns upper bound to be safe.
    """
    if not text:
        return 0
    # Count code-like patterns (braces, semicolons, indentation)
    code_indicators = len(re.findall(r'[{}(\)\[\];]', text))
    total_chars = len(text)
    # If >15% code indicators, use code ratio (3 chars/token); else text ratio (4 chars/token)
    if code_indicators > total_chars * 0.15:
        return int(total_chars / 3.0)
    return int(total_chars / 4.0)


def _compress_context(text: str, max_tokens: int) -> tuple[str, bool]:
    """Compress context to fit within max_tokens.
    Returns (compressed_text, was_compressed).
    Strategy depends on content type:
      - Code: truncate long lines, collapse repeated blocks
      - Logs: keep head 30% + tail 30% + errors in middle
      - General text: keep head + tail, summarise middle
    """
    if not text or _estimate_tokens(text) <= max_tokens:
        return text, False

    # Detect content type
    lines = text.split("\n")
    code_lines = sum(1 for line in lines if re.match(r'^\s{2,}', line) or re.search(r'[{}\[\]();=]', line))
    is_code = code_lines > len(lines) * 0.3
    is_logs = bool(re.search(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}', text[:2000]))

    logger.warning(
        "Context compression triggered: %d chars (~%d tokens) > %d tokens. "
        "Type: %s, lines: %d",
        len(text), _estimate_tokens(text), max_tokens,
        "code" if is_code else ("logs" if is_logs else "text"), len(lines),
    )

    if is_code:
        compressed = _compress_code(lines, max_tokens)
    elif is_logs:
        compressed = _compress_logs(lines, max_tokens)
    else:
        compressed = _compress_text(lines, max_tokens)

    return compressed, True


def _compress_code(lines: list[str], max_tokens: int) -> str:
    """Compress code: truncate long lines, collapse repeated blocks."""
    result = []
    prev_line = ""
    repeat_count = 0
    target_chars = max_tokens * 3  # code ratio ~3 chars/token

    for line in lines:
        # Truncate very long lines (>500 chars)
        if len(line) > 500:
            line = line[:500] + " ... [truncated]"

        # Collapse identical adjacent lines (e.g. repeated imports, blank lines)
        if line == prev_line and line.strip():
            if repeat_count == 0:
                repeat_count = 2
            elif repeat_count >= 2:
                repeat_count += 1
                prev_line = line
                continue
        else:
            if repeat_count > 2:
                result.append(f"  ... [{repeat_count - 1} more identical lines]")
            repeat_count = 0

        result.append(line)
        prev_line = line

        # Stop if we've reached target
        if sum(len(line) for line in result) > target_chars:
            result.append(f"\n... [truncated: {len(lines) - len(result)} lines remaining]")
            break

    return "\n".join(result)


def _compress_logs(lines: list[str], max_tokens: int) -> str:
    """Compress logs: keep head 30%, tail 30%, and error lines from the middle."""
    n = len(lines)
    target_chars = max_tokens * 4  # text ratio

    head_n = int(n * 0.30)
    tail_n = int(n * 0.30)

    # Find error/warning lines in the middle section
    middle = lines[head_n:n - tail_n]
    errors = [line for line in middle if re.search(r'(?i)(error|exception|fatal|critical|traceback|fail|panic)', line)]

    result = lines[:head_n]
    if errors:
        result.append(f"\n--- {len(errors)} error/warning lines from middle {head_n}-{n - tail_n} ---\n")
        result.extend(errors[:50])  # Cap at 50 error lines
    result.append(f"\n--- skipped {len(middle) - len(errors)} info/debug lines ---\n")
    result.extend(lines[n - tail_n:])

    # If still over target, trim further
    joined = "\n".join(result)
    if _estimate_tokens(joined) > max_tokens:
        # Keep head + errors only
        short = lines[:head_n] + errors[:30]
        short.append(f"\n... [{n - len(short)} lines truncated]")
        return "\n".join(short)

    return joined


def _compress_text(lines: list[str], max_tokens: int) -> str:
    """Compress general text: keep head + tail, drop middle."""
    n = len(lines)
    target_chars = max_tokens * 4
    head_n = int(n * 0.40)
    tail_n = int(n * 0.10)

    if head_n + tail_n >= n:
        head_n = int(n * 0.60)
        tail_n = 0

    result = lines[:head_n]
    result.append(f"\n... [{n - head_n - tail_n} lines truncated — context compressed at {COMPRESSION_THRESHOLD*100:.0f}% window]")
    if tail_n > 0:
        result.extend(lines[-tail_n:])

    # If still too large, keep less head
    joined = "\n".join(result)
    if _estimate_tokens(joined) > max_tokens:
        head_n = int(n * 0.25)
        result = lines[:head_n]
        result.append(f"\n... [{n - head_n} lines truncated]")
        return "\n".join(result)

    return joined


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
    r"DAN\s*(mode|prompt)",
    r"jailbreak",
]
_INJECTION_RE = re.compile("|".join(f"(?:{p})" for p in _INJECTION_PATTERNS), re.IGNORECASE)


def _sanitize(text: str) -> str:
    """Flag obvious prompt injection in user input. Tracks attempts for rate escalation."""
    match = _INJECTION_RE.search(text)
    if match:
        global _injection_blocks_total
        _injection_blocks_total += 1

        now = time.time()
        _injection_attempts.append(now)

        # Purge old entries outside the window
        cutoff = now - _INJECTION_WINDOW_SEC
        while _injection_attempts and _injection_attempts[0] < cutoff:
            _injection_attempts.popleft()

        recent_count = len(_injection_attempts)
        # Show the offending snippet (first 60 chars) for forensics
        snippet = text[:80].replace("\n", "\\n") + ("..." if len(text) > 80 else "")

        if recent_count >= _INJECTION_ESCALATE_THRESHOLD:
            logger.critical(
                "Prompt injection ESCALATION: %d attempts in %ds. "
                "Pattern matched: '%s'. Snippet: %s",
                recent_count, _INJECTION_WINDOW_SEC, match.group(), snippet,
            )
        else:
            logger.warning(
                "Prompt injection blocked: pattern='%s' len=%d attempts_recent=%d snippet=%s",
                match.group(), len(text), recent_count, snippet,
            )

        # Deny service if injection attempts exceed threshold
        if recent_count > _MAX_INJECTION_ATTEMPTS:
            logger.error(
                "Prompt injection threshold EXCEEDED: %d attempts in %ds. "
                "Temporarily blocking all requests.",
                recent_count, _INJECTION_WINDOW_SEC,
            )
            raise DeepSeekError("Too many injection attempts — service temporarily unavailable")

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
    max_tokens: int = 2048,
) -> tuple[str, int, bool]:
    """Call DeepSeek with optional context window compression.

    Returns (response_text, token_count, was_compressed).
    If total estimated tokens exceed 80% of 1M context, context_window
    is compressed before sending.
    """
    # Sanitize user input against prompt injection
    _sanitize(user_content)
    if context_window:
        _sanitize(context_window)

    # ── Context window compression ──
    compressed = False
    total_est = _estimate_tokens(system_prompt) + _estimate_tokens(user_content)
    if context_window:
        ctx_est = _estimate_tokens(context_window)
        total_est += ctx_est

    compress_threshold = int(MAX_CONTEXT_TOKENS * COMPRESSION_THRESHOLD)
    if total_est > compress_threshold:
        target = int(MAX_CONTEXT_TOKENS * COMPRESSION_TARGET)
        # Reserve space for system + user content, compress the rest
        reserved = _estimate_tokens(system_prompt) + _estimate_tokens(user_content)
        ctx_max = max(target - reserved, int(MAX_CONTEXT_TOKENS * 0.3))

        if context_window:
            context_window, compressed = _compress_context(context_window, ctx_max)
        else:
            # Without context_window, compress user_content itself
            user_max = max(target - _estimate_tokens(system_prompt), int(MAX_CONTEXT_TOKENS * 0.3))
            user_content, compressed = _compress_context(user_content, user_max)

    messages = [{"role": "system", "content": system_prompt}]

    if context_window:
        messages.append({"role": "user", "content": context_window})

    messages.append({"role": "user", "content": user_content})

    kwargs = {
        "model": settings.deepseek_model,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(**kwargs)
            text = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0
            return text, tokens, compressed
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
    max_tokens: int = 2048,
):
    """Stream DeepSeek response chunk by chunk. Yields (text_fragment | was_compressed_flag).

    First yielded value is always a bool indicating whether compression was applied.
    Subsequent values are text fragments.
    """
    _sanitize(user_content)
    if context_window:
        _sanitize(context_window)

    # ── Context window compression ──
    compressed = False
    total_est = _estimate_tokens(system_prompt) + _estimate_tokens(user_content)
    if context_window:
        ctx_est = _estimate_tokens(context_window)
        total_est += ctx_est

    compress_threshold = int(MAX_CONTEXT_TOKENS * COMPRESSION_THRESHOLD)
    if total_est > compress_threshold:
        target = int(MAX_CONTEXT_TOKENS * COMPRESSION_TARGET)
        reserved = _estimate_tokens(system_prompt) + _estimate_tokens(user_content)
        ctx_max = max(target - reserved, int(MAX_CONTEXT_TOKENS * 0.3))

        if context_window:
            context_window, compressed = _compress_context(context_window, ctx_max)
        else:
            user_max = max(target - _estimate_tokens(system_prompt), int(MAX_CONTEXT_TOKENS * 0.3))
            user_content, compressed = _compress_context(user_content, user_max)

    messages = [{"role": "system", "content": system_prompt}]

    if context_window:
        messages.append({"role": "user", "content": context_window})

    messages.append({"role": "user", "content": user_content})

    kwargs = {
        "model": settings.deepseek_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    # Yield compression flag as first value
    yield compressed

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
