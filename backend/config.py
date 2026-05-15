"""Runtime configuration validation for deployable API and worker processes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

VALID_STORAGE_BACKENDS = {"local", "supabase"}
VALID_WORKER_MODES = {"embedded", "external", "disabled"}
PRODUCTION_ENV_NAMES = {"prod", "production"}

DEFAULT_PROXY_MAX_ATTEMPTS = 5
DEFAULT_PROXY_SESSION_LIFETIME_MIN = 10
DEFAULT_PROXY_BLOCKLIST_TTL_HOURS = 6
DEFAULT_TRANSCRIPT_WORKERS = 4


class RuntimeConfigError(RuntimeError):
    """Raised when required deployment configuration is missing or invalid."""


@dataclass(frozen=True)
class ProxyConfig:
    """Residential-proxy settings for transcript fetching."""

    iproyal_host: str
    iproyal_user: str
    iproyal_pass: str
    webshare_user: str
    webshare_pass: str
    max_attempts: int
    session_lifetime_min: int
    blocklist_ttl_hours: int
    transcript_workers: int

    @property
    def iproyal_enabled(self) -> bool:
        return bool(self.iproyal_host and self.iproyal_user and self.iproyal_pass)

    @property
    def webshare_enabled(self) -> bool:
        return bool(self.webshare_user and self.webshare_pass)

    @property
    def any_provider_enabled(self) -> bool:
        return self.iproyal_enabled or self.webshare_enabled


@dataclass(frozen=True)
class RuntimeConfig:
    """Parsed environment settings shared by the API and worker."""

    role: str
    app_env: str
    storage_backend: str
    pipeline_worker_mode: str
    cors_origins: list[str]
    log_format: str
    proxy: ProxyConfig
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in PRODUCTION_ENV_NAMES

    @property
    def ok(self) -> bool:
        return not self.errors


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_positive_int(name: str, default: int, errors: list[str]) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} must be a positive integer (got {raw!r})")
        return default
    if value <= 0:
        errors.append(f"{name} must be a positive integer (got {value})")
        return default
    return value


def _default_worker_mode(app_env: str) -> str:
    if app_env.lower() in PRODUCTION_ENV_NAMES:
        return "external"
    return "embedded"


def _load_proxy_config(errors: list[str]) -> ProxyConfig:
    return ProxyConfig(
        iproyal_host=_env("IPROYAL_PROXY_HOST"),
        iproyal_user=_env("IPROYAL_PROXY_USER"),
        iproyal_pass=_env("IPROYAL_PROXY_PASS"),
        webshare_user=_env("WEBSHARE_PROXY_USER"),
        webshare_pass=_env("WEBSHARE_PROXY_PASS"),
        max_attempts=_env_positive_int(
            "PROXY_MAX_ATTEMPTS", DEFAULT_PROXY_MAX_ATTEMPTS, errors
        ),
        session_lifetime_min=_env_positive_int(
            "PROXY_SESSION_LIFETIME_MIN", DEFAULT_PROXY_SESSION_LIFETIME_MIN, errors
        ),
        blocklist_ttl_hours=_env_positive_int(
            "PROXY_BLOCKLIST_TTL_HOURS", DEFAULT_PROXY_BLOCKLIST_TTL_HOURS, errors
        ),
        transcript_workers=_env_positive_int(
            "TRANSCRIPT_WORKERS", DEFAULT_TRANSCRIPT_WORKERS, errors
        ),
    )


def load_runtime_config(role: str = "api") -> RuntimeConfig:
    """Load deploy-time configuration and return validation diagnostics."""
    app_env = _env("APP_ENV", "development") or "development"
    storage_backend = _env("STORAGE_BACKEND", "local").lower() or "local"
    worker_mode = (
        _env("PIPELINE_WORKER_MODE", _default_worker_mode(app_env)).lower()
        or _default_worker_mode(app_env)
    )
    cors_origins = _split_csv(_env("CORS_ORIGINS", "http://localhost:5173"))
    log_format = _env("LOG_FORMAT", "plain").lower() or "plain"

    errors: list[str] = []
    warnings: list[str] = []

    proxy = _load_proxy_config(errors)

    if storage_backend not in VALID_STORAGE_BACKENDS:
        errors.append(
            "STORAGE_BACKEND must be one of: " + ", ".join(sorted(VALID_STORAGE_BACKENDS))
        )

    if worker_mode not in VALID_WORKER_MODES:
        errors.append(
            "PIPELINE_WORKER_MODE must be one of: " + ", ".join(sorted(VALID_WORKER_MODES))
        )

    if log_format not in {"plain", "json"}:
        errors.append("LOG_FORMAT must be either 'plain' or 'json'")

    if storage_backend == "supabase":
        for name in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
            if not _env(name):
                errors.append(f"{name} is required when STORAGE_BACKEND=supabase")

    if app_env.lower() in PRODUCTION_ENV_NAMES:
        if storage_backend != "supabase":
            errors.append("STORAGE_BACKEND=supabase is required in production")
        if not _env("SUPABASE_URL"):
            errors.append("SUPABASE_URL is required in production")
        if not _env("MINIMAX_API_KEY"):
            errors.append("MINIMAX_API_KEY is required in production")
        if not cors_origins:
            errors.append("CORS_ORIGINS must include the deployed frontend origin")
        for name in ("IPROYAL_PROXY_HOST", "IPROYAL_PROXY_USER", "IPROYAL_PROXY_PASS"):
            if not _env(name):
                errors.append(f"{name} is required in production")
        if not proxy.webshare_enabled:
            warnings.append(
                "WEBSHARE_PROXY_USER/PASS not set; no fallback proxy when IPRoyal is degraded"
            )
    if role == "worker" and storage_backend != "supabase":
        warnings.append("Standalone worker has no durable queue unless STORAGE_BACKEND=supabase")

    if (
        role == "api"
        and app_env.lower() not in PRODUCTION_ENV_NAMES
        and storage_backend == "supabase"
        and worker_mode == "embedded"
        and _env("ALLOW_LOCAL_SUPABASE_EMBEDDED_WORKER").lower() != "true"
    ):
        warnings.append(
            "PIPELINE_WORKER_MODE=embedded is ignored for local Supabase API runs. "
            "Start backend.worker separately, or set ALLOW_LOCAL_SUPABASE_EMBEDDED_WORKER=true "
            "if this process should claim the shared durable queue."
        )

    if _env("SUPABASE_URL") and not _env("SUPABASE_JWT_SECRET"):
        warnings.append("SUPABASE_JWT_SECRET is not set; HS256 Supabase JWTs cannot be verified")

    return RuntimeConfig(
        role=role,
        app_env=app_env,
        storage_backend=storage_backend,
        pipeline_worker_mode=worker_mode,
        cors_origins=cors_origins,
        log_format=log_format,
        proxy=proxy,
        errors=errors,
        warnings=warnings,
    )


def validate_runtime_config(role: str = "api", *, strict: bool | None = None) -> RuntimeConfig:
    """Return runtime config and raise when strict validation fails."""
    config = load_runtime_config(role)
    should_raise = config.is_production if strict is None else strict
    if should_raise and config.errors:
        raise RuntimeConfigError("; ".join(config.errors))
    return config


def embedded_worker_enabled() -> bool:
    """Return whether the API process should also run pipeline worker tasks."""
    config = load_runtime_config("api")
    if (
        not config.is_production
        and config.storage_backend == "supabase"
        and os.environ.get("ALLOW_LOCAL_SUPABASE_EMBEDDED_WORKER", "").strip().lower()
        != "true"
    ):
        return False
    return config.pipeline_worker_mode == "embedded"


def runtime_report(role: str = "api") -> dict[str, object]:
    """Return a safe readiness payload without exposing secret values."""
    config = load_runtime_config(role)
    return {
        "ok": config.ok,
        "role": config.role,
        "app_env": config.app_env,
        "storage_backend": config.storage_backend,
        "pipeline_worker_mode": config.pipeline_worker_mode,
        "log_format": config.log_format,
        "cors_origins": config.cors_origins,
        "proxy": {
            "iproyal_enabled": config.proxy.iproyal_enabled,
            "webshare_enabled": config.proxy.webshare_enabled,
            "max_attempts": config.proxy.max_attempts,
            "session_lifetime_min": config.proxy.session_lifetime_min,
            "blocklist_ttl_hours": config.proxy.blocklist_ttl_hours,
            "transcript_workers": config.proxy.transcript_workers,
        },
        "errors": config.errors,
        "warnings": config.warnings,
    }
