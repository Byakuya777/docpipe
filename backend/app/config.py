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

    # LLM. "anthropic" calls the real API; "stub" is the deterministic fake,
    # kept so the pipeline still runs with no API key and no network.
    llm_provider: str = "anthropic"
    llm_model: str = "claude-haiku-4-5"
    # Read from ANTHROPIC_API_KEY. Left unset, the SDK resolves credentials
    # from the environment itself.
    anthropic_api_key: str | None = None
    # Identity-linked API keys must name the workspace the request acts in;
    # the API rejects them with a 400 otherwise. Unused by other key types.
    anthropic_workspace_id: str | None = None
    # Rough guard on prompt size — the analysis prompt truncates past this.
    llm_max_input_chars: int = 12000
    # Stop pulling pages once extraction has this much text. Everything past
    # llm_max_input_chars is discarded before the model sees it, so reading a
    # 600-page PDF to the end just to throw 99% of it away is what pushed the
    # worker into an OOM kill. Kept above llm_max_input_chars for headroom.
    extract_max_chars: int = 24000
    # The reply is one small JSON object, so this ceiling is deliberately
    # tight rather than lowballed.
    llm_max_output_tokens: int = 2048
    # Fail fast and let Celery own the backoff, rather than have the SDK
    # silently burn the task's time on its own retry ladder.
    llm_timeout_seconds: float = 60.0
    llm_sdk_max_retries: int = 1

    # Retry/backoff for recoverable failures (LLMError). The delay is computed
    # in tasks.py rather than via Celery's retry_backoff option, which only
    # applies to autoretry_for and is ignored by a manual self.retry() call.
    task_max_retries: int = 3
    retry_backoff_base: float = 2.0
    retry_backoff_max: float = 60.0

    # Fault injection for testing the retry path (PROJECT_SPEC.md §6.2, §11 M4:
    # "mock an LLM timeout"). "off" in normal operation.
    #   always  — every LLM call raises LLMError
    #   first_n — the first llm_fault_attempts attempts raise, then succeed
    llm_fault_mode: str = "off"
    llm_fault_attempts: int = 2


settings = Settings()
