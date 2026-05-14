from openai import AsyncOpenAI
from app.config import settings

client = AsyncOpenAI(
    base_url=settings.deepseek_base_url,
    api_key=settings.deepseek_api_key,
)


async def deepseek_completion(
    system_prompt: str,
    user_content: str,
    context_window: str | None = None,
) -> str:
    messages = [{"role": "system", "content": system_prompt}]

    if context_window:
        messages.append({"role": "user", "content": context_window})

    messages.append({"role": "user", "content": user_content})

    response = await client.chat.completions.create(
        model=settings.deepseek_model,
        messages=messages,
        max_tokens=8192,
    )
    return response.choices[0].message.content
