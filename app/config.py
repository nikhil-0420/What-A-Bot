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

    # Gemini-specific (Shahana) — verified live 27 Sept 2026
    # Primary: gemini-3.5-flash-lite (FC PASS, 2023ms)
    # Fallback: gemini-3.6-flash     (FC PASS, 2532ms)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"          # confirmed primary
    gemini_fallback_model: str = "gemini-3.6-flash"      # confirmed fallback

    elevenlabs_api_key: str = ""

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
