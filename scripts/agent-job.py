# Псевдокод основного цикла
import time
from openai import OpenAI

client = OpenAI(
    base_url="https://api.deepseek.com",
    api_key="ВАШ_API_КЛЮЧ"
)

def main_loop():
    while True:
        # 1. Получить задачу
        task = dgrid_api.get_task()

        if not task:
            time.sleep(60)  # Ждать новые задачи
            continue

        # 2. Оценить сложность задачи
        if task.complexity == "high":
            model = "deepseek-chat"  # V4 Pro, дорогой
        else:
            model = "deepseek-chat"  # V4 Flash, дешевый
            # Примечание: если Flash — отдельный model ID, уточнить в документации DeepSeek

        # 3. Выполнить задачу
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Ты оцениваешь ответы ИИ."},
                {"role": "user", "content": task.prompt}
            ]
        )

        # 4. Отправить результат
        dgrid_api.submit(task.id, response.choices[0].message.content)

        # 5. Краткий сон
        time.sleep(5)