"""Tests for `backend.pipeline.proxy_pool`: rotation, blocklist cache, failover, builder wiring."""

from __future__ import annotations

import pytest

from backend import storage
from backend.pipeline import proxy_pool as proxy_pool_module
from backend.pipeline.proxy_pool import (
    BlocklistStore,
    NoProxyAvailable,
    ProxyConfig,
    ProxyPool,
    build_proxy_pool,
)


class _FakeBlocklist:
    def __init__(self) -> None:
        self.blocked: set[tuple[str, str]] = set()
        self.added: list[tuple[str, str, str]] = []

    def is_blocked(self, provider: str, session_id: str) -> bool:
        return (provider, session_id) in self.blocked

    def add(self, provider: str, session_id: str, reason: str) -> None:
        self.blocked.add((provider, session_id))
        self.added.append((provider, session_id, reason))

    def cleanup_expired(self) -> int:
        return 0


class _StubSupabaseBackend:
    def __init__(self) -> None:
        self.select_calls: list[dict] = []
        self.upsert_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self._select_return: list[dict] = []

    def _select(self, table, *, select=None, filters=None, limit=None, order=None):
        self.select_calls.append({"table": table, "filters": filters})
        return list(self._select_return)

    def _upsert(self, table, row, *, on_conflict=None):
        self.upsert_calls.append({"table": table, "row": row, "on_conflict": on_conflict})

    def _delete(self, table, *, filters=None):
        self.delete_calls.append({"table": table, "filters": filters})


def _provider(name: str = "iproyal") -> ProxyConfig:
    return ProxyConfig(
        name=name,
        host="geo.iproyal.com:12321",
        username="user",
        password="p@ss/word",
        session_param="session",
        rotate_per_request=False,
    )


def _webshare_provider() -> ProxyConfig:
    return ProxyConfig(
        name="webshare",
        host="p.webshare.io:80",
        username="wsuser",
        password="wspass",
        session_param="session",
        rotate_per_request=False,
    )


def test_module_exports_callable_symbols():
    assert callable(build_proxy_pool)
    assert ProxyConfig.__dataclass_fields__
    assert BlocklistStore is not None


def test_proxy_url_embeds_session_and_lifetime_with_escaped_password():
    pool = ProxyPool([_provider()], _FakeBlocklist(), session_lifetime_min=10)
    url = pool.proxy_url(_provider(), "abc1234567")

    assert "user-session-abc1234567-lifetime-10m" in url
    assert "@geo.iproyal.com:12321" in url
    assert "p%40ss%2Fword" in url


def test_acquire_rotates_session_id_across_attempts():
    pool = ProxyPool([_provider()], _FakeBlocklist())

    _, session_a = pool.acquire("vid", attempt=1)
    _, session_b = pool.acquire("vid", attempt=2)

    assert session_a != session_b
    assert len(session_a) == 10
    assert len(session_b) == 10


def test_mark_blocked_records_into_blocklist():
    blocklist = _FakeBlocklist()
    pool = ProxyPool([_provider()], blocklist)
    provider, session_id = pool.acquire("vid", attempt=1)

    pool.mark_blocked(provider, session_id, reason="ip_blocked")

    assert (provider.name, session_id) in blocklist.blocked
    assert blocklist.added == [(provider.name, session_id, "ip_blocked")]


def test_acquire_raises_when_every_session_is_blocked(monkeypatch):
    blocklist = _FakeBlocklist()
    pool = ProxyPool([_provider()], blocklist)

    def always_blocked(_p: str, _s: str) -> bool:
        return True

    monkeypatch.setattr(blocklist, "is_blocked", always_blocked)

    with pytest.raises(NoProxyAvailable):
        pool.acquire("vid", attempt=1)


