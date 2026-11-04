from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://seismo:seismo@localhost:5432/seismo"
    session_ttl_hours: int = 12
    cookie_secure: bool = False
    upload_dir: str = "/data/uploads"
    backup_dir: str = "/data/backups"
    max_upload_mb: int = 50
    admin_username: str = "admin"
    admin_password: str = "ChangeMe123!"
    admin_full_name: str = "Администратор"
    ocr_enabled: bool = True
    ocr_lang: str = "rus+eng"
    cors_origins: str = ""
    preview_rows: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
