# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI Agent API — FastAPI + MCP сервер с 16 платными AI-услугами на DeepSeek V4 Pro (1M контекст). Два интерфейса: HTTP REST API и MCP SSE (`/mcp/sse`). Принимает USDC через x402 (DirectFacilitator + Base/Polygon RPC) и API-ключи (credits для людей). Синхронизированы.

Деплой: `http://77.239.107.30:8000` (VPS serv.host, Ubuntu 24.04, systemd).
GitHub: `https://github.com/AntoNYak0/ai-agent-api`.

**Конкурент:** KronoScan (ETHGlobal Cannes 2026) — тоже DeepSeek + x402 + USDC, только аудит смарт-контрактов, с ончейн-эскроу и ENS.

## Commands

```bash
# Локальный запуск
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Тесты (pytest пока не написан)
pytest tests/ -v

# Деплой на VPS
python scripts/deploy.py

# Проверка
curl http://77.239.107.30:8000/health
curl http://77.239.107.30:8000/
curl http://77.239.107.30:8000/.well-known/x402
python scripts/test_payment.py       # 9 тестов: REST + API-ключи + replay
python scripts/test_dexter.py        # 7 тестов: x402 + Dexter + manifest

# Запустить Python-клиент
python examples/client.py
python examples/client.py --key ak-YOUR_KEY --service audit --data "code"
```

## Architecture

### Два интерфейса (синхронизированы)

**REST API** (`app/routes/*.py`) — 16 FastAPI-роутов. Английские JSON-промпты, `json_mode=True`, ретраи 3x, списание кредитов для людей. Платёж: x402 middleware для агентов, пропускается если `request.state.human_api_key`.

**MCP Server** (`app/mcp_server.py`) — 16 FastMCP-тулов. Те же промпты, ретраи 3x, `json_mode=True`, replay protection, upto pricing, списание кредитов через `api_key` параметр. Основной интерфейс для AI-агентов через `/mcp/sse`.

**Streaming** (`app/routes/stream.py`) — SSE-эндпоинт `POST /api/stream/{tool}` для 5 AI-сервисов (audit, refactor, docs, trading, solidity-scan). Чанки через `text/event-stream`.

### Платёжный поток

```
REST:
  Человек: Authorization: Bearer ak-... → API key middleware → x402 skip → handler → deduct credits
  Агент:   POST /api/audit → 402 + X-Payment-Help header → платит USDC → 
           повтор с payment-signature: <base64-PaymentPayload> → DirectFacilitator verify через Base RPC → handler

MCP (SSE):
  Человек: audit_tool(code, api_key="ak-...") → _verify_payment → credits check → spend_credits
  Агент:   audit_tool(code, payment_tx="0x...") → _verify_payment → DirectFacilitator.verify() → settle
```

**Payment-signature header:** base64-encoded JSON с полями `x402Version`, `payload.transactionHash`, `accepted` (scheme, network, asset, amount, payTo). Формат в `examples/client.py`.

### Middleware chain (main.py, порядок выполнения)

1. `rate_limit_middleware` — 10 запросов/мин/IP, пропускает `/health` и `/.well-known/*`
2. `cache_control_middleware` — `Cache-Control: no-store` на `/api/*`
3. `human_api_key_middleware` — читает `Authorization: Bearer ak-...`, ставит `request.state.human_api_key`
4. `x402_payment_middleware` — проверяет флаг API-ключа, иначе x402; добавляет `X-Payment-Help` на 402

Порядок важен: middleware в FastAPI выполняются в обратном порядке определения (последний → первый). Rate limiter определён последним → выполняется первым.

### Ключевые файлы

