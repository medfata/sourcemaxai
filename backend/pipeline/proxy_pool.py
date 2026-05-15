"""Residential-proxy pool for transcript fetching with Supabase-backed blocklist."""

from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from urllib.parse import quote

from backend import storage
from backend.config import RuntimeConfig, load_runtime_config

SESSION_ID_LEN = 10
SESSION_ID_ALPHABET = string.ascii_lowercase + string.digits
BLOCKLIST_CACHE_TTL_SECONDS = 300
ACQUIRE_RETRY_BUDGET = 5


class NoProxyAvailable(RuntimeError):
    """Raised when every configured provider yields only blocked sessions."""


@dataclass(frozen=True)
class ProxyConfig:
    name: str
    host: str
    username: str
    password: str
    session_param: str
    rotate_per_request: bool


class _BlocklistBackend(Protocol):
    def is_blocked(self, provider: str, session_id: str) -> bool: ...

    def add(self, provider: str, session_id: str, reason: str) -> None: ...

    def cleanup_expired(self) -> int: ...


class BlocklistStore:
    """Supabase-backed read/write of `proxy_blocklist` with a small in-process TTL cache."""

    _TABLE = "proxy_blocklist"

    def __init__(
        self,
        backend: storage.SupabaseStorageBackend,
        *,
        ttl_hours: int = 6,
        cache_ttl_seconds: int = BLOCKLIST_CACHE_TTL_SECONDS,
    ) -> None:
        self.backend = backend
        self.ttl_hours = ttl_hours
        self._cache_ttl = cache_ttl_seconds
        self._cache: dict[tuple[str, str], tuple[bool, float]] = {}

    @staticmethod
    def _eq(value: str) -> str:
        return f"eq.{value}"

    def is_blocked(self, provider: str, session_id: str) -> bool:
        key = (provider, session_id)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached is not None and cached[1] > now:
            return cached[0]

        iso_now = datetime.now(timezone.utc).isoformat()
        rows = self.backend._select(
            self._TABLE,
            select="session_id",
            filters={
                "provider": self._eq(provider),
                "session_id": self._eq(session_id),
                "expires_at": f"gt.{iso_now}",
            },
            limit=1,
        )
        blocked = bool(rows)
        self._cache[key] = (blocked, now + self._cache_ttl)
        return blocked

    def add(self, provider: str, session_id: str, reason: str) -> None:
        row = {
            "provider": provider,
            "session_id": session_id,
            "reason": reason,
        }
        try:
            self.backend._upsert(self._TABLE, row, on_conflict="provider,session_id")
        except storage.SupabaseStorageError:
            pass
        self._cache[(provider, session_id)] = (True, time.monotonic() + self._cache_ttl)

    def cleanup_expired(self) -> int:
        iso_now = datetime.now(timezone.utc).isoformat()
        rows = self.backend._select(
            self._TABLE,
            select="id",
            filters={"expires_at": f"lt.{iso_now}"},
            limit=10000,
        )
        if not rows:
            return 0
        self.backend._delete(self._TABLE, filters={"expires_at": f"lt.{iso_now}"})
        self._cache.clear()
        return len(rows)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class CircuitBreaker:
    """Persistent provider-level breaker backed by the proxy_circuit_state table."""

    _TABLE = "proxy_circuit_state"

    def __init__(
        self,
        backend: storage.SupabaseStorageBackend,
        *,
        failure_threshold: int = 10,
        failure_window_seconds: int = 300,
        open_duration_seconds: int = 900,
    ) -> None:
        self.backend = backend
        self.failure_threshold = failure_threshold
        self.failure_window_seconds = failure_window_seconds
        self.open_duration_seconds = open_duration_seconds

    def is_open(self, provider: str) -> bool:
        row = self._read(provider)
        if row.get("status") != "open":
            return False
        open_until = _parse_iso(row.get("open_until"))
        if open_until is None:
            return False
        return datetime.now(timezone.utc) < open_until

    def should_probe(self, provider: str) -> bool:
        row = self._read(provider)
        if row.get("status") != "open":
            return False
        open_until = _parse_iso(row.get("open_until"))
        if open_until is None:
            return False
        now = datetime.now(timezone.utc)
        if now < open_until:
            return False
        self._write(
            provider,
            status="half_open",
            updated_at=now.isoformat(),
        )
        return True

    def record_failure(self, provider: str, *, reason: str = "") -> None:
        row = self._read(provider)
        now = datetime.now(timezone.utc)

        if row.get("status") == "half_open":
            self._write(
                provider,
                status="open",
                open_until=(now + timedelta(seconds=self.open_duration_seconds)).isoformat(),
                consecutive_failures=0,
                updated_at=now.isoformat(),
            )
            return

        last_updated = _parse_iso(row.get("updated_at"))
        if last_updated is not None and (now - last_updated).total_seconds() > self.failure_window_seconds:
            counter = 1
        else:
            counter = int(row.get("consecutive_failures") or 0) + 1

        if counter >= self.failure_threshold:
            self._write(
                provider,
                status="open",
                open_until=(now + timedelta(seconds=self.open_duration_seconds)).isoformat(),
                consecutive_failures=0,
                updated_at=now.isoformat(),
            )
        else:
            self._write(
                provider,
                status=row.get("status") or "closed",
                consecutive_failures=counter,
                updated_at=now.isoformat(),
            )

    def record_success(self, provider: str) -> None:
        now = datetime.now(timezone.utc)
        self._write(
            provider,
            status="closed",
            consecutive_failures=0,
            open_until=None,
            updated_at=now.isoformat(),
        )

    def _read(self, provider: str) -> dict[str, Any]:
        rows = self.backend._select(
            self._TABLE,
            filters={"provider": f"eq.{provider}"},
            limit=1,
        )
        return rows[0] if rows else {}

    def _write(self, provider: str, **fields: Any) -> None:
        row = {"provider": provider, **fields}
        try:
            self.backend._upsert(self._TABLE, row, on_conflict="provider")
        except storage.SupabaseStorageError:
            pass


