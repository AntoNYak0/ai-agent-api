from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DeepSeek
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
