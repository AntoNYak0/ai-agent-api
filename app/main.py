from fastapi import FastAPI
from app.config import settings
from app.x402_setup import configure_x402
from app.routes import audit, refactor, docs

app = FastAPI(
    title="AI Agent API",
    description="Платные AI-услуги: аудит кода, рефакторинг, документация. Оплата через x402 (USDC).",
    version="1.0.0",
)

configure_x402(
    app=app,
    pay_to_evm=settings.pay_to_address_evm,
    pay_to_solana=settings.pay_to_address_solana,
    facilitator_url=settings.facilitator_url,
    testnet=settings.testnet,
)

app.include_router(audit.router)
app.include_router(refactor.router)
app.include_router(docs.router)


@app.get("/health")
async def health():
    return {"status": "ok", "testnet": settings.testnet}
