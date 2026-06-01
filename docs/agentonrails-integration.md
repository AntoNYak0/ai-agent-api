# AgentOnRails Integration

AgentOnRails — локальный прокси-демон для AI-агентов. Автоматически обрабатывает HTTP 402 (Payment Required) от agent-api, подписывает EIP-3009 авторизации и повторяет запросы. Агент не видит платёжную логику вообще.

## Как это работает

```
AI Agent (curl / httpx / LangChain / CrewAI)
    │  HTTP-запрос без платёжных заголовков
    ▼
AgentOnRails (localhost:8402)
    │  1. Пропускает обычные запросы прозрачно
    │  2. Видит 402 → парсит PAYMENT-REQUIRED
    │  3. Проверяет политики (бюджет, allowlist, velocity)
    │  4. Подписывает EIP-3009 transferWithAuthorization
    │  5. Повторяет запрос с PAYMENT-SIGNATURE
    ▼
agent-api (https://agent-api-ai.duckdns.org)
    │  Верифицирует через Facilitator → возвращает 200 + результат AI
```

## Совместимость

Формат `PAYMENT-REQUIRED` от agent-api полностью совместим с AgentOnRails. Все обязательные поля присутствуют:

- `scheme: "exact"` — EIP-3009 авторизация
- `network: "eip155:8453"` — CAIP-2 формат (Base)
- `asset` — адрес контракта USDC
- `amount` — максимальная сумма в микроюнитах (settlement по фактическому использованию)
- `payTo` — адрес получения USDC
- `maxTimeoutSeconds: 300` — окно авторизации

## Установка и настройка

```bash
# Установка AgentOnRails
go install github.com/AgentOnRails/AgentOnRails/cmd/aor@latest

# Создать конфигурацию агента
mkdir -p ~/.aor/agents

# Импортировать кошелёк агента
aor credentials set-wallet my-agent
# Вставить приватный ключ и задать пароль для vault

# Настроить политики для agent-api
cat > ~/.aor/agents/my-agent.yaml << 'YAML'
rails:
  x402:
    per_call_max_usd: 1.00       # Максимум за один вызов (contract-verify = $1.00)
    daily_limit_usd: 10.00       # Дневной лимит
    weekly_limit_usd: 50.00      # Недельный лимит
    monthly_limit_usd: 200.00    # Месячный лимит
    endpoint_mode: allowlist
    allowed_hosts:
      - agent-api-ai.duckdns.org
    allowed_networks:
      - eip155:8453       # Base
      - eip155:42161      # Arbitrum
      - eip155:10         # Optimism
    velocity:
      max_per_minute: 20
      max_per_hour: 100
YAML

# Запустить демон
export AOR_PASSPHRASE="your-vault-passphrase"
aor start
```

## Использование

```bash
# Через HTTP_PROXY — агент просто делает запрос как обычно
HTTP_PROXY=http://localhost:8402 curl -X POST \
  https://agent-api-ai.duckdns.org/api/audit \
  -H "Content-Type: application/json" \
  -d '{"code": "function transfer(address to, uint amount) { balances[msg.sender] -= amount; balances[to] += amount; }"}'

# AgentOnRails автоматически:
# 1. Видит 402 от agent-api
# 2. Парсит challenge ($0.05 USDC на Base)
# 3. Подписывает EIP-3009 на 50000 микроюнитов
# 4. Ретраит с PAYMENT-SIGNATURE
# 5. Возвращает результат аудита агенту
```

## Интеграция с LangChain / CrewAI

```python
import os
import httpx

# AgentOnRails как прокси
os.environ["HTTP_PROXY"] = "http://localhost:8402"
os.environ["HTTPS_PROXY"] = "http://localhost:8402"

# LangChain использует httpx, который подхватывает HTTP_PROXY
from langchain_openai import ChatOpenAI

# Весь трафик идёт через AgentOnRails
# 402 обрабатывается прозрачно
```

## Сервисы agent-api и их цены

| Сервис | Цена (max) | Endpoint |
|--------|-----------|----------|
| audit | $0.05 | POST /api/audit |
| refactor | $0.05 | POST /api/refactor |
| docs | $0.03 | POST /api/docs |
| defi-analyze | $0.04 | POST /api/defi-analyze |
| trading-signal | $0.03 | POST /api/trading-signal |
| solidity-scan | $0.08 | POST /api/solidity-scan |
| agent-audit | $0.50 | POST /api/agent-audit |
| contract-verify | $1.00 | POST /api/contract-verify |
| security-score | $0.10 | POST /api/security-score |
| whale-tracker | $0.03 | POST /api/whale-tracker |
| smart-money | $0.05 | POST /api/smart-money |
| price-feed | $0.02 | POST /api/price-feed |
| data-feed | $0.02 | POST /api/data-feed |
| debug-log | $0.03 | POST /api/debug-log |
| nl-to-sql | $0.03 | POST /api/nl-to-sql |
| sql-to-nl | $0.02 | POST /api/sql-to-nl |
| translate-code | $0.05 | POST /api/translate-code |
| git-summarize | $0.02 | POST /api/git-summarize |
| validate-json | $0.001 | POST /api/validate-json |
| classify-text | $0.001 | POST /api/classify-text |
| extract-data | $0.005 | POST /api/extract-data |
| generate-regex | $0.002 | POST /api/generate-regex |
| format-data | $0.003 | POST /api/format-data |
| summarize | $0.002 | POST /api/summarize |

## Upto pricing

Все AI-сервисы используют upto-ценообразование: агент авторизует максимальную цену, agent-api списывает только за фактически использованные токены. Например, для `/api/audit`:
- Агент подписывает EIP-3009 на $0.05 (50000 микроюнитов)
- Реально тратится 1200 токенов → settlement на $0.0036
- Ответ содержит `PAYMENT-RESPONSE: true` и `X-Payment-Amount: $0.003600 USDC`

AgentOnRails должен корректно обрабатывать Settlement-Overrides в ответе 200.
