#!/usr/bin/env python3
"""
x402 payer script — делает реальный платёж к нашему API и запускает Bazaar индексацию.

Использование:
  1. Создай scripts/.env с PRIVATE_KEY=... (НЕ тот же кошелёк что PAY_TO!)
  2. Пополни этот кошелёк на ~$1 USDC через Base
  3. Запусти: python scripts/pay_and_trigger.py

Что произойдёт:
  - Скрипт вызовет /api/validate-json с авто-оплатой $0.005 USDC
  - Транзакция пройдёт через Base mainnet
  - Bazaar (Coinbase) увидит платёж → сервис появится в agentic.market

Безопасность:
  - Приватный ключ только в .env (в .gitignore)
  - Используй ОТДЕЛЬНЫЙ кошелёк от приёмного
  - Держи на нём минимум USDC
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env from scripts/ directory
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Also try agent-api/.env for fallback
load_dotenv(Path(__file__).parent.parent / ".env")

PRIVATE_KEY = os.getenv("PRIVATE_KEY", "")
API_URL = os.getenv("API_URL", "https://agent-api-ai.duckdns.org")

if not PRIVATE_KEY:
    print("ОШИБКА: PRIVATE_KEY не задан.")
    print()
    print("Создай файл agent-api/scripts/.env с содержимым:")
    print("  PRIVATE_KEY=0xТВОЙ_ПРИВАТНЫЙ_КЛЮЧ_ОТ_ДРУГОГО_КОШЕЛЬКА")
    print()
    print("Шаги:")
    print("  1. Создай новый кошелёк в MetaMask/Rabby")
    print("  2. Экспортируй приватный ключ")
    print("  3. Пополни его на $1-2 USDC через Base (с биржи или мостом)")
    print("  4. Запиши ключ в scripts/.env")
    sys.exit(1)


async def make_x402_payment():
    """Use the official x402 SDK to pay and call our API."""
    from eth_account import Account
    from x402 import x402Client
    from x402.http.clients.httpx import x402AsyncHTTPXClient
    from x402.mechanisms.evm import EthAccountSigner
    from x402.mechanisms.evm.exact.register import register_exact_evm_client

    print(f"Кошелёк-плательщик: {Account.from_key(PRIVATE_KEY).address}")
    print(f"API: {API_URL}")
    print()

    # Setup x402 client with our wallet as payer
    client = x402Client()
    account = Account.from_key(PRIVATE_KEY)
    register_exact_evm_client(client, EthAccountSigner(account))

    print("Вызываю /api/validate-json с авто-оплатой $0.005 USDC...")

    async with x402AsyncHTTPXClient(client, base_url=API_URL) as http:
        response = await http.post(
            "/api/validate-json",
            json={"data": '{"name": "test", "value": 42}'},
        )
        data = response.json()
        print(f"Статус: {response.status_code}")
        print(f"Ответ: {data}")

    print()
    print("ГОТОВО! Платёж прошёл. Bazaar проиндексирует сервис в течение нескольких минут.")
    print("Проверь: https://agentic.market (поиск по 'AI Agent API')")


async def check_402_first():
    """Verify the API returns 402 before we try to pay."""
    import httpx

    print("Проверяю, что API отвечает 402 без оплаты...")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_URL}/api/validate-json",
            json={"data": "{}"},
        )
        if resp.status_code == 402:
            print("  OK — API требует оплату (402)")
        else:
            print(f"  СТРАННО — статус {resp.status_code}, ожидался 402")
    print()


async def main():
    await check_402_first()
    await make_x402_payment()


if __name__ == "__main__":
    asyncio.run(main())