def _generate_session_id() -> str:
    return "".join(secrets.choice(SESSION_ID_ALPHABET) for _ in range(SESSION_ID_LEN))


class ProxyPool:
    """Hand out fresh proxy URLs per attempt, skipping blocklisted sessions."""

    def __init__(
        self,
        providers: list[ProxyConfig],
        blocklist: _BlocklistBackend,
        *,
        session_lifetime_min: int = 10,
    ) -> None:
        if not providers:
            raise ValueError("ProxyPool requires at least one provider")
        self.providers = list(providers)
        self.blocklist = blocklist
        self.session_lifetime_min = session_lifetime_min

    def acquire(self, video_id: str, attempt: int) -> tuple[ProxyConfig, str]:
        for provider in self.providers:
            for _ in range(ACQUIRE_RETRY_BUDGET):
                session_id = _generate_session_id()
                if not self.blocklist.is_blocked(provider.name, session_id):
                    return provider, session_id
        raise NoProxyAvailable(
            f"All providers exhausted for video={video_id} attempt={attempt}"
        )

    def mark_blocked(self, provider: ProxyConfig, session_id: str, reason: str) -> None:
        self.blocklist.add(provider.name, session_id, reason)

    def proxy_url(self, provider: ProxyConfig, session_id: str) -> str:
        user_part = (
            f"{provider.username}-{provider.session_param}-{session_id}"
            f"-lifetime-{self.session_lifetime_min}m"
        )
        return f"http://{quote(user_part, safe='-')}:{quote(provider.password, safe='')}@{provider.host}"


def _iproyal_from_config(cfg: RuntimeConfig) -> ProxyConfig | None:
    if not cfg.proxy.iproyal_enabled:
        return None
    return ProxyConfig(
        name="iproyal",
        host=cfg.proxy.iproyal_host,
        username=cfg.proxy.iproyal_user,
        password=cfg.proxy.iproyal_pass,
        session_param="session",
        rotate_per_request=False,
    )


def _webshare_from_config(cfg: RuntimeConfig) -> ProxyConfig | None:
    if not cfg.proxy.webshare_enabled:
        return None
    return ProxyConfig(
        name="webshare",
        host="p.webshare.io:80",
        username=cfg.proxy.webshare_user,
        password=cfg.proxy.webshare_pass,
        session_param="session",
        rotate_per_request=False,
    )


def build_proxy_pool() -> ProxyPool | None:
    """Assemble a `ProxyPool` from runtime config, or `None` when no provider is configured."""
    cfg = load_runtime_config()
    providers = [
        provider
        for provider in (_iproyal_from_config(cfg), _webshare_from_config(cfg))
        if provider is not None
    ]
    if not providers:
        return None

    blocklist = BlocklistStore(
        storage.SupabaseStorageBackend.from_env(),
        ttl_hours=cfg.proxy.blocklist_ttl_hours,
    )
    return ProxyPool(
        providers,
        blocklist,
        session_lifetime_min=cfg.proxy.session_lifetime_min,
    )
