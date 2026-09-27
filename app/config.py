"""
Environment/config loading. See .env.example for every variable this
project needs. No business logic here -- Section C/G reference these
values, don't hardcode them elsewhere.
"""
# pyrefly: ignore [missing-import]
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str

    telegram_bot_token: str
    telegram_webhook_secret: str
    send_mode: str = "real"

    model_provider: str = ""
    model_api_key: str = ""
    model_name: str = ""
    model_fallback_name: str = ""

    n8n_webhook_url: str = ""
    n8n_shared_secret: str = ""

    jwt_secret: str = "emberground_super_secret_jwt_key_2026_production_grade_token_secret"
    telegram_bot_username: str = "emberground_bot"
    dodo_api_key: str = ""
    dodo_webhook_secret: str = ""
    breeth_api_key: str = ""
    owner_telegram_bot_token: str = ""
    owner_telegram_chat_id: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
