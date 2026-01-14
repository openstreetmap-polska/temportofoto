from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_connection_string: str = "sqlite:///test.db"
    data_dir: str = "./"
    base_url: str = "http://127.0.0.1:8000"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="temportofoto_")


settings = Settings()  # type: ignore
