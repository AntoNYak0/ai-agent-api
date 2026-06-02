from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DeepSeek
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_model_flash: str = "deepseek-v4-flash"

    # LLM cost control
    llm_budget_limit_usd: float = 0.0  # 0 = no limit; set e.g. 5.00 for $5/day cap
    llm_cost_recording: bool = True    # track costs in global tracker for /health

    # x402 wallet — public receiving address (no private key needed on server)
    pay_to_address_evm: str
    pay_to_address_tron: str | None = None
    pay_to_address_solana: str | None = None

    # x402 facilitator — "payai" (no auth), "payai_auth" (PayAI with API key), "cdp" (Coinbase KYC), "direct" (Sovereign Mode), "chaoschain" (decentralized, Chainlink CRE BFT)
    facilitator_mode: str = "payai"  # "payai" | "payai_auth" | "cdp" | "direct" | "chaoschain"

    # PayAI Facilitator credentials (needed when facilitator_mode="payai_auth")
    payai_api_key_id: str = ""
    payai_api_key_secret: str = ""

    # CDP Facilitator credentials (only needed when facilitator_mode="cdp")
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""

    # App mode
    testnet: bool = True
    environment: str = "development"

    # Feature flags
    x402_enabled: bool = True  # set to false to bypass payment wall for testing

    # Admin API key for /billing/analytics
    admin_api_key: str = ""

    # ── Resilience: Circuit Breaker ──────────────────────────────────
    circuit_breaker_failure_threshold: int = 5   # consecutive failures to trip OPEN
    circuit_breaker_reset_timeout: int = 60       # seconds before HALF_OPEN probe

    # ── Resilience: Retry ────────────────────────────────────────────
    retry_max_attempts: int = 3                     # max attempts (1 = no retries)
    retry_base_delay: float = 1.0                   # seconds — base for exponential backoff
    retry_max_delay: float = 30.0                   # seconds — cap on backoff
    retry_jitter_enabled: bool = True               # ±50% jitter to prevent thundering herd
    retry_max_cumulative_timeout: float = 60.0      # seconds — total budget across all attempts

    # ── Resilience: Timeouts ─────────────────────────────────────────
    deepseek_socket_timeout: float = 30.0           # seconds — OpenAI client socket timeout
    rpc_retry_max_attempts: int = 2                 # RPC retry attempts per URL

    # ── EIP-3009: receiveWithAuthorization ──────────────────────────
    facilitator_eip3009_private_key: str = ""        # 0x-prefixed server private key for EIP-3009 settlement
    eip3009_max_gas_fee_wei: int = 0                 # 0 = auto (eth_gasPrice * 1.2)

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
