"""Smoke tests for `backend.pipeline.proxy_pool`. Full coverage lives in P1.5."""

from __future__ import annotations

import pytest

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


def _provider(name: str = "iproyal") -> ProxyConfig:
    return ProxyConfig(
        name=name,
        host="geo.iproyal.com:12321",
        username="user",
        password="p@ss/word",
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
