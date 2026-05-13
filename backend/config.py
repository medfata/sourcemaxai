"""Runtime configuration validation for deployable API and worker processes."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

VALID_STORAGE_BACKENDS = {"local", "supabase"}
VALID_WORKER_MODES = {"embedded", "external", "disabled"}
PRODUCTION_ENV_NAMES = {"prod", "production"}


class RuntimeConfigError(RuntimeError):
    """Raised when required deployment configuration is missing or invalid."""


@dataclass(frozen=True)
class RuntimeConfig:
    """Parsed environment settings shared by the API and worker."""

    role: str
    app_env: str
    storage_backend: str
    pipeline_worker_mode: str
    cors_origins: list[str]
    log_format: str
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


def _default_worker_mode(app_env: str) -> str:
    if app_env.lower() in PRODUCTION_ENV_NAMES:
        return "external"
    return "embedded"


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

    if role == "worker" and storage_backend != "supabase":
        warnings.append("Standalone worker has no durable queue unless STORAGE_BACKEND=supabase")

    if _env("SUPABASE_URL") and not _env("SUPABASE_JWT_SECRET"):
        warnings.append("SUPABASE_JWT_SECRET is not set; HS256 Supabase JWTs cannot be verified")

    return RuntimeConfig(
        role=role,
        app_env=app_env,
        storage_backend=storage_backend,
        pipeline_worker_mode=worker_mode,
        cors_origins=cors_origins,
        log_format=log_format,
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
        "errors": config.errors,
        "warnings": config.warnings,
    }