def test_build_proxy_pool_returns_none_when_no_creds(monkeypatch):
    for name in (
        "IPROYAL_PROXY_HOST",
        "IPROYAL_PROXY_USER",
        "IPROYAL_PROXY_PASS",
        "WEBSHARE_PROXY_USER",
        "WEBSHARE_PROXY_PASS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert build_proxy_pool() is None


def test_acquire_skips_blocked_sessions_within_provider(monkeypatch):
    sessions = iter(["sessblocked", "sessokokokk"])
    monkeypatch.setattr(proxy_pool_module, "_generate_session_id", lambda: next(sessions))

    blocklist = _FakeBlocklist()
    blocklist.blocked.add(("iproyal", "sessblocked"))
    pool = ProxyPool([_provider()], blocklist)

    provider, session_id = pool.acquire("vid", attempt=1)

    assert provider.name == "iproyal"
    assert session_id == "sessokokokk"


def test_acquire_fails_over_to_second_provider_when_first_fully_blocked():
    blocklist = _FakeBlocklist()

    def is_blocked(provider: str, _session_id: str) -> bool:
        return provider == "iproyal"

    blocklist.is_blocked = is_blocked  # type: ignore[assignment]
    pool = ProxyPool([_provider("iproyal"), _webshare_provider()], blocklist)

    provider, _session_id = pool.acquire("vid", attempt=1)

    assert provider.name == "webshare"


def test_proxy_url_format_includes_lifetime_from_pool_kwarg():
    pool = ProxyPool([_provider()], _FakeBlocklist(), session_lifetime_min=30)
    url = pool.proxy_url(_provider(), "abcdefghij")

    assert "lifetime-30m" in url


def test_blocklist_is_blocked_uses_cache_within_ttl():
    backend = _StubSupabaseBackend()
    store = BlocklistStore(backend, cache_ttl_seconds=300)  # type: ignore[arg-type]

    first = store.is_blocked("iproyal", "abc")
    second = store.is_blocked("iproyal", "abc")

    assert first is False
    assert second is False
    assert len(backend.select_calls) == 1


def test_blocklist_add_updates_cache_and_calls_upsert():
    backend = _StubSupabaseBackend()
    store = BlocklistStore(backend, cache_ttl_seconds=300)  # type: ignore[arg-type]

    store.add("iproyal", "abc", "ip_blocked")
    blocked = store.is_blocked("iproyal", "abc")

    assert blocked is True
    assert len(backend.upsert_calls) == 1
    assert backend.upsert_calls[0]["table"] == "proxy_blocklist"
    assert backend.upsert_calls[0]["row"] == {
        "provider": "iproyal",
        "session_id": "abc",
        "reason": "ip_blocked",
    }
    assert backend.upsert_calls[0]["on_conflict"] == "provider,session_id"
    assert backend.select_calls == []


def test_blocklist_cleanup_expired_returns_deleted_count():
    backend = _StubSupabaseBackend()
    backend._select_return = [{"id": 1}, {"id": 2}, {"id": 3}]
    store = BlocklistStore(backend)  # type: ignore[arg-type]

    deleted = store.cleanup_expired()

    assert deleted == 3
    assert len(backend.delete_calls) == 1
    select_filter = backend.select_calls[0]["filters"]
    delete_filter = backend.delete_calls[0]["filters"]
    assert delete_filter == select_filter
    assert "expires_at" in delete_filter
    assert delete_filter["expires_at"].startswith("lt.")


def _clear_proxy_env(monkeypatch):
    for name in (
        "IPROYAL_PROXY_HOST",
        "IPROYAL_PROXY_USER",
        "IPROYAL_PROXY_PASS",
        "WEBSHARE_PROXY_USER",
        "WEBSHARE_PROXY_PASS",
        "PROXY_MAX_ATTEMPTS",
        "PROXY_SESSION_LIFETIME_MIN",
        "PROXY_BLOCKLIST_TTL_HOURS",
        "TRANSCRIPT_WORKERS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_build_proxy_pool_wires_iproyal_when_creds_set(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("IPROYAL_PROXY_HOST", "geo.iproyal.com:12321")
    monkeypatch.setenv("IPROYAL_PROXY_USER", "ipuser")
    monkeypatch.setenv("IPROYAL_PROXY_PASS", "ippass")

    monkeypatch.setattr(
        storage.SupabaseStorageBackend,
        "from_env",
        classmethod(lambda cls: _StubSupabaseBackend()),  # type: ignore[arg-type]
    )

    pool = build_proxy_pool()

    assert pool is not None
    assert len(pool.providers) == 1
    assert pool.providers[0].name == "iproyal"
    assert pool.providers[0].username == "ipuser"


def test_build_proxy_pool_wires_both_providers_when_all_creds_set(monkeypatch):
    _clear_proxy_env(monkeypatch)
    monkeypatch.setenv("IPROYAL_PROXY_HOST", "geo.iproyal.com:12321")
    monkeypatch.setenv("IPROYAL_PROXY_USER", "ipuser")
    monkeypatch.setenv("IPROYAL_PROXY_PASS", "ippass")
    monkeypatch.setenv("WEBSHARE_PROXY_USER", "wsuser")
    monkeypatch.setenv("WEBSHARE_PROXY_PASS", "wspass")

    monkeypatch.setattr(
        storage.SupabaseStorageBackend,
        "from_env",
        classmethod(lambda cls: _StubSupabaseBackend()),  # type: ignore[arg-type]
    )

    pool = build_proxy_pool()

    assert pool is not None
    assert [p.name for p in pool.providers] == ["iproyal", "webshare"]
