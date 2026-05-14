# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI Agent API — FastAPI сервер с платными AI-услугами (аудит кода, рефакторинг, документация). Принимает USDC через x402 протокол. Модель — DeepSeek V4 Pro (1M контекст). Доступен через HTTP API и MCP (Model Context Protocol) для других ИИ-агентов.

## Commands

```bash
# Локальный запуск
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Тесты (402 без платежа)
pytest tests/ -v

# Публичный доступ через serveo
ssh -R 80:localhost:8000 serveo.net

# Установка зависимостей
pip install -r requirements.txt
```

## Architecture

Два параллельных слоя обслуживания, оба ведут к одному DeepSeek-врапперу:

**HTTP API (x402)** — `POST /api/audit`, `/api/refactor`, `/api/docs`. Запрос без оплаты → HTTP 402 с `PAYMENT-REQUIRED` заголовком (цена, сеть, кошелёк). После оплаты клиент шлёт `payment-signature` → фасилитатор проверяет → выполняется DeepSeek.

**MCP (Model Context Protocol)** — `/mcp/sse` (SSE транспорт). Другие ИИ-агенты подключаются, видят три инструмента (audit/refactor/docs), платят USDC и вызывают их с `payment_tx` параметром.

### Ключевые файлы

| Файл | Роль |
|---|---|
| `app/main.py` | Точка входа: FastAPI + CORS + x402 middleware + MCP mount |
| `app/x402_setup.py` | Конфигурация x402: роуты, цены, сети, Bazaar discovery |
| `app/facilitator.py` | Свой фасилитатор (без Coinbase). Testnet: auto-approve. Mainnet: проверка через публичные RPC Base/Polygon |
| `app/mcp_server.py` | FastMCP сервер с тремя инструментами + верификация платежей |
| `app/services/deepseek.py` | AsyncOpenAI враппер к DeepSeek API |
| `app/config.py` | Pydantic Settings: ключи, адрес кошелька, testnet/mainnet |

### Платёжный поток (x402)

```
Клиент → POST /api/audit
  ← 402 + PAYMENT-REQUIRED (цена, сеть, кошелёк)
Клиент → платит USDC, получает tx hash
Клиент → повтор с payment-signature заголовком
  → DirectFacilitator.verify() — testnet: OK, mainnet: RPC проверка
  → DeepSeek выполняет
  → DirectFacilitator.settle()
  ← 200 + результат
```

### Сети

- **Testnet**: Base Sepolia (`eip155:84532`) — `TESTNET=true` в `.env`
- **Mainnet**: Base (`eip155:8453`) + Polygon PoS (`eip155:137`) — `TESTNET=false`

### Конфигурация

`.env` (не коммитится):
- `DEEPSEEK_API_KEY` — ключ DeepSeek API
- `PAY_TO_ADDRESS_EVM` — 0x адрес для приёма USDC
- `TESTNET` — `true` (тестнет, auto-approve) / `false` (mainnet, RPC проверка)

### Зависимости

`x402[evm,fastapi]>=2.10.0` — тянет web3, eth-account и всё для EIP-3009.  
`mcp>=1.27.0` — FastMCP для SSE сервера (установлен отдельно, не в requirements.txt).  
DeepSeek через `openai` SDK (API-совместим).
