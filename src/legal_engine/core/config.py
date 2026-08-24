"""Pydantic v2 application settings, sourced from environment variables / .env."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="LEGAL_ENGINE_", extra="ignore")

    environment: str = "development"
    log_level: str = "INFO"

    # Formal logic / Z3
    z3_timeout_ms: int = 480
    z3_memory_limit_mb: int = 512
    z3_pool_size: int = 4

    # Game theory
    trembling_hand_epsilon_max: float = 0.05

    # Datastores
    postgres_dsn: str = "postgresql+asyncpg://legal_engine:legal_engine@localhost:5432/legal_engine"
    redis_url: str = "redis://localhost:6379/0"
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"
    qdrant_url: str = "http://localhost:6333"

    # Vector embeddings
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dim: int = 384
    cosine_similarity_threshold: float = 0.18

    # knowledge_graph/factory.py: which backend each Protocol resolves to.
    # Defaults are the in-process implementations the test suite runs
    # against; switching to a "real" backend requires its install extra
    # (graph-neo4j / vector-qdrant / semantic) to actually be installed —
    # the factory raises a clear ImportError if it isn't, rather than
    # failing in some more confusing way at request time.
    graph_backend: Literal["networkx", "neo4j"] = "networkx"
    vector_backend: Literal["in_memory", "qdrant"] = "in_memory"
    embedding_backend: Literal["hashing", "sentence_transformers"] = "hashing"
    qdrant_collection_name: str = "statutes"

    # Ingestion (polite crawling — see ingestion/rate_limiter.py)
    ingestion_user_agent: str = "legal-engine-bot/0.1 (+contact: set LEGAL_ENGINE_INGESTION_CONTACT)"
    ingestion_contact: str = ""
    ingestion_max_concurrency: int = 2
    ingestion_min_delay_seconds: float = 1.0
    ingestion_respect_robots_txt: bool = True

    # WAL
    wal_path: str = "data/wal"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_auth_enabled: bool = False
    api_client_id: str = "demo"
    api_client_secret: str = "change-me-in-production"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60


settings = Settings()