| Файл | Роль |
|---|---|
| `app/main.py` | CORS + middleware chain + все роутеры + MCP mount + dashboard (`GET /`) + health |
| `app/x402_setup.py` | Конфиг x402: 16 роутов, цены, сети, Bazaar discovery, API key bypass, `X-Payment-Help` |
| `app/mcp_server.py` | FastMCP: 16 тулов, verify+settle, upto-логика, replay guard, credits |
| `app/services/deepseek.py` | AsyncOpenAI → DeepSeek, ретраи 3x, json_mode, возвращает `(text, tokens)` + streaming |
| `app/services/replay_guard.py` | HMAC-фингерпринт платежей с TTL 10 мин |
| `app/services/credits.py` | API-key система: create, top-up, spend, balance + bulk-бонусы (10%/20%/30%) |
| `app/services/analytics.py` | Статистика вызовов: tool, payment_method, revenue (JSON, 10K записей, 30 дней) |
| `app/services/rate_limiter.py` | In-memory rate limiter: 10 req/min/IP, 500 tracked IPs max |
| `app/facilitator.py` | DirectFacilitator: testnet-автоодобрение или RPC-верификация ERC-20 Transfer |
| `app/config.py` | Pydantic Settings из `.env` |
| `app/models.py` | Pydantic-модели запросов + `ServiceResponse` |
| `app/well_known.py` | `/.well-known/x402` + `/.well-known/openapi.json` (16 эндпоинтов, x402 extensions) |
| `app/routes/billing.py` | `/billing/create-key`, `/balance`, `/top-up`, `/stats`, `/analytics`, `/tiers` |
| `app/routes/micro.py` | 10 роутов: 6 micro-tasks + translate + nl-to-sql + sql-to-nl + git-summarize |
| `app/routes/stream.py` | SSE-стриминг для 5 AI-сервисов |
| `app/routes/audit.py`, `refactor.py`, `docs.py`, `defi.py`, `trading.py`, `solidity_scan.py` | 6 AI-сервисов |
| `scripts/deploy.py` | SFTP-деплой + systemctl restart |
| `scripts/test_payment.py` | 9 тестов: health, 402, key lifecycle, credits deduction, discovery, replay |
| `scripts/test_dexter.py` | 7 тестов: x402 manifest, PAYMENT-REQUIRED header, OpenAPI, facilitator config |
| `examples/client.py` | Python-клиент: 3 режима (402-гид, API-ключ, x402) |

### 16 сервисов

**AI-услуги (upto pricing — плата по токенам):**
| Тула | Цена |
|---|---|
| audit | $0.02–$0.10 |
| refactor | $0.03–$0.16 |
| docs | $0.01–$0.06 |
| defi | $0.02–$0.08 |
| trading | $0.01–$0.06 |
| solidity-scan | $0.04–$0.20 |
| nl-to-sql | $0.01–$0.06 |
| sql-to-nl | $0.01–$0.04 |
| translate-code | $0.02–$0.10 |
| git-summarize | $0.01–$0.04 |

**Микро-задачи (exact pricing):**
| Тула | Цена |
|---|---|
| validate-json | $0.001 |
| classify-text | $0.002 |
| extract-data | $0.015 |
| generate-regex | $0.005 |
| format-data | $0.01 |
| summarize | $0.005 |

### Фасилитатор

**Production:** `DirectFacilitator(testnet=False, pay_to=...)` — проверяет ERC-20 Transfer events через публичные Base/Polygon RPC. Клиент присылает `transactionHash` в `payment-signature` header, фасилитатор читает receipt, находит Transfer event, сверяет получателя.

**Testnet:** `DirectFacilitator(testnet=True)` — авто-одобрение без блокчейна.

Dexter (`HTTPFacilitatorClient`) не используется — он требует EIP-3009 подписи (Permit2), а не готовый tx hash.

### API-ключи и кредиты

- Формат: `ak-` + 32 hex
- 10 credits = $0.01 (1 credit = $0.001)
- Человеческая цена = x402 × 1.5
- Минимум списания: 1 цент
- Хранение: `/opt/agent-api/data/credits.json`
- Топ-ап: `POST /billing/top-up?key=...&amount_cents=...`
- Bulk-бонусы: +10% ($10), +20% ($50), +30% ($100)
- Авто-списание: REST через `_deduct_and_track()`, MCP через `_verify_payment()` + `credits.spend_credits()`

### Промпты

Все в `app/prompts/` — английские, JSON-схемы ответа. `audit.py`, `refactor.py`, `docs.py`, `defi.py`, `trading.py`, `solidity_scan.py`, `micro.py` (10 промптов).

## Деплой

VPS: `77.239.107.30`, root, пароль в `scripts/deploy.py`.
- systemd: `agent-api` (автозапуск, `systemctl restart agent-api`)
- Порт 8000 открыт (ufw)
- SFTP через paramiko: `python scripts/deploy.py`
- Логи: `journalctl -u agent-api --no-pager -n 50`
- Данные: `/opt/agent-api/data/` (credits.json, analytics.json)

## Известные проблемы

1. **Stripe не подключён** — credits работают, но топ-ап только ручной (`/billing/top-up`).
2. **Solana settlement не зарегистрирован** — x402 SDK не поддерживает SVM. Solana в well-known, но не в роутах.
3. **Нет pytest-тестов** — верификация через `test_payment.py` (9 тестов) и `test_dexter.py` (7 тестов).
4. **Нет HTTPS** — сервер на голом HTTP. Для прода нужен SSL.
