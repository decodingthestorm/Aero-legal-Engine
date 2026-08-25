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
    # persistence/factory.py: the durable, queryable system-of-record for
    # ingested statutes (separate from the graph/vector *indexes* above,
    # which are rebuildable from this). "sql" works against any DSN
    # SQLAlchemy's async engine supports with the right driver installed —
    # postgres_dsn's default is Postgres, but the test suite points this at
    # SQLite (sqlite+aiosqlite:///...) since there's no Postgres in this
    # environment to test against for real.
    statute_backend: Literal["in_memory", "sql"] = "in_memory"
    # persistence/user_repository.py: the registered-user store behind
    # POST /auth/register and POST /auth/token's real-user login path.
    # Same in_memory/sql split and same postgres_dsn as statute_backend —
    # a real deployment wants "sql" for both, but they're independent
    # settings in case a caller genuinely wants one persisted and not the
    # other (e.g. ephemeral demo statutes, durable user accounts).
    user_backend: Literal["in_memory", "sql"] = "in_memory"

    # Ingestion (polite crawling — see ingestion/rate_limiter.py)
    ingestion_user_agent: str = "legal-engine-bot/0.1 (+contact: set LEGAL_ENGINE_INGESTION_CONTACT)"
    ingestion_contact: str = ""
    ingestion_max_concurrency: int = 2
    ingestion_min_delay_seconds: float = 1.0
    ingestion_respect_robots_txt: bool = True

    # WAL / core/key_signer_factory.py: which backend signs and verifies
    # WAL entries. "file" (the default, always available) is a local
    # Ed25519 keypair persisted unencrypted under wal_path — see
    # Ed25519FileKeySigner's docstring for why that's an honest, not a
    # hidden, limitation. "aws_kms"/"vault_transit" need the `kms` install
    # extra (boto3/hvac) and a real key/instance already provisioned —
    # neither creates one, and neither is exercised against a real AWS
    # account or Vault instance in this environment (see
    # core/key_signer.py's module docstring).
    wal_path: str = "data/wal"
    wal_signer_backend: Literal["file", "aws_kms", "vault_transit"] = "file"
    wal_kms_key_id: str = ""
    wal_vault_key_name: str = "legal-engine-wal"
    wal_vault_url: str = "http://127.0.0.1:8200"
    wal_vault_token: str = ""

    # core/email_sender_factory.py: which backend POST /auth/invite,
    # /auth/request-password-reset, and registration's email-verification
    # step send through. "logging" (the default, always available) logs
    # instead of actually sending — see LoggingEmailSender's docstring.
    # "smtp" needs no install extra (smtplib/email are stdlib) but does
    # need a real SMTP server configured; not exercised against a live
    # one in this environment (see core/email_sender.py's module
    # docstring).
    email_backend: Literal["logging", "smtp"] = "logging"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_address: str = "noreply@legal-engine.local"
    smtp_use_tls: bool = True

    # core/timestamper_factory.py: RFC 3161 trusted timestamping. Every
    # timestamp in this system is otherwise self-asserted — the WAL
    # stamps its own clock — so this is what lets a third party check
    # *when* something was logged rather than only that the chain is
    # intact. "local" (the default, always available) is deliberately NOT
    # trusted timestamping and says so in what it returns
    # (TimestampToken.source == "local"); "rfc3161" needs the `tsp` extra
    # and a real TSA at tsa_url, and has not been exercised against a
    # live one here. See core/timestamper.py for what it does and does
    # not verify.
    timestamp_backend: Literal["local", "rfc3161"] = "local"
    tsa_url: str = ""
    timestamp_hash_algorithm: Literal["sha256", "sha384", "sha512"] = "sha384"
    tsa_timeout_seconds: float = 10.0

    # uncertainty/factory.py: semantic-entropy abstention gate over
    # stochastic (LLM) output. "lexical" (the default, always available)
    # is deterministic token-containment scoring — a conservative floor
    # that over-splits paraphrases and so over-abstains, which is the safe
    # direction; "cross_encoder" needs the `semantic` install extra and a
    # real NLI checkpoint. See uncertainty/entailment.py.
    entailment_backend: Literal["lexical", "cross_encoder"] = "lexical"
    entailment_model_name: str = "cross-encoder/nli-deberta-v3-base"
    # Which index of the checkpoint's 3-way NLI output is "entailment".
    # Checkpoint-specific, not a standard — see CrossEncoderEntailmentModel.
    entailment_label_index: int = 1
    # Two texts join the same meaning cluster only if each entails the
    # other at or above this probability.
    semantic_entailment_threshold: float = 0.9
    # Semantic entropy is bounded by log(semantic_entropy_samples) nats —
    # log(10) = 2.3026 — so a threshold at or above that ceiling makes the
    # gate unreachable. SemanticEntropyGate rejects such a threshold at
    # construction rather than silently passing every input; see
    # uncertainty/semantic_entropy.py's module docstring.
    #
    # The 1.0 default sits just under log(3) = 1.0986, so it tolerates a
    # dominant answer with a couple of outliers (8/1/1 scores 0.639, 9/1
    # scores 0.325, an even 5/5 split scores 0.693) but fires on a genuine
    # three-way disagreement (4/3/3 scores 1.089). Tune per corpus; keep
    # it strictly below the ceiling.
    semantic_entropy_samples: int = 10
    semantic_entropy_threshold: float = 1.0

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # ui/ (Next.js dev server) runs on a different origin (localhost:3000)
    # than the API (localhost:8000) — without these, every browser fetch
    # from the dashboard would be silently blocked by CORS, not caught by
    # any test that doesn't use a real browser (TestClient bypasses it).
    cors_allowed_origins: list[str] = ["http://localhost:3000"]
    api_auth_enabled: bool = False
    api_client_id: str = "demo"
    api_client_secret: str = "change-me-in-production"
    # The demo credential's tenant. This one credential still always
    # works unconditionally (POST /auth/token checks it before the real
    # user registry) so zero-config local dev stays zero-config — but
    # POST /auth/register now provisions real, independent tenants too;
    # this is no longer the *only* tenant that can exist. See "User
    # accounts, tokens & revocation" in the README.
    api_client_tenant_id: str = "demo-tenant"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60
    # POST /auth/refresh exchanges a still-valid, not-yet-redeemed refresh
    # token for a new access+refresh pair (rotation: the old refresh
    # token is spent the instant it's used — see
    # compliance/token_ledger.py). Refresh tokens intentionally outlive
    # access tokens by a lot, the same reason any refresh-token design
    # does: the access token is what's on the wire on every request (so
    # it should have a short exposure window), the refresh token is only
    # ever sent to one single-purpose endpoint.
    refresh_token_expires_days: int = 30
    # POST /auth/invite (owner-only) issues one of these; POST
    # /accept-invite redeems it (single-use — see
    # compliance/token_ledger.py's revoke reuse). A week is generous
    # enough that a real emailed invite doesn't expire before it's read.
    invite_token_expires_days: int = 7
    # POST /auth/request-password-reset issues one of these; POST
    # /reset-password redeems it (single-use, same TokenLedger.revoke
    # reuse as invite tokens). Deliberately much shorter-lived than an
    # invite — a reset link sitting in an inbox is a real, if small,
    # window of exposure, so this stays tight (OWASP's usual
    # recommendation is well under an hour).
    password_reset_token_expires_minutes: int = 30
    # POST /auth/register issues one of these; POST /auth/verify-email
    # redeems it. Not single-use via TokenLedger the way invite/reset
    # tokens are — UserAccount.email_verified is itself the durable
    # record, so a second verify-email call with the same token is just a
    # harmless no-op, not a security-relevant reuse.
    email_verification_token_expires_days: int = 7

    # api/dependencies.py's require_verified_email. Off by default so the
    # zero-config path and every existing deployment keep working —
    # turning it on retroactively locks out every account registered
    # before it, which has to be a deliberate choice rather than a
    # surprise on upgrade. UserAccount.email_verified was tracked and
    # displayed but gated nothing at all until this existed.
    require_email_verification: bool = False

    # Tenant every request is scoped to when settings.api_auth_enabled is
    # False (the default) — the whole deployment behaves as one tenant,
    # unchanged from pre-multi-tenancy behavior.
    default_tenant_id: str = "default"


settings = Settings()
