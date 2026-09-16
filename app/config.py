from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str

    test_database_url: str = (
        "postgresql+psycopg://"
        "bita:bita_test_password@localhost:5433/bita_test"
    )

    app_name: str = "BITA Constituent Service"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

settings = Settings()