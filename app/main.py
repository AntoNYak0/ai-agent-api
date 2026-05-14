from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.x402_setup import configure_x402
from app.routes import audit, refactor, docs
from app.mcp_server import mcp as mcp_app

app = FastAPI(
    title="AI Agent API",
    description="Платные AI-услуги: аудит кода, рефакторинг, документация. Оплата через x402 (USDC).",
    version="1.0.0",
)

# CORS — allow agents from anywhere to call MCP tools
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
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

# Mount MCP server at /mcp — other AI agents connect here
app.mount("/mcp", mcp_app.sse_app())


@app.get("/health")
async def health():
    return {"status": "ok", "testnet": settings.testnet}
