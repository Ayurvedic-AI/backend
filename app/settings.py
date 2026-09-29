from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    asr_backend: str = "sarvam"      # sarvam | bhashini | local
    mt_backend: str = "sarvam"       # sarvam | bhashini | local
    storage: str = "local"           # local | s3
    storage_dir: str = "./data/audio"
    s3_bucket: str = ""
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/ayurvedic_ai"

    sarvam_api_key: str = ""
    bhashini_user_id: str = ""
    bhashini_api_key: str = ""

    model_config = {"env_file": ".env"}


settings = Settings()
