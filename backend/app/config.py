from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    # +psycopg selects the psycopg 3 driver; bare postgresql:// would ask for psycopg2.
    database_url: str = "postgresql+psycopg://docpipe:docpipe@localhost:5432/docpipe"

    # Uploads land here. The API writes them and the worker reads them, so this
    # path has to be the same bind mount in both containers.
    storage_dir: Path = Path("/app/data/uploads")

    # LLM. "stub" is a deterministic fake so the pipeline runs without an API
    # key; swapping in a real provider means implementing _complete() in
    # app/services/llm.py and setting llm_provider/llm_model here.
    llm_provider: str = "stub"
    llm_model: str = "stub-v0"
    # Rough guard on prompt size — the analysis prompt truncates past this.
    llm_max_input_chars: int = 12000


settings = Settings()
