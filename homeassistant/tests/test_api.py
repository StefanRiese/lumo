"""Tests of the REST client against the fake server."""

from __future__ import annotations

import aiohttp
import pytest

from custom_components.lumo.api import (
    LumoAuthError,
    LumoClient,
    LumoConnectionError,
    LumoNotFoundError,
    LumoRateLimitedError,
    LumoSetupRequiredError,
    parse_sse,
)

from .fake_server import FakeLumo


async def _lines(text: str):
    for line in text.splitlines(keepends=True):
        yield line


async def test_parse_sse_ignores_comments_and_bad_events() -> None:
    stream = (
        "retry: 5000\n\n"
        'event: sync\ndata: {"running":true}\n\n'
        ": ping\n\n"
        "event: update\ndata: not json\n\n"
        'event: update\r\ndata: {"key":"homework","fetchedAt":"x"}\r\n\r\n'
        "event: update\n\n"
    )
    events = [e async for e in parse_sse(_lines(stream))]
    assert [(e.event, e.data) for e in events] == [
        ("sync", {"running": True}),
        ("update", {"key": "homework", "fetchedAt": "x"}),
    ]


async def test_login_and_get_envelope(fake: tuple[FakeLumo, str], client: LumoClient) -> None:
    server, _ = fake
    await client.login()
    env = await client.get("k3x9ab", "substitutions")
    assert env.data == server.data["substitutions"]
    assert env.key == "substitutions"
    assert env.cached and not env.stale and not env.refreshing
    assert env.fetched_at == "2026-11-10T10:00:00.000Z"


async def test_wrong_password(fake: tuple[FakeLumo, str]) -> None:
    _, url = fake
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as session:
        with pytest.raises(LumoAuthError) as err:
            await LumoClient(session, url, "wrong").login()
    assert err.value.code == "invalid_password"


async def test_expired_session_logs_in_again(
    fake: tuple[FakeLumo, str], client: LumoClient
) -> None:
    server, _ = fake
    assert len(await client.accounts()) == 2
    assert server.logins == 1
    server.expire_sessions()
    assert len(await client.accounts()) == 2
    assert server.logins == 2


async def test_changed_password_raises_auth_error(
    fake: tuple[FakeLumo, str], client: LumoClient
) -> None:
    server, _ = fake
    await client.login()
    server.expire_sessions()
    client._password = "changed"  # noqa: SLF001
    with pytest.raises(LumoAuthError):
        await client.accounts()


async def test_not_found_and_stale_flag(fake: tuple[FakeLumo, str], client: LumoClient) -> None:
    server, _ = fake
    with pytest.raises(LumoNotFoundError) as err:
        await client.get("k3x9ab", "meals")
    assert err.value.code == "feature_disabled"
    with pytest.raises(LumoNotFoundError):
        await client.get("nope", "timetable")
    server.stale = True
    assert (await client.get("k3x9ab", "timetable")).stale is True


async def test_connection_error(socket_enabled: None) -> None:
    async with aiohttp.ClientSession() as session:
        with pytest.raises(LumoConnectionError):
            await LumoClient(session, "http://127.0.0.1:1", "x", timeout=2).healthz()


async def test_rate_limit_and_setup_required(
    fake: tuple[FakeLumo, str], client: LumoClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    server, _ = fake

    async def limited(request):
        return server._error(429, "too_many_attempts", **{"Retry-After": "120"})  # noqa: SLF001

    async def setup(request):
        return server._error(503, "setup_required")  # noqa: SLF001

    monkeypatch.setattr(server, "login", limited)
    # the app is built after the patch: restart the fake server
    await server.stop()
    url = await server.start()
    client._base = url  # noqa: SLF001
    with pytest.raises(LumoRateLimitedError) as err:
        await client.login()
    assert err.value.retry_after == 120

    monkeypatch.setattr(server, "login", setup)
    await server.stop()
    client._base = await server.start()  # noqa: SLF001
    with pytest.raises(LumoSetupRequiredError):
        await client.login()


async def test_actions(fake: tuple[FakeLumo, str], client: LumoClient) -> None:
    server, _ = fake
    await client.refresh("k3x9ab")
    assert ("POST", "refresh") in server.requests
    assert await client.set_homework_done("k3x9ab", "104", "2219", True) is True
    assert server.homework_puts == [("104", "2219", True)]


async def test_events_stream(fake: tuple[FakeLumo, str], client: LumoClient) -> None:
    server, _ = fake
    received = []
    async for event in client.events("k3x9ab"):
        received.append((event.event, event.data))
        if event.event == "sync":
            server.push("update", {"key": "homework", "fetchedAt": "t"})
            server.close_streams()
    assert received == [
        ("sync", {"running": False}),
        ("update", {"key": "homework", "fetchedAt": "t"}),
    ]
    assert server.logins == 1  # logged in again only because the first request had no cookie
