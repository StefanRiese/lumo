"""Async client of the Lumo REST API (docs/API.md)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import aiohttp


class LumoError(Exception):
    """Base class of all client errors."""

    def __init__(self, message: str = "", code: str | None = None) -> None:
        super().__init__(message or code or "lumo error")
        self.code = code


class LumoConnectionError(LumoError):
    """The server is not reachable (or does not answer in time)."""


class LumoAuthError(LumoError):
    """The web UI password is wrong or the login was refused."""


class LumoRateLimitedError(LumoError):
    """Too many failed logins (429); retry after `retry_after` seconds."""

    def __init__(self, retry_after: int | None) -> None:
        super().__init__("too many attempts", "too_many_attempts")
        self.retry_after = retry_after


class LumoSetupRequiredError(LumoError):
    """The server is not set up yet (503 setup_required)."""


class LumoNotFoundError(LumoError):
    """Unknown path, account or disabled area (404)."""


class LumoApiError(LumoError):
    """Any other error answer; `status` is the HTTP status, `code` the API error code."""

    def __init__(self, status: int, code: str | None, message: str = "") -> None:
        super().__init__(message or code or f"HTTP {status}", code)
        self.status = status


@dataclass(frozen=True)
class Envelope:
    """Answer of a data endpoint (docs/API.md "Data endpoints")."""

    data: Any
    key: str | None
    fetched_at: str | None
    cached: bool
    stale: bool
    refreshing: bool
    extra: dict[str, Any]

    @classmethod
    def from_json(cls, body: dict[str, Any]) -> Envelope:
        known = {"data", "key", "fetchedAt", "cached", "stale", "refreshing"}
        return cls(
            data=body.get("data"),
            key=body.get("key"),
            fetched_at=body.get("fetchedAt"),
            cached=bool(body.get("cached", False)),
            stale=bool(body.get("stale", False)),
            refreshing=bool(body.get("refreshing", False)),
            extra={k: v for k, v in body.items() if k not in known},
        )


@dataclass(frozen=True)
class ServerEvent:
    """One Server-Sent Event: `sync` ({"running": bool}) or `update` ({"key", "fetchedAt"})."""

    event: str
    data: dict[str, Any]


async def parse_sse(lines: AsyncIterator[str]) -> AsyncIterator[ServerEvent]:
    """Turns decoded lines of a text/event-stream into events.

    Comments (`: ping`), `retry:` and unknown fields are ignored; an event without a
    `data:` line or with invalid JSON is dropped.
    """
    event = "message"
    data: list[str] = []
    async for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                try:
                    parsed = json.loads("\n".join(data))
                except ValueError:
                    parsed = None
                if isinstance(parsed, dict):
                    yield ServerEvent(event, parsed)
            event, data = "message", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))


class LumoClient:
    """Talks to one Lumo server.

    Pass a session of its own (own cookie jar, `aiohttp.CookieJar(unsafe=True)` for IP
    hosts): the login cookie `sph_session` is kept there. A `401 unauthorized` triggers one
    new login with the stored password.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        password: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._session = session
        self._base = base_url.rstrip("/")
        self._password = password
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._login_lock = asyncio.Lock()

    @property
    def base_url(self) -> str:
        return self._base

    # --- plumbing -------------------------------------------------------------------

    @staticmethod
    async def _error_from(resp: aiohttp.ClientResponse) -> LumoError:
        code: str | None = None
        message = ""
        try:
            body = await resp.json(content_type=None)
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                code = err.get("code")
                message = err.get("message") or ""
        except (ValueError, aiohttp.ClientError):
            pass
        if resp.status == 429:
            retry = resp.headers.get("Retry-After", "")
            return LumoRateLimitedError(int(retry) if retry.isdigit() else None)
        if resp.status == 503 and code == "setup_required":
            return LumoSetupRequiredError(message, code)
        if resp.status == 401:
            return LumoAuthError(message, code)
        if resp.status == 404:
            return LumoNotFoundError(message, code)
        return LumoApiError(resp.status, code, message)

    async def _send(
        self, method: str, path: str, *, json_body: Any = None, params: dict[str, str] | None = None
    ) -> Any:
        """One request without login handling; returns the decoded JSON body."""
        try:
            async with self._session.request(
                method,
                self._base + path,
                json=json_body,
                params=params,
                timeout=self._timeout,
            ) as resp:
                if resp.status >= 400:
                    raise await self._error_from(resp)
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LumoConnectionError(str(err) or type(err).__name__) from err

    async def login(self) -> None:
        """Logs in with the web UI password (sets the session cookie)."""
        async with self._login_lock:
            try:
                await self._send("POST", "/api/auth/login", json_body={"password": self._password})
            except LumoAuthError as err:
                raise LumoAuthError("invalid password", err.code or "invalid_password") from err

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """A request with one automatic re-login when the session has expired."""
        try:
            return await self._send(method, path, **kwargs)
        except LumoAuthError:
            await self.login()
            return await self._send(method, path, **kwargs)

    # --- server-wide ----------------------------------------------------------------

    async def healthz(self) -> dict[str, Any]:
        """`GET /healthz` (no login): `{"status": "ok", "app": "lumo"}`."""
        return await self._send("GET", "/healthz")

    async def accounts(self) -> list[dict[str, Any]]:
        """`GET /api/accounts`: the children (id, name, caseda, untis, …)."""
        body = await self._request("GET", "/api/accounts")
        return list(body.get("accounts", []))

    async def status(self) -> dict[str, Any]:
        """`GET /api/status`: health of the services (accounts[] + server services[])."""
        return await self._request("GET", "/api/status")

    async def update_info(self) -> dict[str, Any]:
        """`GET /api/update`: app update status."""
        return await self._request("GET", "/api/update")

    # --- per account ----------------------------------------------------------------

    @staticmethod
    def _account_path(account_id: str, path: str) -> str:
        return f"/api/accounts/{account_id}/{path.lstrip('/')}"

    async def get(
        self,
        account_id: str,
        path: str,
        *,
        refresh: bool = False,
        params: dict[str, str] | None = None,
    ) -> Envelope:
        """A data endpoint of an account, e.g. `get("k3x9ab", "substitutions")`."""
        params = dict(params or {})
        if refresh:
            params["refresh"] = "1"
        body = await self._request(
            "GET", self._account_path(account_id, path), params=params or None
        )
        return Envelope.from_json(body)

    async def sync_status(self, account_id: str) -> dict[str, Any]:
        """`GET /api/accounts/<id>/sync`."""
        return await self._request("GET", self._account_path(account_id, "sync"))

    async def refresh(self, account_id: str) -> None:
        """`POST /api/accounts/<id>/refresh`: starts a background sync."""
        await self._request("POST", self._account_path(account_id, "refresh"))

    async def set_homework_done(
        self, account_id: str, course_id: str, entry_id: str, done: bool
    ) -> bool:
        """Marks homework as done or not done. **Writes to the real Schulportal.**"""
        body = await self._request(
            "PUT",
            self._account_path(account_id, f"courses/{course_id}/entries/{entry_id}/homework"),
            json_body={"done": done},
        )
        return bool(body.get("done"))

    async def events(self, account_id: str) -> AsyncIterator[ServerEvent]:
        """The event stream of an account. Ends when the server closes it.

        Raises `LumoConnectionError` on a broken connection and `LumoAuthError` when the
        session has expired (after one new login). The caller reconnects.
        """
        url = self._base + self._account_path(account_id, "events")
        # No total timeout: the stream stays open (the server pings every 25 s).
        timeout = aiohttp.ClientTimeout(total=None, connect=self._timeout.total, sock_read=90)
        for attempt in (1, 2):
            try:
                async with self._session.get(url, timeout=timeout) as resp:
                    if resp.status == 401 and attempt == 1:
                        await self.login()
                        continue
                    if resp.status >= 400:
                        raise await self._error_from(resp)

                    async def lines(resp: aiohttp.ClientResponse = resp) -> AsyncIterator[str]:
                        async for raw in resp.content:
                            yield raw.decode("utf-8", "replace")

                    async for event in parse_sse(lines()):
                        yield event
                    return
            except (aiohttp.ClientError, TimeoutError) as err:
                raise LumoConnectionError(str(err) or type(err).__name__) from err
