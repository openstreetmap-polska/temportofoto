from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_connection_string: str
    data_dir: str
    base_url: str

    model_config = SettingsConfigDict(env_file=".env", env_prefix="temportofoto_")


settings = Settings()  # type: ignore
