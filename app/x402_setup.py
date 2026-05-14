from fastapi import FastAPI
from x402 import x402ResourceServer
from x402.http import (
    RouteConfig,
    PaymentOption,
)
from x402.http.middleware.fastapi import (
    payment_middleware,
    PaywallConfig,
)
from x402.mechanisms.evm.exact import register_exact_evm_server

from app.facilitator import DirectFacilitator


def configure_x402(
    app: FastAPI,
    pay_to_evm: str,
    pay_to_solana: str | None,
    facilitator_url: str,  # kept for signature compatibility, unused
    testnet: bool = True,
) -> None:
    # 1. Custom facilitator — no Coinbase, no x402.org
    facilitator = DirectFacilitator(testnet=testnet, pay_to=pay_to_evm)

    # 2. Resource server with our facilitator
    server = x402ResourceServer(facilitator)

    # 3. Register EVM networks and schemes
    base_net = "eip155:84532" if testnet else "eip155:8453"
    polygon_net = "eip155:137"

    register_exact_evm_server(server, [base_net, polygon_net])

    # 4. Build route payment configs
    common_networks = [base_net]
    if not testnet:
        common_networks.append(polygon_net)

    def make_payment_option(network: str, price: str) -> PaymentOption:
        return PaymentOption(
            scheme="exact",
            pay_to=pay_to_evm,
            price=price,
            network=network,
        )

    routes: dict[str, RouteConfig] = {
        "POST /api/audit": RouteConfig(
            accepts=[
                make_payment_option(net, "$15.00") for net in common_networks
            ],
            description="Аудит безопасности кода / смарт-контрактов (1M контекст)",
            mime_type="application/json",
            extensions={
                "bazaar": {
                    "discoverable": True,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Код для аудита"},
                            "context": {"type": "string", "description": "Дополнительный контекст"},
                        },
                        "required": ["code"],
                    },
                }
            },
        ),
        "POST /api/refactor": RouteConfig(
            accepts=[
                make_payment_option(net, "$10.00") for net in common_networks
            ],
            description="Рефакторинг легаси-кода с полным анализом кодовой базы",
            mime_type="application/json",
            extensions={
                "bazaar": {
                    "discoverable": True,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Код для рефакторинга"},
                            "instructions": {"type": "string", "description": "Особые указания"},
                            "context": {"type": "string", "description": "Дополнительный контекст"},
                        },
                        "required": ["code"],
                    },
                }
            },
        ),
        "POST /api/docs": RouteConfig(
            accepts=[
                make_payment_option(net, "$5.00") for net in common_networks
            ],
            description="Генерация технической документации по коду",
            mime_type="application/json",
            extensions={
                "bazaar": {
                    "discoverable": True,
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "Код для документирования"},
                            "format": {"type": "string", "description": "Формат: markdown"},
                            "context": {"type": "string", "description": "Дополнительный контекст"},
                        },
                        "required": ["code"],
                    },
                }
            },
        ),
    }

    # 5. Paywall branding
    paywall = PaywallConfig(
        app_name="AI Agent API — Аудит, Рефакторинг, Документация",
    )

    # 6. Create and apply middleware
    x402_mw = payment_middleware(routes, server, paywall_config=paywall)

    @app.middleware("http")
    async def x402_payment_middleware(request, call_next):
        return await x402_mw(request, call_next)
