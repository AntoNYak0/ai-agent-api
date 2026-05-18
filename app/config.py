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

    # x402 facilitator — "payai" (recommended, no KYC), "cdp" (Coinbase, needs KYC), "direct" (Sovereign Mode)
    facilitator_mode: str = "payai"  # "payai" | "cdp" | "direct"

    # CDP Facilitator credentials (only needed when facilitator_mode="cdp")
    cdp_api_key_id: str = ""
    cdp_api_key_secret: str = ""

    # App mode
    testnet: bool = True
    environment: str = "development"

    # Feature flags
    x402_enabled: bool = True  # set to false to bypass payment wall for testing

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
