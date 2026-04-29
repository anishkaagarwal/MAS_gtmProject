"""
Configuration — loaded from environment with sensible defaults.
No magic config files. Code is the single source of truth.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- LLM ---
    # Providers: "google" (Gemini, free), "anthropic" (Claude), "mock" (dev)
    llm_provider: str = "google"
    llm_model: str = "gemini-2.5-flash-lite"  # or "gemini-2.0-flash", "claude-sonnet-4-20250514"
    llm_api_key: str = ""
    llm_max_tokens: int = 8192
    llm_temperature: float = 0.3  # low for structured output

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600

    # --- Vector store ---
    vector_store_enabled: bool = False
    vector_store_url: str = ""
    embedding_model: str = "text-embedding-3-small"

    # --- Data sources ---
    apollo_api_key: str = ""
    clearbit_api_key: str = ""

    # --- Pipeline ---
    max_pipeline_retries: int = 3
    max_wall_clock_seconds: float = 300.0
    min_companies_required: int = 3
    min_critic_quality: float = 0.5

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = int(__import__("os").environ.get("PORT", 8000))
    cors_origins: str = "*"

    # --- Observability ---
    log_level: str = "INFO"
    otel_endpoint: str = ""  # OpenTelemetry collector

    model_config = {"env_prefix": "OUTMATE_", "env_file": ".env", "env_file_encoding": "utf-8"}
