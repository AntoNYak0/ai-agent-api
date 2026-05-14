from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DeepSeek
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # x402 wallet — public receiving address (no private key needed on server)
    pay_to_address_evm: str
    pay_to_address_solana: str | None = None

    # x402 facilitator
    facilitator_url: str = "https://x402.org/facilitator"

    # App mode
    testnet: bool = True
    environment: str = "development"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
